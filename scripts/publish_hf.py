"""Build the static Hugging Face Space in site/ and (only with --upload) publish it.

    python scripts/publish_hf.py            # build site/ from results/ and out/
    python scripts/publish_hf.py --upload   # build, then upload to spaces/pavanyadava07/hitl-cad-agent

Everything shown on the page is read from results/summary.json, results/run_*.json
and SVG renders exported by real runs (out/<run>/<ecr>/rev*.svg).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SITE = ROOT / "site"
SPACE_ID = "pavanyadava07/hitl-cad-agent"
GALLERY_ECRS = ["rib-03", "rib-02", "brk-03", "lug-05", "clp-05", "lug-01"]
PREFERRED_RUNS = ["qwen3-coder-30b_C_s0", "qwen3-coder-30b_B_s0", "qwen2.5-coder-7b_C_s0", "llama3.1-8b_C_s0",
                  "qwen2.5-coder-7b_B_s0", "qwen3-coder-30b_A_s0", "qwen2.5-coder-7b_A_s0"]

SPACE_README = """---
title: HITL CAD Agent
emoji: "\\U0001F6E9"
colorFrom: blue
colorTo: gray
sdk: static
pinned: false
license: mit
short_description: Local, secure human-in-the-loop CAD change agents, measured
---

Static results page of https://github.com/pavanyadava007/hitl-cad-agent.
All numbers come from results/*.json produced by the evaluation scripts on an NVIDIA L4 (24 GB).
"""


def base_svgs(dest: Path) -> dict:
    from cadquery import exporters

    from hca.parts import PARTS

    out = {}
    for name, part in PARTS.items():
        p = dest / f"{name}_base.svg"
        exporters.export(part.build(part.params()), str(p),
                         opt={"width": 480, "height": 320, "marginLeft": 20, "marginTop": 20, "showAxes": False,
                              "projectionDir": (1.0, -1.4, 0.9), "showHidden": False})
        out[name] = f"assets/gallery/{p.name}"
    return out


def pick_gallery(dest: Path, runs: dict) -> list[dict]:
    items = []
    for ecr_id in GALLERY_ECRS:
        for tag in PREFERRED_RUNS:
            run = runs.get(tag)
            if not run:
                continue
            case = next((c for c in run["ecr"] if c["id"] == ecr_id), None)
            if not case or not case["hitl"]["accepted"]:
                continue
            exp = case["rounds"][-1].get("export")
            if not exp:
                continue
            src = ROOT / exp["svg"]
            if not src.exists():
                continue
            name = f"{ecr_id}_{tag}.svg"
            shutil.copy(src, dest / name)
            last = case["rounds"][-1]["outcome"]
            items.append({"ecr": ecr_id, "part": case["part"], "run": tag, "after": f"assets/gallery/{name}",
                          "changes": last["changes"], "geo": last["geo"], "reviews": case["hitl"]["n_reviews"]})
            break
    return items


def pick_sessions(runs: dict, ecr_text: dict, n: int = 3) -> list[dict]:
    """Real HITL sessions with at least one rejection that ended accepted (or correctly refused)."""
    out, seen = [], set()
    for tag in PREFERRED_RUNS:
        run = runs.get(tag)
        if not run:
            continue
        for c in run["ecr"]:
            if c["id"] in seen or c["hitl"]["n_reviews"] < 2 or not c["hitl"]["accepted"]:
                continue
            seen.add(c["id"])
            out.append({"ecr": c["id"], "part": c["part"], "text": ecr_text[c["id"]], "run": tag,
                        "model": run["meta"]["model"], "approach": run["meta"]["approach"],
                        "rounds": [{"kind": r["outcome"]["kind"], "changes": r["outcome"]["changes"],
                                    "reason_agent": r["outcome"]["reason"] or r["outcome"]["error"],
                                    "geo": r["outcome"]["geo"], "failed_rules": [f["rule"] for f in r["outcome"]["failed_rules"]],
                                    "approved": r["approved"], "review": r["reason"], "repairs": r.get("repairs", 0)}
                                   for r in c["rounds"]]})
            if len(out) >= n:
                return out
    return out


def build() -> None:
    from hca.benchmark import load_attacks, load_ecrs

    summary_p = ROOT / "results" / "summary.json"
    if not summary_p.exists():
        raise SystemExit("run scripts/make_results.py first")
    summary = json.loads(summary_p.read_text())
    runs = {}
    for p in (ROOT / "results").glob("run_*.json"):
        runs[p.stem[4:]] = json.loads(p.read_text())
    gal = SITE / "assets" / "gallery"
    shutil.rmtree(gal, ignore_errors=True)
    gal.mkdir(parents=True)
    ecrs = load_ecrs()
    attacks = load_attacks(canary_url="http://127.0.0.1:PORT")
    data = {
        "summary": summary,
        "base_svgs": base_svgs(gal),
        "gallery": pick_gallery(gal, runs),
        "sessions": pick_sessions(runs, {e.id: e.text for e in ecrs}),
        "ecrs": [{"id": e.id, "part": e.part, "text": e.text, "feasible": e.feasible} for e in ecrs],
        "attacks": [{"id": a.id, "part": a.part, "goal": a.attack["goal"], "channel": a.attack["channel"],
                     "text": a.text, "notes": a.notes} for a in attacks],
    }
    (SITE / "assets" / "data.js").write_text("window.HCA = " + json.dumps(data, indent=0) + ";\n")
    (SITE / "README.md").write_text(SPACE_README)
    print(f"site built: {len(data['gallery'])} gallery items, {len(data['sessions'])} sessions")


def upload() -> None:
    from huggingface_hub import HfApi

    api = HfApi()
    api.create_repo(SPACE_ID, repo_type="space", space_sdk="static", exist_ok=True)
    api.upload_folder(folder_path=str(SITE), repo_id=SPACE_ID, repo_type="space",
                      commit_message="Update HITL CAD agent results page")
    print(f"uploaded to https://huggingface.co/spaces/{SPACE_ID}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--upload", action="store_true", help="upload site/ to the Hugging Face Space")
    args = ap.parse_args()
    build()
    if args.upload:
        upload()
    return 0


if __name__ == "__main__":
    sys.exit(main())
