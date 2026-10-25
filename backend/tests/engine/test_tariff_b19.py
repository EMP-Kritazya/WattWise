"""Seasonal multi-charge tariffs (ENGINE.md section 1, CONTRACTS.md section 1 Tariff "Seasons, days and windows", Meter
`demand_peaks`, Bill `fixed_usd`) on PG&E B-19 (`contracts/fixtures/shapes/tariff_pge_b19.json`, URDB 69de8cdb...).

Every expected number is worked out by hand in the comments; none come from engine output.

B-19 as the fixture carries it (America/Los_Angeles; July = PDT UTC-7, November after the 1st = PST UTC-8):
  energy  winter months 1,2,10,11,12: off_peak_winter 0.12026 21:00-16:00 · peak_winter 0.16188 16:00-21:00
          spring months 3,4,5: off_peak_winter 0.12026 21:00-09:00 and 14:00-16:00 · super_off_peak_spring 0.06442
                                09:00-14:00 · peak_winter 0.16188 16:00-21:00
          summer months 6-9: off_peak_summer 0.12037 23:00-14:00 · part_peak_summer 0.14775 14:00-16:00 and 21:00-23:00
                             · peak_summer 0.18648 16:00-21:00
  demand  max_demand 37.37 $/kW every month, every hour
          peak_demand_winter 2.31 $/kW months 1-5,10-12, 16:00-21:00
          peak_demand_summer 46.16 $/kW months 6-9, 16:00-21:00
          part_peak_demand_summer 10.52 $/kW months 6-9, 14:00-16:00 + 21:00-23:00 (one charge, two windows)
  fixed   customer_charge 11.36882 $/day (GAPS 22), accrues from the first metered minute of each local day (GAPS 25)
Meter costs use the published 0.01 kW peaks (GAPS 26); every peak below is a whole number so rounding never moves them.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pytest

from contracts import MonthToDate, Tariff
from engine import Kitchen
from engine.meter import MeterState, MonthBill, bill, demand_lines
from engine.tariff import TariffView

from tests.engine.conftest import (
    FIXTURES,
    REPO_ROOT,
    as_tick_state,
    catalog,
    hub_report,
    load_catalog,
    load_config,
    local_ts,
    roster,
)

USD = 1e-6  # these are exact sums of decimal products; float noise only
FIXED = 11.36882

B19_PATH = FIXTURES / "shapes" / "tariff_pge_b19.json"
URDB_PATH = REPO_ROOT / "dataset" / "tariffs" / "pge_b19_secondary_voluntary_urdb_69de8cdb02f684104e01267d.json"


def b19() -> Tariff:
    return Tariff.model_validate(json.loads(B19_PATH.read_text()))


def view() -> TariffView:
    return TariffView(b19())


def meter_block(meter: MeterState, block_start: datetime, kw: float) -> None:
    """Meter one 15-min block at constant `kw` (one device), minute by minute, as step(1, ...) does."""
    for i in range(15):
        meter.meter_minute(block_start + timedelta(minutes=i), {"x": kw})


def peaks_by_name(meter: MeterState, now: datetime) -> dict[str, float]:
    return {dp["name"]: dp["peak_kw"] for dp in meter.demand_peaks(now)}


# =====================================================================================================================
# Energy price: the hand-written URDB schedule, every minute
# =====================================================================================================================

# URDB energyweekdayschedule (weekend identical), hour -> period, read off the record by hand:
#   rates [0] 0.06442 [1] 0.12026 [2] 0.16188 [3] 0.12037 [4] 0.14775 [5] 0.18648
_WINTER = [1] * 16 + [2] * 5 + [1] * 3
_SPRING = [1] * 9 + [0] * 5 + [1] * 2 + [2] * 5 + [1] * 3
_SUMMER = [3] * 14 + [4] * 2 + [5] * 5 + [4] * 2 + [3]
_RATES = [0.06442, 0.12026, 0.16188, 0.12037, 0.14775, 0.18648]


def expected_price(month: int, hour: int) -> float:
    row = _SUMMER if 6 <= month <= 9 else _SPRING if 3 <= month <= 5 else _WINTER
    return _RATES[row[hour]]


def test_every_minute_price_matches_urdb_schedule_weekday_and_weekend_each_month():
    tv = view()
    for month in range(1, 13):
        weekday = next(date(2026, month, d) for d in range(1, 8) if date(2026, month, d).weekday() < 5)
        weekend = next(date(2026, month, d) for d in range(1, 8) if date(2026, month, d).weekday() >= 5)
        for day in (weekday, weekend):
            for m in range(1440):
                ts = local_ts(day.year, day.month, day.day, m // 60, m % 60)
                assert tv.energy_price(ts) == expected_price(month, m // 60), (day, m)


def test_spring_super_off_peak_is_0900_to_1400_march_to_may_only():
    tv = view()
    # 15 Apr 08:59 off-peak 0.12026 · 09:00 super-off-peak 0.06442 · 13:59 0.06442 · 14:00 back to 0.12026
    assert tv.energy_price(local_ts(2026, 4, 15, 8, 59)) == 0.12026
    assert tv.energy_price(local_ts(2026, 4, 15, 9, 0)) == 0.06442
    assert tv.energy_price(local_ts(2026, 4, 15, 13, 59)) == 0.06442
    assert tv.energy_price(local_ts(2026, 4, 15, 14, 0)) == 0.12026
    # 31 May 12:00 still spring (0.06442); 1 Jun 12:00 summer off-peak (0.12037); 15 Feb 12:00 winter off-peak (0.12026)
    assert tv.energy_price(local_ts(2026, 5, 31, 12, 0)) == 0.06442
    assert tv.energy_price(local_ts(2026, 6, 1, 12, 0)) == 0.12037
    assert tv.energy_price(local_ts(2026, 2, 15, 12, 0)) == 0.12026


def test_wrapping_period_uses_the_minutes_own_month():
    tv = view()
    # off_peak_summer 23:00-14:00 wraps midnight: 30 Sep 23:30 is September (0.12037); 1 Oct 00:30 is October winter
    # off-peak (0.12026), not the September span continuing past midnight
    assert tv.energy_price(local_ts(2026, 9, 30, 23, 30)) == 0.12037
    assert tv.energy_price(local_ts(2026, 10, 1, 0, 30)) == 0.12026


def test_every_quarter_hour_of_2026_matches_schedule_including_dst_days():
    tv = view()
    ts = local_ts(2026, 1, 1, 0, 0)
    end = local_ts(2027, 1, 1, 0, 0)
    n = 0
    while ts < end:
        loc = tv.local(ts)
        assert tv.energy_price(ts) == expected_price(loc.month, loc.hour), loc
        ts += timedelta(minutes=15)
        n += 1
    # 365 days × 96 blocks; DST spring day −4 blocks, fall day +4 -> 35040
    assert n == 35040


@pytest.mark.skipif(not URDB_PATH.exists(), reason="dataset/ (gitignored) not present: URDB cross-check skipped")
def test_energy_price_equals_urdb_record_hour_by_hour():
    record = json.loads(URDB_PATH.read_text())["items"][0]
    rates = [p[0]["rate"] for p in record["energyratestructure"]]
    tv = view()
    for month in range(1, 13):
        for wkend, key in ((False, "energyweekdayschedule"), (True, "energyweekendschedule")):
            day = next(date(2026, month, d) for d in range(1, 8) if (date(2026, month, d).weekday() >= 5) == wkend)
            for h in range(24):
                for mm in (0, 15, 30, 45):
                    ts = local_ts(day.year, day.month, day.day, h, mm)
                    assert tv.energy_price(ts) == rates[record[key][month - 1][h]], (month, wkend, h, mm)


# =====================================================================================================================
# Tariff validation: exactly one energy period per local minute
# =====================================================================================================================


def test_tariff_with_gap_or_overlap_is_rejected():
    raw = json.loads(B19_PATH.read_text())
    gap = json.loads(json.dumps(raw))
    gap["energy"] = [e for e in gap["energy"] if e["name"] != "super_off_peak_spring"]  # spring 09:00-14:00 uncovered
    with pytest.raises(ValueError):
        TariffView(Tariff.model_validate(gap))
    overlap = json.loads(json.dumps(raw))
    overlap["energy"].append({"name": "dup", "start": "16:00", "end": "17:00", "usd_per_kwh": 0.5, "months": [7],
                              "days": "weekdays"})
    with pytest.raises(ValueError):
        TariffView(Tariff.model_validate(overlap))


def test_day_type_split_is_honoured():
    raw = json.loads(B19_PATH.read_text())
    # replace July peak_summer by a weekday 0.30 / weekend 0.10 pair (still exactly one period per minute)
    for e in raw["energy"]:
        if e["name"] == "peak_summer":
            e["days"] = "weekdays"
            e["usd_per_kwh"] = 0.30
    raw["energy"].append({"name": "peak_summer_weekend", "start": "16:00", "end": "21:00", "usd_per_kwh": 0.10,
                          "months": [6, 7, 8, 9], "days": "weekends"})
    tv = TariffView(Tariff.model_validate(raw))
    assert tv.energy_price(local_ts(2026, 7, 17, 17, 0)) == 0.30  # Fri
    assert tv.energy_price(local_ts(2026, 7, 18, 17, 0)) == 0.10  # Sat


# =====================================================================================================================
# Demand: which charges a block bills
# =====================================================================================================================


def test_summer_1630_block_bills_max_demand_and_peak_demand_summer():
    tv = view()
    meter = MeterState(tv)
    start = local_ts(2026, 7, 16, 16, 30)  # Thu
    meter_block(meter, start, 50.0)
    now = start + timedelta(minutes=15)
    # applicable in July, tariff order: max_demand, peak_demand_summer, part_peak_demand_summer (winter charge absent)
    # 16:30 in [16:00, 21:00) -> peak_demand_summer 50; not in 14-16 / 21-23 -> part-peak 0
    assert peaks_by_name(meter, now) == {"max_demand": 50.0, "peak_demand_summer": 50.0, "part_peak_demand_summer": 0.0}
    assert [dp["cost_usd"] for dp in meter.demand_peaks(now)] == [1868.5, 2308.0, 0.0]  # 50×37.37 · 50×46.16 · 0
    assert meter.month_peak_kw == pytest.approx(50.0)
    assert meter.on_peak_month_peak_kw(now) == pytest.approx(50.0)  # highest-rate windowed July charge = peak_demand_summer
    # energy 50 kW × 0.25 h = 12.5 kWh × 0.18648 = 2.331; demand 1868.5 + 2308 = 4176.5; fixed 1 day 11.36882
    assert meter.cost_usd_month(now) == pytest.approx(2.331 + 4176.5 + FIXED, abs=USD)
    # today: everything was added today (peaks 0 at the first minute) -> same as the month
    assert meter.cost_usd_today(now) == pytest.approx(2.331 + 4176.5 + FIXED, abs=USD)


def test_summer_1415_block_bills_part_peak():
    tv = view()
    meter = MeterState(tv)
    start = local_ts(2026, 7, 16, 14, 15)
    meter_block(meter, start, 30.0)
    now = start + timedelta(minutes=15)
    # 14:15 in the first part-peak window [14:00, 16:00) -> part-peak 30; not in 16-21 -> peak_summer 0
    assert peaks_by_name(meter, now) == {"max_demand": 30.0, "peak_demand_summer": 0.0, "part_peak_demand_summer": 30.0}
    assert meter.on_peak_month_peak_kw(now) == 0.0  # the on-peak charge (peak_demand_summer) has no block yet
    # energy 7.5 kWh × 0.14775 = 1.108125; demand 30×37.37 = 1121.1 + 30×10.52 = 315.6; fixed 11.36882
    assert meter.cost_usd_month(now) == pytest.approx(1.108125 + 1121.1 + 315.6 + FIXED, abs=USD)


def test_summer_2130_block_bills_part_peak_second_window():
    tv = view()
    meter = MeterState(tv)
    start = local_ts(2026, 7, 16, 21, 30)
    meter_block(meter, start, 20.0)
    now = start + timedelta(minutes=15)
    # 21:30 in the second part-peak window [21:00, 23:00) of the same charge -> part-peak 20
    assert peaks_by_name(meter, now) == {"max_demand": 20.0, "peak_demand_summer": 0.0, "part_peak_demand_summer": 20.0}
    # energy 5 kWh × 0.14775 = 0.73875; demand 20×37.37 = 747.4 + 20×10.52 = 210.4; fixed
    assert meter.cost_usd_month(now) == pytest.approx(0.73875 + 747.4 + 210.4 + FIXED, abs=USD)


def test_one_charge_two_windows_keeps_one_peak():
    tv = view()
    meter = MeterState(tv)
    meter_block(meter, local_ts(2026, 7, 16, 14, 15), 30.0)
    meter_block(meter, local_ts(2026, 7, 16, 21, 30), 20.0)
    now = local_ts(2026, 7, 16, 21, 45)
    # part-peak = max(30, 20) = 30, billed once: 30 × 10.52 = 315.6 (not 315.6 + 210.4)
    assert peaks_by_name(meter, now)["part_peak_demand_summer"] == 30.0
    assert [dp["cost_usd"] for dp in meter.demand_peaks(now)] == [1121.1, 0.0, 315.6]


@pytest.mark.parametrize(
    "hhmm, kw, peaks, energy_price",
    [
        # 18 Nov 2026 (Wed, PST). Applicable: max_demand, peak_demand_winter only (summer charges absent)
        ((16, 30), 50.0, {"max_demand": 50.0, "peak_demand_winter": 50.0}, 0.16188),
        ((14, 15), 30.0, {"max_demand": 30.0, "peak_demand_winter": 0.0}, 0.12026),
        ((21, 30), 20.0, {"max_demand": 20.0, "peak_demand_winter": 0.0}, 0.12026),
    ],
)
def test_november_blocks_bill_only_max_demand_and_winter_peak_in_window(hhmm, kw, peaks, energy_price):
    tv = view()
    meter = MeterState(tv)
    start = local_ts(2026, 11, 18, *hhmm)
    meter_block(meter, start, kw)
    now = start + timedelta(minutes=15)
    assert peaks_by_name(meter, now) == peaks
    assert meter.on_peak_month_peak_kw(now) == pytest.approx(peaks["peak_demand_winter"])  # the only windowed charge in November
    demand = kw * 37.37 + peaks["peak_demand_winter"] * 2.31
    # 16:30: 12.5 × 0.16188 = 2.0235 + 1868.5 + 115.5 + fixed · 14:15: 7.5 × 0.12026 + 1121.1 + fixed · 21:30: 5 × 0.12026 + 747.4
    assert meter.cost_usd_month(now) == pytest.approx(kw * 0.25 * energy_price + demand + FIXED, abs=USD)


def test_month_rollover_30_sep_to_1_oct_switches_the_charge_set():
    tv = view()
    meter = MeterState(tv)
    meter_block(meter, local_ts(2026, 9, 30, 16, 0), 40.0)  # summer on-peak block
    meter_block(meter, local_ts(2026, 9, 30, 23, 45), 10.0)  # last September block, closes at 1 Oct 00:00
    at_midnight = local_ts(2026, 10, 1, 0, 0)
    # the minute just metered is September's: September charges, peaks max 40 / summer 40 / part-peak 0
    assert peaks_by_name(meter, at_midnight) == {"max_demand": 40.0, "peak_demand_summer": 40.0,
                                                 "part_peak_demand_summer": 0.0}
    # Sep: energy 10 kWh × 0.18648 = 1.8648 + 2.5 kWh × 0.12037 = 0.300925 -> 2.165725; demand 40×37.37 = 1494.8
    #   + 40×46.16 = 1846.4; fixed 1 day (only 30 Sep metered) 11.36882
    assert meter.cost_usd_month(at_midnight) == pytest.approx(2.165725 + 1494.8 + 1846.4 + FIXED, abs=USD)

    meter.meter_minute(at_midnight, {"x": 12.0})
    now = at_midnight + timedelta(minutes=1)
    # October: max_demand + peak_demand_winter, every peak reset to 0; on-peak = the winter charge
    assert peaks_by_name(meter, now) == {"max_demand": 0.0, "peak_demand_winter": 0.0}
    assert meter.on_peak_month_peak_kw(now) == 0.0
    # 12 kW / 60 = 0.2 kWh × 0.12026 = 0.024052 + fixed 1 Oct 11.36882
    assert meter.cost_usd_month(now) == pytest.approx(0.024052 + FIXED, abs=USD)
    for i in range(1, 15):
        meter.meter_minute(at_midnight + timedelta(minutes=i), {"x": 12.0})
    now = at_midnight + timedelta(minutes=15)
    # block 00:00 closes at 12 kW: max 12, winter peak 0 (00:00 not in 16-21)
    assert peaks_by_name(meter, now) == {"max_demand": 12.0, "peak_demand_winter": 0.0}
    # 3 kWh × 0.12026 = 0.36078 + 12 × 37.37 = 448.44 + 11.36882
    assert meter.cost_usd_month(now) == pytest.approx(0.36078 + 448.44 + FIXED, abs=USD)


# =====================================================================================================================
# Fixed charges
# =====================================================================================================================


def test_fixed_daily_charge_accrues_per_local_day_from_first_metered_minute():
    tv = view()
    meter = MeterState(tv)
    t = local_ts(2026, 7, 16, 23, 59)
    meter.meter_minute(t, {"x": 0.0})
    # one minute of 16 Jul metered -> 1 day: month 11.36882, today 11.36882
    assert meter.cost_usd_month(t + timedelta(minutes=1)) == pytest.approx(FIXED, abs=USD)
    meter.meter_minute(t + timedelta(minutes=1), {"x": 0.0})  # 17 Jul 00:00
    now = t + timedelta(minutes=2)
    # 17 Jul's first minute -> 2 days: month 22.73764, today 11.36882
    assert meter.cost_usd_month(now) == pytest.approx(2 * FIXED, abs=USD)
    assert meter.cost_usd_today(now) == pytest.approx(FIXED, abs=USD)
    # every minute of 17 and 18 Jul -> 3 days in the month
    m = t + timedelta(minutes=2)
    while m < local_ts(2026, 7, 19, 0, 0):
        meter.meter_minute(m, {"x": 0.0})
        m += timedelta(minutes=1)
    assert meter.cost_usd_month(m) == pytest.approx(3 * FIXED, abs=USD)  # 34.10646
    assert meter.cost_usd_today(m) == pytest.approx(FIXED, abs=USD)


def test_fixed_monthly_charge_counts_once_and_today_on_the_1st():
    raw = json.loads(B19_PATH.read_text())
    raw["fixed_charges"] = [{"name": "meter_charge", "usd": 30.0, "per": "month"}]
    tv = TariffView(Tariff.model_validate(raw))
    meter = MeterState(tv)
    first = local_ts(2026, 8, 1, 0, 0)
    meter.meter_minute(first, {"x": 0.0})
    now = first + timedelta(minutes=1)
    assert meter.cost_usd_month(now) == pytest.approx(30.0, abs=USD)
    assert meter.cost_usd_today(now) == pytest.approx(30.0, abs=USD)  # the 1st carries the monthly charge
    second = local_ts(2026, 8, 2, 0, 0)
    meter.meter_minute(second, {"x": 0.0})
    now = second + timedelta(minutes=1)
    assert meter.cost_usd_month(now) == pytest.approx(30.0, abs=USD)  # once per month
    assert meter.cost_usd_today(now) == pytest.approx(0.0, abs=USD)


# =====================================================================================================================
# Demand added today across seasons and charges
# =====================================================================================================================


def test_cost_today_counts_every_charge_increase_since_midnight():
    tv = view()
    meter = MeterState(tv)
    meter_block(meter, local_ts(2026, 7, 15, 16, 0), 40.0)  # yesterday: max 40, summer 40
    meter_block(meter, local_ts(2026, 7, 16, 14, 0), 45.0)  # today: max 45, part-peak 45
    now = local_ts(2026, 7, 16, 14, 15)
    # today: energy 11.25 kWh × 0.14775 = 1.6621875; demand added (45−40)×37.37 = 186.85 + (45−0)×10.52 = 473.4
    #   (summer unchanged); fixed today 11.36882
    assert meter.cost_usd_today(now) == pytest.approx(1.6621875 + 186.85 + 473.4 + FIXED, abs=USD)


# =====================================================================================================================
# bill() / MonthBill (the pure billing function the backtest uses)
# =====================================================================================================================


def test_month_bill_hand_case_july():
    tv = view()
    mb = MonthBill(tv, "2026-07")
    mb.add_block(local_ts(2026, 7, 16, 16, 30), 50.0)  # peak_summer 50, max 50
    mb.add_block(local_ts(2026, 7, 16, 21, 30), 20.0)  # part-peak 20
    mb.add_block(local_ts(2026, 7, 17, 3, 0), 10.0)  # second local day, off-peak
    b = mb.bill()
    # energy 12.5 + 5 + 2.5 = 20 kWh; cost 12.5×0.18648 = 2.331 + 5×0.14775 = 0.73875 + 2.5×0.12037 = 0.300925 -> 3.370675
    assert b["energy_kwh"] == 20.0
    assert b["energy_cost_usd"] == 3.37
    assert b["demand_charges"] == [
        {"name": "max_demand", "peak_kw": 50.0, "cost_usd": 1868.5},
        {"name": "peak_demand_summer", "peak_kw": 50.0, "cost_usd": 2308.0},
        {"name": "part_peak_demand_summer", "peak_kw": 20.0, "cost_usd": 210.4},
    ]
    # 2 local days × 11.36882 = 22.73764 -> 22.74
    assert b["fixed_usd"] == 22.74
    # 3.37 + 1868.5 + 2308 + 210.4 + 22.74 = 4413.01
    assert b["total_usd"] == pytest.approx(4413.01, abs=1e-9)
    assert b["tariff_id"] == "pge_b19_secondary_voluntary"
    with pytest.raises(ValueError):
        mb.add_block(local_ts(2026, 8, 1, 0, 0), 1.0)  # not July


def test_bill_drops_charges_outside_their_months():
    tv = view()
    b = bill(tv, "2026-11", energy_kwh=100.0, energy_cost_usd=12.026,
             peaks_kw={"max_demand": 40.0, "peak_demand_summer": 99.0, "peak_demand_winter": 30.0}, days_metered=0)
    # November: max 40×37.37 = 1494.8 · winter 30×2.31 = 69.3; summer peak ignored; no day metered -> fixed 0
    assert [d["name"] for d in b["demand_charges"]] == ["max_demand", "peak_demand_winter"]
    assert b["total_usd"] == pytest.approx(12.03 + 1494.8 + 69.3, abs=1e-9)
    assert demand_lines(tv, 11, {"max_demand": 1.234})[0]["peak_kw"] == 1.23  # Meter publishes 0.01 kW


# =====================================================================================================================
# Facade: Kitchen on B-19, demand_peaks in the TickState; month_to_date restore with demand_peaks
# =====================================================================================================================


def _b19_kitchen():
    config = load_config().model_dump(mode="json")
    config["tariff_id"] = "pge_b19_secondary_voluntary"
    kitchen = Kitchen(config, b19(), catalog(), "without", 42)
    return kitchen, roster(load_config(), load_catalog())


def test_facade_tick_state_carries_seasonal_demand_peaks():
    kitchen, devices = _b19_kitchen()
    ts = local_ts(2026, 7, 16, 16, 30)
    state = None
    for i in range(15):
        ts = ts + timedelta(minutes=1)
        state = as_tick_state(kitchen.step(1, hub_report(lane="without", tick_id=i + 1, ts=ts, total_kw=50.0,
                                                         devices=devices)))
    m = state.meter
    assert [(d.name, d.peak_kw, d.usd_per_kw, d.cost_usd) for d in m.demand_peaks] == [
        ("max_demand", 50.0, 37.37, 1868.5),
        ("peak_demand_summer", 50.0, 46.16, 2308.0),
        ("part_peak_demand_summer", 0.0, 10.52, 0.0),
    ]
    assert m.on_peak_month_peak_kw == pytest.approx(50.0)
    assert m.price_usd_per_kwh_now == 0.18648  # 16:45 summer peak
    assert m.cost_usd_month == pytest.approx(2.331 + 4176.5 + FIXED, abs=USD)


def test_restore_month_to_date_with_demand_peaks():
    tv = view()
    meter = MeterState(tv)
    start = local_ts(2026, 7, 16, 16, 0)
    mtd = MonthToDate(month="2026-07", month_peak_kw=44.0, on_peak_month_peak_kw=41.0, energy_kwh_month=7000.0,
                      cost_usd_month=5000.0,
                      demand_peaks=[{"name": "max_demand", "peak_kw": 44.0, "usd_per_kw": 37.37, "cost_usd": 1644.28},
                                    {"name": "peak_demand_summer", "peak_kw": 41.0, "usd_per_kw": 46.16,
                                     "cost_usd": 1892.56},
                                    {"name": "part_peak_demand_summer", "peak_kw": 30.0, "usd_per_kw": 10.52,
                                     "cost_usd": 315.6}])
    meter.restore_month_to_date(mtd, start)
    assert peaks_by_name(meter, start) == {"max_demand": 44.0, "peak_demand_summer": 41.0,
                                           "part_peak_demand_summer": 30.0}
    # cost_usd_month continues from the restored value (energy part = 5000 − demand − 16 days fixed)
    assert meter.cost_usd_month(start) == pytest.approx(5000.0, abs=USD)
    meter_block(meter, start, 40.0)  # 16:00 block under every peak: only energy is added, 10 kWh × 0.18648
    assert meter.cost_usd_month(start + timedelta(minutes=15)) == pytest.approx(5001.8648, abs=USD)
