"""Engineering design rules evaluated on built geometry (plus thickness parameters)."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .geometry import GeometryReport, analyze
from .parts import PartType, Strict

MIN_E_OVER_D = 2.0
MIN_PITCH_OVER_D = 3.0


@dataclass
class RuleResult:
    rule: str
    passed: bool
    measured: float | str
    limit: float | str
    text: str

    def as_dict(self) -> dict:
        d = asdict(self)
        if isinstance(d["measured"], float):
            d["measured"] = round(d["measured"], 3)
        return d


def rule_texts(part: PartType) -> list[str]:
    lim = part.limits
    out = [
        "solid: geometry must be one valid closed solid",
        f"mass: mass <= {lim['max_mass_g']} g (aluminium, 2.81 g/cm3)",
        f"envelope: bounding box X,Y,Z <= {lim['envelope_mm']} mm",
        f"edge_distance: every fastener/pin hole e/D >= {MIN_E_OVER_D} (e = centre to nearest free edge)",
        f"pitch: fastener spacing >= {MIN_PITCH_OVER_D} x D",
        f"hole_count: measured holes equal the parameters, at least {lim['min_bolts']} fasteners",
    ]
    for k, v in lim["min_thickness"].items():
        out.append(f"min_thickness_{k}: {k} >= {v} mm")
    if "min_ligament_mm" in lim:
        out.append(f"ligament: lightening hole ligament (to edge or next hole) >= {lim['min_ligament_mm']} mm")
    return out


def check(part: PartType, params: Strict | dict, geo: GeometryReport) -> list[RuleResult]:
    p = params if isinstance(params, dict) else params.model_dump()
    lim = part.limits
    res: list[RuleResult] = []
    ok_solid = geo.valid and geo.n_solids == 1
    res.append(RuleResult("solid", ok_solid, f"valid={geo.valid}, solids={geo.n_solids}", "valid, 1 solid",
                          "geometry must be one valid solid"))
    res.append(RuleResult("mass", geo.mass_g <= lim["max_mass_g"], geo.mass_g, lim["max_mass_g"], "mass [g]"))
    env = lim["envelope_mm"]
    over = [round(b - e, 3) for b, e in zip(geo.bbox, env, strict=True) if b > e + 1e-6]
    res.append(RuleResult("envelope", not over, "x".join(f"{b:.1f}" for b in geo.bbox), "x".join(f"{e:g}" for e in env),
                          "bounding box [mm]"))
    eod = geo.min_e_over_d()
    res.append(RuleResult("edge_distance", eod >= MIN_E_OVER_D - 1e-6, eod if eod != float("inf") else "no holes",
                          MIN_E_OVER_D, "min hole e/D"))
    pod = geo.min_pitch_over_d("bolt")
    res.append(RuleResult("pitch", pod >= MIN_PITCH_OVER_D - 1e-6, pod if pod != float("inf") else "n<2",
                          MIN_PITCH_OVER_D, "min fastener pitch / D"))
    # hole counts: measured vs expected from the parameters
    exp = part.expected_holes(_NS(p))
    meas = {k: len(geo.holes_of(k)) for k in exp}
    ok_count = all(meas[k] == exp[k] for k in exp) and meas.get("bolt", 0) >= lim["min_bolts"]
    res.append(RuleResult("hole_count", ok_count, str(meas), f"{exp}, bolts>={lim['min_bolts']}",
                          "measured holes vs parameters"))
    for k, v in lim["min_thickness"].items():
        val = p.get(k)
        ok = isinstance(val, (int, float)) and val >= v - 1e-9
        res.append(RuleResult(f"min_thickness_{k}", ok, val if val is not None else "missing", v, f"{k} [mm]"))
    if "min_ligament_mm" in lim:
        lig = geo.min_ligament("lightening")
        res.append(RuleResult("ligament", lig >= lim["min_ligament_mm"] - 1e-6, lig if lig != float("inf") else "no holes",
                              lim["min_ligament_mm"], "min lightening ligament [mm]"))
    return res


class _NS:
    def __init__(self, d: dict):
        self.__dict__.update(d)

    def __getattr__(self, k):  # missing params (approach A) count as 0
        return 0


def evaluate(part: PartType, params: Strict | dict, shape) -> tuple[GeometryReport, list[RuleResult]]:
    geo = analyze(shape, part.classify)
    return geo, check(part, params, geo)


def failed(results: list[RuleResult]) -> list[RuleResult]:
    return [r for r in results if not r.passed]
