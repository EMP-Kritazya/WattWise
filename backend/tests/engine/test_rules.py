"""Hand-computed tests for `engine/rules.py` (ENGINE.md section 8, section 15 "Catalog", golden rule 4).

Written before the code (engine-test-author). Every expected value below is worked out by hand from ENGINE.md /
CONTRACTS.md, never taken from engine output.

ASSUMED INTERNAL API of `engine.rules` (ENGINE.md section 8 does not name functions; engine-builder implements exactly this,
or changes these tests together with the main session):

    RuleError                                   # the same class as `engine.RuleError`
    FOOD_SAFETY_MIN_POWER_PCT: int = 50

    power_floor_pct(category: str) -> int
        50 for "refrigeration", else 0 (the absolute floor; ENGINE.md section 6 harm "floor").

    validate_limits(importance: str, limits: dict, category: str) -> None
        Raises RuleError for unsafe limits (used by set_importance and for catalog default_limits):
          always_on  : limits == {}
          flexible   : keys min_power_pct, max_reduce_min; 0 < min_power_pct <= 100; max_reduce_min > 0;
                       refrigeration needs min_power_pct >= 50
          deferrable : keys max_delay_min, must_finish_by; max_delay_min >= 0; must_finish_by "HH:MM"
          unknown importance -> RuleError

    check_engine_command(importance: str, action: str) -> None
        An engine-issued Command on an always_on device -> RuleError, whatever the action.

    check_reduce(importance: str, limits: dict, category: str, value_pct: int, *, escalation: bool = False) -> None
        `reduce` value = % of rated_kw. RuleError if: importance is not flexible; value outside 0..100;
        value < min_power_pct (unless escalation=True: an escalation option may break min_power_pct);
        value < power_floor_pct(category) ALWAYS (food safety, not even by escalation).

    effective_deadline_min(must_finish_by: str, close: str) -> int
        min(must_finish_by, close) as minutes after local midnight ("19:30" -> 1170).

    check_hold(importance: str, limits: dict, *, close: str, cycle_min: int,
               first_applied_min: int, release_min: int, open: str | None = None) -> None
        Times are minutes after local midnight today. RuleError if importance is not deferrable;
        `open` given and first_applied_min < open (holds start only during operating_hours, ENGINE.md §5);
        release_min - first_applied_min > max_delay_min; or release_min + cycle_min > effective deadline.
        Exactly hitting either bound is allowed.

Facade tests use only `from engine import Kitchen, RuleError` (CONTRACTS.md section 3): `set_importance`, `set_peak_cap`,
and Commands emitted by `step`. Config / tariff / catalog come from `contracts/fixtures/shapes/` and are validated with
`backend/contracts/` models, then passed to the engine as plain dicts (golden rule 7: plain objects in).
"""
from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from contracts import (
    ClaudeAuthority,
    EquipmentType,
    HubReport,
    KitchenConfig,
    Tariff,
)

# ---------------------------------------------------------------------------------------------------------------------
# Paths and helpers (local to this file; conftest.py belongs to another agent)
# ---------------------------------------------------------------------------------------------------------------------

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
SHAPES = REPO / "contracts" / "fixtures" / "shapes"
CATALOG_REAL = BACKEND / "data" / "equipment_catalog.json"
CATALOG_FIXTURE = SHAPES / "equipment_catalog.json"

ROUTINE_REASONS = {"stay_under_cap", "avoid_new_peak", "release_into_valley", "catch_up"}


@pytest.fixture
def rules():
    """Lazy import so a missing module fails each test, not the whole collection."""
    import engine.rules as r

    return r


@pytest.fixture
def engine_api():
    import engine

    return engine


def _load_json(path: Path):
    return json.loads(path.read_text())


def _catalog() -> list[dict]:
    path = CATALOG_REAL if CATALOG_REAL.exists() else CATALOG_FIXTURE
    raw = _load_json(path)
    for entry in raw:
        EquipmentType.model_validate(entry)  # contract-valid input
    return raw


def _category(type_id: str) -> str:
    return {e["type_id"]: e["category"] for e in _catalog()}[type_id]


def _config() -> dict:
    raw = _load_json(SHAPES / "kitchen_config.json")
    KitchenConfig.model_validate(raw)
    return raw


def _tariff() -> dict:
    raw = _load_json(SHAPES / "tariff.json")
    Tariff.model_validate(raw)
    return raw


def _as_dict(obj):
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    return obj


# ---------------------------------------------------------------------------------------------------------------------
# 1. Catalog: every default_limits passes rules.py (ENGINE.md §15 "Catalog", §8 last bullet)
# ---------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("entry", _catalog(), ids=lambda e: e["type_id"])
def test_catalog_default_limits_pass_rules(rules, entry):
    # §8: every equipment type's default_limits in equipment_catalog.json passes these rules
    rules.validate_limits(entry["default_importance"], entry["default_limits"], entry["category"])


def test_catalog_walk_in_cooler_flexible_at_least_50(rules):
    walk_in = next(e for e in _catalog() if e["type_id"] == "walk_in_cooler")
    assert walk_in["category"] == "refrigeration"
    assert walk_in["default_importance"] == "flexible"
    # food-safety floor: refrigeration flexible -> min_power_pct >= 50
    assert walk_in["default_limits"]["min_power_pct"] >= 50
    rules.validate_limits("flexible", walk_in["default_limits"], "refrigeration")


def test_catalog_walk_in_cooler_at_49_would_fail(rules):
    # one point below the floor: 49 < 50 -> RuleError
    walk_in = copy.deepcopy(next(e for e in _catalog() if e["type_id"] == "walk_in_cooler"))
    walk_in["default_limits"]["min_power_pct"] = 49
    with pytest.raises(rules.RuleError):
        rules.validate_limits("flexible", walk_in["default_limits"], "refrigeration")


def test_kitchen_builds_from_catalog_defaults(engine_api):
    # A kitchen with one unit of every catalog type at its default importance + default limits must build
    # (no RuleError): the catalog defaults are what a new unit starts with (CONTRACTS.md §1 EquipmentType).
    config = _config()
    config["equipment"] = [
        {"type_id": e["type_id"], "count": 1, "importance": e["default_importance"], "limits": e["default_limits"]}
        for e in _catalog()
    ]
    KitchenConfig.model_validate(config)
    engine_api.Kitchen(config, _tariff(), _catalog(), "with", 42)


# ---------------------------------------------------------------------------------------------------------------------
# 2. validate_limits: the §8 bounds, each edge exactly hit
# ---------------------------------------------------------------------------------------------------------------------


def test_rule_error_is_the_public_one(rules, engine_api):
    assert rules.RuleError is engine_api.RuleError


def test_food_safety_constant_and_floor(rules):
    assert rules.FOOD_SAFETY_MIN_POWER_PCT == 50
    # floor = 50 refrigeration else 0 (ENGINE.md §6 harm tolerance)
    assert rules.power_floor_pct("refrigeration") == 50
    for cat in ("cooling", "cooking", "water_heating", "lighting", "other"):
        assert rules.power_floor_pct(cat) == 0


def test_always_on_empty_limits_ok(rules):
    rules.validate_limits("always_on", {}, "cooking")
    rules.validate_limits("always_on", {}, "refrigeration")


@pytest.mark.parametrize("min_pct", [1, 40, 100])
def test_flexible_min_power_pct_in_range_ok(rules, min_pct):
    # 0 < min_power_pct <= 100: 1 (lowest), 40 (hvac default), 100 (exactly the top)
    rules.validate_limits("flexible", {"min_power_pct": min_pct, "max_reduce_min": 30}, "cooling")


@pytest.mark.parametrize("min_pct", [0, -5, 101])
def test_flexible_min_power_pct_out_of_range_raises(rules, min_pct):
    # 0 is not > 0; 101 > 100
    with pytest.raises(rules.RuleError):
        rules.validate_limits("flexible", {"min_power_pct": min_pct, "max_reduce_min": 30}, "cooling")


def test_flexible_max_reduce_min_one_ok(rules):
    # max_reduce_min > 0: 1 is the smallest allowed
    rules.validate_limits("flexible", {"min_power_pct": 40, "max_reduce_min": 1}, "cooling")


@pytest.mark.parametrize("max_reduce", [0, -1])
def test_flexible_max_reduce_min_not_positive_raises(rules, max_reduce):
    # stricter than the Pydantic NonNegInt: 0 is not > 0
    with pytest.raises(rules.RuleError):
        rules.validate_limits("flexible", {"min_power_pct": 40, "max_reduce_min": max_reduce}, "cooling")


def test_refrigeration_flexible_exactly_50_ok(rules):
    # food-safety floor exactly hit: 50 >= 50
    rules.validate_limits("flexible", {"min_power_pct": 50, "max_reduce_min": 30}, "refrigeration")


@pytest.mark.parametrize("min_pct", [49, 30, 1])
def test_refrigeration_flexible_below_50_raises(rules, min_pct):
    with pytest.raises(rules.RuleError):
        rules.validate_limits("flexible", {"min_power_pct": min_pct, "max_reduce_min": 30}, "refrigeration")


def test_non_refrigeration_flexible_below_50_ok(rules):
    # the 50 % floor is only for refrigeration; water heater default is 40
    rules.validate_limits("flexible", {"min_power_pct": 40, "max_reduce_min": 30}, "water_heating")


@pytest.mark.parametrize("max_delay", [0, 60])
def test_deferrable_max_delay_min_non_negative_ok(rules, max_delay):
    # max_delay_min >= 0: 0 exactly hit, 60 the catalog default
    rules.validate_limits("deferrable", {"max_delay_min": max_delay, "must_finish_by": "15:30"}, "water_heating")


def test_deferrable_negative_max_delay_raises(rules):
    with pytest.raises(rules.RuleError):
        rules.validate_limits("deferrable", {"max_delay_min": -1, "must_finish_by": "15:30"}, "water_heating")


@pytest.mark.parametrize("hhmm", ["00:00", "15:30", "19:30", "23:59"])
def test_deferrable_must_finish_by_hhmm_ok(rules, hhmm):
    rules.validate_limits("deferrable", {"max_delay_min": 60, "must_finish_by": hhmm}, "water_heating")


@pytest.mark.parametrize("bad", ["3:30pm", "25:00", "15:60", "1530", "", "15:30:00"])
def test_deferrable_must_finish_by_not_hhmm_raises(rules, bad):
    with pytest.raises(rules.RuleError):
        rules.validate_limits("deferrable", {"max_delay_min": 60, "must_finish_by": bad}, "water_heating")


@pytest.mark.parametrize(
    "importance,limits",
    [
        ("flexible", {}),
        ("flexible", {"min_power_pct": 40}),
        ("flexible", {"max_reduce_min": 30}),
        ("deferrable", {}),
        ("deferrable", {"max_delay_min": 60}),
        ("deferrable", {"must_finish_by": "15:30"}),
        ("flexible", {"max_delay_min": 60, "must_finish_by": "15:30"}),  # limits of the wrong importance
    ],
)
def test_missing_or_wrong_limits_raise(rules, importance, limits):
    with pytest.raises(rules.RuleError):
        rules.validate_limits(importance, limits, "water_heating")


def test_unknown_importance_raises(rules):
    with pytest.raises(rules.RuleError):
        rules.validate_limits("sometimes", {}, "cooking")


# ---------------------------------------------------------------------------------------------------------------------
# 3. Engine moves: always_on never commanded
# ---------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("action", ["on", "off", "start", "delay", "reduce", "restore"])
def test_always_on_never_commanded(rules, action):
    with pytest.raises(rules.RuleError):
        rules.check_engine_command("always_on", action)


@pytest.mark.parametrize("importance,action", [("flexible", "reduce"), ("flexible", "restore"),
                                               ("deferrable", "delay"), ("deferrable", "start")])
def test_controllable_devices_may_be_commanded(rules, importance, action):
    rules.check_engine_command(importance, action)


# ---------------------------------------------------------------------------------------------------------------------
# 4. Reduce: value >= min_power_pct; refrigeration >= 50 even by escalation
# ---------------------------------------------------------------------------------------------------------------------

HVAC_LIMITS = {"min_power_pct": 40, "max_reduce_min": 30}
WALK_IN_LIMITS = {"min_power_pct": 50, "max_reduce_min": 30}


def test_reduce_exactly_min_power_ok(rules):
    # HVAC rated 12 kW, min 40 %: reduce 40 -> 40 % × 12 kW = 4.8 kW, exactly the floor, allowed
    rules.check_reduce("flexible", HVAC_LIMITS, "cooling", 40)


def test_reduce_section15_value_60_ok(rules):
    # §15 flexible case: 10 kW HVAC, excess 4 kW -> (10 − 4) / 10 = 60 %, 60 >= 40
    rules.check_reduce("flexible", HVAC_LIMITS, "cooling", 60)


def test_reduce_full_power_ok(rules):
    rules.check_reduce("flexible", HVAC_LIMITS, "cooling", 100)


def test_reduce_one_below_min_power_raises(rules):
    # 39 < 40 -> outside the owner's rules
    with pytest.raises(rules.RuleError):
        rules.check_reduce("flexible", HVAC_LIMITS, "cooling", 39)


def test_reduce_below_min_power_allowed_only_through_escalation(rules):
    # §8: a move that breaks a limit only happens through an Escalation (e.g. deep_reduce_hvac 30 %, 10 pct below min)
    rules.check_reduce("flexible", HVAC_LIMITS, "cooling", 30, escalation=True)


@pytest.mark.parametrize("value", [-1, 101])
def test_reduce_value_outside_0_100_raises(rules, value):
    with pytest.raises(rules.RuleError):
        rules.check_reduce("flexible", HVAC_LIMITS, "cooling", value, escalation=True)


def test_reduce_refrigeration_exactly_50_ok(rules):
    # walk-in rated 3.5 kW: 50 % × 3.5 = 1.75 kW, exactly the food-safety floor
    rules.check_reduce("flexible", WALK_IN_LIMITS, "refrigeration", 50)


@pytest.mark.parametrize("escalation", [False, True])
def test_reduce_refrigeration_below_50_never(rules, escalation):
    # food safety: 49 < 50 is never crossable, not even by escalation
    with pytest.raises(rules.RuleError):
        rules.check_reduce("flexible", WALK_IN_LIMITS, "refrigeration", 49, escalation=escalation)


def test_reduce_refrigeration_owner_min_above_floor(rules):
    # owner set walk-in min 60: 55 breaks the owner's rule (escalation may), 49 breaks food safety (never)
    limits = {"min_power_pct": 60, "max_reduce_min": 30}
    with pytest.raises(rules.RuleError):
        rules.check_reduce("flexible", limits, "refrigeration", 55)
    rules.check_reduce("flexible", limits, "refrigeration", 55, escalation=True)
    with pytest.raises(rules.RuleError):
        rules.check_reduce("flexible", limits, "refrigeration", 49, escalation=True)


@pytest.mark.parametrize("importance,limits", [("always_on", {}),
                                               ("deferrable", {"max_delay_min": 60, "must_finish_by": "19:30"})])
def test_reduce_only_for_flexible(rules, importance, limits):
    with pytest.raises(rules.RuleError):
        rules.check_reduce(importance, limits, "cooling", 80, escalation=True)


# ---------------------------------------------------------------------------------------------------------------------
# 5. Holds: inside max_delay_min and the effective deadline min(must_finish_by, close)
# ---------------------------------------------------------------------------------------------------------------------

DISHWASHER_DEMO = {"max_delay_min": 60, "must_finish_by": "19:30"}  # Demo Café dishwasher
CLOSE = "22:00"


@pytest.mark.parametrize(
    "must,close,expected",
    [
        ("19:30", "22:00", 1170),  # 19 × 60 + 30 = 1170 (demo dishwasher; deadline earlier than close)
        ("15:30", "22:00", 930),   # 15 × 60 + 30 = 930 (catalog dishwasher default)
        ("22:00", "22:00", 1320),  # 22 × 60 = 1320 (ice machine: deadline == close)
        ("23:00", "22:00", 1320),  # min(1380, 1320) = 1320 (close earlier than the deadline)
    ],
)
def test_effective_deadline(rules, must, close, expected):
    assert rules.effective_deadline_min(must, close) == expected


def test_hold_finish_exactly_at_must_finish_by_ok(rules):
    # first delay applied 18:30 (1110), release 19:00 (1140): hold 1140 − 1110 = 30 <= 60;
    # finish 1140 + 30 = 1170 = 19:30 = deadline exactly -> allowed
    rules.check_hold("deferrable", DISHWASHER_DEMO, close=CLOSE, cycle_min=30, first_applied_min=1110, release_min=1140)


def test_hold_one_minute_past_must_finish_by_raises(rules):
    # release 19:01 (1141): finish 1141 + 30 = 1171 > 1170 -> past the deadline although hold 31 <= 60
    with pytest.raises(rules.RuleError):
        rules.check_hold("deferrable", DISHWASHER_DEMO, close=CLOSE, cycle_min=30,
                         first_applied_min=1110, release_min=1141)


def test_hold_exactly_max_delay_ok(rules):
    # first applied 17:30 (1050), release 18:30 (1110): hold 60 = max_delay_min; finish 1140 = 19:00 <= 19:30
    rules.check_hold("deferrable", DISHWASHER_DEMO, close=CLOSE, cycle_min=30, first_applied_min=1050, release_min=1110)


def test_hold_one_minute_over_max_delay_raises(rules):
    # release 18:31 (1111): hold 61 > 60; finish 1141 = 19:01 still before 19:30, so only max_delay breaks
    with pytest.raises(rules.RuleError):
        rules.check_hold("deferrable", DISHWASHER_DEMO, close=CLOSE, cycle_min=30,
                         first_applied_min=1050, release_min=1111)


def test_hold_bounded_by_close_when_close_is_earlier(rules):
    # must_finish_by 23:00, close 22:00 -> effective 1320. First 21:00 (1260):
    # release 21:30 (1290) + 30 = 1320 exactly -> ok; release 21:31 (1291) + 30 = 1321 > 1320 -> RuleError
    limits = {"max_delay_min": 60, "must_finish_by": "23:00"}
    rules.check_hold("deferrable", limits, close="22:00", cycle_min=30, first_applied_min=1260, release_min=1290)
    with pytest.raises(rules.RuleError):
        rules.check_hold("deferrable", limits, close="22:00", cycle_min=30, first_applied_min=1260, release_min=1291)


def test_hold_ice_machine_deadline_equals_close(rules):
    # ice machine cycle 20, must_finish_by 22:00, close 22:00 -> effective 1320. First 21:00 (1260):
    # release 21:40 (1300) + 20 = 1320 -> ok; release 21:41 (1301) + 20 = 1321 -> RuleError
    limits = {"max_delay_min": 60, "must_finish_by": "22:00"}
    rules.check_hold("deferrable", limits, close="22:00", cycle_min=20, first_applied_min=1260, release_min=1300)
    with pytest.raises(rules.RuleError):
        rules.check_hold("deferrable", limits, close="22:00", cycle_min=20, first_applied_min=1260, release_min=1301)


@pytest.mark.parametrize("release", [1095, 1110, 1125, 1140])
def test_hold_release_on_block_boundaries(rules, release):
    # first applied 18:15 (1095); releases at :15/:30/:45/:00 -> holds 0, 15, 30, 45 <= 60;
    # finishes 1125, 1140, 1155, 1170 <= 1170 -> all allowed (the last one exactly at 19:30)
    rules.check_hold("deferrable", DISHWASHER_DEMO, close=CLOSE, cycle_min=30,
                     first_applied_min=1095, release_min=release)


def test_hold_job_that_cannot_finish_is_not_delayable(rules):
    # catalog dishwasher default 15:30 (930), cycle 30 -> latest release 900 = 15:00.
    # First applied 15:00 (900), release 15:05 (905): finish 935 > 930 -> not delayable
    limits = {"max_delay_min": 60, "must_finish_by": "15:30"}
    with pytest.raises(rules.RuleError):
        rules.check_hold("deferrable", limits, close=CLOSE, cycle_min=30, first_applied_min=900, release_min=905)


def test_hold_starts_only_during_operating_hours(rules):
    # open 10:00 (600). A hold first applied 09:30 (570) starts before opening -> RuleError;
    # first applied exactly 10:00 (600), release 10:30 (630): hold 30 <= 60, finish 660 <= 1170 -> ok
    with pytest.raises(rules.RuleError):
        rules.check_hold("deferrable", DISHWASHER_DEMO, close=CLOSE, open="10:00", cycle_min=30,
                         first_applied_min=570, release_min=600)
    rules.check_hold("deferrable", DISHWASHER_DEMO, close=CLOSE, open="10:00", cycle_min=30,
                     first_applied_min=600, release_min=630)


@pytest.mark.parametrize("importance,limits", [("always_on", {}), ("flexible", HVAC_LIMITS)])
def test_hold_only_for_deferrable(rules, importance, limits):
    with pytest.raises(rules.RuleError):
        rules.check_hold(importance, limits, close=CLOSE, cycle_min=30, first_applied_min=1050, release_min=1060)


# ---------------------------------------------------------------------------------------------------------------------
# 6. Facade: set_importance / set_peak_cap RuleError cases (CONTRACTS.md §3, facade/*_rule_error.json)
# ---------------------------------------------------------------------------------------------------------------------

T0 = datetime(2026, 7, 18, 0, 25, tzinfo=timezone.utc)  # 17:25 PDT; tick 5 ends at 00:30Z = 17:30 local block start

# Demo Café roster with a fixed hand-chosen draw (kW). always_on total:
#   fryer 10 + oven 6 + grill 5 + lights 2.4 + reach-in 0.8 + freezer 1.4 = 25.6 kW
# flexible: hvac 9 + 9, walk-in 3.5, water heater 4.5 = 26.0 kW ; jobs idle (0 kW)
# total = 25.6 + 26.0 = 51.6 kW > cap 40 -> excess 11.6 kW
# in-rules room: hvac 2 × (9 − 40 % × 12 = 4.8) = 8.4, walk-in 3.5 − 50 % × 3.5 = 1.75, water heater 4.5 − 40 % × 4.5 = 2.7
#   -> 8.4 + 1.75 + 2.7 = 12.85 kW >= 11.6, so the decider has to reduce (non-vacuous) and can stay inside the rules.
BASE_DRAW_KW = {
    "hvac_1": 9.0, "hvac_2": 9.0, "walk_in_cooler_1": 3.5, "reach_in_fridge_1": 0.8, "freezer_1": 1.4,
    "ice_machine_1": 0.0, "fryer_1": 10.0, "oven_1": 6.0, "grill_1": 5.0, "dishwasher_1": 0.0,
    "water_heater_1": 4.5, "lights_1": 2.4,
}


class _MiniHub:
    """Tiny stand-in for the browser hub: applies reduce/restore to the draw, acks every Command next tick."""

    def __init__(self, config: dict):
        cat = {e["type_id"]: e for e in _catalog()}
        self.devices: dict[str, dict] = {}
        for entry in config["equipment"]:
            for n in range(1, entry["count"] + 1):
                did = f"{entry['type_id']}_{n}"
                t = cat[entry["type_id"]]
                self.devices[did] = {
                    "device_id": did, "type_id": t["type_id"], "name": f"{t['name']} {n}",
                    "importance": entry["importance"], "rated_kw": t["rated_kw"],
                }
        self.cap_pct: dict[str, int] = {}
        self.pending_acks: list[dict] = []

    def deliver(self, commands: list[dict]):
        for c in commands:
            if c["action"] == "reduce":
                self.cap_pct[c["device_id"]] = c["value"]
            elif c["action"] == "restore":
                self.cap_pct.pop(c["device_id"], None)
            self.pending_acks.append(
                {"command_id": c["command_id"], "lane": c["lane"], "ok": True, "applied_value": c["value"], "reason": None}
            )

    def report(self, tick_id: int) -> dict:
        devices = []
        for did, d in self.devices.items():
            kw = BASE_DRAW_KW[did]
            state = "on" if kw > 0 else "off"
            if did in self.cap_pct:
                kw = min(kw, self.cap_pct[did] / 100 * d["rated_kw"])
                state = "reduced"
            devices.append({**d, "state": state, "power_kw": round(kw, 4),
                            "power_pct": round(100 * kw / d["rated_kw"]), "source": "simulated"})
        rep = {
            "hub_id": "sim_hub", "lane": "with", "tick_id": tick_id,
            "ts": (T0 + timedelta(minutes=tick_id)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "total_kw": round(sum(d["power_kw"] for d in devices), 4), "customers_per_hour": 60,
            "devices": devices, "acks": self.pending_acks, "source": "simulated",
        }
        self.pending_acks = []
        HubReport.model_validate(rep)
        return rep


def _new_kitchen(engine_api, config=None):
    config = config or _config()
    return engine_api.Kitchen(config, _tariff(), _catalog(), "with", 42), _MiniHub(config)


def _run(kitchen, hub, first_tick: int, last_tick: int, set_importance_hook=None):
    """Step ticks first..last; return [(command, reason_code)] for every Command emitted."""
    out = []
    for tick in range(first_tick, last_tick + 1):
        state = _as_dict(kitchen.step(1, hub.report(tick)))
        reasons = {d["decision_id"]: d["reason_code"] for d in state.get("new_decisions") or []}
        cmds = [_as_dict(c) for c in state.get("new_commands") or []]
        for c in cmds:
            out.append((c, reasons.get(c.get("decision_id"))))
        hub.deliver(cmds)
    return out


def test_set_importance_refrigeration_below_50_raises(engine_api):
    # facade/set_importance_rule_error.json: walk-in flexible with min 30 -> RuleError (30 < 50)
    kitchen, hub = _new_kitchen(engine_api)
    kitchen.step(1, hub.report(1))
    with pytest.raises(engine_api.RuleError):
        kitchen.set_importance("walk_in_cooler_1", "flexible", {"min_power_pct": 30, "max_reduce_min": 30})


@pytest.mark.parametrize(
    "device_id,importance,limits",
    [
        ("hvac_1", "flexible", {"min_power_pct": 0, "max_reduce_min": 30}),
        ("hvac_1", "flexible", {"min_power_pct": 40, "max_reduce_min": 0}),
        ("hvac_1", "flexible", {"min_power_pct": 101, "max_reduce_min": 30}),
        ("dishwasher_1", "deferrable", {"max_delay_min": -1, "must_finish_by": "19:30"}),
        ("dishwasher_1", "deferrable", {"max_delay_min": 60, "must_finish_by": "7:30pm"}),
        ("dishwasher_1", "deferrable", {}),
    ],
)
def test_set_importance_unsafe_limits_raise(engine_api, device_id, importance, limits):
    kitchen, hub = _new_kitchen(engine_api)
    kitchen.step(1, hub.report(1))
    with pytest.raises(engine_api.RuleError):
        kitchen.set_importance(device_id, importance, limits)


def test_set_importance_valid_returns_device(engine_api):
    # facade/set_importance.json: walk-in -> always_on, {} -> Device with importance always_on
    kitchen, hub = _new_kitchen(engine_api)
    kitchen.step(1, hub.report(1))
    device = _as_dict(kitchen.set_importance("walk_in_cooler_1", "always_on", {}))
    assert device["device_id"] == "walk_in_cooler_1"
    assert device["importance"] == "always_on"


def test_set_importance_walk_in_exactly_50_ok(engine_api):
    kitchen, hub = _new_kitchen(engine_api)
    kitchen.step(1, hub.report(1))
    device = _as_dict(kitchen.set_importance("walk_in_cooler_1", "flexible", {"min_power_pct": 50, "max_reduce_min": 30}))
    assert device["importance"] == "flexible"


# ---------------------------------------------------------------------------------------------------------------------
# §8 (new): refrigeration may be deferrable only if its power_model is `job` (the ice machine); a cycling refrigeration
# device on a hold would sit at 0 % -> below the 50 % food-safety floor -> RuleError, through set_importance and config.
# ---------------------------------------------------------------------------------------------------------------------

DEFER_LIMITS = {"max_delay_min": 30, "must_finish_by": "22:00"}  # valid deferrable limits on their own


def test_cycling_refrigeration_types_in_catalog():
    # the rule keys on catalog facts: walk-in / reach-in / freezer are refrigeration + cycling, ice machine is
    # refrigeration + job (so the facade tests below exercise both branches)
    cat = {e["type_id"]: e for e in _catalog()}
    for t in ("walk_in_cooler", "reach_in_fridge", "freezer"):
        assert (cat[t]["category"], cat[t]["power_model"]) == ("refrigeration", "cycling")
    assert (cat["ice_machine"]["category"], cat["ice_machine"]["power_model"]) == ("refrigeration", "job")


@pytest.mark.parametrize("device_id", ["walk_in_cooler_1", "reach_in_fridge_1", "freezer_1"])
def test_set_importance_cycling_refrigeration_deferrable_raises(engine_api, device_id):
    kitchen, hub = _new_kitchen(engine_api)
    kitchen.step(1, hub.report(1))
    before = _as_dict(kitchen.snapshot())
    with pytest.raises(engine_api.RuleError):
        kitchen.set_importance(device_id, "deferrable", dict(DEFER_LIMITS))
    # rejected -> nothing changed: the device keeps its importance in the next snapshot
    after = _as_dict(kitchen.snapshot())
    imp = lambda snap: {d["device_id"]: d["importance"] for d in snap["devices"]}  # noqa: E731
    assert imp(after)[device_id] == imp(before)[device_id]


def test_set_importance_ice_machine_deferrable_ok(engine_api):
    # ice machine: refrigeration + job -> deferrable allowed (a hold delays an ice batch, it never warms food)
    kitchen, hub = _new_kitchen(engine_api)
    kitchen.step(1, hub.report(1))
    device = _as_dict(kitchen.set_importance("ice_machine_1", "deferrable", {"max_delay_min": 45, "must_finish_by": "21:00"}))
    assert device["importance"] == "deferrable"


@pytest.mark.parametrize("type_id", ["walk_in_cooler", "reach_in_fridge", "freezer"])
def test_config_cycling_refrigeration_deferrable_raises(engine_api, type_id):
    config = _config()
    for entry in config["equipment"]:
        if entry["type_id"] == type_id:
            entry["importance"] = "deferrable"
            entry["limits"] = dict(DEFER_LIMITS)
    # the contract model alone can't see the catalog, so it accepts the shape; the engine must refuse it
    KitchenConfig.model_validate(config)
    with pytest.raises(engine_api.RuleError):
        engine_api.Kitchen(config, _tariff(), _catalog(), "with", 42)
    with pytest.raises(engine_api.RuleError):
        engine_api.Kitchen.build_lanes(config, _tariff(), _catalog(), 42)


def test_config_ice_machine_deferrable_builds(engine_api):
    # the Demo Café config already has ice_machine deferrable {60, "22:00"} -> builds, both ways
    config = _config()
    assert next(e for e in config["equipment"] if e["type_id"] == "ice_machine")["importance"] == "deferrable"
    engine_api.Kitchen(config, _tariff(), _catalog(), "with", 42)
    lanes = engine_api.Kitchen.build_lanes(config, _tariff(), _catalog(), 42)
    assert set(lanes) == {"without", "with"}


# ---------------------------------------------------------------------------------------------------------------------
# Limits arrive as JSON numbers: the contract types min_power_pct / max_reduce_min / max_delay_min as int (Pct /
# NonNegInt, Pydantic lax mode; JSON Schema "integer"), and both accept an integral float such as 40.0 as the integer 40.
# ---------------------------------------------------------------------------------------------------------------------


def test_contract_accepts_integral_float_limits():
    from contracts.shapes import DeferrableLimits, FlexibleLimits

    # 40.0 -> 40, 30.0 -> 30: the contract itself settles that integral floats are valid
    flex = FlexibleLimits.model_validate({"min_power_pct": 40.0, "max_reduce_min": 30.0})
    assert (flex.min_power_pct, flex.max_reduce_min) == (40, 30)
    defer = DeferrableLimits.model_validate({"max_delay_min": 60.0, "must_finish_by": "19:30"})
    assert defer.max_delay_min == 60


def test_set_importance_float_limits_accepted(engine_api):
    kitchen, hub = _new_kitchen(engine_api)
    kitchen.step(1, hub.report(1))
    # hvac 40.0 % ≡ 40 %: 0 < 40 <= 100, max_reduce 30.0 ≡ 30 > 0 -> valid
    device = _as_dict(kitchen.set_importance("hvac_1", "flexible", {"min_power_pct": 40.0, "max_reduce_min": 30.0}))
    assert device["importance"] == "flexible"
    # walk-in 50.0 % ≡ 50 %: exactly the food-safety floor -> valid
    kitchen.set_importance("walk_in_cooler_1", "flexible", {"min_power_pct": 50.0, "max_reduce_min": 30.0})
    # dishwasher max_delay 60.0 ≡ 60 >= 0 -> valid
    kitchen.set_importance("dishwasher_1", "deferrable", {"max_delay_min": 60.0, "must_finish_by": "19:30"})


def test_set_importance_float_limits_still_checked(engine_api):
    kitchen, hub = _new_kitchen(engine_api)
    kitchen.step(1, hub.report(1))
    # walk-in 49.0 % ≡ 49 < 50 -> food-safety floor still enforced on float input
    with pytest.raises(engine_api.RuleError):
        kitchen.set_importance("walk_in_cooler_1", "flexible", {"min_power_pct": 49.0, "max_reduce_min": 30.0})
    # 40.5 is not an integer (the contract model rejects it) -> RuleError
    with pytest.raises(engine_api.RuleError):
        kitchen.set_importance("hvac_1", "flexible", {"min_power_pct": 40.5, "max_reduce_min": 30})


def test_set_peak_cap_cap_without_number_raises(engine_api):
    # facade/set_peak_cap_rule_error.json: "peak_mode cap needs a peak_cap_kw"
    kitchen, hub = _new_kitchen(engine_api)
    kitchen.step(1, hub.report(1))
    with pytest.raises(engine_api.RuleError):
        kitchen.set_peak_cap("cap", None)


def test_set_peak_cap_minimize_with_number_raises(engine_api):
    # CONTRACTS.md §1: minimize -> peak_cap_kw is null (contracts._check_peak_mode: "minimize needs peak_cap_kw null")
    kitchen, hub = _new_kitchen(engine_api)
    kitchen.step(1, hub.report(1))
    with pytest.raises(engine_api.RuleError):
        kitchen.set_peak_cap("minimize", 38.0)


def test_set_peak_cap_cap_valid_returns_meter(engine_api):
    # facade/set_peak_cap.json: cap 38 -> Meter peak_mode cap, peak_cap_kw 38, target_kw = peak_cap_kw = 38
    kitchen, hub = _new_kitchen(engine_api)
    kitchen.step(1, hub.report(1))
    meter = _as_dict(kitchen.set_peak_cap("cap", 38.0))
    assert meter["peak_mode"] == "cap"
    assert meter["peak_cap_kw"] == pytest.approx(38.0, abs=0.01)
    assert meter["target_kw"] == pytest.approx(38.0, abs=0.01)


def test_set_peak_cap_minimize_valid_returns_meter(engine_api):
    kitchen, hub = _new_kitchen(engine_api)
    kitchen.step(1, hub.report(1))
    meter = _as_dict(kitchen.set_peak_cap("minimize", None))
    assert meter["peak_mode"] == "minimize"
    assert meter["peak_cap_kw"] is None


@pytest.mark.parametrize("cap", [0.0, -5.0])
def test_set_peak_cap_non_positive_number(cap):
    pytest.skip("TBD: set_peak_cap with peak_cap_kw <= 0 is not specified (KitchenConfig has gt=0, facade says only "
                "'cap without a number' raises); no Main_Gaps row yet")


# ---------------------------------------------------------------------------------------------------------------------
# 7. Facade: emitted Commands respect the rules (inline HubReports, 30 ticks, 6 decision ticks)
# ---------------------------------------------------------------------------------------------------------------------


def _assert_rules_on_commands(emitted, limits_by_device: dict, importance_by_device: dict):
    cat = {e["type_id"]: e for e in _catalog()}
    for cmd, reason in emitted:
        if cmd["issued_by"] != "engine":
            continue
        did = cmd["device_id"]
        type_id = did.rsplit("_", 1)[0]
        # always_on never commanded (golden rule 4)
        assert importance_by_device[did] != "always_on", f"engine commanded always_on device {did}"
        if cmd["action"] == "reduce":
            # food-safety floor: refrigeration >= 50, whatever the reason (escalation included)
            if cat[type_id]["category"] == "refrigeration":
                assert cmd["value"] >= 50, cmd
            # routine moves: reduce >= min_power_pct
            if reason in ROUTINE_REASONS:
                assert cmd["value"] >= limits_by_device[did]["min_power_pct"], cmd


def _limits_and_importance(config: dict):
    limits, importance = {}, {}
    for entry in config["equipment"]:
        for n in range(1, entry["count"] + 1):
            did = f"{entry['type_id']}_{n}"
            limits[did] = entry["limits"]
            importance[did] = entry["importance"]
    return limits, importance


def test_emitted_commands_respect_rules(engine_api):
    kitchen, hub = _new_kitchen(engine_api)
    emitted = _run(kitchen, hub, 1, 30)
    limits, importance = _limits_and_importance(_config())
    # 51.6 kW against a 40 kW cap with 12.85 kW in-rules room -> at least one engine reduce must be issued
    assert any(c["issued_by"] == "engine" and c["action"] == "reduce" for c, _ in emitted)
    _assert_rules_on_commands(emitted, limits, importance)


def test_rejected_set_importance_keeps_food_safety(engine_api):
    # walk-in at min 30 is rejected, so the walk-in keeps min 50: every reduce on it stays >= 50
    kitchen, hub = _new_kitchen(engine_api)
    kitchen.step(1, hub.report(1))
    with pytest.raises(engine_api.RuleError):
        kitchen.set_importance("walk_in_cooler_1", "flexible", {"min_power_pct": 30, "max_reduce_min": 30})
    emitted = _run(kitchen, hub, 2, 30)
    for cmd, _ in emitted:
        if cmd["device_id"] == "walk_in_cooler_1" and cmd["action"] == "reduce":
            assert cmd["value"] >= 50, cmd


def test_device_set_always_on_is_never_commanded(engine_api):
    # walk-in -> always_on before any decision tick; the hub reports the new importance; the engine must leave it alone
    config = _config()
    kitchen, hub = _new_kitchen(engine_api, config)
    kitchen.step(1, hub.report(1))
    kitchen.set_importance("walk_in_cooler_1", "always_on", {})
    hub.devices["walk_in_cooler_1"]["importance"] = "always_on"
    emitted = _run(kitchen, hub, 2, 30)
    assert not [c for c, _ in emitted if c["device_id"] == "walk_in_cooler_1" and c["issued_by"] == "engine"]


def test_raised_min_power_is_honoured(engine_api):
    # hvac_1 min raised to 70: routine reduce on hvac_1 must be >= 70 (70 % × 12 = 8.4 kW)
    kitchen, hub = _new_kitchen(engine_api)
    kitchen.step(1, hub.report(1))
    kitchen.set_importance("hvac_1", "flexible", {"min_power_pct": 70, "max_reduce_min": 30})
    emitted = _run(kitchen, hub, 2, 30)
    for cmd, reason in emitted:
        if cmd["device_id"] == "hvac_1" and cmd["action"] == "reduce" and reason in ROUTINE_REASONS:
            assert cmd["value"] >= 70, cmd


def test_authority_fixture_is_contract_valid():
    # sanity of the input used by the kitchen config (no engine call)
    ClaudeAuthority.model_validate(_load_json(SHAPES / "claude_authority.json"))
