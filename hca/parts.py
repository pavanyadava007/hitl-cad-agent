"""Parametric, aircraft-flavoured parts written for this project (MIT).

Each part has
- a typed pydantic parameter schema with units and hard bounds,
- a builder function that only uses `cadquery` and `math` (so the same source
  can be given to an LLM as a free CadQuery script in approach A),
- design-rule limits that are checked on the built geometry (see rules.py),
- a free-text `notes` metadata field that the agent reads (and that the
  security benchmark poisons with injected instructions).
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Callable

import cadquery as cq
from pydantic import BaseModel, ConfigDict, Field

# --------------------------------------------------------------------------- builders
# Builders must stay self-contained: only `cq`, `math` and attribute access on `p`.


def build_wing_rib(p):
    L, H, tw, fw, tf = p.length, p.height, p.web_t, p.flange_w, p.flange_t
    body = cq.Workplane("XY").box(L, tw, H)
    yf = tw / 2 - fw / 2  # flanges stick out to -Y, flush with the web on +Y
    for zc in (H / 2 - tf / 2, -H / 2 + tf / 2):
        body = body.union(cq.Workplane("XY").box(L, fw, tf).translate((0, yf, zc)))
    n = int(p.n_lightening)
    if n > 0:
        pts = [(-L / 2 + L * (i + 0.5) / n, 0) for i in range(n)]
        cut = cq.Workplane("XZ").pushPoints(pts).circle(p.lightening_d / 2).extrude(tw, both=True)
        body = body.cut(cut)
    nb = int(p.n_bolts_per_flange)
    if nb > 0:
        yb = tw / 2 - fw + p.bolt_edge
        pts = [(-L / 2 + L * (j + 0.5) / nb, yb) for j in range(nb)]
        cut = cq.Workplane("XY").pushPoints(pts).circle(p.bolt_d / 2).extrude(H, both=True)
        body = body.cut(cut)
    return body


def build_l_bracket(p):
    t, w, a, b = p.thickness, p.width, p.leg_a, p.leg_b
    body = cq.Workplane("XY").box(a, w, t, centered=(False, True, False))
    body = body.union(cq.Workplane("XY").box(t, w, b, centered=(False, True, False)))
    if p.inner_fillet > 0:
        body = body.edges(cq.selectors.NearestToPointSelector((t, 0, t))).fillet(p.inner_fillet)
    pts_a = [(a - p.edge_dist - j * p.bolt_pitch, 0) for j in range(int(p.n_bolts_a))]
    if pts_a:
        body = body.cut(cq.Workplane("XY").pushPoints(pts_a).circle(p.bolt_d / 2).extrude(3 * t, both=True))
    pts_b = [(0, b - p.edge_dist - j * p.bolt_pitch) for j in range(int(p.n_bolts_b))]
    if pts_b:
        body = body.cut(cq.Workplane("YZ").pushPoints(pts_b).circle(p.bolt_d / 2).extrude(3 * t, both=True))
    return body


def build_stringer_clip(p):
    L, w, h, t = p.length, p.width, p.height, p.thickness
    body = cq.Workplane("XY").box(L, w, t, centered=(True, True, False))
    for ys in (w / 2 - t / 2, -w / 2 + t / 2):
        body = body.union(cq.Workplane("XY").box(L, t, h, centered=(True, True, False)).translate((0, ys, 0)))
    n = int(p.n_bolts)
    if n == 1:
        xs = [0.0]
    else:
        xs = [-L / 2 + p.end_dist + j * (L - 2 * p.end_dist) / (n - 1) for j in range(n)]
    body = body.cut(cq.Workplane("XY").pushPoints([(x, 0) for x in xs]).circle(p.bolt_d / 2).extrude(3 * t, both=True))
    return body


def build_lug_fitting(p):
    bl, bw, bt = p.base_len, p.base_w, p.base_t
    body = cq.Workplane("XY").box(bl, bw, bt, centered=(True, True, False))
    zc = bt + p.lug_h
    lug = cq.Workplane("XZ").center(0, bt + p.lug_h / 2).rect(p.lug_w, p.lug_h).extrude(p.lug_t / 2, both=True)
    lug = lug.union(cq.Workplane("XZ").center(0, zc).circle(p.lug_w / 2).extrude(p.lug_t / 2, both=True))
    lug = lug.cut(cq.Workplane("XZ").center(0, zc).circle(p.pin_d / 2).extrude(p.lug_t, both=True))
    body = body.union(lug)
    n = int(p.n_bolts_per_side)
    pts = []
    for xs in (bl / 2 - p.base_edge, -(bl / 2 - p.base_edge)):
        for k in range(n):
            pts.append((xs, -bw / 2 + bw * (k + 0.5) / n))
    body = body.cut(cq.Workplane("XY").pushPoints(pts).circle(p.bolt_d / 2).extrude(3 * bt, both=True))
    return body


# --------------------------------------------------------------------------- schemas


def mm(default, lo, hi, desc):
    return Field(default, ge=lo, le=hi, description=f"{desc} [mm]", json_schema_extra={"unit": "mm"})


def count(default, lo, hi, desc):
    return Field(default, ge=lo, le=hi, description=f"{desc} [count]", json_schema_extra={"unit": "count"})


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class WingRibParams(Strict):
    length: float = mm(300.0, 120, 600, "rib chord length")
    height: float = mm(100.0, 40, 200, "rib height (wing box depth)")
    web_t: float = mm(2.0, 0.5, 8, "web thickness")
    flange_w: float = mm(22.0, 8, 40, "flange width incl. web")
    flange_t: float = mm(2.0, 0.5, 8, "flange thickness")
    n_lightening: int = count(3, 0, 8, "lightening holes in the web")
    lightening_d: float = mm(50.0, 12, 150, "lightening hole diameter")
    bolt_d: float = mm(4.8, 2.5, 10, "flange fastener hole diameter")
    n_bolts_per_flange: int = count(4, 0, 12, "fastener holes per flange")
    bolt_edge: float = mm(10.0, 2, 30, "fastener centre to flange free edge")


class LBracketParams(Strict):
    leg_a: float = mm(50.0, 20, 120, "horizontal leg length")
    leg_b: float = mm(40.0, 20, 120, "vertical leg length")
    width: float = mm(30.0, 10, 100, "bracket width")
    thickness: float = mm(3.0, 0.5, 10, "sheet thickness")
    inner_fillet: float = mm(3.0, 0, 10, "inner bend fillet radius")
    bolt_d: float = mm(4.8, 2.5, 10, "fastener hole diameter")
    n_bolts_a: int = count(2, 0, 4, "fastener holes in leg A")
    n_bolts_b: int = count(2, 0, 4, "fastener holes in leg B")
    edge_dist: float = mm(10.0, 2, 40, "first hole centre to leg free end")
    bolt_pitch: float = mm(20.0, 5, 60, "fastener pitch along the leg")


class StringerClipParams(Strict):
    length: float = mm(60.0, 20, 120, "clip length")
    width: float = mm(24.0, 10, 60, "clip width (outer)")
    height: float = mm(25.0, 8, 60, "side wall height")
    thickness: float = mm(1.6, 0.4, 6, "sheet thickness")
    bolt_d: float = mm(4.0, 2.5, 8, "fastener hole diameter")
    n_bolts: int = count(2, 1, 6, "fastener holes in the base")
    end_dist: float = mm(10.0, 2, 40, "end fastener centre to clip end")


class LugFittingParams(Strict):
    base_len: float = mm(80.0, 40, 160, "base plate length")
    base_w: float = mm(60.0, 20, 120, "base plate width")
    base_t: float = mm(6.0, 1, 20, "base plate thickness")
    lug_w: float = mm(36.0, 10, 80, "lug width")
    lug_t: float = mm(8.0, 1, 30, "lug thickness")
    lug_h: float = mm(35.0, 10, 100, "pin centre height above base")
    pin_d: float = mm(8.0, 3, 30, "pin bore diameter")
    bolt_d: float = mm(6.35, 2.5, 12, "base fastener hole diameter")
    n_bolts_per_side: int = count(2, 1, 3, "base fasteners per side")
    base_edge: float = mm(14.0, 3, 40, "base fastener centre to base end")


# --------------------------------------------------------------------------- registry


@dataclass
class PartType:
    name: str
    title: str
    params: type[Strict]
    build: Callable
    classify: Callable[[float, tuple], str]
    limits: dict
    notes: str
    expected_holes: Callable[[Strict], dict] = field(default=lambda p: {})

    def script_template(self, params: Strict) -> str:
        """Full stand-alone CadQuery script for approach A (free code generation)."""
        lines = ["import math", "", "import cadquery as cq", "", "", "class P:"]
        for k, v in params.model_dump().items():
            desc = self.params.model_fields[k].description
            lines.append(f"    {k} = {v!r}  # {desc}")
        lines += ["", ""]
        lines.append(inspect.getsource(self.build).rstrip())
        lines += ["", "", f"result = {self.build.__name__}(P)", ""]
        return "\n".join(lines)


def _axis(ax) -> str:
    a = [abs(v) for v in ax]
    return "XYZ"[a.index(max(a))]


PARTS: dict[str, PartType] = {
    "wing_rib": PartType(
        name="wing_rib",
        title="Wing rib with lightening holes and C-flanges",
        params=WingRibParams,
        build=build_wing_rib,
        classify=lambda d, ax: "lightening" if _axis(ax) == "Y" else "bolt",
        limits={
            "max_mass_g": 250.0,
            "envelope_mm": (600.0, 40.0, 120.0),
            "min_thickness": {"web_t": 1.2, "flange_t": 1.2},
            "min_ligament_mm": 5.0,
            "min_bolts": 2,
        },
        notes="Material AL 2024-T3 sheet. Rib sits in the outer wing box; depth envelope 120 mm.",
        expected_holes=lambda p: {"bolt": 2 * p.n_bolts_per_flange, "lightening": p.n_lightening},
    ),
    "l_bracket": PartType(
        name="l_bracket",
        title="L-bracket / angle fitting",
        params=LBracketParams,
        build=build_l_bracket,
        classify=lambda d, ax: "bolt",
        limits={
            "max_mass_g": 40.0,
            "envelope_mm": (120.0, 60.0, 120.0),
            "min_thickness": {"thickness": 1.6},
            "min_bolts": 2,
        },
        notes="Material AL 7075-T6. Attaches a system bracket to a frame; fastener NAS1611-3 (4.8 mm hole).",
        expected_holes=lambda p: {"bolt": p.n_bolts_a + p.n_bolts_b},
    ),
    "stringer_clip": PartType(
        name="stringer_clip",
        title="Stringer clip (U-channel)",
        params=StringerClipParams,
        build=build_stringer_clip,
        classify=lambda d, ax: "bolt",
        limits={
            "max_mass_g": 30.0,
            "envelope_mm": (120.0, 40.0, 40.0),
            "min_thickness": {"thickness": 1.0},
            "min_bolts": 2,
        },
        notes="Material AL 2024-T3 clad. Connects stringer to frame; must fit 40 x 40 mm stringer bay.",
        expected_holes=lambda p: {"bolt": p.n_bolts},
    ),
    "lug_fitting": PartType(
        name="lug_fitting",
        title="Lug fitting with pin bore",
        params=LugFittingParams,
        build=build_lug_fitting,
        classify=lambda d, ax: "pin" if _axis(ax) == "Y" else "bolt",
        limits={
            "max_mass_g": 150.0,
            "envelope_mm": (160.0, 120.0, 100.0),
            "min_thickness": {"lug_t": 4.0, "base_t": 3.0},
            "min_bolts": 2,
        },
        notes="Material AL 7075-T7351 plate. Actuator attachment lug; pin bore with flanged bushing.",
        expected_holes=lambda p: {"bolt": 2 * p.n_bolts_per_side, "pin": 1},
    ),
}


def get_part(name: str) -> PartType:
    if name not in PARTS:
        raise KeyError(f"unknown part type {name!r}")
    return PARTS[name]
