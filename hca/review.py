"""Interactive human review (`hca review`): approve / reject with comment / edit a value."""

from __future__ import annotations

import sys
from pathlib import Path

from .agents import agent_step, initial_messages, reviewer_message
from .audit import AuditLog
from .eval import export_revision
from .geometry import analyze
from .llm import LocalLLM
from .parts import get_part
from .pipeline import evaluate_params
from .security import ALLOWED_TOOLS, new_case_dirs


def render_diff(base: dict, base_geo, out) -> str:
    lines = []
    if out.kind != "propose":
        lines.append(f"  agent result: {out.kind.upper()}  {out.reason or out.error}")
        return "\n".join(lines)
    lines.append("  parameter            before      after")
    for k, v in base.items():
        nv = (out.params or {}).get(k)
        mark = "  *" if nv != v else ""
        lines.append(f"  {k:<18} {v!s:>9}  {nv!s:>9}{mark}")
    bs, ns = base_geo.summary(), out.geo.summary()
    dm = ns["mass_g"] - bs["mass_g"]
    lines.append(f"  mass [g]           {bs['mass_g']:>9}  {ns['mass_g']:>9}  ({dm:+.2f} g, {dm / bs['mass_g']:+.1%})")
    if "min_e_over_d" in ns:
        lines.append(f"  min e/D            {bs.get('min_e_over_d', '-')!s:>9}  {ns['min_e_over_d']!s:>9}")
    lines.append(f"  holes              {bs['holes']}  ->  {ns['holes']}")
    for r in out.rules:
        lines.append(f"  [{'PASS' if r.passed else 'FAIL'}] {r.rule}: {r.measured} (limit {r.limit})")
    for t in out.tool_calls:
        flag = "" if t["tool"] in ALLOWED_TOOLS else "   <- NOT ALLOWED, will be denied"
        lines.append(f"  tool call: {t['tool']} {t.get('args')}{flag}")
    return "\n".join(lines)


def interactive(part_name: str, text: str, model: str, approach: str = "C", out_dir: str = "out/review",
                inp=input, max_rounds: int = 5) -> dict:
    part = get_part(part_name)
    base = part.params()
    bgeo = analyze(part.build(base), part.classify)
    llm = LocalLLM(model)
    out_path = Path(out_dir)
    audit = AuditLog(out_path / "review_audit.jsonl")
    audit.append("session_start", part=part_name, text=text, approach=approach, reviewer="human")
    msgs = initial_messages(approach, part, base, bgeo, part.notes, text)
    root, work, jail = new_case_dirs()
    for rnd in range(max_rounds):
        step = agent_step(approach, llm, msgs, part, base, True, work, jail)
        out = step.outcome
        audit.append("proposal", round=rnd, **out.summary())
        print(f"\n=== proposal {rnd + 1} ({approach}, {model}, {sum(c.latency_s for c in step.calls):.1f} s) ===")
        print(render_diff(base.model_dump(), bgeo, out))
        if out.kind == "propose" and out.shape is not None:
            prev = export_revision(out.shape, out_path, f"candidate{rnd + 1}")
            print(f"  preview: {prev['svg']}")
        ans = inp("[a]pprove / [r]eject with comment / [e]dit value / [q]uit > ").strip().lower()
        if ans.startswith("a"):
            audit.append("review", round=rnd, approved=True, reviewer="human")
            if out.kind == "propose" and out.shape is not None:
                exp = export_revision(out.shape, out_path, f"approved_rev{rnd + 1}")
                audit.append("merge", round=rnd, export=exp)
                print("approved, exported", exp["step"])
            return {"approved": True, "rounds": rnd + 1}
        if ans.startswith("e") and out.kind == "propose":
            key = inp("parameter > ").strip()
            val = inp("value > ").strip()
            changes = {**out.changes, key: float(val)}
            edited = evaluate_params(part, base, changes, defences=True)
            audit.append("human_edit", round=rnd, param=key, value=val, kind=edited.kind)
            print(render_diff(base.model_dump(), bgeo, edited))
            if edited.rules_ok and inp("approve edited version? [y/n] > ").strip().lower().startswith("y"):
                exp = export_revision(edited.shape, out_path, f"approved_rev{rnd + 1}_edited")
                audit.append("merge", round=rnd, export=exp, edited=True)
                print("approved, exported", exp["step"])
                return {"approved": True, "rounds": rnd + 1, "edited": True}
            note = f"I changed {key} to {val}; continue from there."
            msgs.append({"role": "user", "content": reviewer_message(approach, note)})
            continue
        if ans.startswith("q"):
            audit.append("review", round=rnd, approved=False, reason="quit", reviewer="human")
            return {"approved": False, "rounds": rnd + 1}
        comment = inp("comment for the agent > ").strip() or "Rejected."
        audit.append("review", round=rnd, approved=False, reason=comment, reviewer="human")
        msgs.append({"role": "user", "content": reviewer_message(approach, comment)})
    print("max rounds reached", file=sys.stderr)
    return {"approved": False, "rounds": max_rounds}
