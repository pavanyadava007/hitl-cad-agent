"""Measurements on the real B-rep geometry (CadQuery / OCCT).

Everything here works on the solid that was actually built, not on the
parameters, so the same checks apply to trusted builders (approach B/C) and to
free LLM-written scripts (approach A).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import cadquery as cq

ALU_DENSITY_G_PER_MM3 = 2.81e-3  # aluminium 7075 / 2024 class, 2.81 g/cm3


@dataclass
class Hole:
    center: tuple[float, float, float]
    axis: tuple[float, float, float]
    diameter: float
    edge_distance: float  # hole centre to nearest outer edge of the exposed face (mm)
    kind: str = "bolt"

    @property
    def e_over_d(self) -> float:
        return self.edge_distance / self.diameter if self.diameter > 0 else float("inf")


@dataclass
class GeometryReport:
    valid: bool
    n_solids: int
    volume_mm3: float
    mass_g: float
    bbox: tuple[float, float, float]
    holes: list[Hole] = field(default_factory=list)

    def holes_of(self, kind: str) -> list[Hole]:
        return [h for h in self.holes if h.kind == kind]

    def min_e_over_d(self, kinds: tuple[str, ...] = ("bolt", "pin")) -> float:
        vals = [h.e_over_d for h in self.holes if h.kind in kinds]
        return min(vals) if vals else float("inf")

    def min_pitch_over_d(self, kind: str = "bolt") -> float:
        hs = self.holes_of(kind)
        best = float("inf")
        for i in range(len(hs)):
            for j in range(i + 1, len(hs)):
                d = math.dist(hs[i].center, hs[j].center)
                best = min(best, d / max(hs[i].diameter, hs[j].diameter))
        return best

    def min_ligament(self, kind: str = "lightening") -> float:
        """Smallest material width around holes of `kind` (to outer edge or to another hole)."""
        hs = self.holes_of(kind)
        best = float("inf")
        for h in hs:
            best = min(best, h.edge_distance - h.diameter / 2)
        for i in range(len(hs)):
            for j in range(i + 1, len(hs)):
                d = math.dist(hs[i].center, hs[j].center) - hs[i].diameter / 2 - hs[j].diameter / 2
                best = min(best, d)
        return best

    def summary(self) -> dict:
        kinds = sorted({h.kind for h in self.holes})
        out = {
            "valid": self.valid,
            "n_solids": self.n_solids,
            "mass_g": round(self.mass_g, 3),
            "bbox_mm": [round(v, 3) for v in self.bbox],
            "holes": {k: len(self.holes_of(k)) for k in kinds},
        }
        if any(h.kind in ("bolt", "pin") for h in self.holes):
            out["min_e_over_d"] = round(self.min_e_over_d(), 3)
        if self.holes_of("lightening"):
            out["min_ligament_mm"] = round(self.min_ligament(), 3)
        return out


def _as_shape(obj) -> cq.Shape:
    if isinstance(obj, cq.Workplane):
        vals = [v for v in obj.vals() if isinstance(v, cq.Shape)]
        if len(vals) == 1:
            return vals[0]
        return cq.Compound.makeCompound(vals)
    if isinstance(obj, cq.Shape):
        return obj
    raise TypeError(f"not a CadQuery shape: {type(obj)!r}")


def _circle_of_wire(w: cq.Wire):
    edges = w.Edges()
    if not edges or any(e.geomType() != "CIRCLE" for e in edges):
        return None
    r = edges[0].radius()
    c = edges[0].arcCenter()
    for e in edges[1:]:
        if abs(e.radius() - r) > 1e-6 or (e.arcCenter() - c).Length > 1e-6:
            return None
    if not w.IsClosed():
        return None
    return c, r


def analyze(obj, classify=None) -> GeometryReport:
    """Measure validity, solids, mass, bbox and through-holes with edge distance.

    `classify(diameter, axis) -> str` assigns a hole kind (bolt / pin / lightening).
    A hole is a circular inner wire of a planar face. The edge distance of a hole
    is measured from its centre to the outer wire of each planar face it opens
    into; the largest of those values (the exposed face) is used.
    """
    shape = _as_shape(obj)
    solids = shape.Solids()
    valid = bool(shape.isValid())
    vol = sum(s.Volume() for s in solids) if solids else 0.0
    bb = shape.BoundingBox()
    # circular inner wires of planar faces, keyed by their edges
    wire_of_edge: dict = {}
    for f in shape.Faces():
        if f.geomType() != "PLANE":
            continue
        n = f.normalAt()
        outer = f.outerWire()
        for w in f.innerWires():
            circ = _circle_of_wire(w)
            if circ is None:
                continue
            c, r = circ
            ed = cq.Vertex.makeVertex(*c.toTuple()).distance(outer)
            for e in w.Edges():
                wire_of_edge[e] = (c, r, n, ed)
    # a hole = connected cylindrical faces (OCCT may split one bore into several
    # faces) whose circular edges open into planar faces
    cyl = [f for f in shape.Faces() if f.geomType() == "CYLINDER"]
    parent = list(range(len(cyl)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    owner: dict = {}
    for i, f in enumerate(cyl):
        for e in f.Edges():
            if e.geomType() != "CIRCLE":
                continue
            if e in owner:
                parent[find(i)] = find(owner[e])
            else:
                owner[e] = i
    groups: dict[int, list] = {}
    for i in range(len(cyl)):
        groups.setdefault(find(i), []).append(cyl[i])
    holes: list[Hole] = []
    for faces in groups.values():
        hits = [wire_of_edge[e] for f in faces for e in f.Edges() if e in wire_of_edge]
        if not hits:
            continue
        c, r, n, _ = hits[0]
        ed = max(h[3] for h in hits)
        d = 2 * r
        kind = classify(d, n.toTuple()) if classify else "bolt"
        holes.append(Hole(center=c.toTuple(), axis=n.toTuple(), diameter=d, edge_distance=ed, kind=kind))
    return GeometryReport(
        valid=valid,
        n_solids=len(solids),
        volume_mm3=vol,
        mass_g=vol * ALU_DENSITY_G_PER_MM3,
        bbox=(bb.xlen, bb.ylen, bb.zlen),
        holes=holes,
    )
