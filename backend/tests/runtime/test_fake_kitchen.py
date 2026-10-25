"""FakeKitchen answers every recorded facade call exactly (contracts/fixtures/facade/) and invents nothing."""

import json

import pytest

from api.settings import REPO_ROOT
from fakes.fake_kitchen import FakeKitchen, fake_compare_lanes, fake_run_backtest
from runtime.kitchen_factory import NotRecordedError, RuleError, load_engine

FIXTURES = REPO_ROOT / "contracts" / "fixtures"
FACADE_FILES = sorted((FIXTURES / "facade").glob("*.json"))


def _load(rel):
    return json.loads((FIXTURES / rel).read_text(encoding="utf-8"))


def _jsonl(rel):
    return [json.loads(line) for line in (FIXTURES / rel).read_text(encoding="utf-8").splitlines() if line.strip()]


KITCHEN_ARGS = _load("facade/kitchen.json")["args"]


@pytest.fixture
def lanes():
    base = {k: v for k, v in KITCHEN_ARGS.items() if k != "control"}
    return {lane: FakeKitchen(control=lane, **base) for lane in ("without", "with")}


@pytest.mark.parametrize("fixture_file", FACADE_FILES, ids=[f.stem for f in FACADE_FILES])
def test_facade_fixture_round_trips(lanes, fixture_file):
    fx = json.loads(fixture_file.read_text(encoding="utf-8"))
    call, args = fx["call"], fx["args"]
    if call == "Kitchen":
        kitchen = FakeKitchen(**args)
        assert kitchen.control == args["control"]
        return
    if call == "compare_lanes":
        fn = lambda **a: fake_compare_lanes(a["without"], a["with_"])  # noqa: E731
    elif call == "run_backtest":
        fn = fake_run_backtest
    else:
        fn = getattr(lanes["with"], call)

    if fx.get("raises"):
        with pytest.raises(RuleError) as err:
            fn(**args)
        assert str(err.value) == fx["raises"]["message"]
    else:
        assert fn(**args) == fx["returns"]


def test_every_step_line_round_trips(lanes):
    lines = _jsonl("facade/step_stream.jsonl")
    assert len(lines) == 240
    for line in lines:
        report = line["args"]["hub_report"]
        assert lanes[report["lane"]].step(line["args"]["minutes"], report) == line["returns"]


def test_compare_lanes_answers_every_recorded_tick_pair():
    states = {}
    for line in _jsonl("facade/step_stream.jsonl"):
        states.setdefault(line["args"]["hub_report"]["tick_id"], {})[line["args"]["hub_report"]["lane"]] = line["returns"]
    comparisons = [m["data"] for m in _jsonl("ws/stream.jsonl") if m["type"] == "comparison"]
    assert [fake_compare_lanes(s["without"], s["with"]) for _, s in sorted(states.items())] == comparisons


def test_step_rejects_the_other_lane_and_unrecorded_ticks(lanes):
    line = _jsonl("facade/step_stream.jsonl")[0]
    report = line["args"]["hub_report"]
    other = "with" if report["lane"] == "without" else "without"
    with pytest.raises(ValueError):
        lanes[other].step(1, report)
    with pytest.raises(NotRecordedError):
        lanes[report["lane"]].step(1, {**report, "tick_id": 9999})
    with pytest.raises(NotRecordedError):
        lanes[report["lane"]].step(5, report)


def test_unrecorded_arguments_are_not_faked(lanes):
    with pytest.raises(NotRecordedError):
        lanes["with"].set_peak_cap("cap", 42.0)
    with pytest.raises(NotRecordedError):
        lanes["with"].forecast(60)
    with pytest.raises(NotRecordedError):
        fake_run_backtest(["2026-08"], "base")


def test_argument_free_calls_always_answer(lanes):
    k = lanes["with"]
    assert k.warm_up("anything", months=3) is None
    assert k.set_context({"crowd_effect": {"value": "large", "set_by": "owner", "reason": "x"}}) is None
    assert k.set_preferences("Anything at all") is None
    assert k.set_authority({"enabled": False}) is None


def test_returns_are_copies(lanes):
    k = lanes["with"]
    k.snapshot()["devices"].clear()
    assert k.snapshot() == _load("facade/snapshot.json")["returns"]


def test_kitchen_with_recorded_unsafe_limits_raises_the_recorded_rule_error():
    bad_config = _load("rest/post_kitchen_422.json")["request"]
    with pytest.raises(RuleError) as err:
        FakeKitchen(bad_config, KITCHEN_ARGS["tariff"], "with", 42)
    assert str(err.value) == _load("facade/set_importance_rule_error.json")["raises"]["message"]


def test_unrecorded_kitchen_config_is_not_faked():
    config = {**KITCHEN_ARGS["config"], "name": "Another Café"}
    with pytest.raises(NotRecordedError):
        FakeKitchen(config, KITCHEN_ARGS["tariff"], "with", 42)
    with pytest.raises(ValueError):
        FakeKitchen(KITCHEN_ARGS["config"], KITCHEN_ARGS["tariff"], "both", 42)


def test_owner_resolution_matches_the_rest_fixture(lanes):
    expected = _load("rest/post_escalation_resolve.json")["response"]
    assert lanes["with"].resolve_escalation("e_0001", "accept_overrun", "owner", None) == expected


def test_claude_outside_authority_is_rejected(lanes):
    with pytest.raises(RuleError, match="outside Claude authority"):
        lanes["with"].resolve_escalation("e_0001", "deep_reduce_hvac", "claude", "Not offered")


def test_resolution_with_an_unoffered_option_is_a_rule_error(lanes):
    with pytest.raises(RuleError):
        lanes["with"].resolve_escalation("e_0001", "turn_off_freezer", "owner", None)
    with pytest.raises(NotRecordedError):
        lanes["with"].resolve_escalation("e_9999", "accept_overrun", "owner", None)


def test_factory_fake_mode():
    engine = load_engine("fake")
    assert engine.impl == "fake"
    assert engine.Kitchen is FakeKitchen
    assert engine.build_lanes.__func__ is FakeKitchen.build_lanes.__func__
    assert engine.run_backtest is fake_run_backtest
    assert engine.compare_lanes is fake_compare_lanes
    assert engine.RuleError is RuleError
    with pytest.raises(ValueError):
        load_engine("mock")


def test_build_lanes_shares_ids_and_records_warm_up():
    kitchens = FakeKitchen.build_lanes(
        KITCHEN_ARGS["config"], KITCHEN_ARGS["tariff"], KITCHEN_ARGS["seed"]
    )
    history = {"source": "test", "blocks": []}

    for kitchen in kitchens.values():
        kitchen.warm_up(history)

    assert tuple(kitchens) == ("without", "with")
    assert kitchens["without"].ids is kitchens["with"].ids
    assert [kitchen.warm_up_calls for kitchen in kitchens.values()] == [[history], [history]]
