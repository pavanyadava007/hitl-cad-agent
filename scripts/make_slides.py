"""Generate docs/slides.html (static, ~8 slides) from results/summary.json.

Numbers on the slides are read from the summary, never typed by hand.
Navigate with arrow keys, PageUp/PageDown or the buttons.
"""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AP = {"R": "R rules", "A": "A free code", "B": "B typed tools", "C": "C tools + repair"}


def pct(r: dict) -> str:
    return "-" if not r or not r["n"] else f"{100 * r['p']:.0f}%"


def ci(r: dict) -> str:
    return "" if not r or not r["n"] else f"<span class=ci>[{100 * r['lo']:.0f}-{100 * r['hi']:.0f}] {r['k']}/{r['n']}</span>"


def table(head: list[str], rows: list[list[str]]) -> str:
    h = "".join(f"<th>{x}</th>" for x in head)
    b = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table>"


def main() -> int:
    S = json.loads((ROOT / "results" / "summary.json").read_text())
    G = S["groups"]
    llm = [g for g in G if g["approach"] != "R"]
    dates = ", ".join(sorted({d for g in G for d in g["dates"]}))
    bench = S.get("benchmark_check") or {"rows": []}
    nf = sum(1 for r in bench["rows"] if r["feasible"])
    ref_ok = sum(1 for r in bench["rows"] if r["feasible"] and r["reference_ok"])
    inf = [r for r in bench["rows"] if not r["feasible"]]

    t_ecr = table(["model", "approach", "task success (auto)", "infeasible refused", "HITL accepted", "reviews / accepted",
                   "wrong merges w/o HITL"],
                  [[html.escape(g["model"]), AP[g["approach"]], pct(g["ecr"]["auto_success"]) + " " + ci(g["ecr"]["auto_success"]),
                    pct(g["ecr"]["correct_refusal_infeasible"]) + " " + ci(g["ecr"]["correct_refusal_infeasible"]),
                    pct(g["ecr"]["hitl_accepted"]) + " " + ci(g["ecr"]["hitl_accepted"]),
                    f"{g['ecr']['reviews_per_accepted']:.2f}",
                    pct(g["ecr"]["wrong_merge_without_hitl"]) + " " + ci(g["ecr"]["wrong_merge_without_hitl"])] for g in G])
    t_q = table(["model", "approach", "rule-violating first proposals", "invalid outputs", "mean repair rounds"],
                [[html.escape(g["model"]), AP[g["approach"]], pct(g["ecr"]["rule_violation_proposed"]) + " " + ci(g["ecr"]["rule_violation_proposed"]),
                  pct(g["ecr"]["invalid_output"]) + " " + ci(g["ecr"]["invalid_output"]), f"{g['ecr']['mean_repairs_per_step']:.2f}"] for g in llm])
    t_sec = table(["model", "approach", "defences off", "defences on", "on + HITL", "false blocks (benign)"],
                  [[html.escape(g["model"]), AP[g["approach"]], pct(g["attacks"]["off_auto"]) + " " + ci(g["attacks"]["off_auto"]),
                    pct(g["attacks"]["on_auto"]) + " " + ci(g["attacks"]["on_auto"]),
                    pct(g["attacks"]["on_hitl"]) + " " + ci(g["attacks"]["on_hitl"]),
                    pct(g["ecr"]["false_block_benign"]) + " " + ci(g["ecr"]["false_block_benign"])] for g in llm if g["attacks"]])
    t_lat = table(["model", "approach", "LLM call p50 / p95 [s]", "step p50 / p95 [s]", "output tok/s", "LLM calls / ECR"],
                  [[html.escape(g["model"]), AP[g["approach"]],
                    f"{g['latency']['llm_call_p50_s']:.2f} / {g['latency']['llm_call_p95_s']:.2f}",
                    f"{g['latency']['step_p50_s']:.2f} / {g['latency']['step_p95_s']:.2f}",
                    f"{g['latency']['tokens_per_s_median']:.0f}", f"{g['latency']['llm_calls_per_ecr_mean']:.2f}"] for g in llm])

    slides = [
        ("Local, secure human-in-the-loop CAD agents",
         f"<p class=big>Which agent architecture changes aircraft parts reliably and securely with local LLMs only?</p>"
         f"<p>Three designs, 36 change requests, 24 attacks, every proposal gated by a reviewer.<br>"
         f"Measured on NVIDIA L4 (24 GB), {dates}. Pavan Yadav Annappa - github.com/pavanyadava007/hitl-cad-agent</p>"),
        ("Setup",
         "<ul><li>4 parametric parts (wing rib, L-bracket, stringer clip, lug fitting), CadQuery, typed pydantic schemas</li>"
         "<li>Design rules measured on the real solid: e/D &gt;= 2, pitch &gt;= 3D, thickness, ligament, mass, envelope, hole count</li>"
         f"<li>36 ECRs (27 feasible, 9 infeasible); references pass for {ref_ok}/{nf}; random search finds no solution for "
         f"{sum(1 for r in inf if not r['solutions_found'])}/{len(inf)} infeasible ones</li>"
         "<li>Approaches: A free CadQuery code, B typed JSON patch, C = B + rule feedback (3 rounds); R regex baseline</li>"
         "<li>Oracle reviewer: approves only correct proposals, rejects with a reason, max 3 reviews</li></ul>"),
        ("Autonomous vs. human-in-the-loop", t_ecr + "<p class=note>Wrong merges w/o HITL = passed the automatic rule gate "
         "but still wrong. Only the reviewer catches these.</p>"),
        ("Output quality of the first proposal", t_q),
        ("Security: attack success rate", t_sec + "<p class=note>Same reply, security layer off vs. on (no human gate), "
         "and on + oracle gate. Defences: deny-by-default tools, schema, AST allowlist + network namespace, path jail, rule gate.</p>"),
        ("Latency on one NVIDIA L4 (24 GB)", t_lat),
        ("Best practices (details in BEST_PRACTICES.md)",
         "<ol><li>Let the model edit typed parameters, not code; build geometry with trusted code</li>"
         "<li>Check rules on the real geometry and feed failures back before a human sees the proposal</li>"
         "<li>Keep the human gate: it catches rule-compliant but wrong changes</li>"
         "<li>Run side-effect tools only after approval; deny everything not on the allowlist</li>"
         "<li>If code must run, run it before review in a sandbox without network, secrets or write access</li>"
         "<li>Treat requests and PLM metadata as untrusted input; log every step in a tamper-evident audit log</li></ol>"),
        ("Limits and next steps",
         "<ul><li>Oracle reviewer: review counts are a lower bound on real effort</li>"
         "<li>Simplified parts and rules; no FEA or certification rules</li>"
         "<li>Attack success = the call was made (host-safety net stops real damage)</li>"
         "<li>Next: user study with engineers, prompt-level defences, CAD-kernel tools beyond parameters, larger local models</li></ul>"),
    ]
    sec = "\n".join(f'<section class="slide"><h2>{html.escape(t)}</h2>{body}<div class=num>{i + 1} / {len(slides)}</div></section>'
                    for i, (t, body) in enumerate(slides))
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>HITL CAD Agents</title>
<style>
:root {{ --bg:#f6f7f9; --panel:#fff; --ink:#17202a; --muted:#5b6673; --line:#d9dee4; --accent:#1f5fae; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --bg:#0f1419; --panel:#172029; --ink:#e6ebf0; --muted:#9aa7b4; --line:#2a3642; --accent:#6ea8ff; }} }}
:root[data-theme="dark"] {{ --bg:#0f1419; --panel:#172029; --ink:#e6ebf0; --muted:#9aa7b4; --line:#2a3642; --accent:#6ea8ff; }}
* {{ box-sizing: border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:18px/1.5 system-ui, sans-serif; }}
.slide {{ display:none; min-height:100vh; padding:48px 16px 72px; max-width:1100px; margin:0 auto; position:relative; }}
.slide.on {{ display:block; }}
h2 {{ font-size:1.8rem; color:var(--accent); margin:0 0 20px; }}
.big {{ font-size:1.5rem; }}
table {{ border-collapse:collapse; width:100%; font-size:0.78rem; background:var(--panel); }}
th, td {{ border-bottom:1px solid var(--line); padding:5px 8px; text-align:left; }}
.ci {{ color:var(--muted); font-size:0.85em; }}
.note {{ color:var(--muted); font-size:0.9rem; }}
.num {{ position:absolute; bottom:24px; right:16px; color:var(--muted); font-size:0.85rem; }}
nav {{ position:fixed; bottom:16px; left:16px; display:flex; gap:8px; }}
button {{ font:inherit; font-size:0.9rem; padding:4px 12px; border:1px solid var(--line); background:var(--panel); color:var(--ink); border-radius:6px; }}
@media print {{ .slide {{ display:block; page-break-after:always; min-height:auto; }} nav {{ display:none; }} }}
</style></head><body>
{sec}
<nav><button id=p>Prev</button><button id=n>Next</button></nav>
<script>
const s=[...document.querySelectorAll('.slide')]; let i=0;
const show=()=>s.forEach((x,k)=>x.classList.toggle('on',k===i)); show();
const go=d=>{{i=Math.max(0,Math.min(s.length-1,i+d)); show();}};
document.getElementById('p').onclick=()=>go(-1); document.getElementById('n').onclick=()=>go(1);
document.addEventListener('keydown',e=>{{ if(['ArrowRight','PageDown',' '].includes(e.key)) go(1); if(['ArrowLeft','PageUp'].includes(e.key)) go(-1); }});
</script></body></html>
"""
    (ROOT / "docs" / "slides.html").write_text(page)
    print("wrote docs/slides.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
