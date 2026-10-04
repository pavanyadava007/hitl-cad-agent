"""Turn an agent reply into a checked candidate design (the trusted part of the system)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import cadquery as cq
from pydantic import ValidationError

from .geometry import GeometryReport, analyze
from .parts import PartType
from .rules import RuleResult, check
from .security import extract_params, run_script

MAX_COUNT = 50  # resource guard on hole counts (kept in both modes so off-mode builds cannot hang)


@dataclass
class Outcome:
    kind: str  # propose | refuse | invalid
    params: dict | None = None
    changes: dict = field(default_factory=dict)
    geo: GeometryReport | None = None
    rules: list[RuleResult] = field(default_factory=list)
    reason: str = ""
    error: str = ""
    blocked: list[str] = field(default_factory=list)  # defences that fired
    tool_calls: list[dict] = field(default_factory=list)
    code_events: list[dict] = field(default_factory=list)  # approach A side effects while building
    shape: object | None = None
    raw: str = ""

    @property
    def rules_ok(self) -> bool:
        return self.kind == "propose" and bool(self.rules) and all(r.passed for r in self.rules)

    def summary(self) -> dict:
        return {
            "kind": self.kind,
            "changes": self.changes,
            "params": self.params,
            "geo": self.geo.summary() if self.geo else None,
            "failed_rules": [r.as_dict() for r in self.rules if not r.passed],
            "reason": self.reason[:300],
            "error": self.error[:300],
            "blocked": self.blocked,
            "tool_calls": self.tool_calls,
            "code_events": self.code_events[:10],
        }


# --------------------------------------------------------------------------- parsing


def parse_json_reply(text: str) -> dict | None:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    cand = m.group(1) if m else text
    if not cand.startswith("{"):
        i, j = cand.find("{"), cand.rfind("}")
        if i < 0 or j < 0:
            return None
        cand = cand[i : j + 1]
    try:
        d = json.loads(cand)
    except json.JSONDecodeError:
        return None
    return d if isinstance(d, dict) else None


def tool_calls_of(d: dict) -> list[dict]:
    calls = []
    if d.get("export_name"):
        calls.append({"tool": "export_step", "args": {"name": str(d["export_name"])}})
    tc = d.get("tool_calls") or []
    if isinstance(tc, dict):
        tc = [tc]
    for t in tc if isinstance(tc, list) else []:
        if isinstance(t, dict):
            name = t.get("tool") or t.get("name") or t.get("function")
            args = t.get("args") or t.get("arguments") or t.get("parameters") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {"raw": args}
            calls.append({"tool": str(name), "args": args if isinstance(args, dict) else {"raw": args}})
    return calls


def parse_code_reply(text: str) -> tuple[str, str | None]:
    """Approach A: returns ('refuse', reason) or ('code', script) or ('invalid', msg)."""
    m = re.search(r"```(?:python|py)?\s*\n(.*?)```", text, re.S)
    if m:
        return "code", m.group(1)
    s = text.strip()
    if re.match(r"^\W*refuse", s, re.I):
        return "refuse", s
    if "import cadquery" in s and "result" in s:
        return "code", s
    return "invalid", "no python code block and no REFUSE"


# --------------------------------------------------------------------------- building


class _NS:
    def __init__(self, d):
        self.__dict__.update(d)


def _coerce(base: dict, merged: dict, part: PartType) -> dict:
    out = {}
    for k, v in merged.items():
        if isinstance(v, bool):
            raise ValueError(f"{k}: boolean is not a number")
        fv = float(v)
        ann = part.params.model_fields[k].annotation if k in part.params.model_fields else float
        out[k] = int(round(fv)) if ann is int else fv
    return out


def build_trusted(part: PartType, params: dict):
    for k, f in part.params.model_fields.items():
        v = params.get(k)
        if v is None:
            raise ValueError(f"missing parameter {k}")
        if f.annotation is int and abs(v) > MAX_COUNT:
            raise ValueError(f"{k}={v} exceeds resource guard {MAX_COUNT}")
    return part.build(_NS(params))


def evaluate_params(part: PartType, base, changes: dict, defences: bool) -> Outcome:
    """Approach B/C: apply a JSON patch to the typed parameters and build with trusted code."""
    base_d = base.model_dump()
    if not isinstance(changes, dict):
        return Outcome("invalid", error="changes is not an object")
    if defences:
        try:
            new = part.params(**{**base_d, **changes})
        except ValidationError as e:
            msgs = "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()[:4])
            return Outcome("invalid", changes=changes, error=f"schema: {msgs}", blocked=["schema"])
        params = new.model_dump()
    else:
        try:
            params = _coerce(base_d, {**base_d, **changes}, part)
        except (TypeError, ValueError) as e:
            return Outcome("invalid", changes=changes, error=f"bad value: {e}")
    try:
        shape = build_trusted(part, params)
        geo = analyze(shape, part.classify)
    except Exception as e:  # noqa: BLE001 - any OCCT failure is an invalid design
        return Outcome("invalid", params=params, changes=changes, error=f"build failed: {type(e).__name__}: {e}"[:300])
    return Outcome("propose", params=params, changes=changes, geo=geo, rules=check(part, params, geo), shape=shape)


def evaluate_script(part: PartType, base, code: str, work: Path, jail: Path, defences: bool) -> Outcome:
    """Approach A: run the LLM-written script, then measure what it actually built."""
    res = run_script(code, work, jail, defences)
    events = res.events
    params = extract_params(code)
    base_d = base.model_dump()
    changes = {k: v for k, v in (params or {}).items() if k in base_d and v != base_d[k]}
    calls = [{"tool": "export_step", "args": {"name": res.export_name}}] if res.export_name else []
    if not res.ok:
        blocked = ["ast_allowlist"] if res.blocked else []
        err = "; ".join(res.blocked[:4]) if res.blocked else res.error
        return Outcome("invalid", params=params, changes=changes, error=err, blocked=blocked, code_events=events,
                       tool_calls=calls, raw=code)
    shape = cq.Shape.importBrep(str(res.brep_path))
    geo = analyze(shape, part.classify)
    p = params or {}
    rules = check(part, p, geo)
    # consistency: the parameter block must describe the geometry that was built
    try:
        ref = analyze(build_trusted(part, {**base_d, **p}), part.classify) if params else None
    except Exception:  # noqa: BLE001
        ref = None
    if ref is None:
        rules.append(RuleResult("consistency", False, "P block missing/unbuildable", "P matches geometry",
                                "parameter block vs built solid"))
    else:
        dv = abs(ref.volume_mm3 - geo.volume_mm3) / max(ref.volume_mm3, 1e-9)
        ok = dv <= 0.01 and ref.summary()["holes"] == geo.summary()["holes"]
        rules.append(RuleResult("consistency", ok, round(dv, 4), 0.01, "relative volume difference P-block vs script solid"))
    return Outcome("propose", params=p, changes=changes, geo=geo, rules=rules, shape=shape, code_events=events,
                   tool_calls=calls, raw=code)
