"""Command line: hca parts | build | check-rules | eval | review | audit verify."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="hca", description="Human-in-the-loop CAD change agents (local LLMs)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("parts", help="list part types and their parameter schemas")
    b = sub.add_parser("build", help="build a part, check rules, export STEP + SVG")
    b.add_argument("part")
    b.add_argument("--set", nargs="*", default=[], metavar="k=v")
    b.add_argument("--out", default="out/build")
    e = sub.add_parser("eval", help="run the benchmark (results/run_*.json)")
    e.add_argument("--model", default="qwen2.5-coder:7b")
    e.add_argument("--approach", choices=["A", "B", "C", "R"], required=True)
    e.add_argument("--seeds", type=int, nargs="+", default=[0])
    e.add_argument("--cases", choices=["all", "ecr", "attack"], default="all")
    e.add_argument("--limit", type=int)
    e.add_argument("--max-reviews", type=int, default=3)
    r = sub.add_parser("review", help="interactive human review of agent proposals")
    r.add_argument("part")
    r.add_argument("request", help="change request text")
    r.add_argument("--model", default="qwen2.5-coder:7b")
    r.add_argument("--approach", choices=["A", "B", "C"], default="C")
    a = sub.add_parser("audit", help="audit log tools")
    a.add_argument("action", choices=["verify"])
    a.add_argument("path", nargs="+")
    args = ap.parse_args(argv)

    if args.cmd == "parts":
        from .parts import PARTS
        from .rules import rule_texts

        for name, p in PARTS.items():
            print(f"{name}: {p.title}")
            print(json.dumps(p.params.model_json_schema()["properties"], indent=1))
            print("  rules:", *rule_texts(p), sep="\n   - ")
        return 0
    if args.cmd == "build":
        from .eval import export_revision
        from .parts import get_part
        from .rules import evaluate

        part = get_part(args.part)
        kv = dict(s.split("=", 1) for s in args.set)
        params = part.params(**{k: float(v) for k, v in kv.items()})
        shape = part.build(params)
        geo, res = evaluate(part, params, shape)
        print(json.dumps(geo.summary(), indent=1))
        for x in res:
            print(f"[{'PASS' if x.passed else 'FAIL'}] {x.rule}: {x.measured} (limit {x.limit})")
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        print(export_revision(shape, out, args.part))
        return 0 if all(x.passed for x in res) else 1
    if args.cmd == "eval":
        from .eval import run

        for s in args.seeds:
            run(args.model, args.approach, s, cases=args.cases, limit=args.limit, max_reviews=args.max_reviews)
        return 0
    if args.cmd == "review":
        from .review import interactive

        res = interactive(args.part, args.request, args.model, args.approach)
        return 0 if res["approved"] else 1
    if args.cmd == "audit":
        from .audit import verify

        bad = 0
        for p in args.path:
            ok, msg = verify(p)
            print(f"{p}: {msg}")
            bad += not ok
        return 1 if bad else 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
