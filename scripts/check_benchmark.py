"""Check the ECR benchmark itself (no LLM).

- every feasible ECR: the stored reference solution passes the judge;
- every ECR: random search over its allowed parameters (within schema bounds)
  for any design that meets the acceptance criteria and all rules. Feasible ECRs
  should have solutions; for infeasible ECRs none should be found.
Writes results/benchmark_check.json.
"""

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hca.benchmark import load_ecrs, judge  # noqa: E402
from hca.geometry import analyze  # noqa: E402
from hca.parts import get_part  # noqa: E402
from hca.pipeline import evaluate_params  # noqa: E402

N = int(sys.argv[1]) if len(sys.argv) > 1 else 300


class _Feasible:  # judge an ECR as if it were feasible
    def __init__(self, e):
        self.__dict__.update(e.__dict__)
        self.feasible = True


def main():
    rng = random.Random(0)
    rows = []
    for e in load_ecrs():
        part = get_part(e.part)
        base = e.base_params()
        bgeo = analyze(part.build(base), part.classify)
        fe = _Feasible(e)
        ref_ok = None
        if e.feasible:
            out = evaluate_params(part, base, e.reference, defences=True)
            ref_ok, why = judge(e, base.model_dump(), bgeo, out)
            if not ref_ok:
                print(e.id, "REFERENCE FAILS", why)
        found = 0
        for _ in range(N):
            ch = {}
            for k in e.allow_change:
                f = part.params.model_fields[k]
                lo = next(m.ge for m in f.metadata if hasattr(m, "ge"))
                hi = next(m.le for m in f.metadata if hasattr(m, "le"))
                ch[k] = rng.randint(int(lo), int(hi)) if f.annotation is int else round(rng.uniform(lo, hi), 2)
            for c in e.accept:  # pin exact-value targets, search the rest
                if "param" in c and c["op"] == "eq":
                    ch[c["param"]] = c["value"]
            out = evaluate_params(part, base, ch, defences=False)
            if out.kind == "propose" and judge(fe, base.model_dump(), bgeo, out)[0]:
                found += 1
        rows.append({"id": e.id, "feasible": e.feasible, "reference_ok": ref_ok, "samples": N, "solutions_found": found})
        print(f"{e.id:8s} feasible={e.feasible!s:5s} ref_ok={ref_ok!s:5s} found={found}/{N}")
    bad = [r for r in rows if (r["feasible"] and not r["reference_ok"]) or (not r["feasible"] and r["solutions_found"])]
    Path("results").mkdir(exist_ok=True)
    Path("results/benchmark_check.json").write_text(json.dumps({"rows": rows, "problems": bad}, indent=1))
    print("problems:", bad)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
