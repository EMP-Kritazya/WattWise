"""Hand-computed tests for engine/context.py (docs/design/ENGINE.md section 2, section 15 "Context").

Written before the code (engine-test-author). Every expected number below is worked out by hand from ENGINE.md / CONTRACTS.md,
never taken from engine output.

Facade used (CONTRACTS.md section 3), the only thing most tests rely on:
    Kitchen(config, tariff, catalog, control, seed, ids=None)
    kitchen.step(minutes, hub_report) -> TickState
    kitchen.set_context(context) -> None          # merges; used from the next step
    kitchen.forecast(120) -> list[float]          # latest decision tick's forecast, 8 x 15-min blocks
    kitchen.snapshot()["context"]                 # merged context, numbers unchanged
Inputs are passed as plain JSON-compatible dicts, validated first with the Pydantic models in `backend/contracts/`
(`KitchenConfig`, `Tariff`, `HubReport`, `Context`, `PartialContext`), then `model_dump(mode="json")`.

ASSUMED INTERNAL API (not in any contract; engine-builder please implement with these names or tell the test author):
    engine.context.CROWD_MULTIPLIERS: dict[str, float]   # {"none": 1.00, "small": 1.10, "medium": 1.25, "large": 1.40}
    engine.context.ContextState()                        # empty state
        .merge(context: dict) -> None                    # partial post: every section present replaces that section
        .crowd_multiplier() -> float                     # last known crowd_effect.value mapped; 1.00 if never set
        .current() -> dict | None                        # copy of the merged context; None before any post

Hand scenario used by the forecast tests (all values constant, so every forecaster fallback gives the same base):
    Friday 2026-07-17, T0 = 19:00Z = 12:00 America/Los_Angeles (block-aligned, open 10:00-22:00, off-peak tariff hour).
    tick k has ts = T0 + k min (end of the minute just simulated), tick 1 meters [T0, T0+1).
    devices (catalog types from contracts/fixtures/shapes/equipment_catalog.json):
        lights_1        always_on   fixed           2.4 kW  (rated 2.4)
        fryer_1         always_on   demand_driven   4.0 kW  (rated 14.0)
        water_heater_1  flexible    cycling         2.0 kW  (rated 4.5, min 40 %, max reduce 30 min)
    peak_cap_kw 100 -> nothing is ever over target, so no decision changes any device.
    No warm_up: base = device's last closed block = its constant power. Live ratio over the last 2 closed always_on blocks
    = (2.4 + 4.0) / (2.4 + 4.0) = 1.0, so it changes nothing.
    Forecast per block = 2.4 + 4.0 x crowd + 2.0.
"""
from __future__ import annotations

import copy
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[2]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from contracts import Context, EquipmentType, HubReport, KitchenConfig, PartialContext, Tariff  # noqa: E402

_FIXTURES = _BACKEND.parent / "contracts" / "fixtures"

T0 = datetime(2026, 7, 17, 19, 0, tzinfo=timezone.utc)  # 12:00 local (PDT), Friday, block boundary

LIGHTS_KW = 2.4
FRYER_KW = 4.0
WATER_HEATER_KW = 2.0

CROWD_TABLE = {"none": 1.00, "small": 1.10, "medium": 1.25, "large": 1.40}


# ---------------------------------------------------------------------------------------------------------------------
# Helpers (local to this file; conftest.py is owned by another agent)
# ---------------------------------------------------------------------------------------------------------------------


def _load(rel: str) -> dict:
    return json.loads((_FIXTURES / rel).read_text())


def _catalog() -> list[dict]:
    """Kitchen's `catalog` argument: list[EquipmentType] loaded by path (CONTRACTS.md section 3)."""
    return [EquipmentType.model_validate(t).model_dump(mode="json") for t in _load_list("shapes/equipment_catalog.json")]


def _load_list(rel: str) -> list:
    return json.loads((_FIXTURES / rel).read_text())


def _iso(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def _tariff() -> dict:
    return Tariff.model_validate(_load("shapes/tariff.json")).model_dump(mode="json")


def _config(with_fryer: bool = True, peak_cap_kw: float = 100.0) -> dict:
    base = _load("shapes/kitchen_config.json")
    equipment = [{"type_id": "lights", "count": 1, "importance": "always_on", "limits": {}}]
    if with_fryer:
        equipment.append({"type_id": "fryer", "count": 1, "importance": "always_on", "limits": {}})
    equipment.append(
        {"type_id": "water_heater", "count": 1, "importance": "flexible",
         "limits": {"min_power_pct": 40, "max_reduce_min": 30}}
    )
    base.update(
        {"name": "Context test kitchen", "equipment": equipment, "peak_mode": "cap", "peak_cap_kw": peak_cap_kw,
         "operating_hours": {"open": "10:00", "close": "22:00"}, "run_days": 1, "seed": 42}
    )
    return KitchenConfig.model_validate(base).model_dump(mode="json")


def _device(device_id: str, type_id: str, name: str, importance: str, power_kw: float, rated_kw: float) -> dict:
    return {"device_id": device_id, "type_id": type_id, "name": name, "importance": importance, "state": "on",
            "power_kw": power_kw, "rated_kw": rated_kw, "power_pct": round(100 * power_kw / rated_kw),
            "source": "simulated"}


def _report(tick_id: int, with_fryer: bool = True, water_heater_kw: float = WATER_HEATER_KW,
            lane: str = "with") -> dict:
    devices = [_device("lights_1", "lights", "Lights 1", "always_on", LIGHTS_KW, 2.4)]
    if with_fryer:
        devices.append(_device("fryer_1", "fryer", "Fryer 1", "always_on", FRYER_KW, 14.0))
    devices.append(_device("water_heater_1", "water_heater", "Water heater 1", "flexible", water_heater_kw, 4.5))
    report = {"hub_id": "sim_hub", "lane": lane, "tick_id": tick_id, "ts": _iso(T0 + timedelta(minutes=tick_id)),
              "total_kw": round(sum(d["power_kw"] for d in devices), 6), "customers_per_hour": 40,
              "devices": devices, "acks": [], "source": "simulated"}
    return HubReport.model_validate(report).model_dump(mode="json")


def _kitchen(with_fryer: bool = True, peak_cap_kw: float = 100.0, control: str = "with"):
    from engine import Kitchen

    return Kitchen(_config(with_fryer, peak_cap_kw), _tariff(), _catalog(), control, 42)


def _run(kitchen, first: int, last: int, with_fryer: bool = True, **report_kw) -> list:
    """Step ticks first..last inclusive, 1 minute each; return the TickStates."""
    return [kitchen.step(1, _report(k, with_fryer, **report_kw)) for k in range(first, last + 1)]


def _crowd(value: str, at_tick: int, set_by: str = "claude") -> dict:
    post = {"ts": _iso(T0 + timedelta(minutes=at_tick)),
            "crowd_effect": {"value": value, "set_by": set_by, "reason": "test"}}
    return PartialContext.model_validate(post).model_dump(mode="json", exclude_none=True)


def _weather_only(at_tick: int) -> dict:
    full = _load("shapes/context.json")
    post = {"ts": _iso(T0 + timedelta(minutes=at_tick)), "weather": full["weather"]}
    return PartialContext.model_validate(post).model_dump(mode="json", exclude_none=True)


def _prices_only(at_tick: int, usd_per_kwh: float = 5.00) -> dict:
    hourly = [{"ts": _iso(T0 + timedelta(hours=h)), "usd_per_kwh": usd_per_kwh} for h in range(4)]
    post = {"ts": _iso(T0 + timedelta(minutes=at_tick)),
            "prices": {"label": "recorded", "source": "caiso", "hourly": hourly, "stress": "high"}}
    return PartialContext.model_validate(post).model_dump(mode="json", exclude_none=True)


def _dump(obj):
    """TickState / dict -> JSON-comparable plain data."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    return json.loads(json.dumps(obj, default=str, sort_keys=True))


def _norm_context(ctx) -> dict:
    """Normalise a context (dict or model) through the contract model so ts formats compare equal."""
    data = ctx.model_dump(mode="json") if hasattr(ctx, "model_dump") else ctx
    return Context.model_validate(data).model_dump(mode="json")


def _approx_list(values):
    return [pytest.approx(v, abs=1e-6) for v in values]


# ---------------------------------------------------------------------------------------------------------------------
# Crowd multiplier table (section 2, CONTRACTS.md Context: "fixed table in the engine")
# ---------------------------------------------------------------------------------------------------------------------


def test_crowd_multiplier_table_internal():
    from engine.context import CROWD_MULTIPLIERS

    # none 1.00 · small 1.10 · medium 1.25 · large 1.40 (ENGINE.md section 2)
    assert set(CROWD_MULTIPLIERS) == {"none", "small", "medium", "large"}
    for value, mult in CROWD_TABLE.items():
        assert CROWD_MULTIPLIERS[value] == pytest.approx(mult, abs=1e-12)


def test_context_state_empty_is_multiplier_one_internal():
    from engine.context import ContextState

    state = ContextState()
    # no context at all -> multiplier 1.00, nothing stored
    assert state.crowd_multiplier() == pytest.approx(1.0, abs=1e-12)
    assert state.current() is None


def test_context_state_missing_crowd_keeps_last_known_internal():
    from engine.context import ContextState

    state = ContextState()
    state.merge(_crowd("medium", 30))
    state.merge(_weather_only(40))
    # later post without crowd_effect -> last known medium stays -> 1.25
    assert state.crowd_multiplier() == pytest.approx(1.25, abs=1e-12)
    merged = state.current()
    assert merged["crowd_effect"]["value"] == "medium"
    assert merged["weather"] is not None


@pytest.mark.parametrize("value", ["none", "small", "medium", "large"])
def test_crowd_value_scales_demand_driven_forecast(value):
    k = _kitchen()
    k.set_context(_crowd(value, 0))
    _run(k, 1, 30)
    mult = CROWD_TABLE[value]
    # tick 30, ts 12:30 local, on a block boundary: block 0 = [12:30, 12:45) has 0 metered minutes, all forecast.
    # per block: lights 2.4 + fryer 4.0 x mult + water heater 2.0
    #   none   2.4 + 4.0 + 2.0 = 8.4
    #   small  2.4 + 4.4 + 2.0 = 8.8
    #   medium 2.4 + 5.0 + 2.0 = 9.4
    #   large  2.4 + 5.6 + 2.0 = 10.0
    expected = LIGHTS_KW + FRYER_KW * mult + WATER_HEATER_KW
    assert k.forecast(120) == _approx_list([expected] * 8)


def test_crowd_medium_is_exactly_1_25_on_demand_driven_only():
    """Section 15: crowd effect medium -> multiplier exactly 1.25 on demand_driven forecast only."""
    plain = _kitchen()
    crowded = _kitchen()
    crowded.set_context(_crowd("medium", 0))
    _run(plain, 1, 30)
    _run(crowded, 1, 30)
    plain_fc = plain.forecast(120)
    crowded_fc = crowded.forecast(120)
    # no context: 2.4 + 4.0 + 2.0 = 8.4 kW every block
    assert plain_fc == _approx_list([8.4] * 8)
    # medium: 2.4 + 4.0 x 1.25 + 2.0 = 2.4 + 5.0 + 2.0 = 9.4 kW every block
    assert crowded_fc == _approx_list([9.4] * 8)
    # difference per block = fryer 4.0 x (1.25 - 1) = 1.0 kW exactly; lights and water heater untouched
    for a, b in zip(crowded_fc, plain_fc):
        assert a - b == pytest.approx(FRYER_KW * 0.25, abs=1e-6)


def test_crowd_medium_does_not_touch_non_demand_driven_devices():
    # Same kitchen without the fryer: only lights (fixed) and water heater (cycling, flexible).
    plain = _kitchen(with_fryer=False)
    crowded = _kitchen(with_fryer=False)
    crowded.set_context(_crowd("large", 0))
    _run(plain, 1, 30, with_fryer=False)
    _run(crowded, 1, 30, with_fryer=False)
    # no demand_driven device -> crowd large changes nothing: 2.4 + 2.0 = 4.4 kW in both
    assert plain.forecast(120) == _approx_list([4.4] * 8)
    assert crowded.forecast(120) == _approx_list([4.4] * 8)


# ---------------------------------------------------------------------------------------------------------------------
# "Used from the next step"; forecast only recomputed on decision ticks (tick_id % 5 == 0)
# ---------------------------------------------------------------------------------------------------------------------


def test_set_context_used_from_next_decision_tick_partial_block():
    k = _kitchen()
    _run(k, 1, 30)
    # tick 30 forecast, no context: 8.4 kW every block
    assert k.forecast(120) == _approx_list([8.4] * 8)

    assert k.set_context(_crowd("medium", 30)) is None
    # forecast() returns the latest decision tick's forecast, no recomputation -> still 8.4
    assert k.forecast(120) == _approx_list([8.4] * 8)

    _run(k, 31, 34)
    # ticks 31-34 are not decision ticks (31..34 % 5 != 0) -> forecast unchanged
    assert k.forecast(120) == _approx_list([8.4] * 8)

    _run(k, 35, 35)
    # tick 35, ts 12:35: block 0 = [12:30, 12:45) has 5 metered minutes at 8.4 kW (reports did not change)
    # and 10 forecast minutes at 9.4 kW (medium): (5 x 8.4 + 10 x 9.4) / 15 = (42 + 94) / 15 = 9.066667
    # blocks 1..7: 2.4 + 5.0 + 2.0 = 9.4
    expected = [(5 * 8.4 + 10 * 9.4) / 15] + [9.4] * 7
    assert k.forecast(120) == _approx_list(expected)


# ---------------------------------------------------------------------------------------------------------------------
# Missing / stale -> last known, then 1.00
# ---------------------------------------------------------------------------------------------------------------------


def test_post_without_crowd_keeps_last_known_crowd():
    k = _kitchen()
    k.set_context(_crowd("medium", 0))
    _run(k, 1, 15)
    k.set_context(_weather_only(15))  # partial post, no crowd_effect key
    _run(k, 16, 30)
    # crowd missing in the later post -> last known medium: 2.4 + 5.0 + 2.0 = 9.4
    assert k.forecast(120) == _approx_list([9.4] * 8)


def test_stale_crowd_still_last_known_after_an_hour():
    k = _kitchen()
    k.set_context(_crowd("medium", 0))
    _run(k, 1, 90)
    # 90 sim minutes with no new post: the engine uses the latest it has -> medium.
    # tick 90, ts 13:30 local, block boundary -> all 8 blocks forecast: 2.4 + 5.0 + 2.0 = 9.4
    assert k.forecast(120) == _approx_list([9.4] * 8)


def test_context_without_crowd_ever_is_multiplier_one():
    k = _kitchen()
    k.set_context(_weather_only(0))
    k.set_context(_prices_only(0))
    _run(k, 1, 30)
    # crowd never set -> multiplier 1.00: 2.4 + 4.0 + 2.0 = 8.4
    assert k.forecast(120) == _approx_list([8.4] * 8)


def test_newer_crowd_value_replaces_older():
    k = _kitchen()
    k.set_context(_crowd("medium", 0))
    _run(k, 1, 15)
    k.set_context(_crowd("large", 15))
    _run(k, 16, 30)
    # latest crowd large: 2.4 + 4.0 x 1.4 + 2.0 = 2.4 + 5.6 + 2.0 = 10.0
    assert k.forecast(120) == _approx_list([10.0] * 8)


def test_explicit_none_crowd_overrides_previous_medium():
    k = _kitchen()
    k.set_context(_crowd("medium", 0))
    _run(k, 1, 15)
    k.set_context(_crowd("none", 15, set_by="owner"))
    _run(k, 16, 30)
    # "none" is a real value (not missing): multiplier 1.00 -> 2.4 + 4.0 + 2.0 = 8.4
    assert k.forecast(120) == _approx_list([8.4] * 8)


# ---------------------------------------------------------------------------------------------------------------------
# No context -> identical run; weather and prices never change a number
# ---------------------------------------------------------------------------------------------------------------------


def _tight_run(posts: dict[int, list[dict]], last_tick: int = 60) -> list:
    """cap 10.2 kW, water heater drawing its full 4.5 kW: 2.4 + 4.0 + 4.5 = 10.9 kW > 10.2 -> the decider has to act.
    `posts`: tick -> contexts set just before that tick's step."""
    k = _kitchen(peak_cap_kw=10.2)
    out = []
    for t in range(1, last_tick + 1):
        for ctx in posts.get(t, []):
            k.set_context(ctx)
        out.append(_dump(k.step(1, _report(t, water_heater_kw=4.5))))
    return out


def test_no_context_run_is_deterministic():
    # same tick stream, no context, twice -> byte-identical TickStates
    assert _tight_run({}) == _tight_run({})


def test_crowd_none_run_identical_to_no_context_run():
    # crowd none -> multiplier 1.00 = the no-context multiplier -> every TickState identical
    assert _tight_run({1: [_crowd("none", 0)]}) == _tight_run({})


def test_weather_and_prices_context_leave_run_identical():
    """Weather is not used by the forecast; prices only break ties (one flexible device -> no tie possible)."""
    baseline = _tight_run({})
    with_context = _tight_run({1: [_weather_only(0)], 20: [_prices_only(19, 5.00)], 41: [_prices_only(40, 0.01)]})
    # every TickState (meter, forecast, decisions, commands, warnings) unchanged
    assert with_context == baseline


def test_context_prices_never_set_the_bill():
    plain = _kitchen()
    priced = _kitchen()
    priced.set_context(_prices_only(0, 5.00))
    a = _run(plain, 1, 30)[-1]
    b = _run(priced, 1, 30)[-1]
    meter_a, meter_b = _dump(a)["meter"], _dump(b)["meter"]
    # 12:30 local is in the tariff's off_peak period (00:00-16:00) -> $0.22/kWh, not the context's $5.00
    assert meter_b["price_usd_per_kwh_now"] == pytest.approx(0.22, abs=0.01)
    # 8.4 kW x 0.5 h = 4.2 kWh in both lanes; cost identical: context prices never bill anything
    assert meter_b["energy_kwh_today"] == pytest.approx(4.2, abs=1e-6)
    assert meter_b == meter_a


def test_set_context_creates_no_ids():
    k = _kitchen()
    _run(k, 1, 5)
    before = copy.deepcopy(k.snapshot()["id_counters"])
    k.set_context(_load("shapes/context.json"))
    _run(k, 6, 10)
    # cap 100, load 8.4 -> no decisions; context alone allocates no d_/c_/e_ id
    assert k.snapshot()["id_counters"] == before


# ---------------------------------------------------------------------------------------------------------------------
# snapshot()["context"]: stored unchanged, partial posts merge, weather returned
# ---------------------------------------------------------------------------------------------------------------------


def test_snapshot_context_empty_before_any_post():
    k = _kitchen()
    _run(k, 1, 1)
    ctx = k.snapshot()["context"]
    # nothing posted -> no section known (None, or a context with every section null)
    if ctx is not None:
        data = _dump(ctx)
        for section in ("weather", "prices", "events", "crowd_effect"):
            assert data.get(section) is None


def test_snapshot_returns_full_context_unchanged():
    posted = _load("shapes/context.json")
    k = _kitchen()
    k.set_context(copy.deepcopy(posted))
    _run(k, 1, 1)
    # numbers forwarded unchanged (golden rule 6): every section and value equal to the post
    assert _norm_context(k.snapshot()["context"]) == _norm_context(posted)


def test_snapshot_returns_weather_numbers_exactly():
    k = _kitchen()
    k.set_context(_weather_only(0))
    _run(k, 1, 1)
    weather = _dump(k.snapshot()["context"])["weather"]
    # temps from shapes/context.json, unchanged: 29.1, 28.4, 27.2, 25.8, 24.1, 22.9 °C
    assert [h["temp_c"] for h in weather["hourly"]] == [29.1, 28.4, 27.2, 25.8, 24.1, 22.9]
    assert weather["label"] == "recorded"
    assert weather["source"] == "open-meteo"


def test_partial_posts_merge_section_by_section():
    k = _kitchen()
    k.set_context(_weather_only(0))
    _run(k, 1, 5)
    k.set_context(_crowd("medium", 5))
    _run(k, 6, 10)
    merged = _norm_context(k.snapshot()["context"])
    # first post gave weather, second gave crowd_effect -> both present; prices / events never posted -> null
    assert merged["weather"] == _norm_context({"ts": _iso(T0), **_weather_only(0)})["weather"]
    assert merged["crowd_effect"]["value"] == "medium"
    assert merged["prices"] is None
    assert merged["events"] is None
    # ts of the latest post (tick 5 -> T0 + 5 min)
    assert merged["ts"] == _iso(T0 + timedelta(minutes=5))

    # a newer weather post replaces the weather section only; crowd stays medium
    new_weather = {"ts": _iso(T0 + timedelta(minutes=10)),
                   "weather": {"label": "recorded", "source": "open-meteo",
                               "hourly": [{"ts": _iso(T0 + timedelta(hours=1)), "temp_c": 31.5}]}}
    k.set_context(PartialContext.model_validate(new_weather).model_dump(mode="json", exclude_none=True))
    _run(k, 11, 15)
    merged = _norm_context(k.snapshot()["context"])
    assert [h["temp_c"] for h in merged["weather"]["hourly"]] == [31.5]
    assert merged["crowd_effect"]["value"] == "medium"


def test_snapshot_context_is_a_copy():
    k = _kitchen()
    k.set_context(_load("shapes/context.json"))
    _run(k, 1, 1)
    first = k.snapshot()["context"]
    if not isinstance(first, dict):
        pytest.skip("snapshot context is not a dict; copy semantics checked via model immutability")
    first["weather"]["hourly"][0]["temp_c"] = 999.0
    first["crowd_effect"]["value"] = "large"
    again = _dump(k.snapshot()["context"])
    # snapshot() returns copies: mutating the returned dict changes nothing inside the engine
    assert again["weather"]["hourly"][0]["temp_c"] == 29.1
    assert again["crowd_effect"]["value"] == "medium"


# ---------------------------------------------------------------------------------------------------------------------
# TBD (design does not fix these; not guessed)
# ---------------------------------------------------------------------------------------------------------------------


def test_context_price_breaks_tie_between_equal_peak_moves():
    pytest.skip(
        "TBD: no gap id - ENGINE.md section 2/5 says ties go tariff price, then context price, then device_id, but the "
        "candidate move set where two moves have equal peak effect inside one tariff period is not specified "
        "(holds release 'in the earliest later block with room', reduces tie on device_id), so no hand case exists"
    )


def test_partial_post_with_explicit_null_section():
    pytest.skip(
        "TBD: no gap id - 'Partial posts merge' does not say whether a section sent as null clears the stored "
        "section or is ignored"
    )
