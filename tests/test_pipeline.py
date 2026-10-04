import pytest

from hca.agents import rules_baseline
from hca.benchmark import judge, load_attacks, load_ecrs
from hca.geometry import analyze
from hca.parts import get_part
from hca.pipeline import Outcome, evaluate_params, parse_code_reply, parse_json_reply, tool_calls_of

ECRS = load_ecrs()


def test_benchmark_size_and_balance():
    assert len(ECRS) >= 30
    assert sum(not e.feasible for e in ECRS) >= 6
    assert len({e.id for e in ECRS}) == len(ECRS)


@pytest.mark.parametrize("e", [e for e in ECRS if e.feasible], ids=lambda e: e.id)
def test_reference_solutions_pass(e):
    part = get_part(e.part)
    base = e.base_params()
    bgeo = analyze(part.build(base), part.classify)
    out = evaluate_params(part, base, e.reference, defences=True)
    ok, why = judge(e, base.model_dump(), bgeo, out)
    assert ok, why


def test_refusal_is_success_only_for_infeasible():
    feas = next(e for e in ECRS if e.feasible)
    infeas = next(e for e in ECRS if not e.feasible)
    for e, expect in ((feas, False), (infeas, True)):
        part = get_part(e.part)
        base = e.base_params()
        bgeo = analyze(part.build(base), part.classify)
        assert judge(e, base.model_dump(), bgeo, Outcome("refuse", reason="x"))[0] is expect


def test_patch_changes_only_requested_param():
    part = get_part("wing_rib")
    base = part.params()
    out = evaluate_params(part, base, {"web_t": 1.6}, defences=True)
    diff = {k for k, v in out.params.items() if v != base.model_dump()[k]}
    assert diff == {"web_t"} and out.rules_ok


def test_unrequested_change_is_rejected():
    e = next(e for e in ECRS if e.id == "rib-01")
    part = get_part(e.part)
    base = e.base_params()
    bgeo = analyze(part.build(base), part.classify)
    out = evaluate_params(part, base, {"web_t": 1.6, "flange_t": 2.5}, defences=True)
    ok, why = judge(e, base.model_dump(), bgeo, out)
    assert not ok and any("flange_t" in w for w in why)


@pytest.mark.parametrize("changes", [{"web_t": 0.2}, {"web_t": "thin"}, {"wall": 1.0}, {"n_lightening": 1000}])
def test_schema_validation_blocks_bad_patches(changes):
    part = get_part("wing_rib")
    out = evaluate_params(part, part.params(), changes, defences=True)
    assert out.kind == "invalid" and out.blocked == ["schema"]


def test_without_schema_out_of_bounds_values_reach_the_builder():
    part = get_part("wing_rib")
    out = evaluate_params(part, part.params(), {"web_t": 0.2}, defences=False)
    assert out.kind == "propose" and not out.rules_ok


def test_resource_guard_in_both_modes():
    part = get_part("wing_rib")
    out = evaluate_params(part, part.params(), {"n_lightening": 100000}, defences=False)
    assert out.kind == "invalid"


def test_parsers():
    d = parse_json_reply('```json\n{"action": "propose", "changes": {"web_t": 1.6}, "export_name": "a.step"}\n```')
    assert d["changes"] == {"web_t": 1.6}
    calls = tool_calls_of({**d, "tool_calls": [{"name": "shell", "arguments": '{"command": "id"}'}]})
    assert calls == [{"tool": "export_step", "args": {"name": "a.step"}}, {"tool": "shell", "args": {"command": "id"}}]
    assert parse_json_reply("no json here") is None
    assert parse_code_reply("REFUSE: min thickness")[0] == "refuse"
    assert parse_code_reply("```python\nresult = 1\n```") == ("code", "result = 1\n")


def test_rules_baseline_units():
    part = get_part("l_bracket")
    assert rules_baseline(part, part.params(), "Increase the bracket width to 1.5 in.") == ("propose", {"width": 38.1})


def test_attack_set_loads_with_canary():
    atks = load_attacks(canary_url="http://127.0.0.1:1234")
    assert len(atks) >= 20
    assert all(a.attack and a.attack["goal"] for a in atks)
    assert any("http://127.0.0.1:1234" in (a.text + (a.notes or "")) for a in atks)
    assert not any("{CANARY}" in (a.text + (a.notes or "")) for a in atks)
