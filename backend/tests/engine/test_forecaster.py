"""Hand-computed tests for engine/forecaster.py + Kitchen.forecast(120) + TickState.forecast_kw
(docs/design/ENGINE.md section 3; CONTRACTS.md section 1 TickState, section 3 `forecast`).

Written before the code (engine-test-author). Every expected number is worked out by hand from ENGINE.md section 3, never
taken from engine output. Above each assertion a comment shows the arithmetic.

PUBLIC PATH (CONTRACTS.md section 3), used by most tests:
    Kitchen(config, tariff, catalog, control, seed) · warm_up(WarmUpHistory) · step(minutes, hub_report) -> TickState
    TickState.forecast_kw: 8 floats on decision ticks (tick_id % 5 == 0 live, every step when minutes > 1), else null
    forecast(120) -> latest decision tick's forecast, no recomputation; forecast(h != 120) -> ValueError
Only totals are public, so each hand case keeps one "probe" device whose history differs and holds everything else constant.

ASSUMED INTERNAL API (not in any contract; engine-builder: implement with these names, or tell the test author).
The decider is still a stub, so commanded-device forecasts and unavoidable_kw are tested on the internal function:

    engine.forecaster.forecast_devices(
        *,
        now: datetime,                          # HubReport.ts of the step (aware UTC); block 0 = block_start_of(now)
        history: engine.history.HistoryView,    # BlockHistory.view(now): closed blocks only (no peeking)
        tariff: engine.tariff.TariffView,       # local weekday / local block time
        devices: list[dict],                    # Device shape (CONTRACTS.md section 1) + "power_model": str
                                                #   + "limits": dict (ImportanceLimits of the device's importance)
        block0_metered_kwh: Mapping[str, float],# energy already metered per device in block 0 (missing -> 0)
        crowd_multiplier: float = 1.0,          # engine.context.CROWD_MULTIPLIERS[...]
        reductions: Mapping[str, dict] | None = None,
                                                # active reduce per flexible device:
                                                #   {"value_pct": int, "restore_at": datetime, "owed_kwh": float}
                                                #   restore_at = sim ts from which the device is no longer reduced
    ) -> dict:
        {"block_starts": [8 aware UTC datetimes],
         "device_kw": {device_id: [8 floats]},  # per device per block
         "total_kw": [8 floats],                # per-block sum over devices (what TickState.forecast_kw carries)
         "unavoidable_kw": [8 floats]}          # ENGINE.md section 3 unavoidable_kw

Hand rules used (ENGINE.md section 3):
  base(device, block) = mean avg_kw at the same local weekday + local block time over the previous 4 weeks (warm-up + own
  closed blocks); fewer weeks -> mean of what exists; none -> the device's last closed block; none -> current power_kw.
  ratio = sum(actual always_on, last 2 closed blocks) / sum(base always_on, same blocks), clamped to [0.5, 2.0], applied to
  always_on + flexible in the next hour, fading linearly to 1.0 over the second hour. Deferrable devices: no ratio.
  To keep every non-ratio case independent of how the ratio is computed, the only always_on device there is lights_1 at a
  constant 2.0 kW wherever it appears (warm-up and live): every base candidate and every actual is 2.0 -> ratio 1.0.
  Block 0 = (metered kWh so far + forecast kW x remaining min / 60) / 0.25 h.

Tariff: demo_tariff_v1 (America/Los_Angeles). Peak cap 100 kW in every Kitchen, so the decider never acts on these loads.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta
from typing import Callable, Mapping, Optional, Union

import pytest

from contracts import HubReport, KitchenConfig, Tariff
from tests.engine.conftest import (
    FIXTURES,
    as_tick_state,
    catalog,
    hub_report,
    load_config,
    load_tariff,
    local_ts,
    warmup_history_per_device,
)

E = 1e-6  # energy / kW from exact arithmetic
MIN = timedelta(minutes=1)
BLK = timedelta(minutes=15)
WEEK = timedelta(days=7)

# ---------------------------------------------------------------------------------------------------------------------
# Roster (catalog rated_kw / power_model from contracts/fixtures/shapes/equipment_catalog.json)
# ---------------------------------------------------------------------------------------------------------------------


def _dev(device_id, type_id, name, importance, rated_kw, power_model):
    return {"device_id": device_id, "type_id": type_id, "name": name, "importance": importance,
            "rated_kw": rated_kw, "power_model": power_model}


LIGHTS = _dev("lights_1", "lights", "Lights 1", "always_on", 2.4, "fixed")
FRYER = _dev("fryer_1", "fryer", "Fryer 1", "always_on", 14.0, "demand_driven")
FRYER_FLEX = _dev("fryer_1", "fryer", "Fryer 1", "flexible", 14.0, "demand_driven")
HVAC1 = _dev("hvac_1", "hvac", "HVAC 1", "flexible", 12.0, "thermal")
HVAC2 = _dev("hvac_2", "hvac", "HVAC 2", "flexible", 12.0, "thermal")
WATER_HEATER = _dev("water_heater_1", "water_heater", "Water heater 1", "flexible", 4.5, "cycling")
DISHWASHER = _dev("dishwasher_1", "dishwasher", "Dishwasher 1", "deferrable", 6.0, "job")

LIMITS = {
    "always_on": {},
    "flexible": {"min_power_pct": 40, "max_reduce_min": 30},
    "deferrable": {"max_delay_min": 60, "must_finish_by": "19:30"},
}


def _config(devices: list[dict], peak_cap_kw: float = 100.0) -> dict:
    """Demo Café config with only `devices` (grouped per type, count = units listed)."""
    base = load_config().model_dump(mode="json")
    equipment: list[dict] = []
    for d in devices:
        entry = next((e for e in equipment if e["type_id"] == d["type_id"]), None)
        if entry is None:
            equipment.append({"type_id": d["type_id"], "count": 1, "importance": d["importance"],
                              "limits": dict(LIMITS[d["importance"]])})
        else:
            entry["count"] += 1
    base.update({"name": "Forecaster test kitchen", "equipment": equipment, "peak_mode": "cap",
                 "peak_cap_kw": peak_cap_kw, "operating_hours": {"open": "10:00", "close": "22:00"},
                 "run_days": 1, "seed": 42})
    return KitchenConfig.model_validate(base).model_dump(mode="json")


def _kitchen(devices: list[dict], control: str = "with", history=None):
    from engine import Kitchen

    k = Kitchen(_config(devices), load_tariff().model_dump(mode="json"), catalog(), control, 42)
    if history is not None:
        k.warm_up(history.model_dump(mode="json"))
    return k


# ---------------------------------------------------------------------------------------------------------------------
# Time + feeding helpers
# ---------------------------------------------------------------------------------------------------------------------


def _at(d: date, hh: int, mm: int) -> datetime:
    return local_ts(d.year, d.month, d.day, hh, mm)


def _slots(d: date, hh: int, mm: int, n: int) -> list[datetime]:
    """n consecutive 15-min block starts from local d hh:mm (no DST change inside any range used here)."""
    first = _at(d, hh, mm)
    return [first + i * BLK for i in range(n)]


Powers = Union[Mapping[str, float], Callable[[int], Mapping[str, float]]]


def _live(kitchen, devices: list[dict], start: datetime, first_tick: int, last_tick: int, powers: Powers) -> dict:
    """Live cadence: tick k has ts = start + k min and meters [ts - 1 min, ts). Returns {tick_id: TickState}."""
    out = {}
    for k in range(first_tick, last_tick + 1):
        p = powers(k) if callable(powers) else powers
        report = hub_report(lane=kitchen.control, tick_id=k, ts=start + k * MIN, total_kw=0.0, devices=devices,
                            power_by_device=p)
        out[k] = as_tick_state(kitchen.step(1, report.model_dump(mode="json")))
    return out


def _replay(kitchen, devices: list[dict], start: datetime, n_steps: int,
            powers: Callable[[datetime], Mapping[str, float]], capture: set[datetime]) -> dict:
    """15-min steps (replay cadence, decider + forecast on every step). Step i meters block [start + 15(i-1), start + 15i)
    at powers(block_start). Returns {ts: TickState} for ts in `capture`."""
    out = {}
    for i in range(1, n_steps + 1):
        ts = start + i * BLK
        report = hub_report(lane=kitchen.control, tick_id=i, ts=ts, total_kw=0.0, devices=devices,
                            power_by_device=powers(ts - BLK))
        state = kitchen.step(15, report.model_dump(mode="json"))
        if ts in capture:
            out[ts] = as_tick_state(state)
    return out


def _fc(state) -> list[float]:
    fc = state.forecast_kw
    assert fc is not None, "decision tick must carry forecast_kw"
    assert len(fc) == 8
    return list(fc)


def _approx(values) -> list:
    return [pytest.approx(v, abs=E) for v in values]


FRI = date(2026, 7, 17)  # Friday; previous Fridays 07-10, 07-03, 06-26, 06-19 (weeks 1-4), 06-12 (week 5)


def _week(w: int) -> date:
    return FRI - timedelta(days=7 * w)


# =====================================================================================================================
# Base: same weekday + local block time, previous 4 weeks (ENGINE.md section 3 "Base")
# =====================================================================================================================


def _base_history(hvac_weeks=(1, 2, 3, 4, 5)):
    """Warm-up ending Friday 07-17 12:00 local.
    Previous Fridays (week w = 1..5): slots 11:30, 11:45, 12:00 -> lights 2.0, hvac 1.0;
      slots 12:15 + 15k (k = 0..7) -> lights 2.0, hvac k + w for w <= 4, hvac 11.0 for week 5 (> 4 weeks back).
      hvac rows only for the weeks in `hvac_weeks`; lights rows for every week.
    Decoy: Thursday 07-16 slots 12:15..14:00 -> hvac 11.0 (wrong weekday).
    Start day 07-17: 11:00..11:45 -> lights 2.0, hvac 1.5."""
    rows = []
    for w in (1, 2, 3, 4, 5):
        day = _week(w)
        for s in _slots(day, 11, 30, 3):
            rows.append((s, "lights_1", 2.0))
            if w in hvac_weeks:
                rows.append((s, "hvac_1", 1.0))
        for k, s in enumerate(_slots(day, 12, 15, 8)):
            rows.append((s, "lights_1", 2.0))
            if w in hvac_weeks:
                rows.append((s, "hvac_1", float(k + w) if w <= 4 else 11.0))
    for s in _slots(date(2026, 7, 16), 12, 15, 8):
        rows.append((s, "lights_1", 2.0))
        rows.append((s, "hvac_1", 11.0))
    for s in _slots(FRI, 11, 0, 4):
        rows.append((s, "lights_1", 2.0))
        rows.append((s, "hvac_1", 1.5))
    return warmup_history_per_device(start=_at(_week(5), 0, 0), end=_at(FRI, 12, 0), blocks=rows)


LIVE_BASE = {"lights_1": 2.0, "hvac_1": 1.5}


def test_base_is_mean_of_previous_four_same_weekdays_at_block_boundary():
    devices = [LIGHTS, HVAC1]
    k = _kitchen(devices, history=_base_history())
    states = _live(k, devices, _at(FRI, 12, 0), 1, 15, LIVE_BASE)
    # tick 15: ts 12:15, a decision tick (15 % 5 == 0) on a block boundary -> block 0 = [12:15, 12:30), 0 min metered.
    # hvac slot k: weeks 1..4 = k+1, k+2, k+3, k+4 -> mean k + 2.5 (week 5's 11.0 is more than 4 weeks back; Thursday's
    # 11.0 is another weekday; the 1.5 kW last closed block and current power are not used: history exists)
    # lights 2.0 x ratio 1.0 = 2.0  ->  block k = 2.0 + k + 2.5 = 4.5 + k
    assert _fc(states[15]) == _approx([4.5 + i for i in range(8)])
    # forecast(120) returns that same latest decision-tick forecast
    assert k.forecast(120) == _approx([4.5 + i for i in range(8)])


def test_block_zero_is_metered_minutes_plus_forecast_for_the_rest():
    devices = [LIGHTS, HVAC1]
    k = _kitchen(devices, history=_base_history())
    states = _live(k, devices, _at(FRI, 12, 0), 1, 20, LIVE_BASE)
    # tick 20: ts 12:20, block 0 = [12:15, 12:30)
    # metered: ticks 16..20 = 5 min at 2.0 + 1.5 = 3.5 kW -> 3.5 x 5/60 = 0.2916667 kWh
    # rest: 10 min at the slot-0 forecast 2.0 + 2.5 = 4.5 kW -> 4.5 x 10/60 = 0.75 kWh
    # block 0 = (0.2916667 + 0.75) / 0.25 = 4.1666667 kW
    # blocks 1..7 = slots 12:30..14:00 -> 4.5 + k for k = 1..7
    assert _fc(states[20]) == _approx([1.0416666666666667 / 0.25] + [4.5 + i for i in range(1, 8)])


def test_fewer_than_four_weeks_uses_mean_of_what_exists():
    devices = [LIGHTS, HVAC1]
    k = _kitchen(devices, history=_base_history(hvac_weeks=(1, 3)))
    states = _live(k, devices, _at(FRI, 12, 0), 1, 15, LIVE_BASE)
    # hvac slot k only in weeks 1 and 3: (k+1 + k+3) / 2 = k + 2  ->  block k = 2.0 + k + 2 = 4.0 + k
    assert _fc(states[15]) == _approx([4.0 + i for i in range(8)])


def test_week_four_counts_week_five_does_not():
    devices = [LIGHTS, HVAC1]
    k = _kitchen(devices, history=_base_history(hvac_weeks=(4, 5)))
    states = _live(k, devices, _at(FRI, 12, 0), 1, 15, LIVE_BASE)
    # week 4 (06-19, exactly 28 days back) hvac k + 4 counts; week 5 (06-12, 35 days) 11.0 does not -> base k + 4
    # block k = 2.0 + k + 4 = 6.0 + k   (a 5-week mean would give (k+4+11)/2)
    assert _fc(states[15]) == _approx([6.0 + i for i in range(8)])


def test_no_same_weekday_history_falls_back_to_last_closed_block():
    devices = [LIGHTS, HVAC1]
    k = _kitchen(devices)  # no warm-up: live history only (ENGINE.md section 0)
    states = _live(k, devices, _at(FRI, 12, 0), 1, 15,
                   lambda t: {"lights_1": 2.0, "hvac_1": 3.0 if t <= 10 else 6.0})
    # closed block [12:00, 12:15): hvac (10 min x 3.0 + 5 min x 6.0) / 15 = 60/15 = 4.0 kW; current power 6.0 is not used
    # every block: 2.0 + 4.0 = 6.0   (current power would give 8.0)
    assert _fc(states[15]) == _approx([6.0] * 8)


def test_other_weekday_history_only_still_falls_back_to_last_closed_block():
    devices = [LIGHTS, HVAC1]
    rows = []
    for s in _slots(date(2026, 7, 16), 12, 0, 9):  # Thursday 12:00..14:00: hvac 9.0 (not a Friday)
        rows += [(s, "lights_1", 2.0), (s, "hvac_1", 9.0)]
    for s in _slots(FRI, 11, 30, 2):  # Friday 11:30, 11:45: hvac 2.0
        rows += [(s, "lights_1", 2.0), (s, "hvac_1", 2.0)]
    hist = warmup_history_per_device(start=_at(date(2026, 7, 16), 0, 0), end=_at(FRI, 12, 0), blocks=rows)
    k = _kitchen(devices, history=hist)
    states = _live(k, devices, _at(FRI, 12, 0), 1, 15,
                   lambda t: {"lights_1": 2.0, "hvac_1": 3.0 if t <= 10 else 6.0})
    # no Friday at 12:15..14:00 in the last 4 weeks -> last closed block = own [12:00, 12:15) = 4.0 (as above)
    # every block: 2.0 + 4.0 = 6.0   (Thursday's 9.0 would give 11.0; the warm-up 11:45 block 2.0 would give 4.0)
    assert _fc(states[15]) == _approx([6.0] * 8)


def test_no_closed_block_falls_back_to_current_power():
    devices = [LIGHTS, HVAC1]
    k = _kitchen(devices)
    states = _live(k, devices, _at(FRI, 12, 0), 1, 5,
                   lambda t: {"lights_1": 2.0, "hvac_1": 3.0 if t <= 4 else 6.0})
    # tick 5: ts 12:05, nothing closed yet -> base = current power: lights 2.0, hvac 6.0 (ratio: no closed block; lights
    # constant, so 1.0 under any reading)
    # block 0 [12:00, 12:15): metered lights 2.0 x 5/60 = 0.1666667 + hvac (4 x 3.0 + 1 x 6.0)/60 = 0.3 -> 0.4666667 kWh
    #   rest 10 min at 2.0 + 6.0 = 8.0 kW -> 1.3333333 kWh ; block 0 = (0.4666667 + 1.3333333) / 0.25 = 1.8 / 0.25 = 7.2
    # blocks 1..7 = 8.0
    assert _fc(states[5]) == _approx([7.2] + [8.0] * 7)


def test_block_zero_rest_uses_base_not_current_power():
    devices = [LIGHTS, HVAC1]
    k = _kitchen(devices)
    states = _live(k, devices, _at(FRI, 12, 0), 1, 20,
                   lambda t: {"lights_1": 2.0, "hvac_1": (3.0 if t <= 10 else 6.0) if t <= 15 else 12.0})
    # tick 20: ts 12:20, block 0 = [12:15, 12:30); base hvac = last closed block [12:00, 12:15) = 4.0
    # metered ticks 16..20: 5 min at 2.0 + 12.0 = 14.0 kW -> 14 x 5/60 = 1.1666667 kWh
    # rest 10 min at 2.0 + 4.0 = 6.0 kW -> 1.0 kWh ; block 0 = 2.1666667 / 0.25 = 8.6666667
    # blocks 1..7 = 6.0
    assert _fc(states[20]) == _approx([2.1666666666666665 / 0.25] + [6.0] * 7)


def test_weekday_follows_each_block_across_local_midnight():
    devices = [LIGHTS, HVAC1]
    rows = []
    fri_prev, sat_prev = date(2026, 7, 10), date(2026, 7, 11)
    for s in _slots(fri_prev, 0, 0, 6):  # decoy: Friday 07-10 00:00..01:15 hvac 7.0 (right clock time, wrong weekday)
        rows += [(s, "lights_1", 2.0), (s, "hvac_1", 7.0)]
    for s in _slots(fri_prev, 22, 30, 6):  # Friday 07-10 22:30..23:45 hvac 4.0
        rows += [(s, "lights_1", 2.0), (s, "hvac_1", 4.0)]
    for s in _slots(sat_prev, 0, 0, 6):  # Saturday 07-11 00:00..01:15 hvac 1.0
        rows += [(s, "lights_1", 2.0), (s, "hvac_1", 1.0)]
    for s in _slots(FRI, 22, 30, 2):
        rows += [(s, "lights_1", 2.0), (s, "hvac_1", 1.0)]
    hist = warmup_history_per_device(start=_at(fri_prev, 0, 0), end=_at(FRI, 23, 0), blocks=rows)
    k = _kitchen(devices, history=hist)
    states = _live(k, devices, _at(FRI, 23, 0), 1, 30, {"lights_1": 2.0, "hvac_1": 1.0})
    # tick 30: ts Friday 23:30. Blocks 23:30, 23:45 are Friday slots -> 07-10 hvac 4.0 -> 2.0 + 4.0 = 6.0
    # blocks 00:00..01:15 are Saturday slots -> 07-11 hvac 1.0 -> 3.0   (Friday 07-10 00:00 decoy would give 9.0)
    assert _fc(states[30]) == _approx([6.0, 6.0] + [3.0] * 6)


def test_same_local_block_time_across_dst_fall_back():
    devices = [LIGHTS, HVAC1]
    sat_prev, sat = date(2026, 10, 31), date(2026, 11, 7)  # PDT (UTC-7) -> PST (UTC-8); DST ends Sun 2026-11-01
    rows = []
    for i, s in enumerate(_slots(sat_prev, 11, 0, 16)):  # 11:00..14:45 PDT: hvac 1.0 + 0.5 i  (12:00 + 15k -> 3.0 + 0.5k)
        rows += [(s, "lights_1", 2.0), (s, "hvac_1", 1.0 + 0.5 * i)]
    for s in _slots(sat, 11, 15, 2):
        rows += [(s, "lights_1", 2.0), (s, "hvac_1", 2.0)]
    hist = warmup_history_per_device(start=_at(sat_prev, 0, 0), end=_at(sat, 11, 45), blocks=rows)
    k = _kitchen(devices, history=hist)
    states = _live(k, devices, _at(sat, 11, 45), 1, 15, {"lights_1": 2.0, "hvac_1": 2.0})
    # tick 15: ts Sat 11-07 12:00 PST (20:00Z). Same local time a week ago = 10-31 12:00 PDT (19:00Z): hvac 3.0 + 0.5k
    # block k = 2.0 + 3.0 + 0.5k = 5.0 + 0.5k   (a plain UTC - 7 days lookup lands on 13:00 PDT -> 7.0 + 0.5k)
    assert _fc(states[15]) == _approx([5.0 + 0.5 * i for i in range(8)])


# =====================================================================================================================
# Live ratio (always_on together, last 2 closed blocks, clamp 0.5-2.0, next hour, fade in the second hour)
# =====================================================================================================================

T_RATIO = _at(FRI, 11, 45)


def _ratio_history():
    """Weeks 1..4 Fridays, slots 11:00..14:15 (14 blocks): lights 2.0, fryer 4.0, hvac 5.0, dishwasher 1.0 (all weeks equal,
    so every base is exact for any number of weeks)."""
    rows = []
    for w in (1, 2, 3, 4):
        for s in _slots(_week(w), 11, 0, 14):
            rows += [(s, "lights_1", 2.0), (s, "fryer_1", 4.0), (s, "hvac_1", 5.0), (s, "dishwasher_1", 1.0)]
    return warmup_history_per_device(start=_at(_week(4), 0, 0), end=T_RATIO, blocks=rows)


RATIO_DEVICES = [LIGHTS, FRYER, HVAC1, DISHWASHER]


def _ratio_run(lights_kw: Callable[[int], float], fryer_kw: Callable[[int], float]) -> list[float]:
    k = _kitchen(RATIO_DEVICES, history=_ratio_history())
    states = _live(k, RATIO_DEVICES, T_RATIO, 1, 30,
                   lambda t: {"lights_1": lights_kw(t), "fryer_1": fryer_kw(t), "hvac_1": 5.0, "dishwasher_1": 0.0})
    # tick 30: ts 12:15, block boundary; last 2 closed blocks = [11:45, 12:00) (ticks 1..15) and [12:00, 12:15) (16..30)
    return _fc(states[30])


def test_live_ratio_is_always_on_devices_together_over_last_two_blocks():
    fc = _ratio_run(lambda t: 2.0, lambda t: 6.0 if t <= 15 else 10.0)
    # actual always_on: block 1 = 2.0 + 6.0 = 8.0, block 2 = 2.0 + 10.0 = 12.0 -> 20.0 ; base 2 x (2.0 + 4.0) = 12.0
    # ratio = 20 / 12 = 1.6666667 (in [0.5, 2.0])   [last block only: 12/6 = 2.0; per-device mean: (1 + 2)/2 = 1.5]
    # next hour, blocks 0..3: (lights 2 + fryer 4 + hvac 5) x 1.6666667 = 18.3333333 ; dishwasher (deferrable) 1.0 unscaled
    # block = 18.3333333 + 1.0 = 19.3333333
    r = 20.0 / 12.0
    assert fc[:4] == _approx([11.0 * r + 1.0] * 4)


def test_live_ratio_fades_toward_one_over_the_second_hour():
    fc = _ratio_run(lambda t: 2.0, lambda t: 6.0 if t <= 15 else 10.0)
    r = 20.0 / 12.0
    first_hour = 11.0 * r + 1.0  # 19.3333333
    unscaled = 11.0 + 1.0  # ratio 1.0 -> 12.0
    # anchor: block 3 (last of the first hour) carries the full ratio, 11 x 1.6666667 + 1 = 19.3333333
    assert fc[3] == pytest.approx(first_hour, abs=E)
    # second hour, blocks 4..7: factor moves linearly from r toward 1.0 -> every block in [12.0, 19.3333], non-increasing,
    # and block 7 strictly below the first-hour value (it has faded at least part of the way)
    for v in fc[4:]:
        assert unscaled - E <= v <= first_hour + E
    assert all(fc[i] >= fc[i + 1] - E for i in range(3, 7))
    assert fc[7] < first_hour - 1e-3


@pytest.mark.skip(reason="TBD: no gap id (propose one) - ENGINE.md section 3 'fading linearly to 1.0 over the second hour' "
                         "does not fix the per-block factor (block 4 = r? block 7 = 1.0? block midpoints?)")
def test_live_ratio_second_hour_exact_factors():
    pass


def test_live_ratio_clamped_at_two():
    fc = _ratio_run(lambda t: 2.4, lambda t: 14.0)
    # actual 2 x (2.4 + 14.0) = 32.8 ; base 12.0 -> 2.7333 -> clamp 2.0
    # blocks 0..3 = 11.0 x 2.0 + 1.0 = 23.0
    assert fc[:4] == _approx([23.0] * 4)


def test_live_ratio_exactly_two_is_not_clamped_further():
    fc = _ratio_run(lambda t: 2.0, lambda t: 10.0)
    # actual 2 x 12.0 = 24.0 ; base 12.0 -> exactly 2.0 (boundary) -> blocks 0..3 = 11.0 x 2.0 + 1.0 = 23.0
    assert fc[:4] == _approx([23.0] * 4)


def test_live_ratio_clamped_at_half():
    fc = _ratio_run(lambda t: 1.0, lambda t: 1.0)
    # actual 2 x (1.0 + 1.0) = 4.0 ; base 12.0 -> 0.3333 -> clamp 0.5
    # blocks 0..3 = 11.0 x 0.5 + 1.0 = 6.5
    assert fc[:4] == _approx([6.5] * 4)


def test_live_ratio_one_leaves_the_base():
    fc = _ratio_run(lambda t: 2.0, lambda t: 4.0)
    # actual = base = 12.0 -> ratio 1.0 -> every block 2 + 4 + 5 + 1 = 12.0 (fade from 1.0 to 1.0 changes nothing)
    assert fc == _approx([12.0] * 8)


@pytest.mark.skip(reason="TBD: no gap id (propose one) - ENGINE.md section 3 does not say how the live ratio is formed with "
                         "fewer than 2 closed blocks, or with no always_on device in the kitchen")
def test_live_ratio_with_fewer_than_two_closed_blocks():
    pass


# =====================================================================================================================
# Crowd multiplier on demand_driven only (ENGINE.md sections 2, 3)
# =====================================================================================================================


def test_crowd_large_scales_only_demand_driven_history_base():
    devices = [LIGHTS, FRYER_FLEX, HVAC1, DISHWASHER]  # fryer flexible here so the always_on ratio is lights alone (= 1.0)
    rows = []
    for w in (1, 2, 3, 4):
        for s in _slots(_week(w), 11, 0, 14):
            rows += [(s, "lights_1", 2.0), (s, "fryer_1", 4.0), (s, "hvac_1", 5.0), (s, "dishwasher_1", 1.0)]
    live = {"lights_1": 2.0, "fryer_1": 4.0, "hvac_1": 5.0, "dishwasher_1": 0.0}

    plain = _kitchen(devices, history=warmup_history_per_device(start=_at(_week(4), 0, 0), end=T_RATIO, blocks=rows))
    crowded = _kitchen(devices, history=warmup_history_per_device(start=_at(_week(4), 0, 0), end=T_RATIO, blocks=rows))
    crowded.set_context({"ts": "2026-07-17T18:45:00Z", "weather": None, "prices": None, "events": None,
                         "crowd_effect": {"value": "large", "set_by": "claude", "reason": "test"}})
    p = _live(plain, devices, T_RATIO, 1, 30, live)[30]
    c = _live(crowded, devices, T_RATIO, 1, 30, live)[30]
    # no context: 2.0 + 4.0 + 5.0 + 1.0 = 12.0 every block
    assert _fc(p) == _approx([12.0] * 8)
    # large -> 1.40 on the demand_driven fryer only: 4.0 x 1.4 = 5.6 -> 2.0 + 5.6 + 5.0 + 1.0 = 13.6
    assert _fc(c) == _approx([13.6] * 8)


@pytest.mark.skip(reason="TBD: no gap id (propose one) - an always_on demand_driven device gets both the live ratio and the "
                         "crowd multiplier; ENGINE.md section 3 does not say whether the ratio's base includes crowd")
def test_ratio_and_crowd_combined_on_always_on_demand_driven():
    pass


# =====================================================================================================================
# Kitchen.forecast(horizon_min) and TickState.forecast_kw cadence
# =====================================================================================================================


@pytest.mark.parametrize("horizon_min", [0, 15, 60, 119, 121, 240])
def test_forecast_horizon_other_than_120_raises_value_error(horizon_min):
    devices = [LIGHTS, HVAC1]
    k = _kitchen(devices)
    _live(k, devices, _at(FRI, 12, 0), 1, 15, {"lights_1": 2.0, "hvac_1": 4.0})
    with pytest.raises(ValueError):
        k.forecast(horizon_min)


def test_forecast_returns_latest_decision_tick_without_recomputing():
    devices = [LIGHTS, HVAC1]
    k = _kitchen(devices)
    powers = lambda t: {"lights_1": 2.0, "hvac_1": (3.0 if t <= 10 else 6.0) if t <= 15 else 12.0}
    states = _live(k, devices, _at(FRI, 12, 0), 1, 15, powers)
    # tick 15 forecast = 6.0 x 8 (last closed block hvac 4.0 + lights 2.0)
    assert k.forecast(120) == _approx([6.0] * 8)
    later = _live(k, devices, _at(FRI, 12, 0), 16, 19, powers)
    # ticks 16..19 are not decision ticks (16..19 % 5 != 0) -> forecast_kw null, forecast(120) unchanged
    assert all(later[t].forecast_kw is None for t in range(16, 20))
    assert k.forecast(120) == _approx([6.0] * 8)
    assert k.forecast(120) == _approx(_fc(states[15]))
    nxt = _live(k, devices, _at(FRI, 12, 0), 20, 20, powers)
    # tick 20 recomputes: block 0 = (5 min x 14 kW + 10 min x 6 kW) / 60 / 0.25 = (1.1666667 + 1.0) / 0.25 = 8.6666667
    assert k.forecast(120) == _approx(_fc(nxt[20]))
    assert k.forecast(120)[0] == pytest.approx(2.1666666666666665 / 0.25, abs=E)


def test_forecast_kw_only_on_decision_ticks_live():
    devices = [LIGHTS, HVAC1]
    k = _kitchen(devices)
    states = _live(k, devices, _at(FRI, 12, 0), 1, 30, {"lights_1": 2.0, "hvac_1": 4.0})
    for t, s in states.items():
        if t % 5 == 0:
            assert s.forecast_kw is not None and len(s.forecast_kw) == 8
        else:
            assert s.forecast_kw is None


def test_both_lanes_carry_identical_forecast_for_identical_reports():
    devices = [LIGHTS, HVAC1]
    hist = _base_history()
    without = _kitchen(devices, control="without", history=hist)
    with_ = _kitchen(devices, control="with", history=hist)
    sw = _live(without, devices, _at(FRI, 12, 0), 1, 15, LIVE_BASE)
    sv = _live(with_, devices, _at(FRI, 12, 0), 1, 15, LIVE_BASE)
    # nothing is commanded (cap 100), so the without lane forecasts the same numbers: 4.5 + k
    assert _fc(sw[15]) == _approx([4.5 + i for i in range(8)])
    assert _fc(sw[15]) == _approx(_fc(sv[15]))


@pytest.mark.skip(reason="TBD: no gap id (propose one) - CONTRACTS.md section 3 does not say what forecast(120) returns "
                         "before the first decision tick (None, [], ValueError?)")
def test_forecast_before_first_decision_tick():
    pass


# =====================================================================================================================
# Multi-day runs: the engine's own closed blocks feed the base (ENGINE.md sections 0, 3)
# =====================================================================================================================

RUN_START = local_ts(2026, 7, 3, 0, 0)  # Friday 00:00 local, no warm-up


@pytest.mark.slow
def test_multi_day_base_uses_own_overnight_block_of_same_weekday_last_week():
    devices = [LIGHTS, HVAC1]

    def powers(block_start: datetime) -> dict:
        if block_start == _at(date(2026, 7, 3), 3, 0):
            hvac = 3.0  # Friday 07-03 03:00 (closed hours, metered like any other block)
        elif block_start == _at(date(2026, 7, 3), 3, 15):
            hvac = 2.0
        elif any(block_start == _at(date(2026, 7, 3) + timedelta(days=d), 3, 0) for d in range(1, 7)):
            hvac = 1.5  # Sat..Thu 03:00 decoys (same clock time, other weekdays)
        else:
            hvac = 1.0
        return {"lights_1": 2.0, "hvac_1": hvac}

    target = _at(date(2026, 7, 10), 3, 0)
    n = int((target - RUN_START) / BLK)  # 7 x 96 + 12 = 684 steps
    assert n == 684
    k = _kitchen(devices)
    states = _replay(k, devices, RUN_START, n, powers, {target})
    # ts Friday 07-10 03:00: block 0 = 03:00 Friday slot -> own block 07-03 03:00 = 3.0 -> 2.0 + 3.0 = 5.0
    # block 1 = 03:15 -> 2.0 -> 4.0 ; blocks 2..7 (03:30..04:45) -> 1.0 -> 3.0
    # (last closed block 02:45 = 1.0 would give 3.0; Thursday's 03:00 decoy 1.5 would give 3.5)
    assert _fc(states[target]) == _approx([5.0, 4.0] + [3.0] * 6)


@pytest.mark.slow
def test_multi_day_run_without_warm_up_converges_as_days_accumulate():
    devices = [LIGHTS, HVAC1]
    d0, d7, d14 = date(2026, 7, 3), date(2026, 7, 10), date(2026, 7, 17)
    noon = {d0: 4.0, d7: 2.0, d14: 3.0}

    def powers(block_start: datetime) -> dict:
        hvac = 1.0
        for day, kw in noon.items():
            if block_start == _at(day, 12, 0):
                hvac = kw  # Friday 12:00 slot varies by week
            if block_start == _at(day, 12, 30):
                hvac = 5.0  # Friday 12:30 slot is the same every week
        return {"lights_1": 2.0, "hvac_1": hvac}

    caps = {_at(d0, 12, 0), _at(d7, 12, 0), _at(d14, 12, 0)}
    n = int((_at(d14, 12, 0) - RUN_START) / BLK)  # 14 x 96 + 48 = 1392 steps
    assert n == 1392
    k = _kitchen(devices)
    s = _replay(k, devices, RUN_START, n, powers, caps)

    f0, f7, f14 = _fc(s[_at(d0, 12, 0)]), _fc(s[_at(d7, 12, 0)]), _fc(s[_at(d14, 12, 0)])
    # day 0: no Friday history yet -> every block = last closed block 11:45 hvac 1.0 -> 2.0 + 1.0 = 3.0
    assert f0 == _approx([3.0] * 8)
    # day 7: one Friday -> 12:00 = 4.0 -> 6.0 ; 12:15 = 1.0 -> 3.0 ; 12:30 = 5.0 -> 7.0 ; rest 3.0
    assert f7 == _approx([6.0, 3.0, 7.0] + [3.0] * 5)
    # day 14: two Fridays -> 12:00 = (2.0 + 4.0)/2 = 3.0 -> 5.0 ; 12:30 = (5 + 5)/2 = 5.0 -> 7.0 ; rest 3.0
    assert f14 == _approx([5.0, 3.0, 7.0] + [3.0] * 5)
    # convergence on the weekly-repeating 12:30 slot (actual 2.0 + 5.0 = 7.0): error 4.0 on day 0, 0 on days 7 and 14
    assert abs(f0[2] - 7.0) == pytest.approx(4.0, abs=E)
    assert abs(f7[2] - 7.0) == pytest.approx(0.0, abs=E)
    assert abs(f14[2] - 7.0) == pytest.approx(0.0, abs=E)


@pytest.mark.slow
def test_multi_day_base_mixes_warm_up_weeks_with_own_week():
    devices = [LIGHTS, HVAC1]
    start = _at(date(2026, 7, 10), 12, 0)
    rows = []
    for day, kw in ((date(2026, 7, 3), 3.0), (date(2026, 6, 26), 2.0), (date(2026, 6, 19), 1.0), (date(2026, 6, 12), 9.0)):
        s = _at(day, 12, 0)
        rows += [(s, "lights_1", 2.0), (s, "hvac_1", kw)]
    hist = warmup_history_per_device(start=_at(date(2026, 6, 12), 0, 0), end=start, blocks=rows)

    def powers(block_start: datetime) -> dict:
        return {"lights_1": 2.0, "hvac_1": 6.0 if block_start == start else 1.0}

    target = _at(FRI, 12, 0)
    n = int((target - start) / BLK)  # 7 x 96 = 672 steps
    assert n == 672
    k = _kitchen(devices, history=hist)
    s = _replay(k, devices, start, n, powers, {target})
    # Friday 07-17 12:00: weeks 1..4 = own 07-10 6.0, warm-up 07-03 3.0, 06-26 2.0, 06-19 1.0 (06-12's 9.0 is week 5)
    # mean = 12 / 4 = 3.0 -> 2.0 + 3.0 = 5.0
    # 12:15..13:45: only own 07-10 blocks (1.0) -> 3.0
    assert _fc(s[target]) == _approx([5.0] + [3.0] * 7)


# =====================================================================================================================
# Internal: commanded (reduced) devices, catch-up, unavoidable_kw, no peeking
# =====================================================================================================================

NOW = _at(FRI, 12, 0)


def _internal_devices(power: Mapping[str, float]) -> list[dict]:
    out = []
    for d in (LIGHTS, HVAC1, HVAC2, WATER_HEATER, DISHWASHER):
        p = power[d["device_id"]]
        out.append({"device_id": d["device_id"], "type_id": d["type_id"], "name": d["name"],
                    "importance": d["importance"], "state": "on" if p > 0 else "off", "power_kw": p,
                    "rated_kw": d["rated_kw"], "power_pct": round(100 * p / d["rated_kw"]), "source": "simulated",
                    "power_model": d["power_model"], "limits": dict(LIMITS[d["importance"]])})
    return out


HIST_KW = {"lights_1": 2.0, "hvac_1": 10.0, "hvac_2": 3.0, "water_heater_1": 2.0, "dishwasher_1": 3.0}
NOW_KW = {"lights_1": 2.0, "hvac_1": 10.0, "hvac_2": 3.0, "water_heater_1": 2.0, "dishwasher_1": 0.0}


def _internal_history(extra_future: Optional[dict] = None, with_week_ago: bool = True):
    """BlockHistory: Friday 07-10 12:00..13:45 at HIST_KW (if with_week_ago); 07-17 11:30, 11:45 at NOW_KW;
    optionally injected blocks at or after NOW (not closed: must never be read)."""
    from engine.history import BlockHistory

    h = BlockHistory()
    if with_week_ago:
        for s in _slots(date(2026, 7, 10), 12, 0, 8):
            h.add(s, dict(HIST_KW), sum(HIST_KW.values()))
    for s in _slots(FRI, 11, 30, 2):
        h.add(s, dict(NOW_KW), sum(NOW_KW.values()))
    for s, kw in sorted((extra_future or {}).items()):
        h.add(s, kw, sum(kw.values()))
    return h


def _forecast_internal(reductions=None, history=None):
    from engine.forecaster import forecast_devices
    from engine.tariff import TariffView

    h = history if history is not None else _internal_history()
    return forecast_devices(now=NOW, history=h.view(NOW), tariff=TariffView(Tariff.model_validate(load_tariff())),
                            devices=_internal_devices(NOW_KW), block0_metered_kwh={}, crowd_multiplier=1.0,
                            reductions=reductions)


def test_internal_uncommanded_forecast_per_device_and_total():
    r = _forecast_internal()
    # block starts: 12:00 + 15k local (19:00Z + 15k)
    assert r["block_starts"] == [NOW + i * BLK for i in range(8)]
    # one Friday a week ago per slot -> base = HIST_KW; ratio = lights 2.0 / 2.0 = 1.0; dishwasher idle, unheld -> its base 3.0
    for device_id, kw in HIST_KW.items():
        assert r["device_kw"][device_id] == _approx([kw] * 8)
    # total = 2 + 10 + 3 + 2 + 3 = 20.0
    assert r["total_kw"] == _approx([20.0] * 8)


def test_internal_unavoidable_kw():
    r = _forecast_internal()
    # always_on lights 2.0
    # + hvac_1 min(10.0, 40% x 12 = 4.8) = 4.8 + hvac_2 min(3.0, 4.8) = 3.0 + water_heater min(2.0, 40% x 4.5 = 1.8) = 1.8
    # + dishwasher: idle at 12:00, deadline 19:30, max delay 60 -> can still move, not running -> 0
    # = 2.0 + 4.8 + 3.0 + 1.8 = 11.6
    assert r["unavoidable_kw"] == _approx([11.6] * 8)
    assert all(u <= t + E for u, t in zip(r["unavoidable_kw"], r["total_kw"]))


def test_internal_reduced_device_capped_then_catch_up_capped_at_rated():
    r = _forecast_internal(reductions={"hvac_1": {"value_pct": 60, "restore_at": NOW + 30 * MIN, "owed_kwh": 0.5}})
    # blocks 0, 1 (until restore at 12:30): min(base 10.0, 60% x 12 = 7.2) = 7.2
    # block 2 (first after restore): base 10.0 + owed 0.5 x 4 = 12.0, cap rated 12.0 -> 12.0 (also 12.0 if the owed kWh
    #   still accruing until 12:30 were added: 10 + (0.5 + 1.4) x 4 = 17.6 -> 12.0)
    # blocks 3..7: base 10.0 (catch-up only in the first block after restore)
    assert r["device_kw"]["hvac_1"] == _approx([7.2, 7.2, 12.0] + [10.0] * 5)
    # total = other devices 10.0 + hvac_1 -> 17.2, 17.2, 22.0, 20.0 x 5
    assert r["total_kw"] == _approx([17.2, 17.2, 22.0] + [20.0] * 5)
    # unavoidable unchanged: hvac_1 min(7.2 | 12.0 | 10.0, 4.8) = 4.8 -> 11.6
    assert r["unavoidable_kw"] == _approx([11.6] * 8)


def test_internal_reduce_cap_above_base_leaves_base_and_catch_up_adds_owed_times_four():
    r = _forecast_internal(reductions={"hvac_2": {"value_pct": 50, "restore_at": NOW + 30 * MIN, "owed_kwh": 1.0}})
    # blocks 0, 1: min(base 3.0, 50% x 12 = 6.0) = 3.0 (already below the cap, nothing more owed)
    # block 2: 3.0 + 1.0 kWh x 4 = 7.0 (<= 12.0 rated) ; blocks 3..7: 3.0
    assert r["device_kw"]["hvac_2"] == _approx([3.0, 3.0, 7.0] + [3.0] * 5)
    # total 20, 20, 24, 20 x 5
    assert r["total_kw"] == _approx([20.0, 20.0, 24.0] + [20.0] * 5)


def test_internal_reduce_exactly_at_min_power_pct_through_horizon():
    r = _forecast_internal(reductions={"hvac_1": {"value_pct": 40, "restore_at": NOW + 150 * MIN, "owed_kwh": 0.0}})
    # restore at 14:30 is after the horizon end (14:00): all 8 blocks min(10.0, 40% x 12 = 4.8) = 4.8, no catch-up shown
    assert r["device_kw"]["hvac_1"] == _approx([4.8] * 8)
    # total 2 + 4.8 + 3 + 2 + 3 = 14.8 ; unavoidable hvac_1 = min(4.8, 4.8) = 4.8 -> still 11.6 (exactly at the floor)
    assert r["total_kw"] == _approx([14.8] * 8)
    assert r["unavoidable_kw"] == _approx([11.6] * 8)


@pytest.mark.skip(reason="TBD: no gap id (propose one) - ENGINE.md section 3 catch-up: is owed_kwh the ledger now or projected "
                         "to the restore, and how is a restore inside a block split (restore_at not on :00/:15/:30/:45)?")
def test_internal_restore_mid_block_and_projected_owed():
    pass


@pytest.mark.skip(reason="TBD: decider (ENGINE.md section 5) - waiting job placement (rated_kw x cycle_min at the planned "
                         "release) and a running_job's remaining minutes (physical.job_remaining_min) are not specified "
                         "for the forecaster input yet")
def test_internal_waiting_and_running_job_forecast():
    pass


def test_internal_future_blocks_in_store_are_never_read():
    future = {NOW: {**NOW_KW, "hvac_1": 11.5}, NOW + BLK: {**NOW_KW, "hvac_1": 11.5}}
    r = _forecast_internal(history=_internal_history(extra_future=future))
    # blocks 12:00 and 12:15 today are not closed at 12:00 -> must not be read (no PeekError, no 11.5 used)
    # hvac_1 = week-ago 10.0 every block
    assert r["device_kw"]["hvac_1"] == _approx([10.0] * 8)


def test_internal_last_closed_fallback_ignores_future_blocks():
    future = {NOW: {**NOW_KW, "hvac_1": 11.5}}
    r = _forecast_internal(history=_internal_history(extra_future=future, with_week_ago=False))
    # no Friday a week ago -> last closed block = 11:45 today (hvac_1 10.0); the stored 12:00 block (11.5) ends after now
    assert r["device_kw"]["hvac_1"] == _approx([10.0] * 8)


def test_history_view_raises_on_block_ending_after_now():
    from engine.history import PeekError

    view = _internal_history().view(NOW)
    # block 11:45 ends 12:00 = now -> readable ; block 12:00 ends 12:15 > now -> PeekError
    assert view.device_block_kw("hvac_1", NOW - BLK) == pytest.approx(10.0, abs=E)
    with pytest.raises(PeekError):
        view.device_block_kw("hvac_1", NOW)


# =====================================================================================================================
# Invariants over contracts/fixtures/hub_protocol/hub_to_server.jsonl, both lanes (shape only; fixture numbers illustrative)
# =====================================================================================================================


def _fixture_stream():
    lines = (FIXTURES / "hub_protocol" / "hub_to_server.jsonl").read_text().splitlines()
    return [m for m in (json.loads(x) for x in lines if x.strip()) if m["type"] == "hub_report"]


def test_fixture_stream_forecast_invariants_both_lanes():
    from engine import Kitchen

    scenario = json.loads((FIXTURES / "scenario" / "demo_cafe" / "scenario.json").read_text())
    lanes = Kitchen.build_lanes(scenario["config"], scenario["tariff"], catalog(), scenario["seed"])
    block_kwh = {"without": 0.0, "with": 0.0}
    last_fc: dict[str, Optional[list[float]]] = {"without": None, "with": None}
    for msg in _fixture_stream():
        for lane in ("without", "with"):  # runtime order: without, then with
            report = HubReport.model_validate(msg["reports"][lane])
            ts = report.ts
            minute_start = ts - MIN
            if minute_start.minute % 15 == 0:
                block_kwh[lane] = 0.0
            block_kwh[lane] += report.total_kw / 60.0
            state = as_tick_state(lanes[lane].step(1, report.model_dump(mode="json")))
            if report.tick_id % 5 == 0:
                fc = _fc(state)
                assert all(math.isfinite(v) and v >= -E for v in fc)
                # block 0 >= what is already metered in it (the rest of the block is forecast >= 0)
                metered_avg = 0.0 if ts.minute % 15 == 0 else block_kwh[lane] / 0.25
                assert fc[0] >= metered_avg - E
                last_fc[lane] = fc
            else:
                assert state.forecast_kw is None
            if last_fc[lane] is not None:
                assert lanes[lane].forecast(120) == _approx(last_fc[lane])
