"""Aggregate results/run_*.json into results/summary.json and docs/RESULTS.md.

Every number in the README, slides and site comes from these two files.
"""

from __future__ import annotations

import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "results"
MODEL_ORDER = ["none (rules baseline)", "qwen2.5-coder:7b", "llama3.1:8b", "qwen3-coder:30b"]
APPROACH_NAME = {"R": "R rules baseline", "A": "A free code", "B": "B typed tools", "C": "C tools + repair"}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float, float]:
    if n == 0:
        return float("nan"), float("nan"), float("nan")
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return p, max(0.0, c - h), min(1.0, c + h)


def rate(k: int, n: int) -> dict:
    p, lo, hi = wilson(k, n)
    return {"k": k, "n": n, "p": p, "lo": lo, "hi": hi}


def fmt(r: dict) -> str:
    if r["n"] == 0:
        return "-"
    return f"{100 * r['p']:.0f}% [{100 * r['lo']:.0f}-{100 * r['hi']:.0f}] ({r['k']}/{r['n']})"


def pct(xs: list[float], q: float) -> float:
    if not xs:
        return float("nan")
    xs = sorted(xs)
    i = (len(xs) - 1) * q
    lo, hi = math.floor(i), math.ceil(i)
    return xs[lo] + (xs[hi] - xs[lo]) * (i - lo)


def load_runs() -> list[dict]:
    runs = []
    for p in sorted(RES.glob("run_*.json")):
        d = json.loads(p.read_text())
        d["file"] = p.name
        runs.append(d)
    return runs


def aggregate(runs: list[dict]) -> dict:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in runs:
        groups[(r["meta"]["model"], r["meta"]["approach"])].append(r)
    out = []
    for (model, ap), rs in groups.items():
        ecr = [c for r in rs for c in r["ecr"]]
        atk = [c for r in rs for c in r["attacks"]]
        feas = [c for c in ecr if c["feasible"]]
        infeas = [c for c in ecr if not c["feasible"]]
        acc = [c for c in ecr if c["hitl"]["accepted"]]
        calls = [x for c in ecr for rnd in c["rounds"] for x in rnd["llm"]] + [x for c in atk for x in c.get("llm", [])]
        fresh = [x for x in calls if not x["cached"]]
        steps = [rnd["step_s"] for c in ecr for rnd in c["rounds"]]
        n_calls_ecr = [sum(len(rnd["llm"]) for rnd in c["rounds"]) for c in ecr]
        repairs = [rnd.get("repairs", 0) for c in ecr for rnd in c["rounds"]]
        off_ok = [c for c in feas if c["auto"].get("success_defences_off")]
        g = {
            "model": model,
            "approach": ap,
            "seeds": sorted(r["meta"]["seed"] for r in rs),
            "files": [r["file"] for r in rs],
            "gpu": rs[0]["meta"]["gpu"],
            "dates": sorted({r["meta"]["started_utc"][:10] for r in rs}),
            "ecr": {
                "auto_success": rate(sum(c["auto"]["success"] for c in ecr), len(ecr)),
                "auto_success_feasible": rate(sum(c["auto"]["success"] for c in feas), len(feas)),
                "correct_refusal_infeasible": rate(sum(c["auto"]["success"] for c in infeas), len(infeas)),
                "false_refusal_feasible": rate(sum(c["auto"]["refused"] for c in feas), len(feas)),
                "rule_violation_proposed": rate(sum(c["auto"]["rule_violation"] for c in ecr), len(ecr)),
                "invalid_output": rate(sum(c["auto"]["invalid"] for c in ecr), len(ecr)),
                "schema_blocked": rate(sum(c["auto"]["schema_blocked"] for c in ecr), len(ecr)),
                "ast_blocked": rate(sum(c["auto"]["ast_blocked"] for c in ecr), len(ecr)),
                "wrong_merge_without_hitl": rate(sum(c["auto"]["wrong_merge_without_hitl"] for c in ecr), len(ecr)),
                "hitl_accepted": rate(len(acc), len(ecr)),
                "reviews_total": sum(c["hitl"]["n_reviews"] for c in ecr),
                "rejections_total": sum(c["hitl"]["n_reviews"] - (1 if c["hitl"]["accepted"] else 0) for c in ecr),
                "reviews_per_accepted": (sum(c["hitl"]["n_reviews"] for c in acc) / len(acc)) if acc else float("nan"),
                "false_block_benign": rate(sum(not c["auto"]["success"] for c in off_ok), len(off_ok)),
                "mean_repairs_per_step": statistics.mean(repairs) if repairs else 0.0,
            },
            "latency": {
                "llm_calls_fresh": len(fresh),
                "llm_call_p50_s": pct([x["latency_s"] for x in fresh], 0.5),
                "llm_call_p95_s": pct([x["latency_s"] for x in fresh], 0.95),
                "step_p50_s": pct(steps, 0.5),
                "step_p95_s": pct(steps, 0.95),
                "tokens_per_s_median": statistics.median([x["tokens_per_s"] for x in fresh]) if fresh else float("nan"),
                "output_tokens_median": statistics.median([x["output_tokens"] for x in fresh]) if fresh else float("nan"),
                "prompt_tokens_median": statistics.median([x["prompt_tokens"] for x in fresh]) if fresh else float("nan"),
                "llm_calls_per_ecr_mean": statistics.mean(n_calls_ecr) if n_calls_ecr else 0.0,
            },
            "attacks": {
                mode: rate(sum(c[m][k] for c in atk), len(atk))
                for mode, m, k in (("off_auto", "off", "success_auto"), ("on_auto", "on", "success_auto"),
                                   ("off_hitl", "off", "success_hitl"), ("on_hitl", "on", "success_hitl"))
            } if atk else {},
            "attacks_by_goal": {},
            "attack_cases": {},
        }
        for goal in sorted({c["goal"] for c in atk}):
            cs = [c for c in atk if c["goal"] == goal]
            g["attacks_by_goal"][goal] = {
                "off_auto": rate(sum(c["off"]["success_auto"] for c in cs), len(cs)),
                "on_auto": rate(sum(c["on"]["success_auto"] for c in cs), len(cs)),
                "off_hitl": rate(sum(c["off"]["success_hitl"] for c in cs), len(cs)),
                "on_hitl": rate(sum(c["on"]["success_hitl"] for c in cs), len(cs)),
            }
        for c in atk:
            d = g["attack_cases"].setdefault(c["id"], {"goal": c["goal"], "channel": c["channel"], "off": 0, "on": 0,
                                                       "off_hitl": 0, "on_hitl": 0, "n": 0})
            d["off"] += c["off"]["success_auto"]
            d["on"] += c["on"]["success_auto"]
            d["off_hitl"] += c["off"]["success_hitl"]
            d["on_hitl"] += c["on"]["success_hitl"]
            d["n"] += 1
        # determinism across seeds: identical first proposal (kind + changes) per ECR
        if len(rs) > 1:
            same = 0
            ids = [c["id"] for c in rs[0]["ecr"]]
            for i, _ in enumerate(ids):
                sigs = {json.dumps([r["ecr"][i]["rounds"][0]["outcome"]["kind"], r["ecr"][i]["rounds"][0]["outcome"]["changes"]],
                                   sort_keys=True) for r in rs if i < len(r["ecr"])}
                same += len(sigs) == 1
            g["identical_first_proposal_across_seeds"] = {"k": same, "n": len(ids)}
        out.append(g)
    out.sort(key=lambda g: (MODEL_ORDER.index(g["model"]) if g["model"] in MODEL_ORDER else 99, g["approach"]))
    return {"groups": out}


def md(summary: dict, bench: dict | None) -> str:
    G = summary["groups"]
    gpus = sorted({g["gpu"] for g in G})
    dates = sorted({d for g in G for d in g["dates"]})
    L = ["# Results", "",
         "Generated by `scripts/make_results.py` from `results/run_*.json`. Do not edit by hand.", "",
         f"- Hardware: NVIDIA L4 (24 GB), nvidia-smi reports: {', '.join(gpus)}",
         f"- Measured: {', '.join(dates)} (UTC dates of the runs)",
         "- LLM runtime: Ollama in Docker on the same machine, temperature 0, fixed seed, num_ctx 8192, JSON mode for B/C",
         "- Rates are shown as `percent [Wilson 95% CI] (k/n)`; n pools all seeds of a model/approach pair.",
         "- 36 ECRs per seed (27 feasible, 9 infeasible), 24 attack cases per seed, at most 3 human (oracle) reviews per ECR.",
         ""]
    if bench:
        rows = bench["rows"]
        f_ok = sum(1 for r in rows if r["feasible"] and r["reference_ok"])
        nf = sum(1 for r in rows if r["feasible"])
        inf = [r for r in rows if not r["feasible"]]
        L += ["## Benchmark self-check (no LLM)", "",
              f"- Reference solutions that pass all criteria and rules: {f_ok}/{nf} feasible ECRs.",
              f"- Infeasible ECRs where random search ({inf[0]['samples'] if inf else 0} samples each over the allowed "
              f"parameters) found any valid solution: {sum(1 for r in inf if r['solutions_found'])}/{len(inf)}.", ""]
    L += ["## 1. Change requests: autonomous vs. human-in-the-loop", "",
          "| model | approach | seeds | task success (first proposal) | feasible solved | infeasible refused | "
          "HITL accepted (<=3 reviews) | reviews per accepted change | wrong changes merged without HITL |",
          "|---|---|---|---|---|---|---|---|---|"]
    for g in G:
        e = g["ecr"]
        L.append(f"| {g['model']} | {APPROACH_NAME[g['approach']]} | {len(g['seeds'])} | {fmt(e['auto_success'])} | "
                 f"{fmt(e['auto_success_feasible'])} | {fmt(e['correct_refusal_infeasible'])} | {fmt(e['hitl_accepted'])} | "
                 f"{e['reviews_per_accepted']:.2f} | {fmt(e['wrong_merge_without_hitl'])} |")
    L += ["", "\"Wrong changes merged without HITL\" = first proposals that pass the automatic design-rule gate but do not "
          "do what the ECR asks (or change something unrequested, or change an infeasible ECR instead of refusing). "
          "Without a reviewer these would have been merged.", "",
          "## 2. Output quality of the first proposal", "",
          "| model | approach | rule-violating proposals | invalid outputs | schema-blocked | AST-blocked | "
          "false refusals (feasible) | mean repair rounds |", "|---|---|---|---|---|---|---|---|"]
    for g in G:
        e = g["ecr"]
        L.append(f"| {g['model']} | {APPROACH_NAME[g['approach']]} | {fmt(e['rule_violation_proposed'])} | "
                 f"{fmt(e['invalid_output'])} | {fmt(e['schema_blocked'])} | {fmt(e['ast_blocked'])} | "
                 f"{fmt(e['false_refusal_feasible'])} | {e['mean_repairs_per_step']:.2f} |")
    L += ["", "## 3. Security: attack success rate (24 cases per seed)", "",
          "Same model reply evaluated with the security layer off and on. `auto` = no human gate, `HITL` = oracle "
          "reviewer must approve before tools run and before merge (code in approach A runs before review).", "",
          "| model | approach | defences off, auto | defences on, auto | defences off, HITL | defences on, HITL | "
          "false blocks on benign ECRs |", "|---|---|---|---|---|---|---|"]
    for g in G:
        a = g["attacks"]
        if not a:
            continue
        L.append(f"| {g['model']} | {APPROACH_NAME[g['approach']]} | {fmt(a['off_auto'])} | {fmt(a['on_auto'])} | "
                 f"{fmt(a['off_hitl'])} | {fmt(a['on_hitl'])} | {fmt(g['ecr']['false_block_benign'])} |")
    L += ["", "False blocks = feasible ECRs solved with defences off but not with defences on (same reply).", "",
          "### Attack success by goal (pooled over LLM models)", "",
          "| approach | goal | n | off, auto | on, auto | on, HITL |", "|---|---|---|---|---|---|"]
    pooled: dict = defaultdict(lambda: defaultdict(lambda: [0, 0, 0, 0]))
    for g in G:
        if g["approach"] == "R":
            continue
        for goal, d in g["attacks_by_goal"].items():
            t = pooled[g["approach"]][goal]
            t[0] += d["off_auto"]["k"]
            t[1] += d["on_auto"]["k"]
            t[2] += d["on_hitl"]["k"]
            t[3] += d["off_auto"]["n"]
    for ap in sorted(pooled):
        for goal, (k_off, k_on, k_hitl, n) in sorted(pooled[ap].items()):
            L.append(f"| {APPROACH_NAME[ap]} | {goal} | {n} | {fmt(rate(k_off, n))} | {fmt(rate(k_on, n))} | "
                     f"{fmt(rate(k_hitl, n))} |")
    L += ["", "## 4. Latency and throughput on NVIDIA L4 (24 GB)", "",
          "LLM call = one Ollama chat request (warm model, cache misses only). Step = one full proposal including LLM "
          "call(s), repair rounds, geometry build, rule check and (A) sandbox start.", "",
          "| model | approach | fresh LLM calls | LLM call p50 / p95 [s] | step p50 / p95 [s] | output tok/s (median) | "
          "prompt tokens (median) | LLM calls per ECR |", "|---|---|---|---|---|---|---|---|"]
    for g in G:
        t = g["latency"]
        if g["approach"] == "R":
            L.append(f"| {g['model']} | {APPROACH_NAME['R']} | 0 | - | {t['step_p50_s']:.4f} / {t['step_p95_s']:.4f} | - | - | 0 |")
            continue
        L.append(f"| {g['model']} | {APPROACH_NAME[g['approach']]} | {t['llm_calls_fresh']} | "
                 f"{t['llm_call_p50_s']:.2f} / {t['llm_call_p95_s']:.2f} | {t['step_p50_s']:.2f} / {t['step_p95_s']:.2f} | "
                 f"{t['tokens_per_s_median']:.1f} | {t['prompt_tokens_median']:.0f} | {t['llm_calls_per_ecr_mean']:.2f} |")
    det = [g for g in G if "identical_first_proposal_across_seeds" in g]
    if det:
        L += ["", "## 5. Seed sensitivity at temperature 0", "",
              "| model | approach | ECRs with identical first proposal across seeds |", "|---|---|---|"]
        for g in det:
            d = g["identical_first_proposal_across_seeds"]
            L.append(f"| {g['model']} | {APPROACH_NAME[g['approach']]} | {d['k']}/{d['n']} |")
    L += ["", "## Source files", ""]
    for g in G:
        L.append(f"- {g['model']} / {g['approach']}: " + ", ".join(f"`results/{f}`" for f in g["files"]))
    return "\n".join(L) + "\n"


def readme_block(summary: dict) -> str:
    L = ["| model | approach | task success (auto) | HITL accepted | reviews / accepted | wrong merges w/o HITL | "
         "attacks: defences off | attacks: defences on | step p50 [s] |", "|---|---|---|---|---|---|---|---|---|"]
    for g in summary["groups"]:
        e, a, t = g["ecr"], g["attacks"], g["latency"]
        L.append(f"| {g['model']} | {APPROACH_NAME[g['approach']]} | {fmt(e['auto_success'])} | {fmt(e['hitl_accepted'])} | "
                 f"{e['reviews_per_accepted']:.2f} | {fmt(e['wrong_merge_without_hitl'])} | "
                 f"{fmt(a['off_auto']) if a else '-'} | {fmt(a['on_auto']) if a else '-'} | {t['step_p50_s']:.2f} |")
    return "\n".join(L)


def update_readme(summary: dict) -> None:
    p = ROOT / "README.md"
    if not p.exists():
        return
    s = p.read_text()
    a, b = "<!-- RESULTS:START -->", "<!-- RESULTS:END -->"
    if a in s and b in s:
        s = s[: s.index(a) + len(a)] + "\n" + readme_block(summary) + "\n" + s[s.index(b):]
        p.write_text(s)


def main() -> int:
    runs = load_runs()
    if not runs:
        print("no results/run_*.json found")
        return 1
    summary = aggregate(runs)
    bench_p = RES / "benchmark_check.json"
    bench = json.loads(bench_p.read_text()) if bench_p.exists() else None
    summary["benchmark_check"] = bench
    (RES / "summary.json").write_text(json.dumps(summary, indent=1))
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "RESULTS.md").write_text(md(summary, bench))
    update_readme(summary)
    print(f"wrote results/summary.json and docs/RESULTS.md from {len(runs)} runs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
