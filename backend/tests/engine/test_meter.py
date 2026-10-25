"""Meter (engine/meter.py) through the contract facade: ENGINE.md section 1 and section 15 (Meter, Demand windows G36,
billing boundaries G52, cost_usd_today incl. demand added today), section 0 (warm-up month to date, multi-day runs).

All expected numbers are worked out by hand below; none come from engine output.

Driven only through `Kitchen(config, tariff, catalog, "without", seed)` + `step(minutes, hub_report)` -> TickState.meter
(CONTRACTS.md section 3). The `without` lane never acts, so every Meter number depends on the HubReports alone.

Tariff demo_tariff_v1 (America/Los_Angeles; July = PDT, UTC-7; 1 Nov 2026 = fall-back day):
  energy  0.22 $/kWh 00:00-16:00 and 21:00-24:00 · 0.38 $/kWh 16:00-21:00
  demand  max_demand $20/kW (window null -> month_peak_kw) · peak_demand $8/kW, window [16:00, 21:00) -> on_peak_month_peak_kw
Kitchen: Demo Café, cap 40 kW. Load is spread over the roster in proportion to rated_kw (the meter reads only the sum).
Dates: Thu 16 Jul 2026 is the default day; 31 Jul -> 1 Aug for the month boundary.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Callable, Union

import pytest

from contracts import DemandCharge, HubReport, Meter, MonthToDate, Tariff, WarmUpHistory
from engine import Kitchen

from tests.engine.conftest import (
    FIXTURES,
    LOCAL_TZ,
    as_tick_state,
    catalog,
    hub_report,
    load_catalog,
    load_config,
    load_tariff,
    local_ts,
    meter_of,
    roster,
    warmup_history,
)

E = 1e-6  # energy (kWh) tolerance
USD = 0.01  # $ and kW shown to users

Load = Union[float, Callable[[datetime], float]]


class Feeder:
    """Steps one lane minute by minute (live cadence: step(1, hub_report)), ts = end of the minute just simulated."""

    def __init__(self, kitchen, devices, start_utc: datetime, lane: str = "without", tick0: int = 0):
        self.kitchen = kitchen
        self.devices = devices
        self.ts = start_utc
        self.tick = tick0
        self.lane = lane
        self.meters: dict[datetime, Meter] = {}
        self.states = []

    def feed(self, minutes: int, kw: Load, step_min: int = 1) -> Meter:
        """`kw`: constant, or a function of the minute's *local* start time."""
        meter = None
        for _ in range(minutes // step_min):
            minute_start = self.ts
            self.ts = self.ts + timedelta(minutes=step_min)
            self.tick += 1
            load = kw(minute_start.astimezone(LOCAL_TZ)) if callable(kw) else kw
            report = hub_report(lane=self.lane, tick_id=self.tick, ts=self.ts, total_kw=load, devices=self.devices)
            state = as_tick_state(self.kitchen.step(step_min, report))
            self.states.append(state)
            meter = state.meter
            self.meters[self.ts] = meter
        return meter

    def skip(self, minutes: int) -> None:
        """Metering gap: `minutes` simulated minutes pass with no HubReport (no step); those minutes are never metered."""
        self.ts = self.ts + timedelta(minutes=minutes)
        self.tick += minutes

    def at(self, *local) -> Meter:
        """Meter returned by the step whose ts is this local wall-clock time."""
        return self.meters[local_ts(*local)]


def new_kitchen(tariff: Tariff | None = None, control: str = "without"):
    config = load_config()
    kitchen = Kitchen(config, tariff or load_tariff(), catalog(), control, 42)
    return kitchen, roster(config, load_catalog())


def by_local(rules: list[tuple[tuple, tuple, float]], default: float) -> Callable[[datetime], float]:
    """Piecewise load: [(start (y,m,d,h,mi), end (y,m,d,h,mi), kw)], local start inclusive, end exclusive."""
    spans = [(local_ts(*a), local_ts(*b), kw) for a, b, kw in rules]

    def kw(local_minute_start: datetime) -> float:
        t = local_minute_start
        for a, b, v in spans:
            if a <= t < b:
                return v
        return default

    return kw


# =====================================================================================================================
# Section 15 "Meter": constant 40 kW for 60 min at 1-min steps -> 40 kWh; four blocks of 40 kW; peak 40 kW
# =====================================================================================================================


def test_constant_40kw_for_60_min_gives_40_kwh_and_peak_40():
    kitchen, devices = new_kitchen()
    run = Feeder(kitchen, devices, local_ts(2026, 7, 16, 10, 0))
    m = run.feed(60, 40.0)

    # 40 kW × 60 min / 60 = 40.0 kWh (today and month: the run starts today with no warm-up)
    assert m.energy_kwh_today == pytest.approx(40.0, abs=E)
    assert m.energy_kwh_month == pytest.approx(40.0, abs=E)
    # every minute's total_kw = sum of device power_kw = 40
    assert m.total_kw == pytest.approx(40.0, abs=E)
    # blocks 10:00, 10:15, 10:30, 10:45 each 40 kW × 0.25 h = 10 kWh ÷ 0.25 h = 40 kW -> peak 40
    assert m.month_peak_kw == pytest.approx(40.0, abs=USD)
    # no block starts inside [16:00, 21:00) -> windowed peak still 0 (month to date starts at zero, ENGINE.md section 0)
    assert m.on_peak_month_peak_kw == pytest.approx(0.0, abs=USD)
    # minute starting at ts 11:00 is off-peak -> 0.22
    assert m.price_usd_per_kwh_now == pytest.approx(0.22, abs=1e-9)
    # cost today = energy 40 kWh × 0.22 = 8.80 + demand added today (40 − 0) × 20 = 800 + (0 − 0) × 8 = 0 -> 808.80
    assert m.cost_usd_today == pytest.approx(808.80, abs=USD)
    # cost month = 8.80 + 20 × 40 + 8 × 0 = 808.80
    assert m.cost_usd_month == pytest.approx(808.80, abs=USD)
    # cap mode: target = cap = 40
    assert m.peak_mode == "cap"
    assert m.peak_cap_kw == pytest.approx(40.0, abs=1e-9)
    assert m.target_kw == pytest.approx(40.0, abs=1e-9)


def test_each_of_four_blocks_closes_at_40kw_and_peak_only_moves_on_close():
    kitchen, devices = new_kitchen()
    run = Feeder(kitchen, devices, local_ts(2026, 7, 16, 10, 0))
    run.feed(60, 40.0)

    # ts 10:14: block 10:00 still open (closes when ts reaches 10:00 + 15) -> nothing closed yet -> peak 0
    assert run.at(2026, 7, 16, 10, 14).month_peak_kw == pytest.approx(0.0, abs=USD)
    # ts 10:15, 10:30, 10:45, 11:00: blocks 10:00 / 10:15 / 10:30 / 10:45 close, each 10 kWh ÷ 0.25 h = 40 kW
    for hh, mm in [(10, 15), (10, 30), (10, 45), (11, 0)]:
        assert run.at(2026, 7, 16, hh, mm).month_peak_kw == pytest.approx(40.0, abs=USD)


def test_block_avg_mid_block_counts_unmetered_minutes_as_zero():
    kitchen, devices = new_kitchen()
    run = Feeder(kitchen, devices, local_ts(2026, 7, 16, 10, 0))
    run.feed(23, 40.0)

    m = run.at(2026, 7, 16, 10, 8)
    # open block 10:00 after 8 metered minutes: 40 × 8/60 = 5.3333 kWh ÷ 0.25 h = 21.3333 kW
    assert m.block_avg_kw == pytest.approx(21.333333, abs=1e-4)
    assert m.block_start == local_ts(2026, 7, 16, 10, 0)

    m = run.at(2026, 7, 16, 10, 23)
    # open block 10:15 after 8 minutes (10:15..10:22): same 21.3333 kW
    assert m.block_avg_kw == pytest.approx(21.333333, abs=1e-4)
    assert m.block_start == local_ts(2026, 7, 16, 10, 15)


def test_blocks_are_aligned_to_quarter_hours_not_sliding():
    kitchen, devices = new_kitchen()
    run = Feeder(kitchen, devices, local_ts(2026, 7, 16, 10, 0))
    # 50 kW from 10:08 to 10:23 (15 minutes), 10 kW otherwise; run 10:00 -> 10:45
    load = by_local([((2026, 7, 16, 10, 8), (2026, 7, 16, 10, 23), 50.0)], default=10.0)
    run.feed(45, load)

    # block 10:00: 8 min × 10 kW + 7 min × 50 kW = 1.3333 + 5.8333 = 7.1667 kWh ÷ 0.25 = 28.6667 kW
    assert run.at(2026, 7, 16, 10, 15).month_peak_kw == pytest.approx(28.666667, abs=1e-4)
    # block 10:15: 8 min × 50 + 7 min × 10 = 6.6667 + 1.1667 = 7.8333 kWh ÷ 0.25 = 31.3333 kW
    # (a sliding 15-min window would have found 50 kW)
    assert run.at(2026, 7, 16, 10, 30).month_peak_kw == pytest.approx(31.333333, abs=1e-4)
    # block 10:30: 10 kW -> peak stays 31.3333
    assert run.at(2026, 7, 16, 10, 45).month_peak_kw == pytest.approx(31.333333, abs=1e-4)
    # energy 10:00-10:45: 15 min × 50 = 12.5 + 30 min × 10 = 5.0 -> 17.5 kWh
    assert run.at(2026, 7, 16, 10, 45).energy_kwh_today == pytest.approx(17.5, abs=E)


def test_replay_cadence_one_15_min_step_meters_one_block():
    kitchen, devices = new_kitchen()
    run = Feeder(kitchen, devices, local_ts(2026, 7, 16, 16, 0))
    m = run.feed(15, 45.0, step_min=15)  # one step(15, report), ts 16:15

    # 45 kW × 15/60 = 11.25 kWh
    assert m.energy_kwh_today == pytest.approx(11.25, abs=E)
    # block 16:00 closed at ts 16:15: 11.25 ÷ 0.25 = 45 kW, start 16:00 in window
    assert m.month_peak_kw == pytest.approx(45.0, abs=USD)
    assert m.on_peak_month_peak_kw == pytest.approx(45.0, abs=USD)
    # 11.25 × 0.38 = 4.275 + 45 × 20 = 900 + 45 × 8 = 360 -> 1264.275
    assert m.cost_usd_today == pytest.approx(1264.275, abs=USD)


def test_total_kw_is_sum_of_device_power():
    kitchen, devices = new_kitchen()
    powers = {"hvac_1": 7.5, "hvac_2": 3.25, "fryer_1": 9.0, "lights_1": 2.4}
    ts = local_ts(2026, 7, 16, 10, 1)
    report = hub_report(lane="without", tick_id=1, ts=ts, total_kw=0.0, devices=devices, power_by_device=powers)
    m = meter_of(kitchen.step(1, report))
    # 7.5 + 3.25 + 9.0 + 2.4 = 22.15 kW
    assert m.total_kw == pytest.approx(22.15, abs=E)
    # 22.15 kW × 1/60 h = 0.369167 kWh
    assert m.energy_kwh_today == pytest.approx(22.15 / 60, abs=E)


# =====================================================================================================================
# Energy price of a minute = the energy period containing the minute's local start
# =====================================================================================================================


def test_energy_price_by_minute_local_start_across_1600():
    kitchen, devices = new_kitchen()
    run = Feeder(kitchen, devices, local_ts(2026, 7, 16, 15, 45))
    run.feed(30, 60.0)  # 60 kW = 1 kWh per minute, 15:45 -> 16:15

    # price_usd_per_kwh_now = price of the minute starting at ts
    assert run.at(2026, 7, 16, 15, 59).price_usd_per_kwh_now == pytest.approx(0.22, abs=1e-9)
    assert run.at(2026, 7, 16, 16, 0).price_usd_per_kwh_now == pytest.approx(0.38, abs=1e-9)

    # ts 15:59 -> 16:00: minute [15:59, 16:00) billed off-peak 1 kWh × 0.22 = 0.22,
    # plus block 15:45 closes at ts 16:00: (60 − 0) × $20 = 1200 (15:45 not in the window: + 0 × $8) -> +1200.22
    d1 = run.at(2026, 7, 16, 16, 0).cost_usd_today - run.at(2026, 7, 16, 15, 59).cost_usd_today
    assert d1 == pytest.approx(1200.22, abs=USD)
    # ts 16:00 -> 16:01: minute [16:00, 16:01) billed peak 1 kWh × 0.38, no block closes -> +0.38
    d2 = run.at(2026, 7, 16, 16, 1).cost_usd_today - run.at(2026, 7, 16, 16, 0).cost_usd_today
    assert d2 == pytest.approx(0.38, abs=USD)

    m = run.at(2026, 7, 16, 16, 15)
    # energy 30 kWh: 15 × 0.22 = 3.30 + 15 × 0.38 = 5.70 -> 9.00
    # demand: blocks 15:45 = 60 (max only), 16:00 = 60 (max and on-peak) -> 60 × 20 + 60 × 8 = 1680
    # 9.00 + 1680 = 1689.00
    assert m.energy_kwh_today == pytest.approx(30.0, abs=E)
    assert m.month_peak_kw == pytest.approx(60.0, abs=USD)
    assert m.on_peak_month_peak_kw == pytest.approx(60.0, abs=USD)
    assert m.cost_usd_today == pytest.approx(1689.00, abs=USD)
    assert m.cost_usd_month == pytest.approx(1689.00, abs=USD)


# =====================================================================================================================
# Section 15 "Demand windows (G36)", demo_tariff_v1
# =====================================================================================================================


def test_g36_45kw_block_at_1600_sets_both_peaks():
    kitchen, devices = new_kitchen()
    run = Feeder(kitchen, devices, local_ts(2026, 7, 16, 16, 0))
    m = run.feed(15, 45.0)

    # block 16:00: 45 kW; local start 16:00 is in [16:00, 21:00) -> both peaks 45
    assert m.month_peak_kw == pytest.approx(45.0, abs=USD)
    assert m.on_peak_month_peak_kw == pytest.approx(45.0, abs=USD)
    # 45 × 0.25 = 11.25 kWh × 0.38 = 4.275 + 45 × 20 + 45 × 8 = 1260 -> 1264.275
    assert m.cost_usd_month == pytest.approx(1264.275, abs=USD)


def test_g36_50kw_block_at_1545_sets_month_peak_only():
    kitchen, devices = new_kitchen()
    run = Feeder(kitchen, devices, local_ts(2026, 7, 16, 15, 45))
    load = by_local([((2026, 7, 16, 15, 45), (2026, 7, 16, 16, 0), 50.0)], default=45.0)
    run.feed(30, load)

    m = run.at(2026, 7, 16, 16, 0)
    # block 15:45 closed: 50 kW; 15:45 is outside [16:00, 21:00) -> month 50, on-peak unchanged at 0
    assert m.month_peak_kw == pytest.approx(50.0, abs=USD)
    assert m.on_peak_month_peak_kw == pytest.approx(0.0, abs=USD)

    m = run.at(2026, 7, 16, 16, 15)
    # block 16:00 closed: 45 kW -> month max(50, 45) = 50, on-peak max(0, 45) = 45
    assert m.month_peak_kw == pytest.approx(50.0, abs=USD)
    assert m.on_peak_month_peak_kw == pytest.approx(45.0, abs=USD)
    # energy 50 × 0.25 = 12.5 × 0.22 = 2.75 + 45 × 0.25 = 11.25 × 0.38 = 4.275 -> 7.025
    # demand 50 × 20 = 1000 + 45 × 8 = 360 -> 1367.025
    assert m.cost_usd_month == pytest.approx(1367.025, abs=USD)


def test_g36_2045_block_counts_on_peak_2100_block_does_not():
    kitchen, devices = new_kitchen()
    run = Feeder(kitchen, devices, local_ts(2026, 7, 16, 20, 45))
    load = by_local([((2026, 7, 16, 20, 45), (2026, 7, 16, 21, 0), 30.0)], default=35.0)
    run.feed(30, load)  # 20:45 block 30 kW, 21:00 block 35 kW

    assert run.at(2026, 7, 16, 20, 59).price_usd_per_kwh_now == pytest.approx(0.38, abs=1e-9)
    assert run.at(2026, 7, 16, 21, 0).price_usd_per_kwh_now == pytest.approx(0.22, abs=1e-9)

    m = run.at(2026, 7, 16, 21, 0)
    # block 20:45 (start in [16:00, 21:00)) closed at 30 kW -> both peaks 30
    assert m.month_peak_kw == pytest.approx(30.0, abs=USD)
    assert m.on_peak_month_peak_kw == pytest.approx(30.0, abs=USD)

    m = run.at(2026, 7, 16, 21, 15)
    # block 21:00 (start = window end, excluded) closed at 35 kW -> month 35, on-peak stays 30
    assert m.month_peak_kw == pytest.approx(35.0, abs=USD)
    assert m.on_peak_month_peak_kw == pytest.approx(30.0, abs=USD)
    # energy 7.5 kWh × 0.38 = 2.85 + 8.75 kWh × 0.22 = 1.925 -> 4.775; demand 35 × 20 + 30 × 8 = 940 -> 944.775
    assert m.cost_usd_today == pytest.approx(944.775, abs=USD)


def test_tariff_without_windowed_charge_gives_null_on_peak_peak():
    tariff = load_tariff()
    only_max = tariff.model_copy(update={"demand": [DemandCharge(name="max_demand", windows=None, usd_per_kw=20.0)]})
    kitchen, devices = new_kitchen(tariff=only_max)
    run = Feeder(kitchen, devices, local_ts(2026, 7, 16, 16, 0))
    m = run.feed(15, 45.0)

    # no windowed demand charge -> on_peak_month_peak_kw null
    assert m.on_peak_month_peak_kw is None
    assert m.month_peak_kw == pytest.approx(45.0, abs=USD)
    # 11.25 kWh × 0.38 = 4.275 + 45 × 20 = 900 -> 904.275 (no $8 charge)
    assert m.cost_usd_month == pytest.approx(904.275, abs=USD)
    assert m.cost_usd_today == pytest.approx(904.275, abs=USD)


# =====================================================================================================================
# Section 15: block 23:45 on 31 July bills to July, 00:00 on 1 August resets both peaks (G52, billing month)
# =====================================================================================================================


def test_month_boundary_31_jul_to_1_aug_resets_peaks_and_month_energy():
    kitchen, devices = new_kitchen()
    run = Feeder(kitchen, devices, local_ts(2026, 7, 31, 16, 0))
    load = by_local(
        [
            ((2026, 7, 31, 16, 0), (2026, 7, 31, 16, 15), 45.0),  # on-peak block
            ((2026, 7, 31, 23, 45), (2026, 8, 1, 0, 0), 50.0),  # last July block
            ((2026, 8, 1, 0, 0), (2026, 8, 1, 0, 15), 12.0),  # first August block
        ],
        default=10.0,
    )
    run.feed(495, load)  # 31 Jul 16:00 -> 1 Aug 00:15 (480 + 15 minutes)

    m = run.at(2026, 7, 31, 23, 59)
    # July so far: blocks 16:00 = 45 (on-peak), 16:15..23:30 = 10, 23:45 still open -> month 45, on-peak 45
    assert m.month_peak_kw == pytest.approx(45.0, abs=USD)
    assert m.on_peak_month_peak_kw == pytest.approx(45.0, abs=USD)
    # energy: 45 × 0.25 = 11.25 + 10 × 4.75 h (16:15-21:00) = 47.5 + 10 × 2.75 h (21:00-23:45) = 27.5
    #         + 50 × 14/60 (23:45-23:59) = 11.6667 -> 97.916667 kWh
    assert m.energy_kwh_month == pytest.approx(97.916667, abs=1e-4)
    assert m.energy_kwh_today == pytest.approx(97.916667, abs=1e-4)
    # energy cost: 11.25 × 0.38 = 4.275 + 47.5 × 0.38 = 18.05 + 27.5 × 0.22 = 6.05 + 11.6667 × 0.22 = 2.566667
    #   = 30.941667; demand 45 × 20 = 900 + 45 × 8 = 360 -> 1290.941667
    assert m.cost_usd_month == pytest.approx(1290.941667, abs=USD)
    assert m.cost_usd_today == pytest.approx(1290.941667, abs=USD)

    m = run.at(2026, 8, 1, 0, 14)
    # 1 Aug: both peaks reset at local 00:00 on the 1st; the 50 kW 23:45 block billed to July, so August has
    # no closed block yet -> month 0, on-peak 0
    assert m.month_peak_kw == pytest.approx(0.0, abs=USD)
    assert m.on_peak_month_peak_kw == pytest.approx(0.0, abs=USD)
    # August energy: 12 kW × 14/60 = 2.8 kWh (month and day both reset)
    assert m.energy_kwh_month == pytest.approx(2.8, abs=E)
    assert m.energy_kwh_today == pytest.approx(2.8, abs=E)
    # 2.8 × 0.22 = 0.616, no demand yet
    assert m.cost_usd_month == pytest.approx(0.616, abs=USD)

    m = run.at(2026, 8, 1, 0, 15)
    # block 00:00 closed: 12 × 0.25 = 3 kWh ÷ 0.25 = 12 kW -> month peak 12; 00:00 not in window -> on-peak 0
    assert m.month_peak_kw == pytest.approx(12.0, abs=USD)
    assert m.on_peak_month_peak_kw == pytest.approx(0.0, abs=USD)
    assert m.energy_kwh_month == pytest.approx(3.0, abs=E)
    assert m.energy_kwh_today == pytest.approx(3.0, abs=E)
    # 3 × 0.22 = 0.66 + 12 × 20 = 240 + 0 × 8 -> 240.66 (today: peak at 1 Aug 00:00 is 0 after the reset)
    assert m.cost_usd_month == pytest.approx(240.66, abs=USD)
    assert m.cost_usd_today == pytest.approx(240.66, abs=USD)


def test_boundary_tick_at_0000_on_the_1st_still_shows_july_then_resets():
    # ts 1 Aug 00:00 meters the minute [31 Jul 23:59, 00:00): that tick is still July's; the next tick is August's
    kitchen, devices = new_kitchen()
    run = Feeder(kitchen, devices, local_ts(2026, 7, 31, 16, 0))
    load = by_local(
        [
            ((2026, 7, 31, 16, 0), (2026, 7, 31, 16, 15), 45.0),  # on-peak block
            ((2026, 7, 31, 23, 45), (2026, 8, 1, 0, 0), 50.0),  # last July block
        ],
        default=10.0,
    )
    load_aug = lambda t: 12.0 if t >= local_ts(2026, 8, 1, 0, 0) else load(t)  # noqa: E731
    run.feed(482, load_aug)  # 31 Jul 16:00 -> 1 Aug 00:02 (480 + 2 minutes)

    m = run.at(2026, 8, 1, 0, 0)
    # energy: 45 × 0.25 = 11.25 + 10 × 4.75 h (16:15-21:00) = 47.5 + 10 × 2.75 h (21:00-23:45) = 27.5
    #         + 50 × 0.25 h (23:45-24:00, incl. the minute 23:59 metered by this tick) = 12.5 -> 98.75 kWh
    assert m.energy_kwh_month == pytest.approx(98.75, abs=E)
    assert m.energy_kwh_today == pytest.approx(98.75, abs=E)
    # block 23:45 closes at this ts: 12.5 kWh ÷ 0.25 h = 50 kW -> July peak max(45, 50) = 50; 23:45 outside the window
    #   -> on-peak stays 45
    assert m.month_peak_kw == pytest.approx(50.0, abs=USD)
    assert m.on_peak_month_peak_kw == pytest.approx(45.0, abs=USD)
    # energy cost 11.25 × 0.38 = 4.275 + 47.5 × 0.38 = 18.05 + 27.5 × 0.22 = 6.05 + 12.5 × 0.22 = 2.75 -> 31.125
    # demand 50 × 20 = 1000 + 45 × 8 = 360 -> 1391.125 (today too: the run began on 31 Jul with peaks 0 at its 00:00)
    assert m.cost_usd_month == pytest.approx(1391.125, abs=USD)
    assert m.cost_usd_today == pytest.approx(1391.125, abs=USD)
    # price of the minute starting at ts 00:00 -> off-peak 0.22
    assert m.price_usd_per_kwh_now == pytest.approx(0.22, abs=1e-9)

    m = run.at(2026, 8, 1, 0, 1)
    # first August minute [00:00, 00:01) at 12 kW: 12/60 = 0.2 kWh; month and day reset; both peaks reset to 0
    assert m.energy_kwh_month == pytest.approx(0.2, abs=E)
    assert m.energy_kwh_today == pytest.approx(0.2, abs=E)
    assert m.month_peak_kw == pytest.approx(0.0, abs=USD)
    assert m.on_peak_month_peak_kw == pytest.approx(0.0, abs=USD)
    # 0.2 × 0.22 = 0.044, no demand
    assert m.cost_usd_month == pytest.approx(0.044, abs=USD)
    assert m.cost_usd_today == pytest.approx(0.044, abs=USD)


def test_metering_gap_across_month_boundary():
    # ENGINE.md section 1: minutes not metered count as 0. Reports stop at ts 31 Jul 23:50 and resume at ts 1 Aug 00:10.
    kitchen, devices = new_kitchen()
    run = Feeder(kitchen, devices, local_ts(2026, 7, 31, 23, 0))
    load = by_local(
        [
            ((2026, 7, 31, 23, 45), (2026, 8, 1, 0, 0), 60.0),
            ((2026, 8, 1, 0, 0), (2026, 8, 1, 1, 0), 12.0),
        ],
        default=10.0,
    )
    m = run.feed(50, load)  # ts 23:50
    # blocks 23:00 / 23:15 / 23:30 closed at 10 kW -> July peak 10
    assert m.month_peak_kw == pytest.approx(10.0, abs=USD)
    # 10 × 45/60 = 7.5 + 60 × 5/60 = 5 -> 12.5 kWh
    assert m.energy_kwh_month == pytest.approx(12.5, abs=E)
    # open block 23:45 after 5 metered minutes: 5 kWh ÷ 0.25 h = 20 kW
    assert m.block_avg_kw == pytest.approx(20.0, abs=1e-4)

    run.skip(19)  # minutes 23:50 .. 00:08 never reported
    m = run.feed(1, load)  # minute [00:09, 00:10) at 12 kW, ts 1 Aug 00:10
    # block 23:45 closed during the gap with only 5 kWh (20 kW); it starts in July -> billed to July, and August's
    # peaks start at 0 -> month 0, on-peak 0 (a 20 kW August peak would be the bug)
    assert m.month_peak_kw == pytest.approx(0.0, abs=USD)
    assert m.on_peak_month_peak_kw == pytest.approx(0.0, abs=USD)
    # August energy: one metered minute 12/60 = 0.2 kWh (the gap adds nothing)
    assert m.energy_kwh_month == pytest.approx(0.2, abs=E)
    assert m.energy_kwh_today == pytest.approx(0.2, abs=E)
    # 0.2 × 0.22 = 0.044
    assert m.cost_usd_month == pytest.approx(0.044, abs=USD)
    # open block 00:00: 0.2 kWh ÷ 0.25 h = 0.8 kW
    assert m.block_start == local_ts(2026, 8, 1, 0, 0)
    assert m.block_avg_kw == pytest.approx(0.8, abs=1e-4)

    m = run.feed(5, load)  # ts 00:15, block 00:00 closes
    # block 00:00 metered 00:09..00:15 = 6 min × 12/60 = 1.2 kWh ÷ 0.25 h = 4.8 kW -> peak 4.8, not in window
    assert m.month_peak_kw == pytest.approx(4.8, abs=USD)
    assert m.on_peak_month_peak_kw == pytest.approx(0.0, abs=USD)
    assert m.energy_kwh_month == pytest.approx(1.2, abs=E)
    # 1.2 × 0.22 = 0.264 + 4.8 × 20 = 96 -> 96.264 (today the same: peaks were 0 at 1 Aug 00:00)
    assert m.cost_usd_month == pytest.approx(96.264, abs=USD)
    assert m.cost_usd_today == pytest.approx(96.264, abs=USD)


# =====================================================================================================================
# Local midnight resets today, not the month; overnight minutes metered like any other (multi-day runs)
# =====================================================================================================================


def test_local_midnight_resets_today_but_not_month():
    kitchen, devices = new_kitchen()
    run = Feeder(kitchen, devices, local_ts(2026, 7, 15, 23, 30))
    load = by_local(
        [
            ((2026, 7, 15, 23, 30), (2026, 7, 15, 23, 45), 20.0),
            ((2026, 7, 15, 23, 45), (2026, 7, 16, 0, 0), 25.0),
        ],
        default=8.0,
    )
    run.feed(60, load)  # 15 Jul 23:30 -> 16 Jul 00:30

    m = run.at(2026, 7, 15, 23, 59)
    # today 15 Jul: 20 × 0.25 = 5 + 25 × 14/60 = 5.8333 -> 10.8333 kWh; block 23:30 closed at 20 kW
    assert m.energy_kwh_today == pytest.approx(10.833333, abs=1e-4)
    assert m.month_peak_kw == pytest.approx(20.0, abs=USD)
    # 10.8333 × 0.22 = 2.383333 + 20 × 20 = 400 -> 402.383333
    assert m.cost_usd_today == pytest.approx(402.383333, abs=USD)

    m = run.at(2026, 7, 16, 0, 1)
    # first minute of 16 Jul: 8/60 = 0.133333 kWh today
    assert m.energy_kwh_today == pytest.approx(8 / 60, abs=E)

    m = run.at(2026, 7, 16, 0, 30)
    # today: 8 kW × 0.5 h = 4.0 kWh; month: 5 + 6.25 + 4 = 15.25 kWh (no month reset on the 16th)
    assert m.energy_kwh_today == pytest.approx(4.0, abs=E)
    assert m.energy_kwh_month == pytest.approx(15.25, abs=E)
    # block 23:45 (25 kW) closed at ts 00:00 and belongs to 15 Jul; today's blocks are 8 kW -> month peak 25
    assert m.month_peak_kw == pytest.approx(25.0, abs=USD)
    assert m.on_peak_month_peak_kw == pytest.approx(0.0, abs=USD)
    # cost today = 4 × 0.22 = 0.88 + demand added today: max (25 now − 25 at 00:00) × 20 = 0, on-peak 0 -> 0.88
    assert m.cost_usd_today == pytest.approx(0.88, abs=USD)
    # cost month = 15.25 × 0.22 = 3.355 + 25 × 20 = 500 -> 503.355
    assert m.cost_usd_month == pytest.approx(503.355, abs=USD)


def test_overnight_minutes_are_metered_like_any_other():
    kitchen, devices = new_kitchen()
    run = Feeder(kitchen, devices, local_ts(2026, 7, 16, 2, 0))
    m = run.feed(60, 6.0)  # closed hours 02:00 -> 03:00, always-on style load

    # 6 kW × 1 h = 6 kWh
    assert m.energy_kwh_today == pytest.approx(6.0, abs=E)
    # four 6 kW blocks closed -> month peak 6; none in the window
    assert m.month_peak_kw == pytest.approx(6.0, abs=USD)
    assert m.on_peak_month_peak_kw == pytest.approx(0.0, abs=USD)
    # 6 × 0.22 = 1.32 + 6 × 20 = 120 -> 121.32
    assert m.cost_usd_today == pytest.approx(121.32, abs=USD)
    assert m.price_usd_per_kwh_now == pytest.approx(0.22, abs=1e-9)


@pytest.mark.slow
def test_full_local_day_at_10kw_then_day_reset():
    kitchen, devices = new_kitchen()
    run = Feeder(kitchen, devices, local_ts(2026, 7, 16, 0, 0))
    run.feed(1441, 10.0)  # 16 Jul 00:00 -> 17 Jul 00:01

    m = run.at(2026, 7, 16, 23, 59)
    # 1439 minutes × 10 kW / 60 = 239.833333 kWh
    assert m.energy_kwh_today == pytest.approx(239.833333, abs=1e-4)
    # energy cost: off-peak 00:00-16:00 (960 min) + 21:00-23:59 (179 min) = 1139 min × 10/60 = 189.8333 kWh × 0.22
    #   = 41.763333; peak 16:00-21:00 = 300 min = 50 kWh × 0.38 = 19.00 -> 60.763333
    # demand added today: 10 × 20 + 10 × 8 = 280 -> 340.763333
    assert m.cost_usd_today == pytest.approx(340.763333, abs=USD)
    assert m.month_peak_kw == pytest.approx(10.0, abs=USD)
    assert m.on_peak_month_peak_kw == pytest.approx(10.0, abs=USD)

    m = run.at(2026, 7, 17, 0, 1)
    # new day: 10/60 = 0.166667 kWh; month keeps 1441 × 10/60 = 240.166667 kWh
    assert m.energy_kwh_today == pytest.approx(10 / 60, abs=E)
    assert m.energy_kwh_month == pytest.approx(240.166667, abs=1e-4)
    # today: 0.166667 × 0.22 = 0.036667, no peak increase since 00:00 -> 0.036667
    assert m.cost_usd_today == pytest.approx(0.036667, abs=USD)
    # peaks are kept across days in the same month
    assert m.month_peak_kw == pytest.approx(10.0, abs=USD)
    assert m.on_peak_month_peak_kw == pytest.approx(10.0, abs=USD)


@pytest.mark.slow
def test_dst_fall_back_day_is_25_hours_of_metering():
    kitchen, devices = new_kitchen()
    # Sun 1 Nov 2026 00:00 PDT = 07:00Z; 2 Nov 00:00 PST = 08:00Z -> 1500 minutes (100 blocks) in the local day
    run = Feeder(kitchen, devices, local_ts(2026, 11, 1, 0, 0))
    run.feed(1501, 4.0)  # to 2 Nov 00:01 local

    m = run.at(2026, 11, 1, 23, 59)
    # 1499 minutes × 4 kW / 60 = 99.933333 kWh (a normal day would stop at 1439 min = 95.93)
    assert m.energy_kwh_today == pytest.approx(99.933333, abs=1e-4)
    # off-peak: 00:00-16:00 local = 17 h (01:00 repeats) = 1020 min + 21:00-23:59 = 179 -> 1199 min; peak 300 min
    # energy cost 4/60 × (1199 × 0.22 + 300 × 0.38) = 0.0666667 × 377.78 = 25.185333; demand 4 × 20 + 4 × 8 = 112
    # -> 137.185333
    assert m.cost_usd_today == pytest.approx(137.185333, abs=USD)

    m = run.at(2026, 11, 2, 0, 1)
    # new local day: 4/60 = 0.066667 kWh; month: 1501 × 4/60 = 100.066667 kWh
    assert m.energy_kwh_today == pytest.approx(4 / 60, abs=E)
    assert m.energy_kwh_month == pytest.approx(100.066667, abs=1e-4)


@pytest.mark.slow
def test_dst_spring_forward_day_is_23_hours_92_blocks():
    kitchen, devices = new_kitchen()
    # Sun 8 Mar 2026 00:00 PST = 08:00Z; 9 Mar 00:00 PDT = 07:00Z -> 1380 minutes (23 h) in the local day
    start, end = local_ts(2026, 3, 8, 0, 0), local_ts(2026, 3, 9, 0, 0)
    assert (end - start) == timedelta(minutes=1380)
    run = Feeder(kitchen, devices, start)
    run.feed(1381, 10.0)  # to 9 Mar 00:01 local

    # 1380 min ÷ 15 = 92 blocks, each on a local quarter hour (02:00-02:59 does not exist that day)
    starts = {st.meter.block_start for st in run.states if start < st.ts < end and st.ts.minute % 15 != 0}
    assert len(starts) == 92
    for b in starts:
        loc = b.astimezone(LOCAL_TZ)
        assert loc.minute in (0, 15, 30, 45) and loc.hour != 2

    m = run.at(2026, 3, 9, 0, 0)  # the tick metering 8 Mar 23:59 still belongs to 8 Mar
    # 10 kW × 23 h = 230 kWh
    assert m.energy_kwh_today == pytest.approx(230.0, abs=1e-4)
    assert m.energy_kwh_month == pytest.approx(230.0, abs=1e-4)
    # off-peak 00:00-16:00 = 16 h − 1 skipped = 15 h = 900 min + 21:00-24:00 = 180 min -> 1080 min = 180 kWh × 0.22 = 39.60
    # peak 16:00-21:00 = 300 min = 50 kWh × 0.38 = 19.00 -> energy 58.60; demand 10 × 20 + 10 × 8 = 280 -> 338.60
    assert m.cost_usd_today == pytest.approx(338.60, abs=USD)
    assert m.cost_usd_month == pytest.approx(338.60, abs=USD)
    assert m.month_peak_kw == pytest.approx(10.0, abs=USD)
    assert m.on_peak_month_peak_kw == pytest.approx(10.0, abs=USD)

    m = run.at(2026, 3, 9, 0, 1)
    # new day: 10/60 kWh; month 230 + 10/60 = 230.166667
    assert m.energy_kwh_today == pytest.approx(10 / 60, abs=E)
    assert m.energy_kwh_month == pytest.approx(230.166667, abs=1e-4)


@pytest.mark.slow
def test_three_day_run_at_10kw_day_and_month_totals():
    kitchen, devices = new_kitchen()
    run = Feeder(kitchen, devices, local_ts(2026, 7, 14, 0, 0))
    run.feed(3 * 1440, 10.0)  # Tue 14 Jul 00:00 -> Fri 17 Jul 00:00 local (no DST change)

    # one day: off-peak 960 + 180 = 1140 min × 10/60 = 190 kWh × 0.22 = 41.80; peak 300 min = 50 kWh × 0.38 = 19.00
    #   -> 240 kWh, energy $60.80 per day
    # day 1 also adds demand: 10 × 20 + 10 × 8 = 280 -> 340.80; days 2 and 3 add none (peaks stay 10 / 10)
    for (y, mo, d), today_usd, month_kwh, month_usd in [
        ((2026, 7, 15), 340.80, 240.0, 340.80),  # end of day 1
        ((2026, 7, 16), 60.80, 480.0, 401.60),  # 2 × 60.80 + 280
        ((2026, 7, 17), 60.80, 720.0, 462.40),  # 3 × 60.80 = 182.40 + 280
    ]:
        m = run.at(y, mo, d, 0, 0)  # the tick metering the day's 23:59 minute
        assert m.energy_kwh_today == pytest.approx(240.0, abs=1e-4)
        assert m.cost_usd_today == pytest.approx(today_usd, abs=USD)
        assert m.energy_kwh_month == pytest.approx(month_kwh, abs=1e-4)
        assert m.cost_usd_month == pytest.approx(month_usd, abs=USD)
        assert m.month_peak_kw == pytest.approx(10.0, abs=USD)
        assert m.on_peak_month_peak_kw == pytest.approx(10.0, abs=USD)


# =====================================================================================================================
# Section 15: cost_usd_today includes demand added today
#   (new 45 kW peak over a 40 kW peak from before today -> +5 × $20 + on-peak increase × $8)
# =====================================================================================================================


@pytest.mark.slow
def test_cost_today_includes_demand_added_today_live_two_days():
    kitchen, devices = new_kitchen()
    run = Feeder(kitchen, devices, local_ts(2026, 7, 15, 10, 0))
    load = by_local(
        [
            ((2026, 7, 15, 10, 0), (2026, 7, 15, 10, 15), 40.0),  # yesterday's morning peak
            ((2026, 7, 15, 16, 0), (2026, 7, 15, 16, 15), 30.0),  # yesterday's on-peak peak
            ((2026, 7, 16, 16, 0), (2026, 7, 16, 16, 15), 45.0),  # today's new peak, on-peak
        ],
        default=5.0,
    )
    run.feed(1815, load)  # 15 Jul 10:00 -> 16 Jul 16:15 (30 h 15 min)

    m = run.at(2026, 7, 16, 16, 15)
    assert m.month_peak_kw == pytest.approx(45.0, abs=USD)
    assert m.on_peak_month_peak_kw == pytest.approx(45.0, abs=USD)
    # today energy: 5 kW × 16 h = 80 kWh × 0.22 = 17.60 + 45 × 0.25 = 11.25 kWh × 0.38 = 4.275 -> 91.25 kWh, $21.875
    assert m.energy_kwh_today == pytest.approx(91.25, abs=E)
    # demand added today: (45 − 40) × 20 = 100 + (45 − 30) × 8 = 120 -> 220; cost today 21.875 + 220 = 241.875
    assert m.cost_usd_today == pytest.approx(241.875, abs=USD)


# =====================================================================================================================
# warm_up(history): month to date metered from the current local month's history blocks only (ENGINE.md section 0)
# =====================================================================================================================


def _july_history(devices, month_to_date=None):
    start = local_ts(2026, 7, 16, 16, 0)  # run start = history.end
    blocks = [
        (local_ts(2026, 6, 30, 16, 0), 60.0),  # June: not this month
        (local_ts(2026, 6, 30, 23, 45), 65.0),  # June local (65 kW: under the 68.2 kW rated sum since the 8 kW HVAC catalog change), but 2026-07-01T06:45Z in UTC: not this month
        (local_ts(2026, 7, 1, 0, 0), 8.0),  # first local July block
        (local_ts(2026, 7, 15, 10, 0), 40.0),  # July morning peak
        (local_ts(2026, 7, 15, 16, 0), 30.0),  # July on-peak peak
    ]
    return start, warmup_history(
        start=local_ts(2026, 6, 30, 0, 0), end=start, block_totals_kw=blocks, devices=devices,
        month_to_date=month_to_date,
    )


def test_warm_up_meters_current_month_history_into_month_to_date():
    kitchen, devices = new_kitchen()
    start, history = _july_history(devices)
    kitchen.warm_up(history)
    run = Feeder(kitchen, devices, start)

    m = run.feed(1, 45.0)  # ts 16 Jul 16:01
    # July blocks only (local month): 1 Jul 00:00 = 8, 15 Jul 10:00 = 40, 15 Jul 16:00 = 30 (on-peak)
    #   June 30 16:00 (60) and June 30 23:45 local (65, July in UTC) excluded -> month 40, on-peak 30
    assert m.month_peak_kw == pytest.approx(40.0, abs=USD)
    assert m.on_peak_month_peak_kw == pytest.approx(30.0, abs=USD)
    # history energy: 8 × 0.25 = 2 + 40 × 0.25 = 10 + 30 × 0.25 = 7.5 -> 19.5 kWh; + live 45/60 = 0.75 -> 20.25
    assert m.energy_kwh_month == pytest.approx(20.25, abs=E)
    # nothing in history today -> today = live minute only
    assert m.energy_kwh_today == pytest.approx(0.75, abs=E)
    # history energy cost: 2 × 0.22 = 0.44 + 10 × 0.22 = 2.20 + 7.5 × 0.38 = 2.85 -> 5.49
    # month: 5.49 + live 0.75 × 0.38 = 0.285 + 40 × 20 = 800 + 30 × 8 = 240 -> 1045.775
    assert m.cost_usd_month == pytest.approx(1045.775, abs=USD)
    # today: 0.285, no peak increase since 00:00
    assert m.cost_usd_today == pytest.approx(0.285, abs=USD)

    m = run.feed(14, 45.0)  # ts 16:15, block 16:00 closes at 45 kW
    assert m.month_peak_kw == pytest.approx(45.0, abs=USD)
    assert m.on_peak_month_peak_kw == pytest.approx(45.0, abs=USD)
    # month energy 19.5 + 11.25 = 30.75 kWh; today 11.25
    assert m.energy_kwh_month == pytest.approx(30.75, abs=E)
    assert m.energy_kwh_today == pytest.approx(11.25, abs=E)
    # section 15: today = 11.25 × 0.38 = 4.275 + (45 − 40) × 20 = 100 + (45 − 30) × 8 = 120 -> 224.275
    assert m.cost_usd_today == pytest.approx(224.275, abs=USD)
    # month = 5.49 + 4.275 + 45 × 20 = 900 + 45 × 8 = 360 -> 1269.765
    assert m.cost_usd_month == pytest.approx(1269.765, abs=USD)


def test_warm_up_blocks_from_earlier_today_count_in_today():
    # design choice (confirmed): history blocks of today before the run start count in energy_kwh_today and cost_usd_today
    kitchen, devices = new_kitchen()
    start = local_ts(2026, 7, 16, 16, 0)
    history = warmup_history(
        start=local_ts(2026, 7, 15, 0, 0), end=start, devices=devices,
        block_totals_kw=[
            (local_ts(2026, 7, 15, 10, 0), 40.0),  # yesterday: sets the peak in force at today's 00:00
            (local_ts(2026, 7, 16, 10, 0), 20.0),  # today, off-peak
            (local_ts(2026, 7, 16, 15, 45), 44.0),  # today, off-peak, ends exactly at the start
        ],
    )
    kitchen.warm_up(history)
    run = Feeder(kitchen, devices, start)

    m = run.feed(1, 45.0)  # ts 16:01, minute [16:00, 16:01) on-peak
    # month peak max(40, 20, 44) = 44; no history block starts in [16:00, 21:00) -> on-peak 0
    assert m.month_peak_kw == pytest.approx(44.0, abs=USD)
    assert m.on_peak_month_peak_kw == pytest.approx(0.0, abs=USD)
    # today: 20 × 0.25 = 5 + 44 × 0.25 = 11 + live 45/60 = 0.75 -> 16.75 kWh; month: + 40 × 0.25 = 10 -> 26.75
    assert m.energy_kwh_today == pytest.approx(16.75, abs=E)
    assert m.energy_kwh_month == pytest.approx(26.75, abs=E)
    # today: (5 + 11) × 0.22 = 3.52 + 0.75 × 0.38 = 0.285 -> 3.805; demand added today (44 − 40 at 00:00) × 20 = 80
    #   + on-peak (0 − 0) × 8 -> 83.805
    assert m.cost_usd_today == pytest.approx(83.805, abs=USD)
    # month: (10 + 16) × 0.22 = 5.72 + 0.285 = 6.005 + 44 × 20 = 880 -> 886.005
    assert m.cost_usd_month == pytest.approx(886.005, abs=USD)

    m = run.feed(14, 45.0)  # ts 16:15, block 16:00 closes at 45 kW (on-peak)
    assert m.month_peak_kw == pytest.approx(45.0, abs=USD)
    assert m.on_peak_month_peak_kw == pytest.approx(45.0, abs=USD)
    # today 5 + 11 + 11.25 = 27.25 kWh
    assert m.energy_kwh_today == pytest.approx(27.25, abs=E)
    # today: 3.52 + 11.25 × 0.38 = 4.275 -> 7.795 + (45 − 40) × 20 = 100 + (45 − 0) × 8 = 360 -> 467.795
    assert m.cost_usd_today == pytest.approx(467.795, abs=USD)
    # month: 5.72 + 4.275 = 9.995 + 45 × 20 = 900 + 45 × 8 = 360 -> 1269.995
    assert m.cost_usd_month == pytest.approx(1269.995, abs=USD)


def test_warm_up_month_to_date_given_is_used_as_is():
    kitchen, devices = new_kitchen()
    mtd = MonthToDate(
        month="2026-07", month_peak_kw=44.2, on_peak_month_peak_kw=41.0, energy_kwh_month=7400.0, cost_usd_month=2650.0
    )
    start, history = _july_history(devices, month_to_date=mtd)
    kitchen.warm_up(history)
    run = Feeder(kitchen, devices, start)

    m = run.feed(1, 20.0)
    # restored peaks used as-is (history alone would give 40 / 30)
    assert m.month_peak_kw == pytest.approx(44.2, abs=USD)
    assert m.on_peak_month_peak_kw == pytest.approx(41.0, abs=USD)
    # 7400 + 20/60 = 7400.333333 kWh
    assert m.energy_kwh_month == pytest.approx(7400.333333, abs=1e-4)
    assert m.energy_kwh_today == pytest.approx(20 / 60, abs=E)
    # today: 0.333333 × 0.38 = 0.126667
    assert m.cost_usd_today == pytest.approx(0.126667, abs=USD)

    m = run.feed(14, 20.0)  # block 16:00 closes at 20 kW, below both restored peaks
    assert m.month_peak_kw == pytest.approx(44.2, abs=USD)
    assert m.on_peak_month_peak_kw == pytest.approx(41.0, abs=USD)
    # today: 20 × 0.25 = 5 kWh × 0.38 = 1.90, no demand added
    assert m.cost_usd_today == pytest.approx(1.90, abs=USD)


def test_warm_up_restored_cost_month_continuation():
    pytest.skip(
        "TBD: (no gap id) how cost_usd_month continues from a restored MonthToDate.cost_usd_month: it bundles energy "
        "and demand, and ENGINE.md section 0 says only 'used as-is'; the energy/demand split for a later peak "
        "increase is not specified"
    )


def test_warm_up_block_ending_exactly_at_start_is_accepted_after_start_raises():
    kitchen, devices = new_kitchen()
    start = local_ts(2026, 7, 16, 16, 0)
    # block 15:45 ends 15:45 + 15 = 16:00 = start -> allowed (block_start + 15 min <= start)
    ok = warmup_history(start=local_ts(2026, 7, 15, 0, 0), end=start,
                        block_totals_kw=[(local_ts(2026, 7, 16, 15, 45), 10.0)], devices=devices)
    kitchen.warm_up(ok)

    kitchen2, _ = new_kitchen()
    # block 16:00 ends 16:15 > start -> ValueError (no peeking)
    bad = warmup_history(start=local_ts(2026, 7, 15, 0, 0), end=start,
                         block_totals_kw=[(local_ts(2026, 7, 16, 16, 0), 10.0)], devices=devices)
    with pytest.raises(ValueError):
        kitchen2.warm_up(bad)


# =====================================================================================================================
# Bill per charge, determinism
# =====================================================================================================================


def test_bill_one_demand_charge_entry_per_tariff_charge():
    pytest.skip(
        "TBD: (no gap id) Bill(period) has no signature in CONTRACTS.md section 3 or ENGINE.md section 1 "
        "(not a facade method); per-charge billing is covered here through Meter.cost_usd_month"
    )


def test_identical_report_stream_gives_identical_meters():
    load = by_local([((2026, 7, 16, 16, 0), (2026, 7, 16, 16, 15), 45.0)], default=12.0)
    outs = []
    for _ in range(2):
        kitchen, devices = new_kitchen()
        run = Feeder(kitchen, devices, local_ts(2026, 7, 16, 15, 45))
        run.feed(45, load)
        outs.append([run.meters[t].model_dump(mode="json") for t in sorted(run.meters)])
    # deterministic: same HubReports -> byte-identical Meter stream
    assert outs[0] == outs[1]


def _plain_state(state) -> dict:
    return state.model_dump(mode="json") if hasattr(state, "model_dump") else state


def _fixture_stream_run() -> list[str]:
    scenario = json.loads((FIXTURES / "scenario" / "demo_cafe" / "scenario.json").read_text())
    lanes = Kitchen.build_lanes(scenario["config"], scenario["tariff"], catalog(), scenario["seed"])
    history = WarmUpHistory.model_validate(json.loads((FIXTURES / scenario["warm_up"]["history"]).read_text()))
    for lane in ("without", "with"):
        lanes[lane].warm_up(history.model_dump(mode="json"))
    lines = (FIXTURES / "hub_protocol" / "hub_to_server.jsonl").read_text().splitlines()
    out = []
    for msg in (json.loads(x) for x in lines if x.strip()):
        if msg["type"] != "hub_report":
            continue
        for lane in ("without", "with"):  # runtime order: without, then with
            report = HubReport.model_validate(msg["reports"][lane]).model_dump(mode="json")
            out.append(json.dumps(_plain_state(lanes[lane].step(1, report)), sort_keys=True))
    return out


def test_fixture_stream_both_lanes_byte_identical_across_runs():
    # golden rule 10: same config, catalog, seed, warm-up and HubReport stream -> byte-identical TickStates, both lanes
    # (ids included: the lanes share one allocator and are stepped in a fixed order)
    first, second = _fixture_stream_run(), _fixture_stream_run()
    assert len(first) == 2 * 120  # 120 hub_report messages × 2 lanes
    assert first == second
