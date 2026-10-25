#!/usr/bin/env python3
"""WattWise shared fixture generator. FAKE DATA - not measured, not live.

Seeded (42), Python standard library only. Rerunning produces identical bytes.

Usage:
  python3 contracts/fixtures/generate.py [output_dir]        every committed fixture (default: this folder)
  python3 contracts/fixtures/generate.py --days N --out DIR   full-tick N-day run (hub_protocol + step_stream), not committed

Every number here is illustrative: a toy simulation of the Demo Cafe (customers + appliance physics, standing in for
frontend/src/sim) plus a toy rule-following controller for the `with` lane (standing in for the engine, whose internals
are TBD). They are not engine output and never savings.

One physical run drives everything: tick n is the simulated minute starting at START + (n - 1) min. The evening scenario
(scenario/demo_cafe) is ticks 1..120 of it; the multi-day scenario (scenario/demo_cafe_multiday) is segments of the same run
up to day 2's close; `--days N` writes every tick of an N-day run.
"""
import copy
import json
import math
import os
import random
import sys
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = 42
UTC = timezone.utc
LOCAL_OFFSET = timedelta(hours=-7)     # America/Los_Angeles, PDT for every date used (DST runs 2026-03-08 .. 2026-11-01)
START = datetime(2026, 7, 18, 0, 30, tzinfo=UTC)             # Friday 17 July 2026, 17:30 local
HIST_START = datetime(2026, 5, 17, 7, 0, tzinfo=UTC)         # Sunday 17 May 2026, 00:00 local
REAL_START = datetime(2026, 10, 25, 17, 30, tzinfo=UTC)      # illustrative wall clock for ts_real / created_at
EVENING_TICKS = 120
CAP = 40.0
LANES = ("without", "with")
REPLAN_EVERY = 5
PLAN_MARGIN_KW = 1.0          # toy controller headroom under the target (customer noise); the target itself stays the cap
OPEN_M, CLOSE_M = 600, 1320   # 10:00 / 22:00 local
LIVE_DAYS = 7
MULTI_DAYS = 2
SPEED = 120
CONTEXT_REFRESH_MIN = 300     # fixture stand-in for CONTEXT_INTERVAL_S: recorded context (6 hourly values) re-posted every 5 sim hours
OWNER_MIN_TICK = 95           # the owner presses "start" on the dishwasher once after this tick, while it runs
OWNER_DEVICE = "dishwasher_1"
CROWD = {"none": 1.00, "small": 1.10, "medium": 1.25, "large": 1.40}


# ----------------------------------------------------------------------------- helpers
def iso(dt):
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_ms(dt):
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def rnd(x, d):
    v = round(x + 0.0, d)
    return 0.0 if v == 0 else v


def half_up(x):
    return int(math.floor(x + 0.5))


def loc(dt):
    return (dt + LOCAL_OFFSET).replace(tzinfo=None)


def lmin(dt):
    x = loc(dt)
    return x.hour * 60 + x.minute


def ldate(dt):
    return loc(dt).date()


def utc_of_local(d, minute):
    return datetime(d.year, d.month, d.day, tzinfo=UTC) - LOCAL_OFFSET + timedelta(minutes=minute)


def hm(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def hm_str(minute):
    return "%02d:%02d" % (minute // 60, minute % 60)


def is_open(dt):
    return OPEN_M <= lmin(dt) < CLOSE_M


def sim_dt(n):        # start of the simulated minute stepped in tick n
    return START + timedelta(minutes=n - 1)


def rep_dt(n):        # HubReport ts = end of the minute just stepped
    return START + timedelta(minutes=n)


def tick_at(dt):      # the tick whose minute starts at dt
    return int((dt - START).total_seconds() // 60) + 1


def block_index(n):   # 15-min blocks aligned to local :00/:15/:30/:45; START is aligned
    return (n - 1) // 15


def block_ticks(k):
    return range(15 * k + 1, 15 * k + 16)


def block_start_dt(k):
    return START + timedelta(minutes=15 * k)


def real_dt(n, extra_ms=0):
    return REAL_START + timedelta(milliseconds=500 * n + extra_ms)


def ceil_int(x):
    return int(math.ceil(x - 1e-9))


# ----------------------------------------------------------------------------- catalog + config
CYCLE = {
    "walk_in_cooler": dict(lo=2.0, hi=4.0, a=0.10, b=0.10, rate=0.30, heater=False),
    "reach_in_fridge": dict(lo=2.0, hi=5.0, a=0.08, b=0.12, rate=0.35, heater=False),
    "freezer": dict(lo=-20.0, hi=-17.0, a=0.06, b=0.06, rate=0.25, heater=False),
    "water_heater": dict(lo=60.0, hi=64.0, a=0.15, b=0.25, rate=0.60, heater=True),
}
SETPOINT_C = 22.5
SETBACK_C = 4.0


def duty(type_id):
    """Catalog duty-cycle params implied by the toy cycling physics (idle = no customers, busy = 100 customers/h)."""
    p = CYCLE[type_id]
    return {"duty_idle_pct": half_up(100 * p["a"] / p["rate"]), "duty_busy_pct": half_up(100 * (p["a"] + p["b"]) / p["rate"])}


# Catalog source notes, copied verbatim from backend/data/equipment_catalog.json (branch ashirwad, the frontend's catalog
# is the truth). type_id, power numbers, params and default_limits below already equal that file.
SOURCE_NOTES = {
    "hvac":
        "One 5-ton packaged RTU (PSZ-AC, gas furnace), per unit: DX compressor ~5.45 kW (60 kBtu/h / EER 11) + share of the constant ventilation fans. Sized on NREL ComStock bldg 5847 upgrade 45 (2018): HVAC = cooling + fans + heating (ComStock's electric HVAC group, 74,322 kWh/yr); fans are a constant 5.739 kW (night_fanon_vent); worst 15-min block 15.714 kW (2018-06-23 18:45) = 7.857 kW per unit for 2 units, so 8.0 kW covers the whole year without clipping. 40 % min = 3.2 kW >= the 2.87 kW ventilation fan share per unit. derived",
    "walk_in_cooler":
        "Modeled walk-in condensing load; ENERGY STAR V5 explicitly excludes walk-ins, so this is a transparent demo assumption rather than an ENERGY STAR rating.",
    "reach_in_fridge":
        "Modeled two-door reach-in input; duty behavior is calibrated to ENERGY STAR commercial refrigerator daily-energy criteria, not a claimed product rating.",
    "freezer":
        "Modeled reach-in freezer input; duty behavior is calibrated to ENERGY STAR commercial freezer daily-energy criteria, not a claimed product rating.",
    "ice_machine":
        "Modeled batch ice-machine input; cycle length and draw are explicit demo assumptions informed by ENERGY STAR commercial ice-machine test criteria.",
    "fryer":
        "Modeled standard electric fryer; ENERGY STAR defines electric idle rate <=0.8 kW, while the intentionally conservative 1.5 kW demo idle represents a non-certified baseline.",
    "oven":
        "Modeled full-size electric convection oven input; values are explicit demo assumptions informed by FSTC ASTM-standard appliance testing.",
    "grill":
        "Modeled electric griddle input; rated draw is aligned with published FSTC-tested electric griddle cooking rates near 8.9 kW.",
    "dishwasher":
        "Modeled high-temperature door-type dishwasher including booster demand; draw and batch length are explicit demo assumptions informed by ENERGY STAR commercial dishwasher criteria.",
    "water_heater":
        "Modeled single-element electric water-heater input; rated draw and duty cycle are explicit demo assumptions informed by DOE commercial water-heater test procedures.",
    "lights":
        "Modeled 2,500 ft² restaurant at 0.96 W/ft²; explicit demo assumption within ASHRAE 90.1 restaurant lighting-power-density ranges.",
}

def cat(type_id, name, category, imp, rated, model, params, limits):
    return {"type_id": type_id, "name": name, "category": category, "default_importance": imp, "rated_kw": rated,
            "power_model": model, "params": params, "default_limits": limits, "source_note": SOURCE_NOTES[type_id]}


CATALOG = [
    cat("hvac", "HVAC", "cooling", "flexible", 8.0, "thermal", {"setpoint_c": SETPOINT_C}, {"min_power_pct": 40, "max_reduce_min": 30}),
    cat("walk_in_cooler", "Walk-in cooler", "refrigeration", "flexible", 3.5, "cycling", duty("walk_in_cooler"),
        {"min_power_pct": 50, "max_reduce_min": 30}),
    cat("reach_in_fridge", "Reach-in fridge", "refrigeration", "always_on", 0.8, "cycling", duty("reach_in_fridge"), {}),
    cat("freezer", "Freezer", "refrigeration", "always_on", 1.4, "cycling", duty("freezer"), {}),
    cat("ice_machine", "Ice machine", "refrigeration", "deferrable", 1.6, "job", {"cycle_min": 20},
        {"max_delay_min": 60, "must_finish_by": "22:00"}),
    cat("fryer", "Fryer", "cooking", "always_on", 14.0, "demand_driven", {"idle_kw": 1.5, "kw_per_order": 0.26}, {}),
    cat("oven", "Oven", "cooking", "always_on", 10.0, "demand_driven", {"idle_kw": 2.0, "kw_per_order": 0.12}, {}),
    cat("grill", "Grill", "cooking", "always_on", 8.0, "demand_driven", {"idle_kw": 1.5, "kw_per_order": 0.12}, {}),
    cat("dishwasher", "Dishwasher", "water_heating", "deferrable", 6.0, "job", {"cycle_min": 30},
        {"max_delay_min": 60, "must_finish_by": "15:30"}),
    cat("water_heater", "Water heater", "water_heating", "flexible", 4.5, "cycling", duty("water_heater"),
        {"min_power_pct": 40, "max_reduce_min": 30}),
    cat("lights", "Lights", "lighting", "always_on", 2.4, "fixed", {}, {}),
]
CAT = {c["type_id"]: c for c in CATALOG}

AUTHORITY = {"enabled": True, "max_cap_overrun_kw": 3.0, "max_extra_delay_min": 20, "max_extra_reduce_min": 15,
             "may_go_below_min_power": False}
AUTH_REFERENCE = {"kW": 3.0, "delay": 20, "reduce": 15}

# Demo Cafe (CONTRACTS.md section 1): every catalog type, hvac x 2, catalog default limits, except the dishwasher deadline
# moved to 19:30 so it matters during the 17:30-19:30 demo.
SCENARIO_LIMITS = {"dishwasher": {"max_delay_min": 60, "must_finish_by": "19:30"}}
COUNTS = {"hvac": 2}


def make_config(run_days):
    return {
        "name": "Demo Café",
        "equipment": [{"type_id": c["type_id"], "count": COUNTS.get(c["type_id"], 1), "importance": c["default_importance"],
                       "limits": copy.deepcopy(SCENARIO_LIMITS.get(c["type_id"], c["default_limits"]))} for c in CATALOG],
        "peak_mode": "cap",
        "peak_cap_kw": CAP,
        "operating_hours": {"open": hm_str(OPEN_M), "close": hm_str(CLOSE_M)},
        "location": {"lat": 37.80, "lon": -122.44, "label": "Marina, San Francisco"},
        "owner_preferences": "Keep the dining room comfortable during dinner service.",
        "authority": AUTHORITY,
        "tariff_id": "demo_tariff_v1",
        "run_days": run_days,
        "seed": SEED,
    }


CONFIG = make_config(1)

def _energy(name, start, end, usd, months=None, days="all"):
    return {"name": name, "start": start, "end": end, "usd_per_kwh": usd, "months": months, "days": days}


def _demand(name, windows, usd, months=None, days="all"):
    return {"name": name, "windows": None if windows is None else [{"start": a, "end": b} for a, b in windows],
            "months": months, "days": days, "usd_per_kw": usd}


# demo_tariff_v1 (CONTRACTS.md section 1): the made-up rate of the live demo; every field written out (months null = every
# month, days "all"), no fixed charges.
TARIFF = {
    "tariff_id": "demo_tariff_v1", "name": "WattWise demo commercial rate", "label": "illustrative", "currency": "USD",
    "timezone": "America/Los_Angeles",
    "energy": [_energy("off_peak", "00:00", "16:00", 0.22), _energy("peak", "16:00", "21:00", 0.38),
               _energy("off_peak", "21:00", "24:00", 0.22)],
    "demand": [_demand("max_demand", None, 20.0), _demand("peak_demand", [("16:00", "21:00")], 8.0)],
    "fixed_charges": [],
}

# PG&E B-19 Secondary Voluntary, OpenEI URDB 69de8cdb02f684104e01267d (dataset/tariffs/, gitignored), converted as CONTRACTS.md
# section 1 describes. The URDB numbers below are copied unchanged; check.py re-derives every hour of every month from the URDB
# record when dataset/ is present. URDB energy periods 0..5 (rate $/kWh): 0 0.06442 spring super-off-peak (months 3-5,
# 09-14) · 1 0.12026 winter off-peak · 2 0.16188 winter peak (16-21) · 3 0.12037 summer off-peak · 4 0.14775 summer part-peak
# (14-16, 21-23) · 5 0.18648 summer peak (16-21). Demand: flat 37.37 $/kW in both flat periods (all months); TOU periods
# 1 2.31 (winter 16-21), 2 10.52 (summer 14-16 + 21-23), 3 46.16 (summer 16-21); period 0 is $0 (no charge). Weekday and
# weekend schedules are identical (days "all"). Fixed: fixedchargefirstmeter 11.36882, fixedchargeunits "$/day".
B19_URDB_ID = "69de8cdb02f684104e01267d"
_WINTER, _SPRING, _NONSPRING_WINTER, _SUMMER = [1, 2, 3, 4, 5, 10, 11, 12], [3, 4, 5], [1, 2, 10, 11, 12], [6, 7, 8, 9]
TARIFF_B19 = {
    "tariff_id": "pge_b19_secondary_voluntary",
    "name": "PG&E B-19 Medium General Demand TOU (Secondary) Voluntary",
    "label": "urdb", "currency": "USD", "timezone": "America/Los_Angeles",
    "energy": [
        _energy("off_peak_winter", "21:00", "16:00", 0.12026, _NONSPRING_WINTER),
        _energy("off_peak_winter", "21:00", "09:00", 0.12026, _SPRING),
        _energy("super_off_peak_spring", "09:00", "14:00", 0.06442, _SPRING),
        _energy("off_peak_winter", "14:00", "16:00", 0.12026, _SPRING),
        _energy("peak_winter", "16:00", "21:00", 0.16188, _WINTER),
        _energy("off_peak_summer", "23:00", "14:00", 0.12037, _SUMMER),
        _energy("part_peak_summer", "14:00", "16:00", 0.14775, _SUMMER),
        _energy("peak_summer", "16:00", "21:00", 0.18648, _SUMMER),
        _energy("part_peak_summer", "21:00", "23:00", 0.14775, _SUMMER),
    ],
    "demand": [
        _demand("max_demand", None, 37.37),
        _demand("peak_demand_winter", [("16:00", "21:00")], 2.31, _WINTER),
        _demand("peak_demand_summer", [("16:00", "21:00")], 46.16, _SUMMER),
        _demand("part_peak_demand_summer", [("14:00", "16:00"), ("21:00", "23:00")], 10.52, _SUMMER),
    ],
    "fixed_charges": [{"name": "customer_charge", "usd": 11.36882, "per": "day"}],
}


def in_span(lm, a, b):
    """`[a, b)` in local minutes of the day; b < a wraps past midnight; a == b is empty."""
    if a < b:
        return a <= lm < b
    if a > b:
        return lm >= a or lm < b
    return False


def day_type(d):
    return "weekends" if d.weekday() >= 5 else "weekdays"


class TariffCalc:
    """The bill function of CONTRACTS.md section 1 Tariff (months, day types, windows, fixed charges)."""

    def __init__(self, t):
        self.t = t
        self.energy = [(hm(e["start"]), hm(e["end"]), e["usd_per_kwh"], e["months"], e["days"]) for e in t["energy"]]
        self.charges = [{"name": c["name"], "rate": c["usd_per_kw"], "months": c["months"], "days": c["days"],
                         "windows": None if c["windows"] is None else [(hm(w["start"]), hm(w["end"])) for w in c["windows"]]}
                        for c in t["demand"]]
        self.fixed_day = sum(f["usd"] for f in t["fixed_charges"] if f["per"] == "day")
        self.fixed_month = sum(f["usd"] for f in t["fixed_charges"] if f["per"] == "month")

    @staticmethod
    def _match(months, days, d):
        return (months is None or d.month in months) and (days == "all" or days == day_type(d))

    def price(self, dt):
        x = loc(dt)
        lm = x.hour * 60 + x.minute
        hits = [p for a, b, p, mo, dy in self.energy if self._match(mo, dy, x.date()) and in_span(lm, a, b)]
        assert len(hits) == 1, (iso(dt), hits)
        return hits[0]

    def applicable(self, month):
        """Charges that apply in a local month (1..12), tariff order."""
        return [c for c in self.charges if c["months"] is None or month in c["months"]]

    def counts(self, c, block_start):
        """A closed block counts for a charge when its local start is in any window, its month applies, its day type matches."""
        x = loc(block_start)
        lm = x.hour * 60 + x.minute
        return self._match(c["months"], c["days"], x.date()) and (
            c["windows"] is None or any(in_span(lm, a, b) for a, b in c["windows"]))

    def on_peak_name(self, month):
        """The highest-rate windowed charge that applies this month (first in tariff order on a tie), or None."""
        win = [c for c in self.applicable(month) if c["windows"] is not None]
        return max(win, key=lambda c: c["rate"])["name"] if win else None


TC = TariffCalc(TARIFF)


def tariff_price(dt):
    return TC.price(dt)


DEVICES = []
for _eq in CONFIG["equipment"]:
    _c = CAT[_eq["type_id"]]
    for _i in range(1, _eq["count"] + 1):
        DEVICES.append({"device_id": "%s_%d" % (_c["type_id"], _i), "type_id": _c["type_id"], "name": "%s %d" % (_c["name"], _i),
                        "importance": _eq["importance"], "limits": _eq["limits"], "rated_kw": _c["rated_kw"],
                        "power_model": _c["power_model"], "params": _c["params"], "category": _c["category"]})
DEV = {d["device_id"]: d for d in DEVICES}
IDX = {d["device_id"]: i for i, d in enumerate(DEVICES)}
ND = len(DEVICES)
FLEX = [d["device_id"] for d in DEVICES if d["importance"] == "flexible"]
JOBS = [d["device_id"] for d in DEVICES if d["importance"] == "deferrable"]
ALWAYS = [d["device_id"] for d in DEVICES if d["importance"] == "always_on"]


# ----------------------------------------------------------------------------- daily inputs (weather, prices, crowd, surges)
WEEKDAY = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
HIST_DATES = [date(2026, 5, 17) + timedelta(days=i) for i in range(62)]           # 2026-05-17 .. 2026-07-17
LIVE_DATES = [date(2026, 7, 17) + timedelta(days=i) for i in range(LIVE_DAYS)]    # 2026-07-17 .. 2026-07-23
ALL_DATES = sorted(set(HIST_DATES) | set(LIVE_DATES))
HOT_DAYS = {date(2026, 5, 29): 29.0, date(2026, 6, 9): 32.0, date(2026, 6, 10): 34.5, date(2026, 6, 11): 31.5,
            date(2026, 6, 26): 27.5, date(2026, 7, 11): 28.0, date(2026, 7, 17): 29.6}
# the recorded evening of the demo (kept from the first fixture version so the 120-tick scenario stays stable)
REC_TEMPS = {(date(2026, 7, 17), h): t for h, t in ((17, 29.1), (18, 28.4), (19, 27.2), (20, 25.8), (21, 24.1), (22, 22.9),
                                                       (23, 21.8))}
REC_TEMPS.update({(date(2026, 7, 18), 0): 20.9, (date(2026, 7, 18), 1): 20.2})
# 17 July: a mild morning, then the heat builds through the afternoon into the recorded hot evening
REC_TEMPS.update({(date(2026, 7, 17), h): t for h, t in enumerate(
    (17.8, 17.4, 17.1, 16.9, 16.8, 16.9, 17.3, 18.0, 19.0, 20.1, 21.0, 22.0, 23.1, 24.4, 25.9, 27.4, 28.6))})
REC_PRICES = {(date(2026, 7, 17), h): p for h, p in ((17, 0.29), (18, 0.34), (19, 0.37), (20, 0.33), (21, 0.27), (22, 0.22),
                                                        (23, 0.19))}
REC_PRICES.update({(date(2026, 7, 18), 0): 0.17, (date(2026, 7, 18), 1): 0.16})
PRICE_SHAPE = [0.16] * 6 + [0.19] * 4 + [0.23] * 6 + [0.29] + [0.33] * 3 + [0.27, 0.23, 0.20, 0.20]


def _event(name, d, minute, km, people):
    return {"name": name, "venue": "Oracle Park", "start": iso(utc_of_local(d, minute)), "distance_km": km,
            "expected_attendance": people}


EVENTS = {date(2026, 6, 26): [_event("Giants vs Rockies", date(2026, 6, 26), 19 * 60 + 15, 1.8, 38000)],
          date(2026, 7, 17): [_event("Giants vs Dodgers", date(2026, 7, 17), 19 * 60 + 5, 1.8, 40000)]}
CROWD_REASON = {date(2026, 6, 26): "Game ends 22:10, 1.8 km away", date(2026, 7, 17): "Game ends 22:00, 1.8 km away"}
SURGES = {
    date(2026, 5, 23): [{"surge_id": None, "start_local": "19:00", "customers": 30, "duration_min": 60}],
    date(2026, 6, 13): [{"surge_id": None, "start_local": "12:30", "customers": 35, "duration_min": 60}],
    date(2026, 7, 11): [{"surge_id": None, "start_local": "19:00", "customers": 25, "duration_min": 60}],
    date(2026, 7, 17): [{"surge_id": "s_0001", "start_local": "18:00", "customers": 40, "duration_min": 60}],
    date(2026, 7, 18): [{"surge_id": "s_0002", "start_local": "12:15", "customers": 35, "duration_min": 45}],
}


def build_daily():
    rng = random.Random(SEED + 11)
    out = {}
    for d in ALL_DATES:
        tmax = 24.5 + rng.uniform(-1.5, 3.0)
        tmin = 14.5 + rng.uniform(-1.0, 1.5)
        if d.month == 7 and d.day < 17:
            tmax = min(tmax, 25.0)                    # a mild first half of July
        tmax = HOT_DAYS.get(d, tmax)
        if d == date(2026, 7, 18):
            tmin, tmax = 17.0, 28.5                   # warm night and a warm Saturday after the hot Friday
        if d in HOT_DAYS:
            tmin += 3.0
        t0 = tmin + 0.35 * (tmax - tmin)
        temps = []
        for h in range(24):
            if h < 5:
                t = tmin + (t0 - tmin) * (5 - h) / 5
            elif h <= 15:
                t = tmin + (tmax - tmin) * (1 - math.cos(math.pi * (h - 5) / 10)) / 2
            else:
                t = tmax - (tmax - t0) * (h - 15) / 9
            temps.append(REC_TEMPS.get((d, h), rnd(t, 1)))
        heat = 1 + 0.02 * max(0.0, tmax - 24)
        prices = [REC_PRICES.get((d, h), rnd(PRICE_SHAPE[h] * heat, 2)) for h in range(24)]
        mx = max(prices)
        stress = "high" if d == date(2026, 7, 17) or mx >= 0.36 else "normal" if mx >= 0.30 else "low"
        out[d] = {"date": d.isoformat(), "weekday": WEEKDAY[d.weekday()],
                  "in_history": d in HIST_DATES, "in_live": d in LIVE_DATES,
                  "hourly_outdoor_temp_c": temps, "hourly_grid_usd_per_kwh": prices, "price_stress": stress,
                  "crowd_effect": "medium" if d in EVENTS else "none",
                  "events": EVENTS.get(d, []), "surges": SURGES.get(d, [])}
    return out


DAILY = build_daily()


def temp_at(dt):
    x = loc(dt)
    di = DAILY.get(x.date())
    if di is None:            # beyond the fixture calendar (forecast look-ahead after the last day): a mild night
        return 15.0
    return di["hourly_outdoor_temp_c"][x.hour]


def crowd_of(d):
    di = DAILY.get(d)
    return "none" if di is None else di["crowd_effect"]


# live surges (run ticks): requested by a judge the minute before they start
LIVE_SURGES = []
for _d in LIVE_DATES:
    for _s in DAILY[_d]["surges"]:
        _t = tick_at(utc_of_local(_d, hm(_s["start_local"])))
        LIVE_SURGES.append({"surge_id": _s["surge_id"], "customers": _s["customers"], "duration_min": _s["duration_min"],
                            "start_tick": _t, "request_tick": _t - 1})


# ----------------------------------------------------------------------------- customers (one stream, both lanes)
PROFILE = [(600, 8), (660, 20), (720, 52), (810, 52), (870, 22), (990, 22), (1050, 38), (1110, 58), (1230, 58), (1320, 30)]
WEEKDAY_FACTOR = [0.82, 0.85, 0.90, 0.95, 1.00, 1.25, 1.15]   # Mon..Sun; weekends busier


def base_cph(dt):
    """Simulated customer flow (customers/h) at a minute, before the crowd multiplier and noise. 0 while closed."""
    lm = lmin(dt)
    if not OPEN_M <= lm < CLOSE_M:
        return 0.0
    v = PROFILE[-1][1]
    for (m0, c0), (m1, c1) in zip(PROFILE, PROFILE[1:]):
        if m0 <= lm < m1:
            v = c0 + (c1 - c0) * (lm - m0) / (m1 - m0)
            break
    return v * WEEKDAY_FACTOR[ldate(dt).weekday()]


# ----------------------------------------------------------------------------- simulation (toy physics, both lanes)
RACKS_PER_CUSTOMER = 0.06
HVAC_BASE = 34
HVAC_LOAD_KW = 0.12        # dining-room cooling load per load point, in kW: the load belongs to the room, not to the unit, so
                           # each 8 kW unit (catalog) meets it up to its rated_kw and runs at a higher duty than a bigger one
RACK_THRESHOLD = 8.0
MIN_PHYSICAL_PCT = 20       # appliances cannot run below 20 % (a lower reduce is clamped, ack reason out_of_range)
ICE_LOW = 25.0
ROOM_GAIN = 0.001          # dining-room warming per minute per % of HVAC shortfall
DW_START_RACKS = 5.8
ICE_START_PCT = 62.0


def initial_state(seed):
    r = random.Random(seed)
    st = {}
    for d in DEVICES:
        s = {"cap": 100, "on": True}
        if d["power_model"] == "thermal":
            u = r.uniform(-0.05, 0.05)
            st.setdefault("_room", {"temp": 22.6 + u})     # one dining room shared by every HVAC unit
        elif d["power_model"] == "cycling":
            p = CYCLE[d["type_id"]]
            s["temp"] = r.uniform(p["lo"], p["hi"])
            s["running"] = r.random() < 0.5
        elif d["power_model"] == "job":
            s["remaining"] = 0
            s["hold_until"] = None
            s["force"] = False
            s["level"] = DW_START_RACKS if d["type_id"] == "dishwasher" else ICE_START_PCT
        st[d["device_id"]] = s
    return st


INIT = initial_state(SEED + 1)


class Sim:
    """Toy appliance physics for one lane. Steps one simulated minute at a time; `m` = minute index (tick - 1)."""

    def __init__(self, init):
        self.st = copy.deepcopy(init)
        self.pw = [0.0] * ND
        self.states = ["off"] * ND
        self.phys = [None] * ND

    def clone(self):
        s = Sim.__new__(Sim)
        s.st = {k: dict(v) for k, v in self.st.items()}
        s.pw = list(self.pw)
        s.states = list(self.states)
        s.phys = list(self.phys)
        return s

    def apply(self, cmd, m):
        """Hub applies a Command before minute m is stepped. Returns a CommandAck."""
        s = self.st.get(cmd["device_id"])
        a, v = cmd["action"], cmd["value"]

        def ack(ok, applied, reason):
            return {"command_id": cmd["command_id"], "lane": cmd["lane"], "ok": ok, "applied_value": applied, "reason": reason}

        if s is None:
            return ack(False, None, "unknown_device")
        d = DEV[cmd["device_id"]]
        if a == "reduce":
            if d["power_model"] not in ("thermal", "cycling"):
                return ack(False, None, "unknown_device")
            applied = min(100, max(MIN_PHYSICAL_PCT, v))
            s["cap"] = applied
            return ack(True, applied, None if applied == v else "out_of_range")
        if a == "restore":
            s["cap"] = 100
            return ack(True, None, None)
        if a == "delay":
            if d["power_model"] != "job":
                return ack(False, None, "unknown_device")
            if s["remaining"] > 0:
                return ack(False, None, "job_running")
            s["hold_until"] = (m + v) if v > 0 else None
            return ack(True, v, None)
        if a == "start":
            if d["power_model"] != "job":
                return ack(False, None, "unknown_device")
            if s["remaining"] > 0:
                return ack(False, None, "job_running")
            s["force"] = True
            return ack(True, None, None)
        if a == "off":
            if not s["on"]:
                return ack(False, None, "already_off")
            s["on"] = False
            return ack(True, None, None)
        if a == "on":
            s["on"] = True
            return ack(True, None, None)
        return ack(False, None, "unknown_device")

    def step(self, m, dt, cph, t_out, open_):
        lm = lmin(dt)
        preheat = (not open_) and OPEN_M - 30 <= lm < OPEN_M
        after_close = (not open_) and CLOSE_M <= lm < CLOSE_M + 15
        shortfalls = []
        total = 0.0
        st = self.st
        for i, d in enumerate(DEVICES):
            s = st[d["device_id"]]
            model, rated, physical = d["power_model"], d["rated_kw"], None
            state = "on"
            if not s["on"]:
                power, state = 0.0, "off"
            elif model == "fixed":
                power = rated if open_ else rated * 0.10          # night / security lighting while closed
            elif model == "demand_driven":
                if open_ or after_close or preheat:
                    orders = half_up(cph * 0.2)
                    power = min(rated, d["params"]["idle_kw"] + d["params"]["kw_per_order"] * orders)
                else:
                    orders = 0
                    power, state = 0.0, "off"
                physical = {"orders_in_progress": orders}
            elif model == "thermal":
                room = st["_room"]["temp"]
                sp = d["params"]["setpoint_c"] + (0.0 if open_ or preheat else SETBACK_C)
                load_kw = HVAC_LOAD_KW * (HVAC_BASE + 5 * (t_out - 24) + 0.1 * cph + 8 * (room - sp))
                need = min(100.0, max(0.0, 100 * load_kw / rated))
                act = min(need, s["cap"])
                power = rated * act / 100
                shortfalls.append((need - act, sp))
                state = "reduced" if s["cap"] < 100 else "on"
                physical = {"indoor_temp_c": None}      # set after every unit has run
            elif model == "cycling":
                p = CYCLE[d["type_id"]]
                if p["heater"]:
                    if s["temp"] <= p["lo"]:
                        s["running"] = True
                    elif s["temp"] >= p["hi"]:
                        s["running"] = False
                else:
                    if s["temp"] >= p["hi"]:
                        s["running"] = True
                    elif s["temp"] <= p["lo"]:
                        s["running"] = False
                gain = p["a"] + p["b"] * cph / 100
                frac = s["cap"] / 100
                power = rated * frac if s["running"] else 0.0
                delta = (p["rate"] * frac if s["running"] else 0.0) - gain
                s["temp"] += delta if p["heater"] else -delta
                state = "reduced" if s["cap"] < 100 else "on"
                physical = {"box_temp_c": rnd(s["temp"], 1)}
            else:  # job
                dw = d["type_id"] == "dishwasher"
                if dw:
                    s["level"] += cph / 60 * RACKS_PER_CUSTOMER
                else:
                    s["level"] = max(0.0, s["level"] - (0.3 + 0.004 * cph))
                held = s["hold_until"] is not None and m < s["hold_until"]
                if dw and not open_ and lm == CLOSE_M and s["level"] >= 1 and s["remaining"] == 0 and not held:
                    s["force"] = True                       # last dishwasher cycle right after close
                if s["remaining"] == 0:
                    ready = s["level"] >= RACK_THRESHOLD if dw else s["level"] < ICE_LOW
                    if s["force"] or (ready and not held):
                        s["remaining"] = d["params"]["cycle_min"]
                        s["hold_until"] = None
                        if dw:
                            s["level"] = 0.0
                    s["force"] = False
                if s["remaining"] > 0:
                    power = rated
                    s["remaining"] -= 1
                    state = "running_job"
                    if not dw:
                        s["level"] = min(100.0, s["level"] + 3.5)
                else:
                    power = 0.0
                    if s["hold_until"] is not None and m < s["hold_until"]:
                        state = "waiting"
                    else:
                        s["hold_until"] = None
                        state = "off"
                physical = ({"dirty_racks": int(s["level"]), "job_remaining_min": s["remaining"]} if dw else
                            {"ice_level_pct": half_up(s["level"]), "job_remaining_min": s["remaining"]})
            pk = rnd(power, 2)
            self.pw[i] = pk
            self.states[i] = state
            self.phys[i] = physical
            total += pk
        if shortfalls:
            room = st["_room"]
            short = sum(x for x, _ in shortfalls) / len(shortfalls)
            sp = shortfalls[0][1]
            room["temp"] += ROOM_GAIN * short if short > 0 else -0.03 * (room["temp"] - sp)
            t_in = rnd(room["temp"], 1)
            for i, d in enumerate(DEVICES):
                if d["power_model"] == "thermal":
                    self.phys[i] = {"indoor_temp_c": t_in}
        return rnd(total, 2)

    def devices(self):
        out = []
        for i, d in enumerate(DEVICES):
            dev = {"device_id": d["device_id"], "type_id": d["type_id"], "name": d["name"], "importance": d["importance"],
                   "state": self.states[i], "power_kw": self.pw[i], "rated_kw": d["rated_kw"],
                   "power_pct": half_up(100 * self.pw[i] / d["rated_kw"]), "source": "simulated"}
            if self.phys[i] is not None:
                dev["physical"] = dict(self.phys[i])
            out.append(dev)
        return out


# ----------------------------------------------------------------------------- fake 2-month history (G59)
HISTORY_DATASET_ID = "fixture_synthetic_demo_cafe_v1"


def build_history():
    """Per-device 15-min averages of the Demo Cafe running uncontrolled, 2026-05-17 00:00 -> 2026-07-17 17:30 local."""
    sim = Sim(initial_state(SEED + 2))
    rng = random.Random(SEED + 3)
    acc = [0.0] * ND
    blocks, totals = [], []
    t, m = HIST_START, 0
    one = timedelta(minutes=1)
    surges = []
    for d in HIST_DATES:
        for s in DAILY[d]["surges"]:
            s0 = utc_of_local(d, hm(s["start_local"]))
            surges.append((s0, s0 + timedelta(minutes=s["duration_min"]), s["customers"]))
    while t < START:
        d = ldate(t)
        open_ = is_open(t)
        cph = 0
        if open_:
            cph = max(0, half_up(base_cph(t) * CROWD[DAILY[d]["crowd_effect"]] + rng.gauss(0, 2.0)))
            cph += sum(c for a, b, c in surges if a <= t < b)
        sim.step(m, t, cph, temp_at(t), open_)
        for i in range(ND):
            acc[i] += sim.pw[i]
        m += 1
        t += one
        if m % 15 == 0:
            bs = t - timedelta(minutes=15)
            tot = 0.0
            for i, dv in enumerate(DEVICES):
                a = rnd(acc[i] / 15, 3)
                blocks.append({"block_start": iso(bs), "device_id": dv["device_id"], "avg_kw": a})
                tot += a
                acc[i] = 0.0
            totals.append((bs, tot))
    hist = {"source": "fixture_synthetic", "label": "simulated", "dataset_id": HISTORY_DATASET_ID, "scale": 1.0,
            "day_offset": 0, "start": iso(HIST_START), "end": iso(START), "blocks": blocks, "month_to_date": None}
    return hist, totals


def history_meter_init(totals):
    """What the engine meters from the history blocks of the current month (month_to_date null): the run's starting Meter."""
    day, month = ldate(START - timedelta(minutes=1)), (2026, 7)
    peaks = {c["name"]: 0.0 for c in TC.charges}
    month_peak = 0.0
    peaks_mid = None
    days = set()
    e_today = c_today = e_month = c_month = 0.0
    for bs, tot in totals:
        d = ldate(bs)
        if (d.year, d.month) != month:
            continue
        if d == day and peaks_mid is None:
            peaks_mid = dict(peaks)
        days.add(d)
        e = tot * 0.25
        c = e * tariff_price(bs)
        e_month += e
        c_month += c
        if d == day:
            e_today += e
            c_today += c
        month_peak = max(month_peak, tot)
        for ch in TC.applicable(d.month):
            if TC.counts(ch, bs):
                peaks[ch["name"]] = max(peaks[ch["name"]], tot)
    return {"day": day, "month": month, "energy_today": e_today, "ecost_today": c_today, "energy_month": e_month,
            "ecost_month": c_month, "peaks": peaks, "month_peak": month_peak,
            "peaks_midnight": peaks_mid if peaks_mid is not None else dict(peaks),
            "fixed_days": len(days)}


# ----------------------------------------------------------------------------- recorded context (Fetch agents, demo mode)
def context_post_ticks(n_ticks):
    ticks = [1, 61]
    t = 61 + CONTEXT_REFRESH_MIN
    while t <= n_ticks:
        ticks.append(t)
        t += CONTEXT_REFRESH_MIN
    return [x for x in ticks if x <= n_ticks]


def make_context(post_n):
    dt = sim_dt(post_n)
    x = loc(dt)
    d0, h0 = x.date(), x.hour
    hours = [(d0 + timedelta(days=(h0 + i) // 24), (h0 + i) % 24) for i in range(6)]
    hours = [(d, h) for d, h in hours if d in DAILY]        # the last post of a 7-day run stops at the calendar's end
    di = DAILY[d0]
    events = copy.deepcopy(di["events"])
    crowd = di["crowd_effect"]
    return {
        "ts": iso(dt),
        "weather": {"label": "recorded", "source": "open-meteo",
                    "hourly": [{"ts": iso(utc_of_local(d, h * 60)), "temp_c": DAILY[d]["hourly_outdoor_temp_c"][h]}
                               for d, h in hours]},
        "prices": {"label": "recorded", "source": "caiso",
                   "hourly": [{"ts": iso(utc_of_local(d, h * 60)), "usd_per_kwh": DAILY[d]["hourly_grid_usd_per_kwh"][h]}
                              for d, h in hours], "stress": di["price_stress"]},
        "events": {"label": "recorded", "source": "demo_events", "items": events},
        "crowd_effect": {"value": crowd, "set_by": "claude" if events else "default",
                         "reason": CROWD_REASON.get(d0, "No events nearby")},
    }


def ctx_hourly(ctx, section, key, dt):
    h = iso(dt.replace(minute=0, second=0))
    for row in ctx[section]["hourly"]:
        if row["ts"] == h:
            return row[key]
    raise KeyError("context %s has no hour %s" % (ctx["ts"], h))


def agent_logs(tick, ctx):
    base = real_dt(tick - 1)
    items = ctx["events"]["items"]
    rows = [("concierge", "weather", "request", "Forecast 6 h for 37.80,-122.44"),
            ("weather", "concierge", "response", "6 hourly temperatures (recorded)"),
            ("concierge", "grid", "request", "Prices 6 h for caiso_np15"),
            ("grid", "concierge", "response", "6 hourly prices, stress %s (recorded)" % ctx["prices"]["stress"]),
            ("concierge", "events", "request", "Events within 5 km in the next 12 h"),
            ("events", "concierge", "response", ("%d event: %s" % (len(items), items[0]["name"])) if items else "0 events"),
            ("concierge", "claude", "request", "Classify crowd effect for %d event%s" % (len(items), "" if len(items) == 1 else "s")),
            ("claude", "concierge", "response", "crowd_effect %s" % ctx["crowd_effect"]["value"]),
            ("concierge", "engine", "post", "Context posted to /api/context")]
    return [{"ts_real": iso_ms(base + timedelta(milliseconds=40 * (i + 1))), "from_agent": f, "to_agent": t, "kind": k,
             "summary": s} for i, (f, t, k, s) in enumerate(rows)]


# ----------------------------------------------------------------------------- meter (engine-style, per lane)
def demand_peaks_of(peaks, month):
    """Meter `demand_peaks`: every charge that applies this month, tariff order; cost on the published (0.01 kW) peak."""
    return [{"name": c["name"], "peak_kw": rnd(peaks[c["name"]], 2), "usd_per_kw": c["rate"],
             "cost_usd": rnd(c["rate"] * rnd(peaks[c["name"]], 2), 2)} for c in TC.applicable(month)]


class LaneMeter:
    """Engine-style meter for one lane (ENGINE.md section 1): one month peak per demand charge, any number of charges."""

    def __init__(self, init):
        self.day, self.month = init["day"], init["month"]
        self.e_today, self.c_today = init["energy_today"], init["ecost_today"]
        self.e_month, self.c_month = init["energy_month"], init["ecost_month"]
        self.peaks = dict(init["peaks"])
        self.month_peak = init["month_peak"]
        self.peaks_mid = dict(init["peaks_midnight"])
        self.fixed_days = init["fixed_days"]             # local days of this month already metered (fixed charges per day)
        self.bk, self.bsum, self.bn = None, 0.0, 0

    def step(self, n, total):
        dt = sim_dt(n)
        d = ldate(dt)                       # the day / month of the minute just metered
        if d != self.day:
            if (d.year, d.month) != self.month:
                self.month = (d.year, d.month)
                self.e_month = self.c_month = 0.0
                self.peaks = {k: 0.0 for k in self.peaks}
                self.month_peak = 0.0
                self.fixed_days = 0
            self.day = d
            self.e_today = self.c_today = 0.0
            self.peaks_mid = dict(self.peaks)
            self.fixed_days += 1
        e = total / 60
        c = e * tariff_price(dt)
        self.e_today += e
        self.e_month += e
        self.c_today += c
        self.c_month += c
        k = block_index(n)
        if k != self.bk:
            self.bk, self.bsum, self.bn = k, 0.0, 0
        self.bsum += total
        self.bn += 1
        avg = self.bsum / self.bn
        mo = self.month[1]
        if n % 15 == 0:                     # ts reaches block_start + 15: the block closes
            bs = block_start_dt(k)
            self.month_peak = max(self.month_peak, avg)
            for ch in TC.applicable(mo):
                if TC.counts(ch, bs):
                    self.peaks[ch["name"]] = max(self.peaks[ch["name"]], avg)
        dps = demand_peaks_of(self.peaks, mo)
        demand_today = sum(c_["rate"] * (rnd(self.peaks[c_["name"]], 2) - rnd(self.peaks_mid[c_["name"]], 2))
                           for c_ in TC.applicable(mo))
        demand_month = sum(c_["rate"] * rnd(self.peaks[c_["name"]], 2) for c_ in TC.applicable(mo))
        fixed_today = TC.fixed_day + (TC.fixed_month if d.day == 1 else 0.0)
        fixed_month = TC.fixed_day * self.fixed_days + TC.fixed_month
        op = TC.on_peak_name(mo)
        return {"ts": iso(rep_dt(n)), "total_kw": total, "block_avg_kw": rnd(avg, 2), "block_start": iso(block_start_dt(k)),
                "month_peak_kw": rnd(self.month_peak, 2),
                "on_peak_month_peak_kw": None if op is None else rnd(self.peaks[op], 2),
                "peak_mode": "cap", "peak_cap_kw": CAP, "target_kw": CAP,
                "energy_kwh_today": rnd(self.e_today, 3), "energy_kwh_month": rnd(self.e_month, 3),
                "price_usd_per_kwh_now": tariff_price(rep_dt(n)),
                "cost_usd_today": rnd(self.c_today + demand_today + fixed_today, 2),
                "cost_usd_month": rnd(self.c_month + demand_month + fixed_month, 2),
                "demand_peaks": dps}


def meter_peaks(m):
    """{charge name: month peak so far} from a Meter (what a plan must not beat)."""
    return {dp["name"]: dp["peak_kw"] for dp in m["demand_peaks"]}


# ----------------------------------------------------------------------------- forecasting (toy stand-in for the forecaster)
class Forecast:
    __slots__ = ("k0", "blocks", "r1", "totals", "dev_avg", "job_start")


def cph_known(now, t, mult):
    dt = sim_dt(t)
    if not is_open(dt):
        return 0
    c = half_up(base_cph(dt) * mult)
    for s in LIVE_SURGES:
        if s["request_tick"] <= now and s["start_tick"] <= t < s["start_tick"] + s["duration_min"]:
            c += s["customers"]
    return c


def forward(lane, n, plan, mult):
    """Re-simulate a copy of the lane from the state after tick n with a plan {deliver_tick: [cmd]}; 8 blocks from n + 1."""
    sim = lane.sim.clone()
    k0 = block_index(n + 1)
    end = max(15 * (k0 + 8), n + 120)
    totals = {}
    dsum = [[0.0] * ND for _ in range(8)]
    job_start = {}
    for t in range(n + 1, end + 1):
        dt = sim_dt(t)
        for c in plan.get(t, ()):
            sim.apply(c, t - 1)
        totals[t] = sim.step(t - 1, dt, cph_known(n, t, mult), temp_at(dt), is_open(dt))
        j = block_index(t) - k0
        if j < 8:
            row = dsum[j]
            for i in range(ND):
                row[i] += sim.pw[i]
        for dev in JOBS:
            if dev not in job_start and sim.states[IDX[dev]] == "running_job":
                job_start[dev] = t
    f = Forecast()
    f.k0, f.totals, f.job_start = k0, totals, job_start
    f.blocks, f.dev_avg = [], []
    for j in range(8):
        k = k0 + j
        s = 0.0
        row = list(dsum[j])
        for t in block_ticks(k):
            if t <= n:
                s += lane.totals[t]
                for i in range(ND):
                    row[i] += lane.devpow[t][i]
            else:
                s += totals[t]
        f.blocks.append(s / 15)
        f.dev_avg.append([x / 15 for x in row])
    f.r1 = [rnd(b, 1) for b in f.blocks]
    return f


def plan_cost(f, n, peaks, blocks=None):
    """cost(x) = sum_c rate_c x max(peak_c(x), month_peak_c) + energy cost over the 2 h horizon (ENGINE.md section 5)."""
    b = f.r1 if blocks is None else blocks
    dem = 0.0
    for c in TC.applicable(ldate(block_start_dt(f.k0)).month):
        pk = max([b[j] for j in range(8) if TC.counts(c, block_start_dt(f.k0 + j))] or [0.0])
        dem += c["rate"] * max(pk, peaks[c["name"]])
    return dem + sum(f.totals[t] / 60 * tariff_price(sim_dt(t)) for t in range(n + 1, n + 121))


def effect_of(before, after, n, peaks):
    return {"peak_before_kw": max(before.r1), "peak_after_kw": max(after.r1),
            "saving_usd": rnd(plan_cost(before, n, peaks) - plan_cost(after, n, peaks), 2)}


# ----------------------------------------------------------------------------- escalation helpers
def harm_of(breaks):
    h = 0.0
    for b in breaks:
        k = b["kind"]
        if k == "cap_overrun":
            tol = AUTHORITY["max_cap_overrun_kw"] or AUTH_REFERENCE["kW"]
        elif k in ("past_deadline", "over_max_delay"):
            tol = AUTHORITY["max_extra_delay_min"] or AUTH_REFERENCE["delay"]
        elif k == "over_max_reduce":
            tol = AUTHORITY["max_extra_reduce_min"] or AUTH_REFERENCE["reduce"]
        else:
            dv = DEV[b["device_id"]]
            tol = dv["limits"]["min_power_pct"] - (50 if dv["category"] == "refrigeration" else 0)
        h += b["amount"] / tol
    return rnd(h, 3)


def within_authority(breaks):
    if not AUTHORITY["enabled"]:
        return False
    for b in breaks:
        if b["kind"] == "cap_overrun" and b["amount"] > AUTHORITY["max_cap_overrun_kw"]:
            return False
        if b["kind"] == "below_min_power" and not AUTHORITY["may_go_below_min_power"]:
            return False
        if b["kind"] in ("past_deadline", "over_max_delay") and b["amount"] > AUTHORITY["max_extra_delay_min"]:
            return False
        if b["kind"] == "over_max_reduce" and b["amount"] > AUTHORITY["max_extra_reduce_min"]:
            return False
    return True


def deadline_minute(n, dev):
    """Effective deadline min(must_finish_by, close), local today, as a minute index from START."""
    today = ldate(rep_dt(n))
    lm = min(hm(DEV[dev]["limits"]["must_finish_by"]), CLOSE_M)
    return int((utc_of_local(today, lm) - START).total_seconds() // 60)


def problem_reason(n):
    dt = rep_dt(n)
    lm = lmin(dt)
    parts = ["lunch rush" if lm < 15 * 60 else "dinner rush" if lm < CLOSE_M else "closed-hours load"]
    if any(s["request_tick"] <= n < s["start_tick"] + s["duration_min"] for s in LIVE_SURGES):
        parts.append("customer surge")
    if temp_at(dt) >= 27:
        parts.append("hot evening" if lm >= 17 * 60 else "hot day")
    return " + ".join(parts)


def best_option(picks, holds_, peak_of, base_peak):
    """One best alternative: the lowest harm among those that hold the target, else the lowest peak."""
    picks = [p for p in picks if p is not None]
    if not picks:
        return None
    holding = [p for p in picks if holds_(p["fc"])]
    if holding:
        return min(holding, key=lambda p: (harm_of(p["breaks"]), peak_of(p["fc"]), p["option_id"]))
    return min(picks, key=lambda p: (peak_of(p["fc"]), harm_of(p["breaks"]), p["option_id"]))


def explain(dec):
    name = DEV[dec["device_id"]]["name"]
    e = dec["effect"]
    arrow = "(%.1f → %.1f kW)" % (e["peak_before_kw"], e["peak_after_kw"])
    a, v, r = dec["action"], dec["value"], dec["reason_code"]
    what = {"delay": "Delayed %s %s min" % (name, v), "reduce": "Reduced %s to %s %%" % (name, v),
            "restore": "Restored %s to normal power" % name, "start": "Started %s" % name,
            "on": "Turned %s on" % name, "off": "Turned %s off" % name}[a]
    why = {"stay_under_cap": "to stay under the cap", "avoid_new_peak": "to avoid a new peak",
           "catch_up": "to repay its energy", "release_into_valley": "into a quieter block",
           "owner_override": "as the owner asked", "escalation_fallback": "as the escalation's safe default",
           "escalation_choice": "as the escalation option chosen"}[r]
    return "%s %s %s." % (what, why, arrow)


# ----------------------------------------------------------------------------- toy controller (stands in for the engine, with lane)
class ToyEngine:
    def __init__(self, run):
        self.run = run
        self.reduced = {}     # dev -> {"first": issue tick, "value": pct, "due": restore decision tick}
        self.cooldown = {}    # dev -> first tick a new reduce may start
        self.holds = {}       # dev -> {"first_m": minute the first delay applied, "release_m": minute, "issued": tick}
        self.protected = {}   # dev -> tick until which the engine leaves it alone (owner action)
        self.esc_blocks = set()
        self.warned_blocks = set()
        self.active = {}      # escalation_id -> latest object (open)
        self.esc_prev = {}    # escalation_id -> {dev: state before the fallback} (to move devices on a switch)
        self.esc_acts = {}    # escalation_id -> {option_id: (acts, restores, holds)}
        self.switch = None    # pending escalation_choice commands for the next step
        self.active_cmds = {} # dev -> Command in force (snapshot active_commands)
        self.owed = {d: 0.0 for d in FLEX}
        self.issued = {}      # command_id -> Command

    # ---- bookkeeping from the HubReport
    def on_report(self, n, reports, acks):
        lane = self.run.lanes["with"]
        for a in acks:
            if a["lane"] != "with":
                continue
            c = self.issued.get(a["command_id"])
            if c is None:
                continue
            dev = c["device_id"]
            if a["ok"]:
                if c["action"] == "reduce":
                    self.active_cmds[dev] = c
                    if dev in self.reduced:
                        self.reduced[dev]["value"] = a["applied_value"]
                elif c["action"] == "restore" or c["action"] == "start":
                    self.active_cmds.pop(dev, None)
                elif c["action"] == "delay":
                    if c["value"] > 0:
                        self.active_cmds[dev] = c
                    else:
                        self.active_cmds.pop(dev, None)
            else:
                if c["action"] == "reduce":
                    self.reduced.pop(dev, None)
                if c["action"] in ("delay", "start"):
                    self.holds.pop(dev, None)
        for dev in JOBS:
            st = lane.sim.states[IDX[dev]]
            h = self.holds.get(dev)
            if h is not None and n > h["issued"] + 1 and st != "waiting":
                self.holds.pop(dev)
            ac = self.active_cmds.get(dev)
            if ac is not None and ac["action"] == "delay" and st != "waiting" and tick_at(datetime.strptime(
                    ac["ts"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)) + 1 < n:
                self.active_cmds.pop(dev)
        wo = self.run.lanes["without"].sim
        for dev in FLEX:
            i = IDX[dev]
            act, exp = lane.sim.pw[i], wo.pw[i]
            if lane.sim.states[i] == "reduced":
                self.owed[dev] += max(0.0, exp - act) / 60
            else:
                self.owed[dev] = max(0.0, self.owed[dev] - max(0.0, act - exp) / 60)

    # ---- plan helpers
    def plan(self, n, moves, restores):
        p = {}
        for mv in moves:
            p.setdefault(mv.get("at", n + 1), []).append({"command_id": "x", "lane": "with", "device_id": mv["device_id"],
                                                          "action": mv["action"], "value": mv["value"]})
        for dev, due in sorted(restores.items()):
            if due is not None and due > n:
                p.setdefault(due + 1, []).append({"command_id": "x", "lane": "with", "device_id": dev, "action": "restore",
                                                  "value": None})
        return p

    def fc(self, n, moves, restores):
        return forward(self.run.lanes["with"], n, self.plan(n, moves, restores), self.run.mult_at(n))

    def is_protected(self, dev, n):
        return self.protected.get(dev, -1) > n

    # ---- issuing
    def issue(self, n, mv, reason, inside, eff, out):
        run = self.run
        cid, did = run.next_id("c"), run.next_id("d")
        ts = iso(rep_dt(n))
        dec = {"decision_id": did, "ts": ts, "device_id": mv["device_id"], "action": mv["action"], "value": mv["value"],
               "reason_code": reason, "inside_rules": inside, "status": "executed", "effect": eff}
        cmd = {"command_id": cid, "lane": "with", "ts": ts, "device_id": mv["device_id"], "action": mv["action"],
               "value": mv["value"], "decision_id": did, "issued_by": "engine"}
        self.issued[cid] = cmd
        out["decisions"].append(dec)
        out["commands"].append(cmd)
        run.register(dec, cmd, "with")
        return dec, cmd

    def track(self, n, mv, due=None):
        dev, a = mv["device_id"], mv["action"]
        if a == "reduce":
            r = self.reduced.get(dev)
            if r is None:
                lim = DEV[dev]["limits"]
                self.reduced[dev] = {"first": n, "value": mv["value"],
                                     "due": due if due is not None else n + 5 * (lim["max_reduce_min"] // 5)}
            else:
                r["value"] = mv["value"]
                if due is not None:
                    r["due"] = due
        elif a == "restore":
            if dev in self.reduced:
                self.reduced.pop(dev)
                self.cooldown[dev] = n + DEV[dev]["limits"]["max_reduce_min"]
        elif a == "delay":
            h = self.holds.get(dev)
            if mv["value"] == 0:
                self.holds.pop(dev, None)
            elif h is None:
                self.holds[dev] = {"first_m": n, "release_m": n + mv["value"], "issued": n}
            else:
                h["release_m"], h["issued"] = n + mv["value"], n

    # ---- one step of the with lane
    def step(self, n, meter):
        out = {"decisions": [], "commands": [], "escalations": [], "warnings": [], "forecast": None}
        peaks = meter_peaks(meter)
        if self.switch is not None:
            sw, self.switch = self.switch, None
            before = self.fc(n, [], self.restores())
            done = []
            for mv, due in sw["moves"]:
                after = self.fc(n, [m for m, _ in done] + [mv], self.restores_with(done + [(mv, due)]))
                self.issue(n, mv, "escalation_choice", sw["inside"], effect_of(before, after, n, peaks), out)
                done.append((mv, due))
                self.track(n, mv, due)
                before = after
        if n % REPLAN_EVERY == 0:
            self.expire(n, out)
            self.decide(n, peaks, out)
        return out

    def restores(self):
        return {d: r["due"] for d, r in self.reduced.items()}

    def restores_with(self, pairs):
        r = self.restores()
        for mv, due in pairs:
            if mv["action"] == "restore":
                r.pop(mv["device_id"], None)
            elif mv["action"] == "reduce" and mv["device_id"] not in r:
                r[mv["device_id"]] = due if due is not None else None
        return r

    def expire(self, n, out):
        ts = rep_dt(n)
        for eid in sorted(self.active):
            e = self.active[eid]
            dl = datetime.strptime(e["deadline_sim_ts"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
            if ts >= dl:
                e = dict(copy.deepcopy(e), status="expired_default", resolved_by="default", updated_ts=iso(ts))
                self.active.pop(eid)
                self.run.esc_latest[eid] = e
                out["escalations"].append(e)

    def near(self, f, n):
        lim = rep_dt(n) + timedelta(minutes=30)
        return [j for j in range(8) if block_start_dt(f.k0 + j) < lim]

    def decide(self, n, peaks, out):
        target = CAP
        ts = rep_dt(n)
        open_now = is_open(ts)
        moves = []
        due_now = sorted(d for d, r in self.reduced.items() if r["due"] <= n)
        rest = {d: r["due"] for d, r in self.reduced.items() if r["due"] > n}
        f = self.fc(n, [], rest)
        # 1. restores at their time limit
        for dev in due_now:
            mv = {"device_id": dev, "action": "restore", "value": None}
            after = self.fc(n, moves + [mv], rest)
            self.issue(n, mv, "catch_up", True, effect_of(f, after, n, peaks), out)
            moves.append(mv)
            self.track(n, mv)
            f = after
        # 2. restores no longer needed
        for dev in sorted(rest):
            mv = {"device_id": dev, "action": "restore", "value": None}
            r2 = {d: x for d, x in rest.items() if d != dev}
            trial = self.fc(n, moves + [mv], r2)
            if max(trial.blocks) <= target - PLAN_MARGIN_KW:
                self.issue(n, mv, "catch_up", True, effect_of(f, trial, n, peaks), out)
                moves.append(mv)
                self.track(n, mv)
                rest, f = r2, trial
        near = self.near(f, n)
        # 3. holds and reductions (now, or planned for a near block's start: part of the desired state, issued when that
        #    block begins), best improvement first against the excess over the 2 h horizon (catch-up included)
        for _ in range(6):
            if not open_now or self.objective(f, near)[0] <= 0 and max(f.blocks) <= target - PLAN_MARGIN_KW:
                break
            best = None
            for mv, due in self.candidates(n, f, moves, rest, near):
                r2 = dict(rest)
                if mv["action"] == "reduce" and mv["device_id"] not in r2:
                    r2[mv["device_id"]] = due
                trial = self.fc(n, moves + [mv], r2)
                key = self.objective(trial, near)
                if best is None or key < best[0]:
                    best = (key, mv, trial, due)
            if best is None or not best[0] < self.objective(f, near):
                break
            _, mv, trial, due = best
            if mv["action"] == "reduce" and mv["device_id"] not in rest:
                rest[mv["device_id"]] = due
            if mv.get("at", n + 1) == n + 1:
                self.issue(n, mv, "stay_under_cap", True, effect_of(f, trial, n, peaks), out)
                self.track(n, mv, due)
            moves.append(mv)
            f = trial
        # 4. cap_unreachable (once per block) and escalation for a block still over the target
        for j in near:
            u = self.unavoidable(n, f, j)
            k = f.k0 + j
            if u > target and k not in self.warned_blocks:
                self.warned_blocks.add(k)
                out["warnings"].append({"code": "cap_unreachable",
                                        "message": "Even with every allowed move the kitchen needs %.1f kW in the %s block. "
                                                   "Raise the cap or change an importance."
                                                   % (u, hm_str(lmin(block_start_dt(k)))),
                                        "data": {"unavoidable_kw": rnd(u, 1), "peak_cap_kw": CAP, "target_kw": target}})
        over = [j for j in near if f.r1[j] > target and block_start_dt(f.k0 + j) not in self.esc_blocks]
        if over:
            f = self.open_escalation(n, f, moves, rest, over[0], peaks, out)
        out["forecast"] = f.r1

    @staticmethod
    def objective(f, near):
        lim = CAP - PLAN_MARGIN_KW
        return (rnd(max(0.0, max(f.blocks[j] for j in near) - lim), 3), rnd(max(0.0, max(f.blocks) - lim), 3),
                rnd(sum(max(0.0, b - lim) for b in f.blocks), 3))

    def candidates(self, n, f, moves, rest, near):
        """In-rules moves: holds of jobs expected in the horizon, reductions now or at the start of a near block."""
        out = []
        moved = {m["device_id"] for m in moves}
        sim = self.run.lanes["with"].sim
        for dev in sorted(JOBS):
            if self.is_protected(dev, n) or dev in moved or sim.states[IDX[dev]] == "running_job":
                continue
            js = f.job_start.get(dev)
            if js is None:
                continue
            lim, cycle = DEV[dev]["limits"], DEV[dev]["params"]["cycle_min"]
            first_m = self.holds[dev]["first_m"] if dev in self.holds else n
            dl = deadline_minute(n, dev)
            for jj in range(0, 8):
                r_m = 15 * (f.k0 + jj)
                if r_m <= js - 1:
                    continue
                if r_m - first_m > lim["max_delay_min"] or r_m + cycle > dl:
                    break
                out.append(({"device_id": dev, "action": "delay", "value": r_m - n}, None))
        for j in near:
            at = n + 1 if j == 0 else 15 * (f.k0 + j) + 1
            issue_t = at - 1
            lm = lmin(rep_dt(issue_t))
            for dev in FLEX:
                if self.is_protected(dev, issue_t) or dev in moved or issue_t < self.cooldown.get(dev, -1):
                    continue
                d = DEV[dev]
                lim, rated = d["limits"], d["rated_kw"]
                r = self.reduced.get(dev)
                if r is not None and (r["due"] < at or at > n + 1):
                    continue
                if r is None and (not is_open(rep_dt(issue_t)) or lm + lim["max_reduce_min"] > CLOSE_M):
                    continue
                avg = f.dev_avg[j][IDX[dev]]
                cur = r["value"] if r else 100
                if min(avg, cur / 100 * rated) - lim["min_power_pct"] / 100 * rated <= 0.1:
                    continue
                excess = f.blocks[j] - (CAP - PLAN_MARGIN_KW)
                need = max(lim["min_power_pct"], ceil_int(100 * max(0.0, avg - max(excess, 0.0)) / rated))
                need = min(100, 5 * ceil_int(need / 5))
                if need > 85:
                    need = lim["min_power_pct"]      # a token reduction is not worth a command
                due = r["due"] if r else issue_t + 5 * (lim["max_reduce_min"] // 5)
                for v in sorted({lim["min_power_pct"], need}):
                    if v < cur:
                        mv = {"device_id": dev, "action": "reduce", "value": v}
                        if at > n + 1:
                            mv["at"] = at
                        out.append((mv, due))
        return out

    def unavoidable(self, n, f, j):
        u = 0.0
        for dev in ALWAYS:
            u += f.dev_avg[j][IDX[dev]]
        for dev in FLEX:
            lim = DEV[dev]["limits"]
            u += min(f.dev_avg[j][IDX[dev]], lim["min_power_pct"] / 100 * DEV[dev]["rated_kw"])
        k = f.k0 + j
        sim = self.run.lanes["with"].sim
        for dev in JOBS:
            s = sim.st[dev]
            if s["remaining"] > 0:
                ticks = [t for t in block_ticks(k) if n < t <= n + s["remaining"]]
                u += DEV[dev]["rated_kw"] * len(ticks) / 15
        return u

    def try_hold(self, n, f, j, moves, rest, near):
        if not is_open(rep_dt(n)):
            return None
        target = CAP - PLAN_MARGIN_KW
        k = f.k0 + j
        moved = {m["device_id"] for m in moves}
        sim = self.run.lanes["with"].sim
        for dev in sorted(JOBS):
            if self.is_protected(dev, n) or dev in moved or sim.states[IDX[dev]] == "running_job":
                continue
            js = f.job_start.get(dev)
            cycle = DEV[dev]["params"]["cycle_min"]
            if js is None or not (block_index(js) <= k <= block_index(js + cycle - 1)):
                continue
            lim = DEV[dev]["limits"]
            first_m = self.holds[dev]["first_m"] if dev in self.holds else n
            dl = deadline_minute(n, dev)
            for jj in range(j + 1, 8):
                r_m = 15 * (f.k0 + jj)
                if r_m - first_m > lim["max_delay_min"] or r_m + cycle > dl:
                    break
                mv = {"device_id": dev, "action": "delay", "value": r_m - n}
                trial = self.fc(n, moves + [mv], rest)
                span = [x for x in range(jj, 8) if f.k0 + x <= block_index(r_m + cycle)]
                if max(trial.blocks[x] for x in near) < max(f.blocks[x] for x in near) - 0.05 and \
                        all(trial.blocks[x] <= target for x in span):
                    return mv, trial, None
        return None

    def try_reduce(self, n, f, j, moves, rest, at):
        """Largest reducible kW first; `at` = tick the reduce is delivered (n + 1 now, or the block's first tick)."""
        target = CAP - PLAN_MARGIN_KW
        issue_t = at - 1
        moved = {m["device_id"] for m in moves}
        lm = lmin(rep_dt(issue_t))
        cands = []
        for dev in FLEX:
            if self.is_protected(dev, issue_t) or dev in moved or issue_t < self.cooldown.get(dev, -1):
                continue
            d = DEV[dev]
            lim, rated = d["limits"], d["rated_kw"]
            r = self.reduced.get(dev)
            if r is not None and r["due"] < at:
                continue                    # restored before that block starts: cooldown applies
            if r is None and (not is_open(rep_dt(issue_t)) or lm + lim["max_reduce_min"] > CLOSE_M):
                continue                    # no new reduce while closed or in the last max_reduce_min before close
            floor_kw = lim["min_power_pct"] / 100 * rated
            avg = f.dev_avg[j][IDX[dev]]
            cur = (r["value"] if r else 100)
            reducible = min(avg, cur / 100 * rated) - floor_kw
            if reducible > 0.1:
                cands.append((-round(reducible, 6), dev, avg, cur))
        for _, dev, avg, cur in sorted(cands):
            d = DEV[dev]
            lim, rated = d["limits"], d["rated_kw"]
            excess = f.blocks[j] - target
            new_kw = max(lim["min_power_pct"] / 100 * rated, avg - excess)
            v = max(lim["min_power_pct"], ceil_int(100 * new_kw / rated))
            if v >= cur:
                continue
            mv = {"device_id": dev, "action": "reduce", "value": v}
            if at > n + 1:
                mv["at"] = at
            due = self.reduced[dev]["due"] if dev in self.reduced else issue_t + 5 * (lim["max_reduce_min"] // 5)
            r2 = dict(rest)
            r2[dev] = due
            trial = self.fc(n, moves + [mv], r2)
            # lowers this block without pushing the 2 h peak up (the restore's catch-up is in the forecast)
            if trial.blocks[j] < f.blocks[j] - 0.05 and max(trial.blocks) <= max(max(f.blocks), target) + 0.05:
                return mv, trial, due
        return None

    # ---- escalation
    def open_escalation(self, n, f, moves, rest, j, peaks, out):
        run = self.run
        target = CAP
        ts = rep_dt(n)
        k = f.k0 + j
        bs = block_start_dt(k)
        end_tick = 15 * (k + 1)
        self.esc_blocks.add(bs)
        held_blocks = list(f.r1)
        held_blocks[j] = min(held_blocks[j], target)
        base_cost = plan_cost(f, n, peaks, held_blocks)
        now_moves = [m for m in moves if m.get("at", n + 1) == n + 1]

        def without_planned(devs):
            return [m for m in moves if not (m.get("at", n + 1) > n + 1 and m["device_id"] in devs)]

        def opt_peak(fc_):
            """The problem block, plus any later block the option changes (displaced load)."""
            return max([fc_.r1[j]] + [fc_.r1[x] for x in range(j + 1, 8) if abs(fc_.r1[x] - f.r1[x]) > 0.05])

        def capb(fc_):
            pk = opt_peak(fc_)
            return [{"kind": "cap_overrun", "amount": rnd(pk - target, 1), "unit": "kW"}] if pk > target else []

        def holds_(fc_):
            return opt_peak(fc_) <= target

        cands = [{"option_id": "accept_overrun", "acts": [], "fc": f, "breaks": capb(f), "rest": rest, "holds": {},
                  "summary": "Let the peak reach %.1f kW for one block" % f.r1[j]}]
        until = hm_str(lmin(block_start_dt(k + 1)))
        # deep_reduce_<type>: that type's flexible devices past max_reduce_min and/or below min_power_pct, least first
        deep = []
        for T in sorted({DEV[d]["type_id"] for d in FLEX}):
            devs = [d for d in FLEX if DEV[d]["type_id"] == T and not self.is_protected(d, n)]
            if not devs:
                continue
            variants = []
            red = [d for d in devs if d in self.reduced and rest.get(d, n) < end_tick]
            if red:                                       # keep current reductions through the problem block
                variants.append([(d, self.reduced[d]["value"]) for d in red])
            minp = DEV[devs[0]]["limits"]["min_power_pct"]
            floor_ = 50 if DEV[devs[0]]["category"] == "refrigeration" else MIN_PHYSICAL_PCT
            active = [d for d in devs if f.dev_avg[j][IDX[d]] > 0.1]
            for v in range(minp - 5, floor_ - 1, -5):     # never generated below 50 % for refrigeration
                if active:
                    variants.append([(d, v) for d in active])
            picks = []
            for var in variants:
                acts = [{"device_id": d, "action": "reduce", "value": v} for d, v in var]
                r2 = dict(rest)
                breaks = []
                for d, v in var:
                    lim = DEV[d]["limits"]
                    first = self.reduced[d]["first"] if d in self.reduced else n
                    due = r2.get(d) or n + 5 * (lim["max_reduce_min"] // 5)
                    keep = max(due, end_tick)
                    r2[d] = keep
                    if v < lim["min_power_pct"]:
                        breaks.append({"kind": "below_min_power", "device_id": d, "amount": lim["min_power_pct"] - v,
                                       "unit": "pct"})
                    if keep - first > lim["max_reduce_min"]:
                        breaks.append({"kind": "over_max_reduce", "device_id": d,
                                       "amount": keep - first - lim["max_reduce_min"], "unit": "min"})
                if not breaks:
                    continue
                trial = self.fc(n, without_planned({d for d, _ in var}) + acts, r2)
                names = " and ".join(DEV[d]["name"] for d, _ in var)
                vals = sorted({v for _, v in var})
                picks.append({"option_id": "deep_reduce_" + T, "acts": acts, "fc": trial,
                              "breaks": capb(trial) + breaks, "rest": r2, "holds": {},
                              "summary": "%s at %s %% until %s" % (names, "/".join(str(x) for x in vals), until)})
            best = best_option(picks, holds_, opt_peak, f.r1[j])
            if best is not None:
                deep.append(best)
        # extend_delay_<type>: a job past max_delay_min and/or its deadline, least first
        ext = []
        sim = run.lanes["with"].sim
        for T in sorted({DEV[d]["type_id"] for d in JOBS}):
            picks = []
            for d in [x for x in JOBS if DEV[x]["type_id"] == T]:
                if sim.states[IDX[d]] == "running_job" or self.is_protected(d, n):
                    continue
                js = f.job_start.get(d)
                if js is None:
                    continue
                lim, cycle = DEV[d]["limits"], DEV[d]["params"]["cycle_min"]
                first_m = self.holds[d]["first_m"] if d in self.holds else n
                dl = deadline_minute(n, d)
                limit_r = min(first_m + lim["max_delay_min"], dl - cycle)
                r = max(limit_r, js - 1)
                for _ in range(12):
                    r += 5
                    mv = {"device_id": d, "action": "delay", "value": r - n}
                    past, overd = max(0, r + cycle - dl), max(0, r - first_m - lim["max_delay_min"])
                    breaks = []
                    if past:
                        breaks.append({"kind": "past_deadline", "device_id": d, "amount": past, "unit": "min"})
                    if overd:
                        breaks.append({"kind": "over_max_delay", "device_id": d, "amount": overd, "unit": "min"})
                    if not breaks:
                        continue
                    trial = self.fc(n, [m for m in moves if m["device_id"] != d] + [mv], rest)
                    noun = DEV[d]["name"][:-2].lower()
                    picks.append({"option_id": "extend_delay_" + T, "acts": [mv], "fc": trial,
                                  "breaks": capb(trial) + breaks, "rest": rest, "holds": {d: (first_m, r)},
                                  "summary": ("Delay the %s %d min past its deadline" % (noun, past)) if past
                                  else "Hold the %s %d min past its max delay" % (noun, overd)})
                    if holds_(trial):
                        break
            best = best_option(picks, holds_, opt_peak, f.r1[j])
            if best is not None:
                ext.append(best)
        for group in (deep, ext):
            best = best_option(group, holds_, opt_peak, f.r1[j])
            if best is not None:
                cands.append(best)
        eid = run.next_id("e")
        options = []
        for c in cands:
            acts = [{"command_id": run.next_id("c"), "lane": "with", "ts": iso(ts), "device_id": a["device_id"],
                     "action": a["action"], "value": a["value"], "decision_id": None, "issued_by": "engine"} for a in c["acts"]]
            c["cost_delta"] = rnd(plan_cost(c["fc"], n, peaks) - base_cost, 2)
            c["harm"] = harm_of(c["breaks"])
            c["within"] = within_authority(c["breaks"])
            options.append({"option_id": c["option_id"], "summary": c["summary"], "actions": acts,
                            "projected": {"peak_kw": opt_peak(c["fc"]), "cost_delta_usd": c["cost_delta"],
                                          "max_indoor_temp_change_c": None},
                            "rule_breaks": c["breaks"], "within_authority": c["within"], "harm_score": c["harm"], "rank": None})
        order = sorted(range(len(cands)), key=lambda i: (not cands[i]["within"], cands[i]["harm"], cands[i]["cost_delta"],
                                                          len({a["device_id"] for a in cands[i]["acts"]}),
                                                          cands[i]["option_id"]))
        for r_, i in enumerate(order, 1):
            options[i]["rank"] = r_
        top = cands[order[0]]
        default = top["option_id"] if top["within"] else "accept_overrun"
        deadline = max(ts + timedelta(minutes=5), min(ts + timedelta(minutes=15), bs - timedelta(minutes=5)))
        esc = {"escalation_id": eid, "lane": "with", "ts": iso(ts), "updated_ts": iso(ts), "block_start": iso(bs),
               "problem": {"forecast_peak_kw": f.r1[j], "target_kw": target, "excess_kw": rnd(f.r1[j] - target, 1),
                           "reason": problem_reason(n)},
               "options": options, "default_option_id": default,
               "active_option_id": default,
               "deadline_sim_ts": iso(deadline), "status": "open", "resolved_by": None, "chosen_option_id": None,
               "rationale": None, "claude_attempts": []}
        self.esc_acts[eid] = {c["option_id"]: c for c in cands}
        self.esc_prev[eid] = {}
        final = f
        fallback = next(c for c in cands if c["option_id"] == default)
        final = self.apply_option(n, eid, fallback, moves, peaks, out, "escalation_fallback", f)
        self.active[eid] = esc
        run.esc_latest[eid] = esc
        out["escalations"].append(esc)
        return final

    def apply_option(self, n, eid, opt, moves, peaks, out, reason, before):
        devs = {a["device_id"] for a in opt["acts"]}
        base = [m for m in moves if not (m.get("at", n + 1) > n + 1 and m["device_id"] in devs)]
        base = [m for m in base if not (m["action"] == "delay" and m["device_id"] in devs)]
        done = []
        for a in opt["acts"]:
            d = a["device_id"]
            self.esc_prev[eid].setdefault(d, (copy.deepcopy(self.reduced.get(d)), copy.deepcopy(self.holds.get(d))))
            r2 = {x: y for x, y in opt["rest"].items()}
            after = self.fc(n, base + done + [a], r2)
            self.issue(n, a, reason, not [b for b in opt["breaks"]], effect_of(before, after, n, peaks), out)
            if a["action"] == "reduce":
                self.track(n, a, opt["rest"][d])
                self.reduced[d]["due"] = opt["rest"][d]
            else:
                self.track(n, a)
                if d in opt["holds"]:
                    self.holds[d]["first_m"] = opt["holds"][d][0]
            done.append(a)
            before = after
        return before

    def resolve(self, eid, option_id, resolved_by, rationale, n):
        """resolve_escalation(...) between step n and step n + 1 (Claude answers asynchronously)."""
        e = self.run.esc_latest[eid]
        if e["status"] != "open":
            return e
        opt = next(o for o in e["options"] if o["option_id"] == option_id)
        e = copy.deepcopy(e)
        e["updated_ts"] = iso(rep_dt(n))
        late = iso(rep_dt(n)) >= e["deadline_sim_ts"]
        accepted = opt["within_authority"] and not late
        e["claude_attempts"].append({"ts": iso(rep_dt(n)), "option_id": option_id, "accepted": accepted,
                                    "reason": "after_deadline" if late else None if accepted else "outside_authority",
                                    "rationale": rationale})
        if not accepted:
            self.active[eid] = e
        else:
            e["chosen_option_id"], e["rationale"], e["resolved_by"] = option_id, rationale, "claude"
            e["status"] = "resolved"
            self.active.pop(eid, None)
            if option_id != e["active_option_id"]:
                self.switch = self.switch_moves(eid, e["active_option_id"], option_id, opt)
                e["active_option_id"] = option_id
        self.run.esc_latest[eid] = e
        return e

    def switch_moves(self, eid, active_id, chosen_id, opt):
        chosen = self.esc_acts[eid][chosen_id]
        moves = [(a, chosen["rest"].get(a["device_id"]) if a["action"] == "reduce" else None) for a in chosen["acts"]]
        touched = {a["device_id"] for a in chosen["acts"]}
        if active_id is not None:
            for a in self.esc_acts[eid][active_id]["acts"]:
                d = a["device_id"]
                if d in touched:
                    continue
                prev_red, prev_hold = self.esc_prev[eid].get(d, (None, None))
                if DEV[d]["power_model"] == "job":
                    v = 0 if prev_hold is None else max(1, prev_hold["release_m"] - (self.run.n + 1))
                    moves.append(({"device_id": d, "action": "delay", "value": v}, None))
                elif prev_red is None:
                    moves.append(({"device_id": d, "action": "restore", "value": None}, None))
                else:
                    moves.append(({"device_id": d, "action": "reduce", "value": prev_red["value"]}, prev_red["due"]))
        return {"moves": moves, "inside": not opt["rule_breaks"]}


# ----------------------------------------------------------------------------- the run (runtime + both lanes)
class Lane:
    def __init__(self, init):
        self.sim = Sim(INIT)
        self.meter = LaneMeter(init)
        self.totals = [0.0]
        self.devpow = [None]


class Run:
    def __init__(self, n_ticks, run_days, meter_init):
        self.N, self.run_days = n_ticks, run_days
        self.lanes = {l: Lane(meter_init) for l in LANES}
        self.counters = {"d": 0, "c": 0, "e": 0}
        rng = random.Random(SEED)
        self.noise = [0.0] + [rng.gauss(0, 1.5) for _ in range(n_ticks + 10)]
        self.pending = {}
        self.posts = context_post_ticks(n_ticks)
        self.ctx_by_post = {}
        self.ctx = None
        self.recs = [None]
        self.engine = ToyEngine(self)
        self.esc_latest = {}
        self.explain = {}
        self.decisions, self.commands = [], []
        self.dec_lane = {}
        self.owner_queue = {}
        self.owner_done = False
        self.claude_done = False
        self.n = 0
        self.hooks = {}          # tick -> callable(run, n) run after the step (read-only examples)
        self.hook_out = {}

    def next_id(self, p):
        self.counters[p] += 1
        return "%s_%04d" % (p, self.counters[p])

    def register(self, dec, cmd, lane):
        self.decisions.append(dec)
        self.commands.append(cmd)
        self.dec_lane[dec["decision_id"]] = lane
        self.explain[dec["decision_id"]] = explain(dec)

    def mult_at(self, n):
        return CROWD[self.ctx["crowd_effect"]["value"]]

    def clock_after(self, n):
        last = n >= self.N
        nxt = sim_dt(n + 1)
        day_index = 1 + sum(1 for i in range(1, self.run_days) if utc_of_local(LIVE_DATES[i], OPEN_M) <= nxt)
        if last:
            return {"playing": False, "speed": SPEED, "sim_ts": iso(rep_dt(n)), "tick_id": n, "paused_reason": "run_complete",
                    "day_index": self.run_days, "run_days": self.run_days, "phase": "closed"}
        return {"playing": True, "speed": SPEED, "sim_ts": iso(rep_dt(n)), "tick_id": n, "paused_reason": None,
                "day_index": min(day_index, self.run_days), "run_days": self.run_days,
                "phase": "service" if is_open(nxt) else "overnight"}

    def owner_click(self, n, device_id, action, value):
        """Owner clicks a device after step n: owner_command() on both lanes (without first)."""
        for lane_name in LANES:
            lane = self.lanes[lane_name]
            did, cid = self.next_id("d"), self.next_id("c")
            ts = iso(rep_dt(n))
            mv = {"command_id": "x", "lane": lane_name, "device_id": device_id, "action": action, "value": value}
            mult = self.mult_at(n)
            base_plan = self.engine.plan(n, [], self.engine.restores()) if lane_name == "with" else {}
            before = forward(lane, n, base_plan, mult)
            p2 = {k: list(v) for k, v in base_plan.items()}
            p2.setdefault(n + 2, []).append(mv)
            after = forward(lane, n, p2, mult)
            peaks = meter_peaks(self.recs[n]["states"][lane_name]["meter"])
            dec = {"decision_id": did, "ts": ts, "device_id": device_id, "action": action, "value": value,
                   "reason_code": "owner_override", "inside_rules": True, "status": "executed",
                   "effect": effect_of(before, after, n, peaks)}
            cmd = {"command_id": cid, "lane": lane_name, "ts": ts, "device_id": device_id, "action": action, "value": value,
                   "decision_id": did, "issued_by": "owner"}
            self.register(dec, cmd, lane_name)
            self.owner_queue.setdefault(n + 1, {}).setdefault(lane_name, []).append((dec, cmd))
            if lane_name == "with":
                self.engine.issued[cid] = cmd
                self.engine.protected[device_id] = n + 30

    def run(self):
        for n in range(1, self.N + 1):
            self.n = n
            self.tick(n)
        return self

    def tick(self, n):
        dt = sim_dt(n)
        post = None
        if n in self.posts:
            self.ctx = make_context(n)
            post = self.ctx
            self.ctx_by_post[n] = self.ctx
        ctx = self.ctx
        open_ = is_open(dt)
        inputs = {"outdoor_temp_c": ctx_hourly(ctx, "weather", "temp_c", dt),
                  "crowd_multiplier": CROWD[ctx["crowd_effect"]["value"]], "is_open": open_}
        surges = [{"surge_id": s["surge_id"], "customers": s["customers"], "duration_min": s["duration_min"]}
                  for s in LIVE_SURGES if s["start_tick"] == n]
        cmds = self.pending.pop(n, [])
        acks = [self.lanes[c["lane"]].sim.apply(c, n - 1) for c in cmds]
        cph = 0
        if open_:
            cph = max(0, half_up(base_cph(dt) * inputs["crowd_multiplier"] + self.noise[n]))
        cph += sum(s["customers"] for s in LIVE_SURGES if s["start_tick"] <= n < s["start_tick"] + s["duration_min"])
        reports = {}
        for l in LANES:
            lane = self.lanes[l]
            total = lane.sim.step(n - 1, dt, cph, inputs["outdoor_temp_c"], open_)
            lane.totals.append(total)
            lane.devpow.append(list(lane.sim.pw))
            reports[l] = {"hub_id": "sim_hub", "lane": l, "tick_id": n, "ts": iso(rep_dt(n)), "total_kw": total,
                          "customers_per_hour": cph, "devices": lane.sim.devices(),
                          "acks": [a for a in acks if a["lane"] == l], "source": "simulated"}
        sim_tick = {"type": "sim_tick", "tick_id": n, "sim_ts": iso(dt), "minutes": 1, "surges": surges, "inputs": inputs,
                    "commands": cmds, "replay": False, "fast_forward": not open_}
        self.engine.on_report(n, reports, acks)
        states = {}
        for l in LANES:
            lane = self.lanes[l]
            meter = lane.meter.step(n, reports[l]["total_kw"])
            st = {"lane": l, "ts": iso(rep_dt(n)), "hub": reports[l], "meter": meter,
                  "customers_per_hour": cph, "new_decisions": [], "new_commands": [], "new_escalations": [], "warnings": [],
                  "indoor_temp_c": next(d["physical"]["indoor_temp_c"] for d in reports[l]["devices"]
                                        if d["type_id"] == "hvac"),
                  "forecast_kw": None}
            for dec, cmd in self.owner_queue.get(n, {}).get(l, []):
                st["new_decisions"].append(dec)
                st["new_commands"].append(cmd)
            if l == "with":
                out = self.engine.step(n, meter)
                st["new_decisions"] += out["decisions"]
                st["new_commands"] += out["commands"]
                st["new_escalations"] += out["escalations"]
                st["warnings"] += out["warnings"]
                st["forecast_kw"] = out["forecast"]
            elif n % REPLAN_EVERY == 0:
                st["forecast_kw"] = forward(lane, n, {}, self.mult_at(n)).r1
            states[l] = st
        nxt = states["without"]["new_commands"] + states["with"]["new_commands"]
        if nxt:
            self.pending[n + 1] = nxt
        rec = {"n": n, "sim_tick": sim_tick, "reports": reports, "states": states, "post": post,
               "logs": agent_logs(n, post) if post else [], "after": [], "clock": None}
        self.recs.append(rec)
        # ---- between steps: Claude's answer, owner clicks, read-only examples
        for e in states["with"]["new_escalations"]:
            if e["status"] == "open" and e["ts"] == iso(rep_dt(n)):
                ans = self.claude_answer(e, n)
                if ans is not None:
                    rec["after"].append(ans)
        if not self.owner_done and n >= OWNER_MIN_TICK and all(
                reports[l]["devices"][IDX[OWNER_DEVICE]]["state"] == "running_job" for l in LANES):
            self.owner_done = True
            self.owner_tick = n
            self.owner_click(n, OWNER_DEVICE, "start", None)
        if n in self.hooks:
            self.hook_out[n] = self.hooks[n](self, n)
        rec["clock"] = self.clock_after(n)

    def claude_answer(self, e, n):
        """Scripted stand-in for Claude: sees every option, chooses an authorized one by cost then rank.
        No authorized choice -> no answer, the engine fallback stays."""
        cands = [o for o in e["options"] if o["within_authority"]]
        if not cands:
            return None
        o = min(cands, key=lambda x: (x["projected"]["cost_delta_usd"], x["rank"]))
        hvac_offered = any(x["option_id"].startswith("deep_reduce_hvac") for x in e["options"])
        why = ("The owner wants a comfortable dining room tonight, so I left HVAC alone. " if hvac_offered and not
               o["option_id"].startswith("deep_reduce_hvac") else "")
        rationale = why + "%s: projected peak %.1f kW, extra cost $%.2f, inside my authority." % (
            o["summary"], o["projected"]["peak_kw"], o["projected"]["cost_delta_usd"])
        self.self_rationale = rationale
        return self.engine.resolve(e["escalation_id"], o["option_id"], "claude", rationale, n)


def run_ticks_for_days(days):
    last_day = LIVE_DATES[days - 1]
    return tick_at(utc_of_local(last_day, CLOSE_M)) - 1


# ----------------------------------------------------------------------------- fake backtest on the history (G59; never savings)
BACKTEST_DATASET = "Simulated fixture data (contracts/fixtures/history, fixture_synthetic): not ComStock, not a measured bill"


def bill_from_blocks(period, rows, tc=None):
    """rows: [(block_start, total_kw)] of one local month (or its first days). Same per-charge function as the Meter (ENGINE.md
    section 1): energy at each block's price, every charge that applies in the month on its peak, fixed charges per local day
    metered (+ per month)."""
    tc = tc or TC
    month = int(period[5:])
    e = sum(t * 0.25 for _, t in rows)
    c = sum(t * 0.25 * tc.price(bs) for bs, t in rows)
    dcs = []
    for ch in tc.applicable(month):
        pk = max([t for bs, t in rows if tc.counts(ch, bs)] or [0.0])
        dcs.append({"name": ch["name"], "peak_kw": rnd(pk, 3), "cost_usd": rnd(rnd(pk, 3) * ch["rate"], 2)})
    days = len({ldate(bs) for bs, _ in rows})
    fixed = rnd(tc.fixed_day * days + (tc.fixed_month if rows else 0.0), 2)
    return {"period": period, "energy_kwh": rnd(e, 3), "energy_cost_usd": rnd(c, 2), "demand_charges": dcs,
            "fixed_usd": fixed, "total_usd": rnd(rnd(c, 2) + sum(d["cost_usd"] for d in dcs) + fixed, 2),
            "tariff_id": tc.t["tariff_id"]}


def history_matrix(hist):
    """{block_start: [avg_kw per device in roster order]} in time order."""
    out = {}
    for b in hist["blocks"]:
        out.setdefault(b["block_start"], [0.0] * ND)[IDX[b["device_id"]]] = b["avg_kw"]
    return [(datetime.strptime(k, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC), v) for k, v in out.items()]


def replay_policy(mat, policy):
    """Toy replay plant on 15-min rows (stand-in for backtest/replay.py): returns rows, energy moved, rule violations."""
    rows = [(bs, list(v)) for bs, v in mat]
    violations = 0
    by_day = {}
    for i, (bs, _) in enumerate(rows):
        by_day.setdefault(ldate(bs), []).append(i)
    target = CAP - PLAN_MARGIN_KW
    for d, idxs in by_day.items():
        open_idx = [i for i in idxs if is_open(rows[i][0])]
        if policy == "timer":
            for dev in JOBS:
                c = IDX[dev]
                dl = min(hm(DEV[dev]["limits"]["must_finish_by"]), CLOSE_M)
                for i in sorted(open_idx, reverse=True):
                    bs = rows[i][0]
                    lm = lmin(bs)
                    if 16 * 60 <= lm < 21 * 60 and lm + 60 + 15 <= dl and i + 4 in open_idx:
                        rows[i + 4][1][c] += rows[i][1][c]
                        rows[i][1][c] = 0.0
            continue
        cool = {dev: -1 for dev in FLEX}
        streak = {dev: 0 for dev in FLEX}
        owed = {dev: 0.0 for dev in FLEX}
        last = len(open_idx) - 1
        for pos, i in enumerate(open_idx):
            v = rows[i][1]
            for dev in FLEX:                                  # repay owed energy where there is room (catch-up)
                c = IDX[dev]
                if owed[dev] > 0 and streak[dev] == 0:
                    put = min(owed[dev], max(0.0, target - sum(v)), max(0.0, DEV[dev]["rated_kw"] - v[c]))
                    v[c] += put
                    owed[dev] -= put
            excess = sum(v) - target
            if excess > 0:
                for dev in JOBS:                              # hold job energy into a later block with room
                    c = IDX[dev]
                    if v[c] <= 0 or excess <= 0:
                        continue
                    dl = min(hm(DEV[dev]["limits"]["must_finish_by"]), CLOSE_M)
                    for step_ in range(1, 5):                 # max_delay_min 60
                        if pos + step_ > last:
                            break
                        k = open_idx[pos + step_]
                        if lmin(rows[k][0]) + 15 > dl:
                            break
                        if sum(rows[k][1]) + v[c] <= target:
                            rows[k][1][c] += v[c]
                            excess -= v[c]
                            v[c] = 0.0
                            break
            cut_now = set()
            if excess > 0 and pos <= last - 2:                # no new reduce in the last 30 min before close
                for dev in sorted(FLEX, key=lambda x: (-v[IDX[x]], x)):
                    c = IDX[dev]
                    floor_kw = DEV[dev]["limits"]["min_power_pct"] / 100 * DEV[dev]["rated_kw"]
                    if excess <= 0 or pos < cool[dev] or streak[dev] >= 2 or v[c] <= floor_kw:
                        continue
                    cut = min(excess, v[c] - floor_kw)
                    v[c] -= cut
                    owed[dev] += cut
                    excess -= cut
                    cut_now.add(dev)
            for dev in FLEX:                                  # 30 min max, then restore and cool down 30 min
                if dev in cut_now:
                    streak[dev] += 1
                elif streak[dev]:
                    streak[dev] = 0
                    cool[dev] = pos + 2
        if open_idx:
            v = rows[open_idx[-1]][1]
            for dev in FLEX:                                  # whatever is still owed goes into the last block before close
                v[IDX[dev]] += owed[dev]
    for (bs, raw), (_, pol) in zip(mat, rows):                # rule check: always_on untouched, flexible above its floor
        for dev in ALWAYS:
            if abs(raw[IDX[dev]] - pol[IDX[dev]]) > 1e-9:
                violations += 1
        for dev in FLEX:
            floor_kw = DEV[dev]["limits"]["min_power_pct"] / 100 * DEV[dev]["rated_kw"]
            if pol[IDX[dev]] < raw[IDX[dev]] - 1e-9 and pol[IDX[dev]] < floor_kw - 1e-9:
                violations += 1
    return rows, violations


BACKTEST_MONTHS = ("2026-06", "2026-07")
BACKTEST_RUN = "run_0001"
POLICIES = ("without", "timer", "with")


def build_backtest(hist):
    """Fake run_backtest over the history: one BacktestResult per month, one BacktestPoint per local day, and the on_progress
    events in the contract order (points per day, the month at its end, progress). Illustrative, never savings."""
    mat = history_matrix(hist)
    raw_total = {}
    for m in BACKTEST_MONTHS:
        y, mo = int(m[:4]), int(m[5:])
        raw_total[m] = [(bs, sum(v)) for bs, v in mat if (ldate(bs).year, ldate(bs).month) == (y, mo)]
    rows_by = {}
    viol = 0
    for pol in POLICIES:
        rows, v = (mat, 0) if pol == "without" else replay_policy(mat, pol)
        viol += v
        for m in BACKTEST_MONTHS:
            y, mo = int(m[:4]), int(m[5:])
            rows_by[(pol, m)] = [(bs, sum(x)) for bs, x in rows if (ldate(bs).year, ldate(bs).month) == (y, mo)]
    results, points, events = [], [], []
    saved_before = 0.0
    hist_end_local = ldate(START - timedelta(minutes=1))
    for m in BACKTEST_MONTHS:
        y, mo = int(m[:4]), int(m[5:])
        bills = {p: bill_from_blocks(m, rows_by[(p, m)]) for p in POLICIES}
        raw_bill = bill_from_blocks(m, raw_total[m])
        e_without = sum(t for _, t in rows_by[("without", m)])
        conserved = all(abs(sum(t for _, t in rows_by[(p, m)]) - e_without) <= 1e-6 * max(1.0, e_without)
                        for p in ("timer", "with"))
        days = sorted({ldate(bs) for bs, _ in rows_by[("without", m)]})
        n_cal = (date(y + mo // 12, mo % 12 + 1, 1) - date(y, mo, 1)).days
        partial = len(days) < n_cal or days[-1] == hist_end_local
        res = {"dataset": BACKTEST_DATASET, "month": m, "policies": bills,
               "checks": {"baseline_matches_raw": raw_bill == bills["without"], "energy_conserved": conserved,
                          "rule_violations": viol},
               "assumptions_id": "base", "tariff_id": TARIFF["tariff_id"], "partial": partial,
               "saved_usd": rnd(bills["without"]["total_usd"] - bills["with"]["total_usd"], 2),
               "saved_vs_timer_usd": rnd(bills["timer"]["total_usd"] - bills["with"]["total_usd"], 2)}
        for i, d in enumerate(days):
            cost = {p: bill_from_blocks(m, [(bs, t) for bs, t in rows_by[(p, m)] if ldate(bs) <= d])["total_usd"]
                    for p in POLICIES}
            saved = rnd(cost["without"] - cost["with"], 2)
            pt = {"dataset": BACKTEST_DATASET, "assumptions_id": "base", "tariff_id": TARIFF["tariff_id"], "month": m,
                  "day": d.isoformat(), "ts": iso(utc_of_local(d + timedelta(days=1), 0)), "partial": partial,
                  "cost_to_date_usd": cost, "saved_month_to_date_usd": saved,
                  "saved_vs_timer_month_to_date_usd": rnd(cost["timer"] - cost["with"], 2),
                  "saved_year_to_date_usd": rnd(saved_before + saved, 2)}
            points.append(pt)
            events.append({"type": "backtest_point", "data": pt})
            if i + 1 == len(days):
                events.append({"type": "backtest_month", "data": res})
            pct = int(100 * (i + 1) // len(days))
            if pct // 25 > int(100 * i // len(days)) // 25:            # progress every quarter of the month
                events.append({"type": "backtest_progress", "month": m, "pct": pct})
        assert points[-1]["saved_month_to_date_usd"] == res["saved_usd"], (m, points[-1], res["saved_usd"])
        saved_before += res["saved_usd"]
        results.append(res)
    return results, points, events


BACKTEST_INPUT_DAYS = 3


def backtest_inputs(hist):
    """BacktestInputs (CONTRACTS.md section 1) as the caller would pass it, with the series cut to the first
    BACKTEST_INPUT_DAYS local days of the first replayed month to keep the file small (the real series covers the 4 warm-up
    weeks + every replayed month). Fixture history, so `fixture_synthetic` / `simulated`."""
    first = date(int(BACKTEST_MONTHS[0][:4]), int(BACKTEST_MONTHS[0][5:]), 1)
    a, b = utc_of_local(first, 0), utc_of_local(first + timedelta(days=BACKTEST_INPUT_DAYS), 0)
    blocks = [x for x in hist["blocks"] if a <= datetime.strptime(x["block_start"], "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=UTC) < b]
    series = dict(hist, start=iso(a), end=iso(b), blocks=blocks)
    return {"config": CONFIG, "tariff": TARIFF, "catalog": CATALOG, "seed": SEED, "series": series,
            "assumptions": {"assumptions_id": "base", "flex_scale": 1.0, "draw_scale": 1.0, "forecast_noise_pct": 0.0}}


# ----------------------------------------------------------------------------- writers
WRITTEN = []
OUT = HERE


def _path(rel):
    p = os.path.join(OUT, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    WRITTEN.append(rel)
    return p


def wjson(rel, obj):
    with open(_path(rel), "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def wjsonl(rel, rows):
    with open(_path(rel), "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")


def wjson_rows(rel, obj, key="blocks"):
    """Pretty JSON, except every list named `key` is written one compact element per line (keeps big files small)."""
    marker = "\u0000ROWS\u0000"
    rows_by_marker = []

    def strip(o):
        if isinstance(o, dict):
            out = {}
            for k, v in o.items():
                if k == key and isinstance(v, list):
                    rows_by_marker.append(v)
                    out[k] = marker + str(len(rows_by_marker) - 1)
                else:
                    out[k] = strip(v)
            return out
        if isinstance(o, list):
            return [strip(x) for x in o]
        return o
    text = json.dumps(strip(obj), indent=2, ensure_ascii=False)
    for i, rows in enumerate(rows_by_marker):
        tag = json.dumps(marker + str(i))
        line_start = text.index(tag)
        indent = text.rfind("\n", 0, line_start)
        pad = " " * (len(text[indent + 1:line_start]) - len(text[indent + 1:line_start].lstrip()) + 2)
        body = ("[\n" + ",\n".join(pad + json.dumps(r, ensure_ascii=False, separators=(",", ":")) for r in rows) + "\n" +
                pad[:-2] + "]") if rows else "[]"
        text = text.replace(tag, body, 1)
    with open(_path(rel), "w", encoding="utf-8", newline="\n") as f:
        f.write(text + "\n")


def cj(obj):
    return None if obj is None else json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


# ----------------------------------------------------------------------------- row builders (SpacetimeDB)
def live_tick_row(st, n, fc, fc_ts):
    m = st["meter"]
    return {"lane": st["lane"], "ts": st["ts"], "tick_id": n, "total_kw": m["total_kw"], "block_avg_kw": m["block_avg_kw"],
            "month_peak_kw": m["month_peak_kw"], "on_peak_month_peak_kw": m["on_peak_month_peak_kw"],
            "peak_mode": m["peak_mode"], "peak_cap_kw": m["peak_cap_kw"], "target_kw": m["target_kw"],
            "energy_kwh_today": m["energy_kwh_today"], "energy_kwh_month": m["energy_kwh_month"],
            "price_usd_per_kwh_now": m["price_usd_per_kwh_now"], "cost_usd_today": m["cost_usd_today"],
            "cost_usd_month": m["cost_usd_month"], "demand_peaks_json": cj(m["demand_peaks"]),
            "customers_per_hour": st["customers_per_hour"],
            "indoor_temp_c": st["indoor_temp_c"], "forecast_kw_json": cj(fc), "forecast_ts": fc_ts}


def tick_history_row(st):
    return {"lane": st["lane"], "ts": st["ts"], "total_kw": st["meter"]["total_kw"], "block_avg_kw": st["meter"]["block_avg_kw"]}


def live_device_row(lane, d):
    return {"key": "%s:%s" % (lane, d["device_id"]), "lane": lane, "device_id": d["device_id"], "type_id": d["type_id"],
            "name": d["name"], "importance": d["importance"], "state": d["state"], "power_kw": d["power_kw"],
            "rated_kw": d["rated_kw"], "power_pct": d["power_pct"], "source": d["source"], "physical_json": cj(d.get("physical"))}


def feed_row(dec, lane, text):
    return {"decision_id": dec["decision_id"], "lane": lane, "ts": dec["ts"], "device_id": dec["device_id"],
            "action": dec["action"], "value": dec["value"], "status": dec["status"], "reason_code": dec["reason_code"],
            "effect_json": cj(dec["effect"]), "explanation": text, "explanation_source": "template"}


def escalation_row(e):
    return {"escalation_id": e["escalation_id"], "lane": e["lane"], "status": e["status"], "block_start": e["block_start"],
            "updated_ts": e["updated_ts"], "problem_json": cj(e["problem"]), "options_json": cj(e["options"]),
            "default_option_id": e["default_option_id"], "active_option_id": e["active_option_id"],
            "deadline_sim_ts": e["deadline_sim_ts"], "chosen_option_id": e["chosen_option_id"],
            "resolved_by": e["resolved_by"], "rationale": e["rationale"],
            "claude_attempts_json": cj(e["claude_attempts"]),
            "explanation": escalation_message(e)["explanation"], "explanation_source": "template"}


def escalation_message(e):
    verdict = "Claude's choice accepted." if e["status"] == "resolved" else "Engine fallback remains active."
    if e["claude_attempts"] and not e["claude_attempts"][-1]["accepted"]:
        verdict = "Claude's choice rejected: %s. Engine fallback remains active." % e["claude_attempts"][-1]["reason"]
    return {"type": "escalation", "data": e, "explanation": verdict, "explanation_source": "template"}


def backtest_point_row(run_id, p):
    return {"key": "%s:%s" % (run_id, p["day"]), "run_id": run_id, "day": p["day"], "month": p["month"], "ts": p["ts"],
            "partial": p["partial"], "cost_to_date_json": cj(p["cost_to_date_usd"]),
            "saved_month_to_date_usd": p["saved_month_to_date_usd"],
            "saved_vs_timer_month_to_date_usd": p["saved_vs_timer_month_to_date_usd"],
            "saved_year_to_date_usd": p["saved_year_to_date_usd"], "dataset": p["dataset"], "tariff_id": p["tariff_id"],
            "assumptions_id": p["assumptions_id"]}


def backtest_month_row(run_id, r):
    return {"key": "%s:%s" % (run_id, r["month"]), "run_id": run_id, "month": r["month"], "partial": r["partial"],
            "saved_usd": r["saved_usd"], "saved_vs_timer_usd": r["saved_vs_timer_usd"], "policies_json": cj(r["policies"]),
            "checks_json": cj(r["checks"]), "dataset": r["dataset"], "tariff_id": r["tariff_id"],
            "assumptions_id": r["assumptions_id"]}


def context_row(c):
    w, p, ev = c["weather"], c["prices"], c["events"]
    return {"id": 0, "weather_summary": "%.1f °C now" % w["hourly"][0]["temp_c"], "weather_label": w["label"],
            "prices_summary": "%.2f USD/kWh now, stress %s" % (p["hourly"][0]["usd_per_kwh"], p["stress"]),
            "prices_label": p["label"],
            "events_summary": "; ".join("%s at %s, %.1f km" % (i["name"], i["venue"], i["distance_km"]) for i in ev["items"])
            or "No events nearby", "events_label": ev["label"], "crowd_effect": c["crowd_effect"]["value"]}


def comparison(sw, sv):
    a, b = sw["meter"], sv["meter"]
    return {"ts": sv["ts"], "saved_today_usd": rnd(a["cost_usd_today"] - b["cost_usd_today"], 2),
            "peak_avoided_kw": rnd(a["month_peak_kw"] - b["month_peak_kw"], 2),
            "month_peak_without_kw": a["month_peak_kw"], "month_peak_with_kw": b["month_peak_kw"]}


def clock_state(n, run_days, last_tick):
    """ClockState after tick n (n = 0: before the first tick)."""
    if n >= last_tick:
        return {"playing": False, "speed": SPEED, "sim_ts": iso(rep_dt(n)), "tick_id": n, "paused_reason": "run_complete",
                "day_index": run_days, "run_days": run_days, "phase": "closed"}
    nxt = sim_dt(n + 1)
    day_index = 1 + sum(1 for i in range(1, run_days) if utc_of_local(LIVE_DATES[i], OPEN_M) <= nxt)
    return {"playing": True, "speed": SPEED, "sim_ts": iso(rep_dt(n)), "tick_id": n, "paused_reason": None,
            "day_index": day_index, "run_days": run_days, "phase": "service" if is_open(nxt) else "overnight"}


SET_CLOCK_ARGS = ("playing", "speed", "sim_ts", "tick_id", "paused_reason", "day_index", "run_days", "phase", "sim_host")


# ----------------------------------------------------------------------------- streams for a set of ticks
def build_streams(R, ticks, run_days, last_tick, mode):
    """mode "every_tick" (evening: every tick published) or "multiday" (overnight published once per closed block)."""
    rec = R.recs
    build_cfg = make_config(run_days)
    hello = {"type": "hub_hello", "protocol": 1, "hub_id": "sim_hub", "role": "sim_host", "client": "wattwise-web/0.1"}
    welcome = {"type": "hub_welcome", "accepted": True, "reason": None, "tick_id": 0}
    roster = [{"device_id": d["device_id"], "type_id": d["type_id"], "name": d["name"], "importance": d["importance"],
               "state": "off", "power_kw": 0.0, "rated_kw": d["rated_kw"], "power_pct": 0, "source": "simulated"}
              for d in DEVICES]
    sim_build = {"type": "sim_build", "kitchen_id": "k_01", "config": build_cfg, "catalog": CATALOG, "devices": roster,
                 "seed": SEED, "start_sim_ts": iso(START)}
    s2h = [welcome, sim_build] + [rec[n]["sim_tick"] for n in ticks]
    h2s = [hello] + [{"type": "hub_report", "tick_id": n, "reports": {l: rec[n]["reports"][l] for l in LANES}} for n in ticks]
    steps = [{"args": {"minutes": 1, "hub_report": rec[n]["reports"][l]}, "returns": rec[n]["states"][l]}
             for n in ticks for l in LANES]
    latest_fc = {l: (None, None) for l in LANES}
    for n in range(1, ticks[0]):
        for l in LANES:
            st = rec[n]["states"][l]
            if st["forecast_kw"] is not None:
                latest_fc[l] = (st["forecast_kw"], st["ts"])
    rows, ws, clocks = [], [], []
    first = ticks[0]
    c0 = clock_state(first - 1, run_days, last_tick)
    ws.append(dict({"type": "clock"}, **c0))
    clocks.append(c0)
    in_force = max(p for p in R.posts if p <= first)
    if in_force < first or first == 1:
        if first == 1:
            ws.append({"type": "context", "data": R.ctx_by_post[1]})
            ws += [{"type": "agent_log", "data": x} for x in rec[1]["logs"]]
        else:
            ws.append({"type": "context", "data": R.ctx_by_post[in_force]})
    prev_clock = c0
    for n in ticks:
        r = rec[n]
        open_ = is_open(sim_dt(n))
        publish = mode == "every_tick" or open_ or n % 15 == 0
        if r["post"] is not None and n != 1:
            ws += [{"type": "agent_log", "data": x} for x in r["logs"]] + [{"type": "context", "data": r["post"]}]
        sw, sv = r["states"]["without"], r["states"]["with"]
        for l in LANES:
            if r["states"][l]["forecast_kw"] is not None:
                latest_fc[l] = (r["states"][l]["forecast_kw"], r["states"][l]["ts"])
        if publish:
            ws += [{"type": "tick", "data": sw}, {"type": "tick", "data": sv}, {"type": "comparison", "data": comparison(sw, sv)}]
            rows.append({"live_tick": [live_tick_row(sw, n, *latest_fc["without"]), live_tick_row(sv, n, *latest_fc["with"])],
                         "tick_history": [tick_history_row(sw), tick_history_row(sv)],
                         "live_device": [live_device_row(l, d) for l in LANES for d in r["reports"][l]["devices"]],
                         "live_comparison": dict({"id": 0}, **comparison(sw, sv))})
        for l in LANES:
            for d in r["states"][l]["new_decisions"]:
                ws.append({"type": "decision", "data": d, "explanation": R.explain[d["decision_id"]],
                           "explanation_source": "template"})
        for l in LANES:
            for e in r["states"][l]["new_escalations"]:
                ws.append(escalation_message(e))
            for w in r["states"][l]["warnings"]:
                ws.append(dict({"type": "warning"}, **w))
        for e in r["after"]:
            ws.append(escalation_message(e))
        c = clock_state(n, run_days, last_tick)
        if mode == "multiday" and (c["phase"] != prev_clock["phase"] or c["day_index"] != prev_clock["day_index"] or
                                   (c["phase"] == "overnight" and n % 15 == 0) or c["paused_reason"] is not None):
            ws.append(dict({"type": "clock"}, **c))
            clocks.append(c)
            prev_clock = c
    return {"s2h": s2h, "h2s": h2s, "steps": steps, "rows": rows, "ws": ws, "clocks": clocks, "sim_build": sim_build,
            "hello": hello, "welcome": welcome}


def segments_of(ticks):
    segs, start, prev = [], ticks[0], ticks[0]
    for t in ticks[1:] + [None]:
        if t is None or t != prev + 1 or is_open(sim_dt(t)) != is_open(sim_dt(prev)):
            segs.append((start, prev))
            if t is not None:
                start = t
        if t is not None:
            prev = t
    return segs


def describe_segments(ticks, run_days, last_tick):
    out = []
    segs = segments_of(ticks)
    for i, (a, b) in enumerate(segs):
        c = clock_state(a - 1 if a > 1 else 0, run_days, last_tick)
        ph = "service" if is_open(sim_dt(a)) else "overnight"
        out.append({"from_tick": a, "to_tick": b, "ticks": b - a + 1, "phase": ph,
                    "day_index": clock_state(a, run_days, last_tick)["day_index"] if ph == "service" else c["day_index"],
                    "from_local": loc(sim_dt(a)).strftime("%a %d %b %H:%M"), "to_local": loc(rep_dt(b)).strftime("%a %d %b %H:%M"),
                    "is_open": ph == "service", "fast_forward": ph == "overnight",
                    "published": "every tick" if ph == "service" else "once per closed 15-min block (publish_ticks, set_clock, "
                                                                      "ws tick/comparison/clock)"})
        if i + 1 < len(segs) and segs[i + 1][0] != b + 1:
            out.append({"gap": True, "from_tick": b + 1, "to_tick": segs[i + 1][0] - 1,
                        "note": "omitted to keep the files small; the run continues (same physics, same ids) and the "
                                "omitted ticks are in `generate.py --days 2`"})
    if clock_state(ticks[-1], run_days, last_tick)["phase"] == "closed":
        out.append({"phase": "closed", "after_tick": ticks[-1], "paused_reason": "run_complete",
                    "note": "clock stops after the last day's close; POST /api/sim/control {action: next_day} adds a day"})
    return out


# ----------------------------------------------------------------------------- read-only examples taken during the run
def what_if_hook(device_id, action, value):
    def hook(run, n):
        eng = run.engine
        lane = run.lanes["with"]
        base = eng.plan(n, [], eng.restores())
        p2 = {k: list(v) for k, v in base.items()}
        p2.setdefault(n + 1, []).append({"command_id": "x", "lane": "with", "device_id": device_id, "action": action,
                                         "value": value})
        if action == "reduce":
            p2.setdefault(n + 31, []).append({"command_id": "x", "lane": "with", "device_id": device_id, "action": "restore",
                                              "value": None})
        mult = run.mult_at(n)
        m = run.recs[n]["states"]["with"]["meter"]
        peaks = meter_peaks(m)
        return effect_of(forward(lane, n, base, mult), forward(lane, n, p2, mult), n, peaks)
    return hook


def snapshot_hook(run, n):
    eng = run.engine
    return {"active_commands": [copy.deepcopy(c) for _, c in sorted(eng.active_cmds.items(), key=lambda x: x[1]["command_id"])],
            "owed_kwh": {d: rnd(eng.owed[d], 3) for d in FLEX},
            "open_escalations": [copy.deepcopy(e) for _, e in sorted(eng.active.items())],
            "id_counters": {k: run.counters[k] for k in ("d", "c", "e")},
            "clamp_effect": what_if_hook("water_heater_1", "reduce", 10)(run, n)}


def esc_hook(run, n):
    """At the escalation tick: the unavoidable load of the near blocks (for the illustrative cap_unreachable example)."""
    eng = run.engine
    f = eng.fc(n, [], eng.restores())
    j = max(eng.near(f, n), key=lambda x: eng.unavoidable(n, f, x))
    return {"unavoidable": rnd(eng.unavoidable(n, f, j), 1), "block": block_start_dt(f.k0 + j)}


def first_escalation_tick(R, upto):
    for n in range(1, upto + 1):
        if any(e["status"] == "open" for e in R.recs[n]["states"]["with"]["new_escalations"]):
            return n
    raise RuntimeError("no escalation in the evening")


MAN = [
    ("shapes/tariff_pge_b19.json", "§1 Tariff (PG&E B-19 from URDB 69de8cdb02f684104e01267d: seasons, windows, fixed charge)",
     ["Kritazya (engine tariff/meter tests, backend/data/tariff_urdb.py target)", "Ashirwad (bill breakdown UI)"], "S2"),
    ("shapes/backtest_", "§1 BacktestResult / BacktestPoint / BacktestInputs (fake, never savings)",
     ["Kritazya (run_backtest tests)", "Suyog (API backtest route)", "Ashirwad (Proof screen)"], "S1 S2"),
    ("facade/run_backtest", "§3 run_backtest (inputs, returns, on_progress events in order)",
     ["Suyog (fakes/fake_kitchen.py replays on_progress)", "Kritazya (engine tests)"], "S2"),
    ("ws/backtest_", "§2 WebSocket /ws (Proof chart, LIVE_TRANSPORT=ws)", ["Ashirwad (Proof screen /ws mock)", "Suyog (API tests)"],
     "S1"),
    ("spacetime/tables/backtest_", "§5 SpacetimeDB backtest_point / backtest_month (Proof chart rows)",
     ["Ashirwad (Proof screen mock live hook)", "Kritazya (fakes/fake_live.py, spacetime/seed.ts)"], "S3"),
    ("spacetime/reducers/publish_backtest_", "§5 SpacetimeDB reducers (Proof)", ["Kritazya (live/spacetime_client.py)"], "S3"),
    ("spacetime/reducers/reset_backtest", "§5 SpacetimeDB reducers (Proof)", ["Kritazya (live/spacetime_client.py)"], "S3"),
    ("shapes/", "§1 Shared shapes", ["Ashirwad", "Suyog", "Kritazya"], "all"),
    ("history/", "§1 WarmUpHistory + daily inputs (G59)", ["Kritazya (engine warm_up, backtest)", "Suyog (runtime warm-up)",
                                                         "Ashirwad (Proof screen)"], "S2"),
    ("hub_protocol/server_to_hub.jsonl", "§8 Hub protocol", ["Ashirwad (src/mocks/mockHubServer.ts)", "Kritazya"], "S6"),
    ("hub_protocol/hub_to_server.jsonl", "§8 Hub protocol", ["Suyog (fakes/fake_hub_client.py)", "Kritazya (engine input)"], "S6"),
    ("hub_protocol/", "§8 Hub protocol", ["Ashirwad", "Suyog", "Kritazya"], "S6"),
    ("rest/", "§2 REST", ["Ashirwad (src/mocks REST handlers)", "Suyog (API tests)"], "S1"),
    ("ws/", "§2 WebSocket /ws", ["Ashirwad (src/mocks, /ws fallback hook)", "Suyog (API tests)"], "S1"),
    ("facade/", "§3 Engine facade", ["Suyog (fakes/fake_kitchen.py)", "Kritazya (engine tests)"], "S2"),
    ("ai_tools/", "§4 AI tools", ["Suyog (agent/tools.py tests)"], "S2 via API"),
    ("spacetime/", "§5 SpacetimeDB", ["Ashirwad (mock live hook)", "Kritazya (fakes/fake_live.py, spacetime/seed.ts)"], "S3"),
    ("convex/", "§6 Convex", ["Suyog (store/, STORE=memory seed)"], "S4"),
    ("agents/", "§7 Agent messages", ["Suyog (agents --recorded)"], "S5"),
    ("scenario/demo_cafe_multiday/", "§8 Day lifecycle (multi-day run, G56-G58)",
     ["Ashirwad (mock clock walks the phases)", "Suyog (runtime day lifecycle tests)", "Kritazya (engine across midnight)"],
     "S1 S3 S6"),
    ("scenario/", "Demo Café scenario (DEMO.md)", ["Kritazya", "Suyog", "Ashirwad"], "all"),
]


def manifest_entry(f):
    for prefix, section, consumers, seam in MAN:
        if f.startswith(prefix):
            return {"contract_section": section, "consumers": consumers, "seam": seam}
    return {"contract_section": "meta", "consumers": ["everyone"], "seam": "-"}


def write_days(days, out_dir):
    """`--days N --out DIR`: every tick of an N-day run (hub_protocol + step_stream). Not committed."""
    global OUT
    OUT = out_dir
    if not 1 <= days <= LIVE_DAYS:
        raise SystemExit("--days must be 1..%d (daily inputs cover 2026-07-17 .. 2026-07-23)" % LIVE_DAYS)
    hist, totals = build_history()
    last = run_ticks_for_days(days)
    R = Run(last, days, history_meter_init(totals)).run()
    S = build_streams(R, list(range(1, last + 1)), days, last, "multiday")
    wjsonl("server_to_hub.jsonl", S["s2h"])
    wjsonl("hub_to_server.jsonl", S["h2s"])
    wjsonl("step_stream.jsonl", S["steps"])
    wjson("index.json", {"label": "FAKE DATA - not measured, not live", "run_days": days, "ticks": last,
                         "start_sim_ts": iso(START), "end_sim_ts": iso(rep_dt(last)),
                         "segments": describe_segments(list(range(1, last + 1)), days, last),
                         "files": ["server_to_hub.jsonl", "hub_to_server.jsonl", "step_stream.jsonl"],
                         "generated_by": "python3 contracts/fixtures/generate.py --days %d --out <dir>" % days})


def main(out_dir):
    global OUT
    OUT = out_dir
    for retired in ("shapes/escalation_awaiting_owner.json", "shapes/proposal_resolve_escalation.json",
                    "ai_tools/propose_escalation_choice.json", "rest/post_escalation_resolve.json"):
        path = os.path.join(OUT, retired)
        if os.path.isfile(path):
            os.unlink(path)

    hist, totals = build_history()
    init = history_meter_init(totals)
    multi_last = run_ticks_for_days(MULTI_DAYS)
    probe = Run(EVENING_TICKS, MULTI_DAYS, init).run()
    esc_n = first_escalation_tick(probe, EVENING_TICKS)
    R = Run(multi_last, MULTI_DAYS, init)
    R.hooks = {80: what_if_hook("walk_in_cooler_1", "reduce", 50), esc_n: esc_hook, EVENING_TICKS: snapshot_hook}
    R.run()
    N = EVENING_TICKS
    rec = R.recs

    def st(n, l):
        return rec[n]["states"][l]

    def rep(n, l):
        return rec[n]["reports"][l]

    ev_dec_ids = [x["decision_id"] for n in range(1, N + 1) for l in LANES for x in st(n, l)["new_decisions"]]
    ev_decisions = [d for d in R.decisions if d["decision_id"] in set(ev_dec_ids)]
    ev_commands = [c for n in range(1, N + 1) for l in LANES for c in st(n, l)["new_commands"]]
    esc_open = next(e for e in st(esc_n, "with")["new_escalations"] if e["status"] == "open")
    resolved = next(e for e in rec[esc_n]["after"] if e["escalation_id"] == esc_open["escalation_id"])
    ev_escalations = [e for n in range(1, N + 1) for e in st(n, "with")["new_escalations"]]
    first_dec = next(d for d in ev_decisions if d["reason_code"] == "stay_under_cap")
    first_cmd = next(c for c in ev_commands if c["decision_id"] == first_dec["decision_id"])
    acks_by = {a["command_id"]: a for n in range(1, R.N + 1) for l in LANES for a in rep(n, l)["acks"]}
    first_ack = acks_by[first_cmd["command_id"]]
    owner_n = R.owner_tick
    owner_cmd = next(c for c in st(owner_n + 1, "with")["new_commands"] if c["issued_by"] == "owner")
    owner_ack = acks_by[owner_cmd["command_id"]]
    surge = {"surge_id": "s_0001", "customers": LIVE_SURGES[0]["customers"], "duration_min": LIVE_SURGES[0]["duration_min"]}
    surge_req = LIVE_SURGES[0]
    CONTEXT_1, CONTEXT_2 = R.ctx_by_post[1], R.ctx_by_post[61]
    logs1, logs2 = rec[1]["logs"], rec[61]["logs"]
    all_logs = logs1 + logs2
    snap = R.hook_out[N]
    # standalone examples use ids after the last id of the longest committed run, so they never collide with a stream
    clamp_dec_id, clamp_cmd_id = "d_%04d" % (R.counters["d"] + 1), "c_%04d" % (R.counters["c"] + 1)
    clamp_cmd = {"command_id": clamp_cmd_id, "lane": "with", "ts": iso(rep_dt(N)), "device_id": "water_heater_1",
                 "action": "reduce", "value": 10, "decision_id": clamp_dec_id, "issued_by": "owner"}
    clamped_ack = Sim(INIT).apply(clamp_cmd, N)
    clamp_dec = {"decision_id": clamp_dec_id, "ts": iso(rep_dt(N)), "device_id": "water_heater_1", "action": "reduce",
                 "value": 10, "reason_code": "owner_override", "inside_rules": False, "status": "executed",
                 "effect": snap["clamp_effect"]}
    wi_effect = R.hook_out[80]
    wi_args = {"device_id": "walk_in_cooler_1", "action": "reduce", "value": 50, "at": iso(rep_dt(80))}
    reading = {"hub_id": "esp32_1", "channel": 0, "device_id": "dishwasher_1", "ts": iso(rep_dt(115)),
               "raw_w": 5.8, "scale": 1000, "power_kw": 5.8}
    dw_dev = next(d for d in rep(115, "with")["devices"] if d["device_id"] == "dishwasher_1")
    measured = dict(copy.deepcopy(dw_dev), power_kw=reading["power_kw"],
                    power_pct=half_up(100 * reading["power_kw"] / dw_dev["rated_kw"]), source="measured")
    exp_by_id = R.explain

    # ---- escalation variants (alternative outcomes of the same e_0001; only `resolved` is in the stream)
    eid = esc_open["escalation_id"]
    outside = next(o for o in esc_open["options"] if not o["within_authority"])
    rejected = copy.deepcopy(esc_open)
    rejected["claude_attempts"] = [{"ts": esc_open["ts"], "option_id": outside["option_id"], "accepted": False,
                                     "reason": "outside_authority", "rationale": "The engine rejected this pick outside authority."}]
    expired = dict(copy.deepcopy(rejected), status="expired_default", resolved_by="default",
                   updated_ts=esc_open["deadline_sim_ts"])
    obsolete = dict(copy.deepcopy(esc_open), status="obsolete", updated_ts=iso(rep_dt(esc_n + REPLAN_EVERY)))

    # ---- proposals (one per kind)
    def proposal(pid, kind, payload, summary, ts_n=N, expires=None):
        return {"proposal_id": pid, "ts": iso(rep_dt(ts_n)), "kind": kind, "payload": payload, "summary": summary,
                "status": "pending", "created_by": "ai", "confirmed_via": None,
                "expires_at": expires or iso(rep_dt(ts_n) + timedelta(minutes=30))}
    undo_target = next(d for d in ev_decisions if d["action"] in ("reduce", "delay") and
                       any(c["decision_id"] == d["decision_id"] for c in snap["active_commands"]))
    proposal_pending = proposal("p_0001", "importance",
                                {"device_id": "walk_in_cooler_1", "importance": "always_on", "limits": {}},
                                "Never touch the walk-in after 21:00")
    proposal_confirmed = dict(proposal_pending, status="confirmed", confirmed_via="ui")
    proposals_by_kind = {
        "importance": proposal_pending,
        "peak_cap": proposal("p_0002", "peak_cap", {"peak_mode": "cap", "peak_cap_kw": 38.0}, "Lower the cap to 38 kW"),
        "authority": proposal("p_0003", "authority", dict(AUTHORITY, max_cap_overrun_kw=2.0),
                              "Let Claude accept at most 2 kW over the cap"),
        "undo_decision": proposal("p_0004", "undo_decision", {"decision_id": undo_target["decision_id"]},
                                  "Undo: %s" % exp_by_id[undo_target["decision_id"]].rstrip(".")),
        "customer_event": proposal("p_0005", "customer_event",
                                   {"customers": 40, "duration_min": 60, "start_sim_ts": iso(rep_dt(N) + timedelta(minutes=30))},
                                   "40-person party at 20:00"),
    }

    # ---- bills and backtest
    def meter_bill(m, period="2026-07"):
        """Bill(period) as the engine would return it now: the Meter's month to date, charge by charge."""
        dcs = [{"name": dp["name"], "peak_kw": dp["peak_kw"], "cost_usd": dp["cost_usd"]} for dp in m["demand_peaks"]]
        fixed = rnd(TC.fixed_day * loc(START).day + TC.fixed_month, 2)
        ecost = rnd(m["cost_usd_month"] - sum(d["cost_usd"] for d in dcs) - fixed, 2)
        return {"period": period, "energy_kwh": m["energy_kwh_month"], "energy_cost_usd": ecost, "demand_charges": dcs,
                "fixed_usd": fixed, "total_usd": m["cost_usd_month"], "tariff_id": TARIFF["tariff_id"]}
    bill_with = meter_bill(st(N, "with")["meter"])
    bill_without = meter_bill(st(N, "without")["meter"])
    backtest, bt_points, bt_events = build_backtest(hist)
    bt_july = backtest[-1]
    bt_point = next(p for p in bt_points if p["day"] == "2026-07-14")
    bt_inputs = backtest_inputs(hist)
    ok = {"ok": True}

    def clock_msg(n, run_days=1):
        return dict({"type": "clock"}, **clock_state(n, run_days, run_ticks_for_days(run_days)))
    unav = R.hook_out[esc_n]
    low_cap = 5.0 * math.floor((unav["unavoidable"] - 0.1) / 5.0)
    warning = {"code": "cap_unreachable",
               "message": "Even with every allowed move the kitchen needs %.1f kW in the %s block. Raise the cap or change an "
                          "importance." % (unav["unavoidable"], hm_str(lmin(unav["block"]))),
               "data": {"unavoidable_kw": unav["unavoidable"], "peak_cap_kw": low_cap, "target_kw": low_cap}}

    # ---- snapshot (with lane, after tick 120)
    latest_fc = next((st(n, "with")["forecast_kw"], st(n, "with")["ts"]) for n in range(N, 0, -1)
                     if st(n, "with")["forecast_kw"] is not None)
    recent = [d for d in reversed(R.decisions) if d["decision_id"] in set(ev_dec_ids) and R.dec_lane[d["decision_id"]] == "with"]
    snapshot = {"tick_id": N, "sim_ts": iso(rep_dt(N)), "lane": "with", "control": "with", "peak_mode": CONFIG["peak_mode"],
                "config": CONFIG, "meter": st(N, "with")["meter"], "forecast_kw": latest_fc[0], "forecast_ts": latest_fc[1],
                "devices": rep(N, "with")["devices"], "active_commands": snap["active_commands"], "owed_kwh": snap["owed_kwh"],
                "open_escalations": snap["open_escalations"], "warnings": st(N, "with")["warnings"],
                "recent_decisions": recent[:20], "context": CONTEXT_2, "id_counters": snap["id_counters"]}

    # ---------------- shapes
    S = "shapes/"
    wjson(S + "equipment_catalog.json", CATALOG)
    wjson(S + "kitchen_config.json", CONFIG)
    wjson(S + "kitchen_config_minimize.json", dict(copy.deepcopy(CONFIG), peak_mode="minimize", peak_cap_kw=None))
    wjson(S + "claude_authority.json", AUTHORITY)
    wjson(S + "tariff.json", TARIFF)
    wjson(S + "device.json", next(d for d in rep(50, "with")["devices"] if d["device_id"] == "hvac_1"))
    wjson(S + "device_measured.json", measured)
    wjson(S + "hub_report_with.json", rep(50, "with"))
    wjson(S + "hub_report_without.json", rep(50, "without"))
    wjson(S + "reading.json", reading)
    wjson(S + "command.json", first_cmd)
    wjson(S + "command_ack_ok.json", first_ack)
    wjson(S + "command_ack_rejected.json", owner_ack)
    wjson(S + "command_owner.json", clamp_cmd)
    wjson(S + "command_ack_clamped.json", clamped_ack)
    wjson(S + "decision.json", first_dec)
    wjson(S + "decision_owner_override.json", clamp_dec)
    wjson(S + "context.json", CONTEXT_1)
    wjson(S + "warning_cap_unreachable.json", warning)
    wjson(S + "escalation_open.json", esc_open)
    wjson(S + "escalation_resolved_claude.json", resolved)
    wjson(S + "escalation_rejected_claude.json", rejected)
    wjson(S + "escalation_expired_default.json", expired)
    wjson(S + "escalation_obsolete.json", obsolete)
    wjson(S + "meter.json", st(esc_n, "with")["meter"])
    wjson(S + "tick_state_with.json", st(esc_n, "with"))
    wjson(S + "tick_state_without.json", st(esc_n, "without"))
    wjson(S + "lane_comparison.json", comparison(st(N, "without"), st(N, "with")))
    for kind, p in proposals_by_kind.items():
        if kind != "importance":
            wjson(S + "proposal_%s.json" % kind, p)
    wjson(S + "proposal_pending.json", proposal_pending)
    wjson(S + "proposal_confirmed.json", proposal_confirmed)
    wjson(S + "bill.json", bill_with)
    wjson(S + "backtest_result.json", bt_july)
    wjson(S + "backtest_point.json", bt_point)
    wjson_rows(S + "backtest_inputs.json", bt_inputs)
    wjson(S + "tariff_pge_b19.json", TARIFF_B19)
    wjson(S + "agent_log.json", logs1[0])
    last_block = [b for b in hist["blocks"] if b["block_start"] == iso(START - timedelta(minutes=15))]
    wjson(S + "warm_up_history.json", dict(hist, start=iso(START - timedelta(minutes=15)), blocks=last_block))

    # ---------------- history (G59)
    H = "history/"
    wjson_rows(H + "warmup_demo_cafe.json", hist)
    wjson_rows(H + "daily_inputs.json", {
        "label": "simulated", "note": "FAKE DATA - not measured, not live. Inputs behind history/warmup_demo_cafe.json and the "
                                      "live streams: the recorded context posts and sim_tick.inputs copy these values.",
        "timezone": TARIFF["timezone"], "operating_hours": CONFIG["operating_hours"],
        "crowd_multiplier": CROWD, "customer_profile_per_h": [{"local": hm_str(m), "customers_per_h": c} for m, c in PROFILE],
        "weekday_factor": {WEEKDAY[i]: f for i, f in enumerate(WEEKDAY_FACTOR)},
        "days": [DAILY[d] for d in ALL_DATES]}, key="days")

    # ---------------- hub protocol + facade step stream + spacetime rows + ws (evening, every tick)
    E = build_streams(R, list(range(1, N + 1)), 1, run_ticks_for_days(1), "every_tick")
    P = "hub_protocol/"
    wjson(P + "hub_hello.json", E["hello"])
    wjson(P + "hub_welcome_accepted.json", E["welcome"])
    wjson(P + "hub_welcome_host_taken.json", {"type": "hub_welcome", "accepted": False, "reason": "host_taken", "tick_id": 0})
    wjson(P + "sim_build.json", E["sim_build"])
    wjson(P + "sim_tick.json", rec[36]["sim_tick"])
    wjson(P + "sim_tick_replay.json", dict(rec[36]["sim_tick"], replay=True))
    wjson(P + "sim_tick_overnight.json", rec[300]["sim_tick"])
    wjson(P + "hub_report.json", E["h2s"][36])
    wjson(P + "sim_control.json", {"type": "sim_control", "action": "play", "speed": SPEED, "paused_reason": None})
    wjsonl(P + "server_to_hub.jsonl", E["s2h"])
    wjsonl(P + "hub_to_server.jsonl", E["h2s"])

    # ---------------- facade
    F = "facade/"
    wjsonl(F + "step_stream.jsonl", E["steps"])
    wjson(F + "kitchen.json", {"call": "Kitchen", "args": {"config": CONFIG, "tariff": TARIFF, "catalog": CATALOG,
                                                            "control": "with", "seed": SEED, "ids": None}, "returns": None})
    wjson_rows(F + "warm_up.json", {"call": "warm_up", "args": {"history": hist}, "returns": None})
    wjson(F + "ingest_reading.json", {"call": "ingest_reading", "args": {"reading": reading}, "returns": measured})
    wjson(F + "owner_command.json", {"call": "owner_command", "args": {"device_id": owner_cmd["device_id"],
                                     "action": owner_cmd["action"], "value": owner_cmd["value"]}, "returns": owner_cmd})
    wc_dev = next(d for d in rep(N, "with")["devices"] if d["device_id"] == "walk_in_cooler_1")
    wjson(F + "set_importance.json", {"call": "set_importance", "args": {"device_id": "walk_in_cooler_1",
                                      "importance": "always_on", "limits": {}},
                                      "returns": dict(copy.deepcopy(wc_dev), importance="always_on")})
    rule_msg = "walk_in_cooler_1: refrigeration set to flexible needs min_power_pct >= 50"
    wjson(F + "set_importance_rule_error.json", {"call": "set_importance", "args": {"device_id": "walk_in_cooler_1",
          "importance": "flexible", "limits": {"min_power_pct": 30, "max_reduce_min": 30}}, "returns": None,
          "raises": {"error": "RuleError", "message": rule_msg}})
    cap38 = dict(st(N, "with")["meter"], peak_cap_kw=38.0, target_kw=38.0)
    wjson(F + "set_peak_cap.json", {"call": "set_peak_cap", "args": {"peak_mode": "cap", "peak_cap_kw": 38.0}, "returns": cap38})
    cap_msg = "peak_mode cap needs a peak_cap_kw"
    wjson(F + "set_peak_cap_rule_error.json", {"call": "set_peak_cap", "args": {"peak_mode": "cap", "peak_cap_kw": None},
                                               "returns": None, "raises": {"error": "RuleError", "message": cap_msg}})
    undone = dict(copy.deepcopy(undo_target), status="undone")
    wjson(F + "undo.json", {"call": "undo", "args": {"decision_id": undo_target["decision_id"]}, "returns": undone})
    wjson(F + "set_context.json", {"call": "set_context", "args": {"context": CONTEXT_2}, "returns": None})
    wjson(F + "set_authority.json", {"call": "set_authority", "args": {"authority": AUTHORITY}, "returns": None})
    wjson(F + "set_preferences.json", {"call": "set_preferences", "args": {"text": CONFIG["owner_preferences"]},
                                       "returns": None})
    wjson(F + "open_escalations.json", {"call": "open_escalations", "args": {}, "returns": [esc_open]})
    wjson(F + "resolve_escalation.json", {"call": "resolve_escalation", "args": {"escalation_id": eid,
          "option_id": resolved["chosen_option_id"], "resolved_by": "claude", "rationale": resolved["rationale"]},
          "returns": resolved})
    wjson(F + "forecast.json", {"call": "forecast", "args": {"horizon_min": 120}, "returns": snapshot["forecast_kw"]})
    wjson(F + "what_if.json", {"call": "what_if", "args": wi_args, "returns": wi_effect})
    wjson(F + "snapshot.json", {"call": "snapshot", "args": {}, "returns": snapshot})
    wjson_rows(F + "run_backtest.json", {
        "call": "run_backtest",
        "note": "FAKE DATA - illustrative, label simulated, never savings. `inputs.series` is cut to the first %d days of %s to "
                "keep the file small; `returns` is the fixture backtest over the whole fixture history (2026-06 + 2026-07 to "
                "the 17th 17:30). The on_progress events FakeKitchen replays are in run_backtest_on_progress.jsonl."
                % (BACKTEST_INPUT_DAYS, BACKTEST_MONTHS[0]),
        "args": {"inputs": bt_inputs, "months": list(BACKTEST_MONTHS), "assumptions_id": "base", "on_progress": None},
        "returns": backtest})
    wjsonl(F + "run_backtest_on_progress.jsonl", bt_events)
    wjson(F + "compare_lanes.json", {"call": "compare_lanes", "args": {"without": st(N, "without"), "with_": st(N, "with")},
                                     "returns": comparison(st(N, "without"), st(N, "with"))})

    # ---------------- ai tools
    A = "ai_tools/"
    offered = [o["option_id"] for o in esc_open["options"]]
    wjson(A + "get_kitchen_state.json", {"tool": "get_kitchen_state", "input": {}, "output": snapshot})
    wjson(A + "get_forecast.json", {"tool": "get_forecast", "input": {}, "output": snapshot["forecast_kw"]})
    wjson(A + "what_if.json", {"tool": "what_if", "input": dict(wi_args, lane="with"), "output": wi_effect})
    wjson(A + "get_bill.json", {"tool": "get_bill", "input": {"period": "2026-07"}, "output": bill_with})
    wjson(A + "explain_decision.json", {"tool": "explain_decision", "input": {"decision_id": first_dec["decision_id"]},
                                        "output": first_dec})
    for tool, kind in (("propose_importance_change", "importance"), ("propose_peak_cap_change", "peak_cap"),
                       ("propose_undo", "undo_decision"),
                       ("propose_customer_event", "customer_event")):
        p = proposals_by_kind[kind]
        wjson(A + tool + ".json", {"tool": tool, "input": dict(p["payload"], summary=p["summary"]), "output": p})
    wjson(A + "get_context.json", {"tool": "get_context", "input": {}, "output": CONTEXT_2})
    wjson(A + "get_escalation.json", {"tool": "get_escalation", "input": {}, "output": [esc_open]})
    wjson(A + "choose_escalation_option.json", {"tool": "choose_escalation_option", "input_enum": {"option_id": offered},
          "input": {"option_id": resolved["chosen_option_id"], "rationale": resolved["rationale"]}, "output": resolved})
    wjson(A + "set_crowd_effect.json", {"tool": "set_crowd_effect", "input_enum": {"value": list(CROWD)},
          "input": {"value": "medium", "reason": CONTEXT_1["crowd_effect"]["reason"]}, "output": ok})

    # ---------------- ws (viewer socket)
    Wd = "ws/"
    first_engine_dec = first_dec
    chat_id = "chat_0001"
    wjson(Wd + "tick.json", {"type": "tick", "data": st(esc_n, "with")})
    wjson(Wd + "decision.json", {"type": "decision", "data": first_engine_dec, "explanation": exp_by_id[first_engine_dec["decision_id"]],
                                 "explanation_source": "template"})
    wjson(Wd + "clock.json", clock_msg(esc_n))
    wjson(Wd + "warning.json", dict({"type": "warning"}, **warning))
    wjson(Wd + "chat_delta.json", {"type": "chat_delta", "chat_id": chat_id,
                                   "text": "Tonight I kept the engine's choice for the 18:45 block"})
    wjson(Wd + "chat_done.json", {"type": "chat_done", "chat_id": chat_id})
    wjson(Wd + "backtest_progress.json", {"type": "backtest_progress", "run_id": BACKTEST_RUN, "month": "2026-07", "pct": 50})
    wjson(Wd + "backtest_point.json", {"type": "backtest_point", "run_id": BACKTEST_RUN, "data": bt_point})
    wjson(Wd + "backtest_month.json", {"type": "backtest_month", "run_id": BACKTEST_RUN, "data": bt_july})
    wjson(Wd + "comparison.json", {"type": "comparison", "data": comparison(st(N, "without"), st(N, "with"))})
    wjson(Wd + "proposal.json", {"type": "proposal", "data": proposal_pending})
    wjson(Wd + "escalation.json", escalation_message(esc_open))
    wjson(Wd + "context.json", {"type": "context", "data": CONTEXT_1})
    wjson(Wd + "agent_log.json", {"type": "agent_log", "data": logs1[0]})
    wjsonl(Wd + "stream.jsonl", E["ws"])

    # ---------------- rest
    Rr = "rest/"

    def rest(name, method, path, request, response, status=200):
        wjson(Rr + name + ".json", {"method": method, "path": path, "status": status, "request": request, "response": response})

    def err404(what):
        return {"detail": "Unknown %s" % what}
    rest("get_catalog", "GET", "/api/catalog", None, CATALOG)
    rest("post_kitchen", "POST", "/api/kitchen", CONFIG, {"kitchen_id": "k_01"})
    bad_cfg = copy.deepcopy(CONFIG)
    for eq in bad_cfg["equipment"]:
        if eq["type_id"] == "walk_in_cooler":
            eq["limits"] = {"min_power_pct": 30, "max_reduce_min": 30}
    rest("post_kitchen_422", "POST", "/api/kitchen", bad_cfg, {"detail": rule_msg}, 422)
    rest("get_kitchen", "GET", "/api/kitchen", None, {"config": CONFIG, "devices": rep(N, "with")["devices"], "tariff": TARIFF})
    rest("put_device_importance", "PUT", "/api/kitchen/devices/walk_in_cooler_1/importance",
         {"importance": "always_on", "limits": {}}, dict(copy.deepcopy(wc_dev), importance="always_on"))
    rest("put_device_importance_422", "PUT", "/api/kitchen/devices/walk_in_cooler_1/importance",
         {"importance": "flexible", "limits": {"min_power_pct": 30, "max_reduce_min": 30}}, {"detail": rule_msg}, 422)
    rest("put_device_importance_404", "PUT", "/api/kitchen/devices/pizza_oven_1/importance",
         {"importance": "always_on", "limits": {}}, err404("device pizza_oven_1"), 404)
    rest("put_peak_cap", "PUT", "/api/kitchen/peak-cap", {"peak_mode": "cap", "peak_cap_kw": 38.0}, cap38)
    rest("put_peak_cap_422", "PUT", "/api/kitchen/peak-cap", {"peak_mode": "cap", "peak_cap_kw": None}, {"detail": cap_msg}, 422)
    play = dict(clock_state(0, 1, run_ticks_for_days(1)))
    rest("post_sim_control", "POST", "/api/sim/control", {"action": "play", "speed": SPEED}, play)
    day1_close = run_ticks_for_days(1)
    next_day = dict(clock_state(day1_close, 2, run_ticks_for_days(2)))
    rest("post_sim_control_next_day", "POST", "/api/sim/control", {"action": "next_day"}, next_day)
    rest("post_sim_control_422", "POST", "/api/sim/control", {"action": "next_day"},
         {"detail": "next_day only while paused_reason is run_complete"}, 422)
    rest("post_device_command", "POST", "/api/devices/%s/command" % owner_cmd["device_id"], {"action": owner_cmd["action"]},
         owner_cmd)
    rest("post_device_command_404", "POST", "/api/devices/pizza_oven_1/command", {"action": "start"},
         err404("device pizza_oven_1"), 404)
    rest("post_events_customers", "POST", "/api/events/customers", {"customers": 40, "duration_min": 60}, ok)
    rest("post_decision_undo", "POST", "/api/decisions/%s/undo" % undo_target["decision_id"], None, undone)
    restore_dec = next(d for d in ev_decisions if d["action"] == "restore")
    rest("post_decision_undo_422", "POST", "/api/decisions/%s/undo" % restore_dec["decision_id"], None,
         {"detail": "%s: only an executed reduce or delay whose command is still in force can be undone"
                    % restore_dec["decision_id"]}, 422)
    rest("post_decision_undo_404", "POST", "/api/decisions/d_9999/undo", None, err404("decision d_9999"), 404)
    rest("get_decisions", "GET", "/api/decisions?limit=50", None, list(reversed(ev_decisions))[:50])
    rest("post_backtest_run", "POST", "/api/backtest/run", {"months": ["2026-06", "2026-07"], "assumptions_id": "base"},
         {"run_id": "run_0001"})
    rest("get_backtest", "GET", "/api/backtest/run_0001", None, backtest)
    rest("post_chat", "POST", "/api/chat", {"message": "What did you decide about tonight?"}, {"chat_id": chat_id})
    rest("get_proposals", "GET", "/api/proposals?status=pending", None, [proposal_pending])
    rest("post_proposal_confirm", "POST", "/api/proposals/p_0001/confirm", {"confirm": True}, proposal_confirmed)
    rest("put_authority", "PUT", "/api/kitchen/authority", AUTHORITY, ok)
    rest("put_preferences", "PUT", "/api/kitchen/preferences", {"text": CONFIG["owner_preferences"]}, ok)
    rest("get_context", "GET", "/api/context", None, CONTEXT_2)
    rest("post_context", "POST", "/api/context", {"ts": CONTEXT_2["ts"], "weather": CONTEXT_2["weather"]}, ok)
    rest("post_context_crowd_effect", "POST", "/api/context/crowd-effect",
         {"value": "medium", "reason": CONTEXT_1["crowd_effect"]["reason"]}, ok)
    rest("get_escalations", "GET", "/api/escalations?status=open", None, [esc_open])
    rest("post_agent_log", "POST", "/api/agent-log", logs1[0], ok)
    rest("get_health", "GET", "/api/health", None, {"ok": True, "kitchen_impl": "fake", "live_transport": "spacetime",
                                                     "store": "convex", "hardware": "off", "sim_host": "connected"})

    # ---------------- spacetime
    SP = "spacetime/"
    wjsonl(SP + "rows_stream.jsonl", E["rows"])
    last = E["rows"][-1]
    wjson(SP + "tables/live_tick.json", last["live_tick"])
    wjson(SP + "tables/tick_history.json", [tick_history_row(st(n, l)) for n in range(N - 4, N + 1) for l in LANES])
    wjson(SP + "tables/live_device.json", last["live_device"])
    wjson(SP + "tables/live_comparison.json", [last["live_comparison"]])
    feed = [feed_row(d, R.dec_lane[d["decision_id"]], exp_by_id[d["decision_id"]]) for d in ev_decisions][-50:]
    wjson(SP + "tables/live_feed.json", feed)
    clock_row = dict({"id": 0}, **clock_state(N, 1, run_ticks_for_days(1)), sim_host="connected")
    wjson(SP + "tables/live_clock.json", [clock_row])
    wjson(SP + "tables/live_context.json", [context_row(CONTEXT_2)])
    esc_latest = {}
    for e in ev_escalations + [x for n in range(1, N + 1) for x in rec[n]["after"]]:
        esc_latest[e["escalation_id"]] = e
    wjson(SP + "tables/live_escalation.json", [escalation_row(e) for _, e in sorted(esc_latest.items())])
    wjson(SP + "tables/live_agent_log.json", [dict({"id": i + 1}, **x) for i, x in enumerate(all_logs)])
    surge_row = {"id": 1, "customers": surge["customers"], "duration_min": surge["duration_min"],
                 "requested_by": "c200a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8",
                 "created_at": iso_ms(real_dt(surge_req["request_tick"], 120)), "consumed": True}
    wjson(SP + "tables/surge_request.json", [surge_row])
    red = SP + "reducers/"
    wjson(red + "publish_ticks.json", {"reducer": "publish_ticks", "args": [cj(last)]})
    wjson(red + "publish_feed.json", {"reducer": "publish_feed", "args": [cj(feed[0])]})
    wjson(red + "set_clock.json", {"reducer": "set_clock", "args": [clock_row[k] for k in SET_CLOCK_ARGS]})
    wjson(red + "publish_context.json", {"reducer": "publish_context", "args": [cj(context_row(CONTEXT_2))]})
    wjson(red + "publish_escalation.json", {"reducer": "publish_escalation", "args": [cj(escalation_row(resolved))]})
    wjson(red + "log_agent.json", {"reducer": "log_agent", "args": [cj(logs1[0])]})
    wjson(red + "reset_all.json", {"reducer": "reset_all", "args": []})
    wjson(red + "request_surge.json", {"reducer": "request_surge", "args": [surge["customers"], surge["duration_min"]]})
    wjson(red + "consume_surge.json", {"reducer": "consume_surge", "args": [1]})
    bt_point_rows = [backtest_point_row(BACKTEST_RUN, p) for p in bt_points]
    bt_month_rows = [backtest_month_row(BACKTEST_RUN, r) for r in backtest]
    wjson(SP + "tables/backtest_point.json", bt_point_rows)
    wjson(SP + "tables/backtest_month.json", bt_month_rows)
    wjson(red + "publish_backtest_point.json", {"reducer": "publish_backtest_point",
                                                "args": [cj(backtest_point_row(BACKTEST_RUN, bt_point))]})
    wjson(red + "publish_backtest_month.json", {"reducer": "publish_backtest_month",
                                                "args": [cj(backtest_month_row(BACKTEST_RUN, bt_july))]})
    wjson(red + "reset_backtest.json", {"reducer": "reset_backtest", "args": [BACKTEST_RUN]})

    # ---------------- convex
    CV = "convex/"
    wjson(CV + "tables/kitchens.json", [{"config": CONFIG, "created_at": iso_ms(real_dt(0, -2000))}])
    wjson(CV + "tables/decisions.json", [dict(copy.deepcopy(d), lane=R.dec_lane[d["decision_id"]],
                                              explanation=exp_by_id[d["decision_id"]], explanation_source="template")
                                         for d in ev_decisions])
    wjson(CV + "tables/commands.json", [dict(copy.deepcopy(c), hub_id=None,
                                             delivery="acked" if acks_by[c["command_id"]]["ok"] else "failed")
                                        for c in ev_commands if c["command_id"] in acks_by and
                                        int(c["command_id"][2:]) <= max(int(x["command_id"][2:]) for n in range(1, N + 1)
                                                                        for l in LANES for x in rep(n, l)["acks"])])
    wjson(CV + "tables/readings.json", [reading])
    wjson(CV + "tables/device_map.json", [{"hub_id": "esp32_1", "channel": 0, "device_id": "dishwasher_1", "scale": 1000}])
    wjson(CV + "tables/hubs.json", [{"hub_id": "esp32_1", "last_seen": iso_ms(real_dt(115)), "firmware": "convex-esp32/0.1"}])
    wjson(CV + "tables/proposals.json", [proposal_confirmed])
    wjson(CV + "tables/bills.json", [dict(bill_without, lane="without"), dict(bill_with, lane="with")])
    wjson(CV + "tables/backtest_results.json", [dict(b, run_id="run_0001") for b in backtest])
    blocks = []
    for l in LANES:
        for d in DEVICES:
            avg = sum(next(x["power_kw"] for x in rep(n, l)["devices"] if x["device_id"] == d["device_id"])
                      for n in block_ticks(0)) / 15
            blocks.append({"lane": l, "device_id": d["device_id"], "block_start": iso(block_start_dt(0)),
                           "avg_kw": rnd(avg, 3), "source": "simulated"})
    wjson(CV + "tables/device_blocks.json", blocks)
    wjson(CV + "tables/escalations.json", [resolved])
    wjson(CV + "tables/context_snapshots.json", [CONTEXT_2])
    fn = CV + "functions/"
    wjson(fn + "commands_forDevice.json", {"function": "commands:forDevice", "type": "query", "args": {"hub_id": "esp32_1"},
                                           "returns": []})
    wjson(fn + "commands_ack.json", {"function": "commands:ack", "type": "mutation",
                                     "args": {"command_id": first_cmd["command_id"], "ok": first_ack["ok"],
                                              "applied_value": first_ack["applied_value"], "reason": first_ack["reason"]},
                                     "returns": None})
    wjson(fn + "commands_enqueue.json", {"function": "commands:enqueue", "type": "mutation",
                                         "args": {"command": first_cmd, "lane": "with", "hub_id": None}, "returns": None})
    wjson(fn + "decisions_record.json", {"function": "decisions:record", "type": "mutation",
                                         "args": {"decisions": [dict(copy.deepcopy(first_dec), lane="with",
                                                                     explanation=exp_by_id[first_dec["decision_id"]],
                                                                     explanation_source="template")]}, "returns": None})
    wjson(fn + "proposals_upsert.json", {"function": "proposals:upsert", "type": "mutation",
                                         "args": {"proposal": proposal_confirmed}, "returns": None})
    wjson(fn + "bills_save.json", {"function": "bills:save", "type": "mutation", "args": {"bill": bill_with, "lane": "with"},
                                   "returns": None})
    wjson(fn + "backtest_save.json", {"function": "backtest:save", "type": "mutation",
                                      "args": {"run_id": "run_0001", "results": backtest}, "returns": None})
    wjson(fn + "devices_report.json", {"function": "devices:report", "type": "mutation", "args": {"reading": reading},
                                       "returns": None})
    wjson(fn + "hubs_heartbeat.json", {"function": "hubs:heartbeat", "type": "mutation", "args": {"hub_id": "esp32_1"},
                                       "returns": None})

    # ---------------- agents
    AG = "agents/"
    wjson(AG + "weather_request.json", {"lat": 37.80, "lon": -122.44, "hours": 6})
    wjson(AG + "weather_response.json", {"hourly": CONTEXT_2["weather"]["hourly"], "source": "open-meteo", "label": "recorded"})
    wjson(AG + "price_request.json", {"region": "caiso_np15", "hours": 6})
    wjson(AG + "price_response.json", {"hourly": CONTEXT_2["prices"]["hourly"], "stress": CONTEXT_2["prices"]["stress"],
                                       "source": "caiso", "label": "recorded"})
    wjson(AG + "events_request.json", {"lat": 37.80, "lon": -122.44, "radius_km": 5, "window_h": 12})
    wjson(AG + "events_response.json", {"items": CONTEXT_2["events"]["items"], "source": "demo_events", "label": "recorded"})
    wjsonl(AG + "agent_log.jsonl", all_logs)
    wjson(AG + "context_post.json", {"method": "POST", "path": "/api/context", "headers": {"X-Agent-Token": "<AGENT_TOKEN>"},
                                     "body": CONTEXT_2})

    # ---------------- scenario: evening
    def timeline_of(ticks):
        tl = []
        for n in ticks:
            r = rec[n]
            if r["post"] is not None:
                tl.append({"tick": n, "what": "recorded context posted (Context ts %s), crowd_effect %s"
                           % (r["post"]["ts"], r["post"]["crowd_effect"]["value"])})
            for s in LIVE_SURGES:
                if s["request_tick"] == n:
                    tl.append({"tick": n, "what": "judge calls request_surge(%d, %d)" % (s["customers"], s["duration_min"])})
                if s["start_tick"] == n:
                    tl.append({"tick": n, "what": "sim_tick carries surge %s (+%d customers for %d min)"
                               % (s["surge_id"], s["customers"], s["duration_min"])})
            for l in LANES:
                for d in r["states"][l]["new_decisions"]:
                    tl.append({"tick": n, "what": "%s %s %s %s%s (%s)" % (d["decision_id"], l, d["device_id"], d["action"],
                                                                           "" if d["value"] is None else " %s" % d["value"],
                                                                           d["reason_code"])})
            for e in r["states"]["with"]["new_escalations"]:
                tl.append({"tick": n, "what": "escalation %s %s for the %s block (forecast %.1f kW, target %.1f), default %s"
                           % (e["escalation_id"], e["status"], hm_str(lmin(datetime.strptime(e["block_start"],
                                                                                            "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC))),
                              e["problem"]["forecast_peak_kw"], e["problem"]["target_kw"], e["default_option_id"])})
            for e in r["after"]:
                tl.append({"tick": n, "what": "Claude answers %s: %s, chosen %s (between ticks %d and %d)"
                           % (e["escalation_id"], e["status"], e["chosen_option_id"], n, n + 1)})
        return tl
    sc_common = {"name": "Demo Café", "label": "FAKE DATA - not measured, not live", "seed": SEED,
                 "timezone": TARIFF["timezone"], "start_sim_ts": iso(START), "start_local": "2026-07-17 17:30 (Friday)",
                 "minutes_per_tick": 1, "speed": SPEED, "peak_cap_kw": CAP, "kitchen_id": "k_01", "tariff": TARIFF,
                 "warm_up": {"history": "history/warmup_demo_cafe.json", "month_to_date": None,
                             "starting_meter_from_history": init_round(init)},
                 "context_post_ticks": R.posts,
                 "initial_conditions": {"dishwasher_dirty_racks": DW_START_RACKS, "ice_level_pct": ICE_START_PCT}}
    wjson("scenario/demo_cafe/scenario.json", dict(sc_common, config=CONFIG, ticks=N, run_days=1,
                                                   timeline=timeline_of(range(1, N + 1))))
    wjson("scenario/demo_cafe/index.json", {
        "server_to_hub": "hub_protocol/server_to_hub.jsonl", "hub_to_server": "hub_protocol/hub_to_server.jsonl",
        "engine_steps": "facade/step_stream.jsonl", "spacetime_publish_ticks": "spacetime/rows_stream.jsonl",
        "viewer_ws": "ws/stream.jsonl", "agent_log": "agents/agent_log.jsonl", "warm_up": "history/warmup_demo_cafe.json",
        "daily_inputs": "history/daily_inputs.json",
        "escalation": {"open": "shapes/escalation_open.json", "resolved": "shapes/escalation_resolved_claude.json",
                       "opened_tick": esc_n},
        "owner_click_after_tick": owner_n,
        "decision_ids": ev_dec_ids, "command_ids": [c["command_id"] for c in ev_commands],
        "escalation_ids": sorted(esc_latest),
        "escalation_option_command_ids": [c["command_id"] for e in ev_escalations for o in e["options"] for c in o["actions"]],
        "standalone_example_ids": {"decision": clamp_dec_id, "command": clamp_cmd_id}})

    # ---------------- scenario: multi-day (segments of the same run, run_days 2)
    day1_tail = tick_at(utc_of_local(LIVE_DATES[0], 21 * 60 + 30))
    day2_open = tick_at(utc_of_local(LIVE_DATES[1], OPEN_M))
    day2_lunch_end = tick_at(utc_of_local(LIVE_DATES[1], 13 * 60 + 30)) - 1
    day2_close_seg = tick_at(utc_of_local(LIVE_DATES[1], CLOSE_M - 15))
    mticks = list(range(day1_tail, day2_lunch_end + 1)) + list(range(day2_close_seg, multi_last + 1))
    M = build_streams(R, mticks, MULTI_DAYS, multi_last, "multiday")
    MD = "scenario/demo_cafe_multiday/"
    wjsonl(MD + "server_to_hub.jsonl", M["s2h"])
    wjsonl(MD + "hub_to_server.jsonl", M["h2s"])
    wjsonl(MD + "step_stream.jsonl", M["steps"])
    wjsonl(MD + "rows_stream.jsonl", M["rows"])
    wjsonl(MD + "ws_stream.jsonl", M["ws"])
    wjsonl(MD + "clock_stream.jsonl", [{"reducer": "set_clock", "args": [dict(c, sim_host="connected")[k] for k in SET_CLOCK_ARGS]}
                                       for c in M["clocks"]])
    m_dec = [d for n in mticks for l in LANES for d in rec[n]["states"][l]["new_decisions"]]
    m_esc = [e for n in mticks for e in rec[n]["states"]["with"]["new_escalations"]]
    wjson(MD + "scenario.json", dict(sc_common, config=make_config(MULTI_DAYS), ticks=multi_last, run_days=MULTI_DAYS,
                                     segments=describe_segments(mticks, MULTI_DAYS, multi_last),
                                     timeline=[x for x in timeline_of(mticks) if not x["what"].startswith("judge")] +
                                     [{"tick": multi_last, "what": "day 2 closes at 22:00: clock stops, phase closed, "
                                                                   "paused_reason run_complete"}]))
    wjson(MD + "index.json", {
        "label": "FAKE DATA - not measured, not live", "run_days": MULTI_DAYS, "ticks_in_run": multi_last,
        "ticks_in_files": len(mticks), "segments": describe_segments(mticks, MULTI_DAYS, multi_last),
        "server_to_hub": MD + "server_to_hub.jsonl", "hub_to_server": MD + "hub_to_server.jsonl",
        "engine_steps": MD + "step_stream.jsonl", "spacetime_publish_ticks": MD + "rows_stream.jsonl",
        "spacetime_set_clock": MD + "clock_stream.jsonl", "viewer_ws": MD + "ws_stream.jsonl",
        "decision_ids": [d["decision_id"] for d in m_dec], "escalation_ids": sorted({e["escalation_id"] for e in m_esc}),
        "midnight_tick": tick_at(utc_of_local(LIVE_DATES[1], 0)), "day2_open_tick": day2_open,
        "full_run": "python3 contracts/fixtures/generate.py --days 2 --out <dir> writes every tick of this run"})

    # ---------------- manifest
    files = sorted(set(WRITTEN + ["MANIFEST.json", "README.md", "GAPS.md", "generate.py", "check.py"]))
    wjson("MANIFEST.json", {f: manifest_entry(f) for f in files})


def init_round(init):
    return {"energy_kwh_today": rnd(init["energy_today"], 3), "energy_kwh_month": rnd(init["energy_month"], 3),
            "month_peak_kw": rnd(init["month_peak"], 2),
            "on_peak_month_peak_kw": rnd(init["peaks"][TC.on_peak_name(init["month"][1])], 2),
            "demand_peaks": demand_peaks_of(init["peaks"], init["month"][1]),
            "energy_cost_usd_today": rnd(init["ecost_today"], 2), "energy_cost_usd_month": rnd(init["ecost_month"], 2)}


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--days" in args:
        i = args.index("--days")
        days = int(args[i + 1])
        out = os.path.abspath(args[args.index("--out") + 1]) if "--out" in args else None
        if out is None:
            raise SystemExit("usage: generate.py --days N --out DIR")
        write_days(days, out)
    else:
        main(os.path.abspath(args[0]) if args else HERE)
