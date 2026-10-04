import math

import pytest

from hca.geometry import ALU_DENSITY_G_PER_MM3
from hca.parts import PARTS, get_part
from hca.rules import evaluate, failed


def run(name, **kw):
    part = get_part(name)
    p = part.params(**kw)
    geo, res = evaluate(part, p, part.build(p))
    return geo, {r.rule: r for r in res}


@pytest.mark.parametrize("name", list(PARTS))
def test_default_designs_pass_all_rules(name):
    part = PARTS[name]
    p = part.params()
    geo, res = evaluate(part, p, part.build(p))
    assert geo.valid and geo.n_solids == 1
    assert failed(res) == []


def test_rib_mass_matches_hand_calculation():
    geo, _ = run("wing_rib")
    L, H, tw, fw, tf = 300, 100, 2, 22, 2
    vol = L * H * tw + 2 * L * fw * tf - 2 * L * tw * tf  # web + flanges - overlap
    vol -= 3 * math.pi * 25**2 * tw  # lightening holes through the web
    vol -= 8 * math.pi * 2.4**2 * tf  # fastener holes through the flanges
    assert geo.mass_g == pytest.approx(vol * ALU_DENSITY_G_PER_MM3, rel=1e-6)
    assert len(geo.holes_of("bolt")) == 8 and len(geo.holes_of("lightening")) == 3


def test_edge_distance_known_answers():
    geo, _ = run("l_bracket")
    assert geo.min_e_over_d() == pytest.approx(10 / 4.8, rel=1e-6)
    geo, _ = run("stringer_clip")
    assert geo.min_e_over_d() == pytest.approx(10 / 4.0, rel=1e-6)
    geo, _ = run("lug_fitting")
    pin = geo.holes_of("pin")[0]
    assert pin.edge_distance == pytest.approx(18.0, abs=1e-6)  # lug_w / 2
    assert pin.e_over_d == pytest.approx(18 / 8, rel=1e-6)


def test_ligament_known_answer():
    geo, _ = run("wing_rib", lightening_d=60)
    # web face is 100 mm high: 50 - 30 = 20 mm to the edge, 100 - 60 = 40 mm between holes
    assert geo.min_ligament() == pytest.approx(20.0, abs=1e-6)


@pytest.mark.parametrize(
    "name,kw,rule",
    [
        ("l_bracket", {"thickness": 1.2}, "min_thickness_thickness"),
        ("wing_rib", {"height": 140}, "envelope"),
        ("lug_fitting", {"pin_d": 20}, "edge_distance"),
        ("lug_fitting", {"lug_t": 25}, "mass"),
        ("stringer_clip", {"n_bolts": 6}, "pitch"),
        ("l_bracket", {"bolt_d": 6.35}, "edge_distance"),
        ("wing_rib", {"lightening_d": 94}, "ligament"),
        ("wing_rib", {"n_lightening": 4, "lightening_d": 80}, "hole_count"),  # overlapping cutters: count differs
        ("wing_rib", {"n_lightening": 4, "lightening_d": 80}, "solid"),
        ("stringer_clip", {"n_bolts": 1}, "hole_count"),  # below the minimum fastener count
    ],
)
def test_rule_violations_are_detected(name, kw, rule):
    _, res = run(name, **kw)
    assert not res[rule].passed, res[rule]
