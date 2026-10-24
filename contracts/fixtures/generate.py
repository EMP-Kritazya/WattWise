#!/usr/bin/env python3
"""WattWise shared fixture generator. FAKE DATA - not measured, not live.

Seeded (42), Python standard library only. Rerunning produces identical bytes.
Usage: python3 contracts/fixtures/generate.py [output_dir]   (default: this folder)

Every number here is illustrative: a toy simulation of the Demo Cafe scenario plus a scripted
"engine" for the `with` lane. Engine internals are TBD (docs/design/ENGINE.md); these are not engine output.
"""
import copy
import json
import math
import os
import random
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else HERE
DEBUG = os.environ.get("FIXTURE_DEBUG") == "1"

SEED = 42
UTC = timezone.utc
PDT = timedelta(hours=-7)                                   # America/Los_Angeles in July
START = datetime(2026, 7, 18, 0, 30, tzinfo=UTC)            # Friday 17:30 local
REAL_START = datetime(2026, 10, 25, 17, 30, tzinfo=UTC)     # illustrative wall clock for ts_real / created_at
N = 120                                                     # emitted ticks
H = 300                                                     # internal horizon (forecasts look 2 h ahead)
CAP = 40.0
LANES = ("without", "with")
REPLAN_EVERY = 5
ESCALATION_SPEED = 1        # clock speed while an escalation is open (outside demo mode)
ESC_TICK = 60
CHOICE_TICK = 61
CONTEXT_TICKS = (1, 61)     # context posted on build (used from tick 1) and refreshed at tick 61
SURGE_REQ_TICK, SURGE_START, SURGE_CUSTOMERS, SURGE_MIN = 30, 31, 40, 60


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


def sim_dt(n):        # start of the simulated minute stepped in tick n
    return START + timedelta(minutes=n - 1)


def rep_dt(n):        # HubReport ts = end of the minute just stepped
    return START + timedelta(minutes=n)


def real_dt(n, extra_ms=0):
    return REAL_START + timedelta(milliseconds=500 * n + extra_ms)


def local_hm(dt):
    return (dt + PDT).strftime("%H:%M")


def local_minutes(hm):
    h, m = hm.split(":")
    return int(h) * 60 + int(m)


def block_index(n):   # 15-min blocks aligned to :00/:15/:30/:45 local; START is aligned
    return (n - 1) // 15


def block_ticks(k):
    return range(15 * k + 1, 15 * k + 16)


def block_start_dt(k):
    return START + timedelta(minutes=15 * k)


# ----------------------------------------------------------------------------- catalog + config
CYCLE = {
    "walk_in_cooler": dict(lo=2.0, hi=4.0, a=0.10, b=0.10, rate=0.30, heater=False),
    "reach_in_fridge": dict(lo=2.0, hi=5.0, a=0.08, b=0.12, rate=0.35, heater=False),
    "freezer": dict(lo=-20.0, hi=-17.0, a=0.06, b=0.06, rate=0.25, heater=False),
    "water_heater": dict(lo=60.0, hi=64.0, a=0.15, b=0.25, rate=0.60, heater=True),
}
SETPOINT_C = 22.5


def duty(type_id):
    """Catalog duty-cycle params implied by the toy cycling physics (idle = no customers, busy = 100 customers/h)."""
    p = CYCLE[type_id]
    return {"duty_idle_pct": half_up(100 * p["a"] / p["rate"]), "duty_busy_pct": half_up(100 * (p["a"] + p["b"]) / p["rate"])}


def cat(type_id, name, category, imp, rated, model, params, limits):
    return {"type_id": type_id, "name": name, "category": category, "default_importance": imp,
            "rated_kw": rated,
            "power_model": model, "params": params, "default_limits": limits, "source_note": "PLACEHOLDER"}


CATALOG = [
    cat("hvac", "HVAC", "cooling", "flexible", 12.0, "thermal", {"setpoint_c": SETPOINT_C}, {"min_power_pct": 40, "max_reduce_min": 30}),
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

# Demo Cafe: hvac / dishwasher / fryer as in CONTRACTS.md section 1, every other catalog type at count 1 with its
# default limits. Dishwasher deadline moved to 19:30 so it falls inside the 17:30-19:30 demo window (GAPS.md G01).
SCENARIO_LIMITS = {"hvac": {"min_power_pct": 40, "max_reduce_min": 30},
                   "dishwasher": {"max_delay_min": 60, "must_finish_by": "19:30"},
                   "fryer": {}}
COUNTS = {"hvac": 2}
CONFIG = {
    "name": "Demo Café",
    "equipment": [{"type_id": c["type_id"], "count": COUNTS.get(c["type_id"], 1), "importance": c["default_importance"],
                   "limits": copy.deepcopy(SCENARIO_LIMITS.get(c["type_id"], c["default_limits"]))} for c in CATALOG],
    "peak_mode": "cap",
    "peak_cap_kw": CAP,
    "operating_hours": {"open": "10:00", "close": "22:00"},
    "location": {"lat": 37.80, "lon": -122.44, "label": "Marina, San Francisco"},
    "owner_preferences": "Keep the dining room comfortable during dinner service.",
    "authority": AUTHORITY,
    "tariff_id": "demo_tariff_v1",
    "seed": SEED,
}

TARIFF = {
    "tariff_id": "demo_tariff_v1", "name": "WattWise demo commercial rate", "label": "illustrative", "currency": "USD",
    "timezone": "America/Los_Angeles",
    "energy": [{"name": "off_peak", "start": "00:00", "end": "16:00", "usd_per_kwh": 0.22},
               {"name": "peak", "start": "16:00", "end": "21:00", "usd_per_kwh": 0.38},
               {"name": "off_peak", "start": "21:00", "end": "24:00", "usd_per_kwh": 0.22}],
    "demand": [{"name": "max_demand", "window": None, "usd_per_kw": 20.0},
               {"name": "peak_demand", "window": {"start": "16:00", "end": "21:00"}, "usd_per_kw": 8.0}],
}


def _in_window(local_min, start, end):
    return local_minutes(start) <= local_min < (1440 if end == "24:00" else local_minutes(end))


def tariff_price(dt):
    lm = local_minutes(local_hm(dt))
    return next(e["usd_per_kwh"] for e in TARIFF["energy"] if _in_window(lm, e["start"], e["end"]))


def demand_rates_for_block(k):
    """USD/kW of every demand charge whose window contains block k (15-min block from START)."""
    lm = local_minutes(local_hm(block_start_dt(k)))
    return [c for c in TARIFF["demand"] if c["window"] is None or _in_window(lm, c["window"]["start"], c["window"]["end"])]


DEVICES = []
for eq in CONFIG["equipment"]:
    c = CAT[eq["type_id"]]
    for i in range(1, eq["count"] + 1):
        DEVICES.append({"device_id": "%s_%d" % (c["type_id"], i), "type_id": c["type_id"], "name": "%s %d" % (c["name"], i),
                        "importance": eq["importance"], "limits": eq["limits"], "rated_kw": c["rated_kw"],
                        "power_model": c["power_model"], "params": c["params"]})
DEV = {d["device_id"]: d for d in DEVICES}

# ----------------------------------------------------------------------------- recorded context
TEMPS = {17: 29.1, 18: 28.4, 19: 27.2, 20: 25.8, 21: 24.1, 22: 22.9, 23: 21.8, 0: 20.9, 1: 20.2}
PRICES = {17: 0.29, 18: 0.34, 19: 0.37, 20: 0.33, 21: 0.27, 22: 0.22, 23: 0.19, 0: 0.17, 1: 0.16}
CROWD = {"none": 1.00, "small": 1.10, "medium": 1.25, "large": 1.40}
EVENT_START = datetime(2026, 7, 18, 2, 5, tzinfo=UTC)   # 19:05 local


def hour_dt(local_hour):
    base = datetime(2026, 7, 18, 0, 0, tzinfo=UTC)      # 17:00 local
    return base + timedelta(hours=(local_hour - 17) % 24)


def make_context(ts_dt, first_hour, hours=6):
    hs = [(first_hour + i) % 24 for i in range(hours)]
    return {
        "ts": iso(ts_dt),
        "weather": {"label": "recorded", "source": "open-meteo",
                    "hourly": [{"ts": iso(hour_dt(h)), "temp_c": TEMPS[h]} for h in hs]},
        "prices": {"label": "recorded", "source": "caiso",
                   "hourly": [{"ts": iso(hour_dt(h)), "usd_per_kwh": PRICES[h]} for h in hs], "stress": "high"},
        "events": {"label": "recorded", "source": "demo_events",
                   "items": [{"name": "Giants vs Dodgers", "venue": "Oracle Park", "start": iso(EVENT_START),
                              "distance_km": 1.8, "expected_attendance": 40000}]},
        "crowd_effect": {"value": "medium", "set_by": "claude", "reason": "Game ends 22:00, 1.8 km away"},
    }


CONTEXT_1 = make_context(START, 17)
CONTEXT_2 = make_context(sim_dt(61), 18)


def context_for_tick(n):
    return CONTEXT_2 if n >= 61 else CONTEXT_1


def lookup_hourly(ctx_section, key, dt):
    h = dt.replace(minute=0, second=0)
    for row in ctx_section["hourly"]:
        if row["ts"] == iso(h):
            return row[key]
    raise KeyError(iso(h))


def price_at(n):
    """The bill always uses the tariff; Context grid prices are only a market signal."""
    return tariff_price(sim_dt(n))


def tout_at(n):
    return lookup_hourly(context_for_tick(n)["weather"], "temp_c", sim_dt(n)) if n <= N else TEMPS[(sim_dt(n) + PDT).hour]


def price_any(n):
    return price_at(n)


MULT = CROWD[CONTEXT_1["crowd_effect"]["value"]]

# ----------------------------------------------------------------------------- customers (one stream, both lanes)
def base_cph(n):
    m = n - 1
    if m < 60:
        return 38 + 20 * m / 60
    if m < 180:
        return 58
    if m < 270:
        return 58 - 28 * (m - 180) / 90
    return 30


def surge_active(n):
    return SURGE_START <= n < SURGE_START + SURGE_MIN


_rng = random.Random(SEED)
NOISE = [0.0] + [_rng.gauss(0, 1.5) for _ in range(H)]
CPH_TRUE = [0] + [max(0, half_up(base_cph(n) * MULT + NOISE[n])) + (SURGE_CUSTOMERS if surge_active(n) else 0)
                  for n in range(1, H + 1)]


def cph_known(now):
    """What the engine knows at tick `now`: past customers, then the profile (+ surge once requested)."""
    out = [0]
    for k in range(1, H + 1):
        if k <= now:
            out.append(CPH_TRUE[k])
        else:
            out.append(half_up(base_cph(k) * MULT) + (SURGE_CUSTOMERS if (now >= SURGE_REQ_TICK and surge_active(k)) else 0))
    return out


# ----------------------------------------------------------------------------- simulation (toy physics)
RACKS_PER_CUSTOMER = 0.06
HVAC_BASE = 34
RACK_THRESHOLD = 8.0
MIN_PHYSICAL_PCT = 20       # appliances cannot run below 20 % (a lower reduce is clamped, ack reason out_of_range)
ICE_LOW = 25.0


def initial_state():
    r = random.Random(SEED + 1)
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
            s["level"] = 5.6 if d["type_id"] == "dishwasher" else 52.0
        st[d["device_id"]] = s
    return st


INIT = initial_state()


class Sim:
    def __init__(self):
        self.st = copy.deepcopy(INIT)

    def apply(self, cmd, n):
        """Hub applies a Command before the minute of tick n is stepped. Returns a CommandAck."""
        m = n - 1
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
            s["hold_until"] = m + v
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

    def step(self, n, cph, t_out):
        m = n - 1
        out = []
        shortfalls = []
        for d in DEVICES:
            s = self.st[d["device_id"]]
            model, rated, physical = d["power_model"], d["rated_kw"], None
            state = "on"
            if not s["on"]:
                power, state = 0.0, "off"
            elif model == "fixed":
                power = rated
            elif model == "demand_driven":
                orders = half_up(cph * 0.2)
                power = min(rated, d["params"]["idle_kw"] + d["params"]["kw_per_order"] * orders)
                physical = {"orders_in_progress": orders}
            elif model == "thermal":
                room = self.st["_room"]["temp"]
                sp = d["params"]["setpoint_c"]
                need = min(100.0, max(0.0, HVAC_BASE + 5 * (t_out - 24) + 0.1 * cph + 8 * (room - sp)))
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
                if s["remaining"] == 0:
                    ready = s["level"] >= RACK_THRESHOLD if dw else s["level"] < ICE_LOW
                    held = s["hold_until"] is not None and m < s["hold_until"]
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
            dev = {"device_id": d["device_id"], "type_id": d["type_id"], "name": d["name"], "importance": d["importance"],
                   "state": state, "power_kw": pk, "rated_kw": rated, "power_pct": half_up(100 * pk / rated),
                   "source": "simulated"}
            if physical is not None:
                dev["physical"] = physical
            out.append(dev)
        if shortfalls:
            room = self.st["_room"]
            short = sum(x for x, _ in shortfalls) / len(shortfalls)
            sp = shortfalls[0][1]
            room["temp"] += 0.002 * short if short > 0 else -0.03 * (room["temp"] - sp)
            for dev in out:
                if "indoor_temp_c" in dev.get("physical", {}):
                    dev["physical"]["indoor_temp_c"] = rnd(room["temp"], 1)
        return out


def run_plan(plan, cph, until=H):
    """plan: list of (issue_tick, device_id, action, value). Returns totals[1..until] and hvac_1 indoor temps."""
    sim = Sim()
    by_tick = {}
    for (t, dev, a, v) in plan:
        by_tick.setdefault(t + 1, []).append({"command_id": "x", "lane": "with", "device_id": dev, "action": a, "value": v})
    totals, temps = [0.0], [0.0]
    for n in range(1, until + 1):
        for c in by_tick.get(n, []):
            sim.apply(c, n)
        devs = sim.step(n, cph[n], tout_at(n))
        totals.append(rnd(sum(x["power_kw"] for x in devs), 2))
        temps.append(next(x["physical"]["indoor_temp_c"] for x in devs if x["device_id"] == "hvac_1"))
    return totals, temps


def block_avgs(totals, first_block, count):
    return [rnd(sum(totals[t] for t in block_ticks(k)) / 15, 1) for k in range(first_block, first_block + count)]


def horizon_blocks(n):
    """The 8 blocks of the 2 h after tick n (starting with the block holding tick n + 1)."""
    return block_index(n + 1), 8


def charge_peaks(totals, n):
    """Per tariff demand charge: (usd_per_kw, highest 15-min block over the 2 h horizon inside its window)."""
    first, count = horizon_blocks(n)
    out = []
    for c in TARIFF["demand"]:
        ks = [k for k in range(first, first + count) if c in demand_rates_for_block(k)]
        out.append((c["usd_per_kw"], max(block_avgs(totals, k, 1)[0] for k in ks) if ks else 0.0))
    return out


def demand_saving(before, after, n, month_peak):
    return sum(rate * max(0.0, pb - max(pa, month_peak))
               for (rate, pb), (_, pa) in zip(charge_peaks(before, n), charge_peaks(after, n)))


def demand_over(totals, n, target):
    return sum(rate * max(0.0, p - target) for rate, p in charge_peaks(totals, n))


def horizon_energy_cost(totals, n):
    return sum(totals[t] / 60 * price_any(t) for t in range(n + 1, n + 121))


# ----------------------------------------------------------------------------- the scripted "engine" (with lane)
# (issue tick, device_id, action, value, reason_code, restore tick or None). Replan ticks only.
SCRIPT = [
    (35, "dishwasher_1", "delay", 50, "avoid_new_peak", None),
    (40, "water_heater_1", "reduce", 40, "stay_under_cap", 70),
    (45, "hvac_1", "reduce", 44, "stay_under_cap", 75),
    (55, "hvac_2", "reduce", 45, "stay_under_cap", 85),
    (65, "walk_in_cooler_1", "reduce", 50, "stay_under_cap", 95),
    (75, "water_heater_1", "reduce", 40, "stay_under_cap", 105),
    (85, "hvac_1", "reduce", 50, "stay_under_cap", 115),
    (105, "hvac_2", "reduce", 45, "stay_under_cap", 135),
    (110, "water_heater_1", "reduce", 40, "stay_under_cap", 140),
    # planned beyond the emitted 120 ticks (only used by forecasts / effects)
    (125, "walk_in_cooler_1", "reduce", 50, "stay_under_cap", 155),
    (130, "hvac_1", "reduce", 40, "stay_under_cap", 160),
    (140, "water_heater_1", "reduce", 40, "stay_under_cap", 170),
    (160, "hvac_2", "reduce", 45, "stay_under_cap", 190),
]
# Escalation options evaluated at ESC_TICK; commands issued at CHOICE_TICK if chosen.
DW_DEADLINE = "19:30"
EXTEND_PAST_MIN = 20
CHOSEN = "extend_delay_dishwasher"


def routine_entries():
    ents = []
    for (t, dev, a, v, reason, rt) in SCRIPT:
        ents.append({"tick": t, "device_id": dev, "action": a, "value": v, "reason_code": reason, "parent": None})
        if rt is not None:
            ents.append({"tick": rt, "device_id": dev, "action": "restore", "value": None, "reason_code": "catch_up",
                         "parent": (t, dev)})
    return ents


def extend_delay_value():
    cycle = CAT["dishwasher"]["params"]["cycle_min"]
    start_local = local_minutes(DW_DEADLINE) + EXTEND_PAST_MIN - cycle
    start_m = start_local - local_minutes(local_hm(START))     # minute index of the new start
    applied_m = (CHOICE_TICK + 1) - 1
    return start_m - applied_m


def option_entries(option_id):
    if option_id == "accept_overrun" or option_id == "ask_owner":
        return []
    if option_id == "deep_reduce_hvac":
        return [(CHOICE_TICK, "hvac_1", "reduce", 30), (CHOICE_TICK, "hvac_2", "reduce", 30)]
    if option_id == "extend_delay_dishwasher":
        return [(CHOICE_TICK, "dishwasher_1", "delay", extend_delay_value())]
    raise ValueError(option_id)


def plan_tuple(e):
    return (e["tick"], e["device_id"], e["action"], e["value"])


def committed(entries, n, exclude=None):
    """The engine's plan as seen at tick n: every routine move it plans (its decider looks 2 h ahead), plus the
    escalation choice once it has been made. `exclude` removes one move (and its planned restore) for effects."""
    inc = [e for e in entries if (e["reason_code"] != "escalation_choice" or n >= e["tick"]) and e is not exclude]
    if exclude is not None and exclude["parent"] is None:
        inc = [e for e in inc if e["parent"] != (exclude["tick"], exclude["device_id"])]
    return [plan_tuple(e) for e in inc]


# ----------------------------------------------------------------------------- build the scenario
def build():
    W = {}                                       # results
    choice_entry = {"tick": CHOICE_TICK, "device_id": "dishwasher_1", "action": "delay", "value": extend_delay_value(),
                    "reason_code": "escalation_choice", "parent": None}
    entries = sorted(routine_entries() + [choice_entry], key=lambda e: e["tick"])   # stable
    emitted = [e for e in entries if e["tick"] <= N]

    # ---- ids: commands and decisions in issue order; escalation option commands allocated at ESC_TICK
    counters = {"c": 0, "d": 0}

    def next_id(p):
        counters[p] += 1
        return "%s_%04d" % (p, counters[p])

    by_tick = {}
    for e in emitted:
        by_tick.setdefault(e["tick"], []).append(e)

    # ---- escalation (computed at ESC_TICK from the committed plan)
    cph60 = cph_known(ESC_TICK)
    base60 = committed(entries, ESC_TICK)
    hb = horizon_blocks(ESC_TICK)
    opt_ids = ["accept_overrun", "deep_reduce_hvac", "extend_delay_dishwasher"]
    runs = {o: run_plan(base60 + option_entries(o), cph60) for o in opt_ids}
    acc_tot, acc_tmp = runs["accept_overrun"]
    acc_blocks = block_avgs(acc_tot, *hb)
    acc_cost = horizon_energy_cost(acc_tot, ESC_TICK)

    # ---- actual stream
    sims = {l: Sim() for l in LANES}
    meter_state = {"without": dict(energy=286.4, cost_today=72.85, cost_month=1907.40, month_peak=42.6),
                   "with": dict(energy=286.4, cost_today=70.12, cost_month=1835.10, month_peak=39.4)}
    bsum = {l: {} for l in LANES}
    pending = {}
    ticks = []
    decisions, commands, decision_explain = [], [], {}
    escalation = None
    option_cmds = {}
    for n in range(1, N + 1):
        cmds = pending.get(n, [])
        acks = [sims[c["lane"]].apply(c, n) for c in cmds]
        reports, states = {}, {}
        for l in LANES:
            devs = sims[l].step(n, CPH_TRUE[n], tout_at(n))
            reports[l] = {"hub_id": "sim_hub", "lane": l, "tick_id": n, "ts": iso(rep_dt(n)),
                          "total_kw": rnd(sum(d["power_kw"] for d in devs), 2), "customers_per_hour": CPH_TRUE[n],
                          "devices": devs, "acks": [a for a in acks if a["lane"] == l], "source": "simulated"}
        for l in LANES:
            ms, tot = meter_state[l], reports[l]["total_kw"]
            k = block_index(n)
            b = bsum[l].setdefault(k, [0.0, 0])
            b[0] += tot
            b[1] += 1
            block_avg = rnd(b[0] / b[1], 2)
            if n % 15 == 0:
                ms["month_peak"] = max(ms["month_peak"], block_avg)
            price = price_at(n)
            ms["energy"] += tot / 60
            ms["cost_today"] += tot / 60 * price
            ms["cost_month"] += tot / 60 * price
            meter = {"ts": iso(rep_dt(n)), "total_kw": tot, "block_avg_kw": block_avg, "block_start": iso(block_start_dt(k)),
                     "month_peak_kw": rnd(ms["month_peak"], 2), "peak_mode": CONFIG["peak_mode"], "peak_cap_kw": CAP,
                     "target_kw": CAP,
                     "energy_kwh_today": rnd(ms["energy"], 3), "price_usd_per_kwh_now": price,
                     "cost_usd_today": rnd(ms["cost_today"], 2), "cost_usd_month": rnd(ms["cost_month"], 2)}
            states[l] = {"lane": l, "ts": iso(rep_dt(n)), "hub": reports[l], "meter": meter,
                         "customers_per_hour": CPH_TRUE[n], "new_decisions": [], "new_commands": [],
                         "new_escalations": [],
                         "indoor_temp_c": next(d["physical"]["indoor_temp_c"] for d in reports[l]["devices"]
                                               if d["device_id"] == "hvac_1"),
                         "forecast_kw": None}
        ticks.append({"n": n, "cmds": cmds, "acks": acks, "reports": reports, "states": states})
        # with-lane engine moves (effects filled in afterwards)
        for e in by_tick.get(n, []):
            cid, did = next_id("c"), next_id("d")
            dec = {"decision_id": did, "ts": iso(rep_dt(n)), "device_id": e["device_id"], "action": e["action"],
                   "value": e["value"], "reason_code": e["reason_code"], "inside_rules": e["reason_code"] != "escalation_choice",
                   "status": "executed", "effect": None, "_entry": e}
            cmd = {"command_id": cid, "lane": "with", "ts": iso(rep_dt(n)), "device_id": e["device_id"],
                   "action": e["action"], "value": e["value"], "decision_id": did, "issued_by": "engine"}
            decisions.append(dec)
            commands.append(cmd)
            states["with"]["new_decisions"].append(dec)
            states["with"]["new_commands"].append(cmd)
        if n == ESC_TICK:
            for o in opt_ids:
                option_cmds[o] = []
                for (t, dev, a, v) in option_entries(o):
                    option_cmds[o].append({"command_id": next_id("c"), "lane": "with", "ts": iso(rep_dt(n)),
                                           "device_id": dev, "action": a, "value": v, "decision_id": None,
                                           "issued_by": "engine"})
        nxt = states["without"]["new_commands"] + states["with"]["new_commands"]
        if nxt:
            pending[n + 1] = nxt
        for l in LANES:
            ms = meter_state[l]
    # ---- forecasts on replan ticks (both lanes), from the plan committed at that tick
    for t in ticks:
        n = t["n"]
        if n % REPLAN_EVERY:
            continue
        ck = cph_known(n)
        for l in LANES:
            plan = committed(entries, n) if l == "with" else []
            tot, _ = run_plan(plan, ck, until=min(H, n + 135))
            t["states"][l]["forecast_kw"] = block_avgs(tot, *horizon_blocks(n))

    # ---- decision effects (re-run the forecast with and without the move)
    month_peak_at = {t["n"]: t["states"]["with"]["meter"]["month_peak_kw"] for t in ticks}
    for dec in decisions:
        e = dec.pop("_entry")
        n = e["tick"]
        ck = cph_known(n)
        bt, _ = run_plan(committed(entries, n, exclude=e), ck, until=min(H, n + 135))
        at, _ = run_plan(committed(entries, n), ck, until=min(H, n + 135))
        pb, pa = max(block_avgs(bt, *horizon_blocks(n))), max(block_avgs(at, *horizon_blocks(n)))
        saving = demand_saving(bt, at, n, month_peak_at[n]) + \
            (horizon_energy_cost(bt, n) - horizon_energy_cost(at, n))
        dec["effect"] = {"peak_before_kw": pb, "peak_after_kw": pa, "saving_usd": rnd(saving, 2)}
        decision_explain[dec["decision_id"]] = explanation(dec)

    # ---- escalation object
    esc_ts = rep_dt(ESC_TICK)
    first_over = next(i for i, v in enumerate(acc_blocks) if v > CAP)
    options = []
    for o in opt_ids:
        tot, tmp = runs[o]
        peak = max(block_avgs(tot, *hb))
        cost_delta = demand_over(tot, ESC_TICK, CAP) + (horizon_energy_cost(tot, ESC_TICK) - acc_cost)
        dtemp = max(0.0, max(tmp[k] - acc_tmp[k] for k in range(ESC_TICK + 1, ESC_TICK + 121)))
        breaks = []
        if o == "deep_reduce_hvac":
            for c in option_cmds[o]:
                breaks.append({"kind": "below_min_power", "device_id": c["device_id"],
                               "amount": DEV[c["device_id"]]["limits"]["min_power_pct"] - c["value"], "unit": "pct"})
        if o == "extend_delay_dishwasher":
            breaks.append({"kind": "past_deadline", "device_id": "dishwasher_1", "amount": EXTEND_PAST_MIN, "unit": "min"})
            # total hold, counted from the first delay the hub applied, versus the owner's max_delay_min
            first_delay = next(e for e in entries if e["device_id"] == "dishwasher_1" and e["action"] == "delay")
            held = (CHOICE_TICK + 1 - 1 + extend_delay_value()) - first_delay["tick"]
            over = held - DEV["dishwasher_1"]["limits"]["max_delay_min"]
            if over > 0:
                breaks.append({"kind": "over_max_delay", "device_id": "dishwasher_1", "amount": over, "unit": "min"})
        if peak > CAP:
            breaks.insert(0, {"kind": "cap_overrun", "amount": rnd(peak - CAP, 1), "unit": "kW"})
        summary = {"accept_overrun": "Let the peak reach %.1f kW for one block" % peak,
                   "deep_reduce_hvac": "HVAC 1 and 2 to 30 % until their planned restore",
                   "extend_delay_dishwasher": "Delay the dishwasher %d min past its deadline" % EXTEND_PAST_MIN}[o]
        options.append({"option_id": o, "summary": summary, "actions": option_cmds[o],
                        "projected": {"peak_kw": peak, "cost_delta_usd": rnd(cost_delta, 2),
                                      "max_indoor_temp_change_c": rnd(dtemp, 1)},
                        "rule_breaks": breaks, "within_authority": within_authority(breaks)})
    options.append({"option_id": "ask_owner", "summary": "Ask the owner", "actions": [], "projected": None,
                    "rule_breaks": [], "within_authority": True})
    acc_opt = options[0]
    escalation = {"escalation_id": "e_0001", "lane": "with", "ts": iso(esc_ts),
                  "block_start": iso(block_start_dt(hb[0] + first_over)),
                  "problem": {"forecast_peak_kw": max(acc_blocks), "target_kw": CAP,
                              "excess_kw": rnd(max(acc_blocks) - CAP, 1),
                              "reason": "dinner rush + customer surge + hot evening"},
                  "options": options,
                  "default_option_id": "accept_overrun" if acc_opt["within_authority"] else "ask_owner",
                  "deadline_sim_ts": iso(min(esc_ts + timedelta(minutes=15),
                                             block_start_dt(hb[0] + first_over) - timedelta(minutes=5))), "status": "open",
                  "resolved_by": None, "chosen_option_id": None, "rationale": None}
    ticks[ESC_TICK - 1]["states"]["with"]["new_escalations"].append(escalation)
    chosen = next(o for o in options if o["option_id"] == CHOSEN)
    resolved = dict(copy.deepcopy(escalation), status="resolved", resolved_by="claude", chosen_option_id=CHOSEN,
                    rationale="The owner wants a comfortable dining room tonight, so I kept HVAC as planned and moved "
                              "the dishwasher instead: projected peak %.1f kW, inside my authority."
                              % chosen["projected"]["peak_kw"])
    W.update(ticks=ticks, decisions=decisions, commands=commands, escalation=escalation, resolved=resolved,
             explain=decision_explain, entries=entries, option_cmds=option_cmds, counters=counters)
    return W


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


def explanation(dec):
    name = DEV[dec["device_id"]]["name"]
    e = dec["effect"]
    if dec["reason_code"] == "escalation_choice":
        return "Delayed %s %d min (escalation option chosen) (%.1f → %.1f kW)." % (
            name, dec["value"], e["peak_before_kw"], e["peak_after_kw"])
    if dec["action"] == "delay":
        return "Delayed %s %d min to avoid a new peak (%.1f → %.1f kW)." % (
            name, dec["value"], e["peak_before_kw"], e["peak_after_kw"])
    if dec["action"] == "reduce":
        return "Reduced %s to %d %% to stay under the cap (%.1f → %.1f kW)." % (
            name, dec["value"], e["peak_before_kw"], e["peak_after_kw"])
    return "Restored %s to normal power to repay its energy (%.1f → %.1f kW)." % (
        name, e["peak_before_kw"], e["peak_after_kw"])


# ----------------------------------------------------------------------------- writers
WRITTEN = []


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


def cj(obj):
    return None if obj is None else json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


# ----------------------------------------------------------------------------- row builders
def live_tick_row(st, n, fc, fc_ts):
    m = st["meter"]
    return {"lane": st["lane"], "ts": st["ts"], "tick_id": n, "total_kw": m["total_kw"], "block_avg_kw": m["block_avg_kw"],
            "month_peak_kw": m["month_peak_kw"], "peak_mode": m["peak_mode"], "peak_cap_kw": m["peak_cap_kw"],
            "target_kw": m["target_kw"], "energy_kwh_today": m["energy_kwh_today"],
            "price_usd_per_kwh_now": m["price_usd_per_kwh_now"], "cost_usd_today": m["cost_usd_today"],
            "cost_usd_month": m["cost_usd_month"], "customers_per_hour": st["customers_per_hour"],
            "indoor_temp_c": st["indoor_temp_c"], "forecast_kw_json": cj(fc), "forecast_ts": fc_ts}


def tick_history_row(st):
    return {"lane": st["lane"], "ts": st["ts"], "total_kw": st["meter"]["total_kw"], "block_avg_kw": st["meter"]["block_avg_kw"]}


def live_device_row(lane, d):
    return {"key": "%s:%s" % (lane, d["device_id"]), "lane": lane, "device_id": d["device_id"], "type_id": d["type_id"], "name": d["name"],
            "importance": d["importance"], "state": d["state"], "power_kw": d["power_kw"], "rated_kw": d["rated_kw"],
            "power_pct": d["power_pct"], "source": d["source"], "physical_json": cj(d.get("physical"))}


def feed_row(dec, text):
    return {"decision_id": dec["decision_id"], "lane": "with", "ts": dec["ts"], "device_id": dec["device_id"],
            "action": dec["action"], "value": dec["value"], "status": dec["status"], "reason_code": dec["reason_code"],
            "effect_json": cj(dec["effect"]), "explanation": text, "explanation_source": "template"}


def escalation_row(e):
    return {"escalation_id": e["escalation_id"], "lane": e["lane"], "status": e["status"], "problem_json": cj(e["problem"]),
            "options_json": cj(e["options"]), "chosen_option_id": e["chosen_option_id"], "resolved_by": e["resolved_by"],
            "rationale": e["rationale"]}


def context_row(c):
    w, p, ev = c["weather"], c["prices"], c["events"]
    return {"id": 0, "weather_summary": "%.1f °C now" % w["hourly"][0]["temp_c"], "weather_label": w["label"],
            "prices_summary": "%.2f USD/kWh now, stress %s" % (p["hourly"][0]["usd_per_kwh"], p["stress"]),
            "prices_label": p["label"],
            "events_summary": "; ".join("%s at %s, %.1f km" % (i["name"], i["venue"], i["distance_km"]) for i in ev["items"]),
            "events_label": ev["label"], "crowd_effect": c["crowd_effect"]["value"]}


def comparison(sw, sv):
    a, b = sw["meter"], sv["meter"]
    return {"ts": sv["ts"], "saved_today_usd": rnd(a["cost_usd_today"] - b["cost_usd_today"], 2),
            "peak_avoided_kw": rnd(a["month_peak_kw"] - b["month_peak_kw"], 2),
            "month_peak_without_kw": a["month_peak_kw"], "month_peak_with_kw": b["month_peak_kw"]}


def agent_logs(tick, ctx):
    base = real_dt(tick - 1)
    rows = [("concierge", "weather", "request", "Forecast 6 h for 37.80,-122.44"),
            ("weather", "concierge", "response", "6 hourly temperatures (recorded)"),
            ("concierge", "grid", "request", "Prices 6 h for caiso_np15"),
            ("grid", "concierge", "response", "6 hourly prices, stress %s (recorded)" % ctx["prices"]["stress"]),
            ("concierge", "events", "request", "Events within 5 km in the next 12 h"),
            ("events", "concierge", "response", "%d event: %s" % (len(ctx["events"]["items"]), ctx["events"]["items"][0]["name"])),
            ("concierge", "claude", "request", "Classify crowd effect for 1 event"),
            ("claude", "concierge", "response", "crowd_effect %s" % ctx["crowd_effect"]["value"]),
            ("concierge", "engine", "post", "Context posted to /api/context")]
    return [{"ts_real": iso_ms(base + timedelta(milliseconds=40 * (i + 1))), "from_agent": f, "to_agent": t, "kind": k,
             "summary": s} for i, (f, t, k, s) in enumerate(rows)]


# ----------------------------------------------------------------------------- main
def main():
    W = build()
    T = W["ticks"]
    st = lambda n, l: T[n - 1]["states"][l]
    rep = lambda n, l: T[n - 1]["reports"][l]
    decisions, esc, resolved = W["decisions"], W["escalation"], W["resolved"]
    dec_by_id = {d["decision_id"]: d for d in decisions}
    first_dec, first_cmd = decisions[0], W["commands"][0]
    first_ack = next(a for t in T for a in t["acks"] if a["command_id"] == first_cmd["command_id"])
    choice_dec = next(d for d in decisions if d["reason_code"] == "escalation_choice")
    surge = {"surge_id": "s_0001", "customers": SURGE_CUSTOMERS, "duration_min": SURGE_MIN}
    logs1, logs2 = agent_logs(1, CONTEXT_1), agent_logs(61, CONTEXT_2)
    all_logs = logs1 + logs2
    owner_cmd = {"command_id": "c_%04d" % (W["counters"]["c"] + 1), "lane": "with", "ts": iso(rep_dt(50)),
                 "device_id": "ice_machine_1", "action": "start", "value": None, "decision_id": None, "issued_by": "owner"}
    owner_ack = {"command_id": owner_cmd["command_id"], "lane": "with", "ok": False, "applied_value": None,
                 "reason": "job_running"}
    owner_cmd2 = {"command_id": "c_%04d" % (W["counters"]["c"] + 2), "lane": "with", "ts": iso(rep_dt(N)),
                  "device_id": "water_heater_1", "action": "reduce", "value": 10, "decision_id": None, "issued_by": "owner"}
    _probe = Sim()
    clamped_ack = _probe.apply(owner_cmd2, N + 1)
    clock = lambda n, speed=120, slowed=None: {"type": "clock", "playing": True, "speed": speed,
                                               "sim_ts": iso(START + timedelta(minutes=n)), "tick_id": n,
                                               "paused_reason": None, "slowed_reason": slowed}
    snapshot = {"config": CONFIG, "devices": rep(N, "with")["devices"], "meter": st(N, "with")["meter"],
                "context": CONTEXT_2, "recent_decisions": decisions[-10:], "open_escalations": []}
    reading = {"hub_id": "esp32_1", "channel": 0, "device_id": "dishwasher_1", "ts": iso(rep_dt(115)),
               "raw_w": 5.8, "scale": 1000, "power_kw": 5.8}
    dw_dev = next(d for d in rep(115, "with")["devices"] if d["device_id"] == "dishwasher_1")
    measured = dict(copy.deepcopy(dw_dev), power_kw=reading["power_kw"],
                    power_pct=half_up(100 * reading["power_kw"] / dw_dev["rated_kw"]), source="measured")
    proposal_pending = {"proposal_id": "p_0001", "ts": iso(rep_dt(N)), "kind": "importance",
                        "payload": {"device_id": "walk_in_cooler_1", "importance": "always_on", "limits": {}},
                        "summary": "Never touch the walk-in after 21:00", "status": "pending", "created_by": "ai",
                        "confirmed_via": None, "expires_at": iso(rep_dt(N) + timedelta(minutes=30))}
    proposal_confirmed = dict(proposal_pending, status="confirmed", confirmed_via="ui")

    def proposal(pid, kind, payload, summary, ts_n=N, expires=None):
        return {"proposal_id": pid, "ts": iso(rep_dt(ts_n)), "kind": kind, "payload": payload, "summary": summary,
                "status": "pending", "created_by": "ai", "confirmed_via": None,
                "expires_at": expires or iso(rep_dt(ts_n) + timedelta(minutes=30))}
    proposals_by_kind = {
        "importance": proposal_pending,
        "peak_cap": proposal("p_0002", "peak_cap", {"peak_mode": "cap", "peak_cap_kw": 38.0}, "Lower the cap to 38 kW"),
        "authority": proposal("p_0003", "authority", dict(AUTHORITY, max_cap_overrun_kw=2.0),
                              "Let Claude accept at most 2 kW over the cap"),
        "undo_decision": proposal("p_0004", "undo_decision", {"decision_id": first_dec["decision_id"]},
                                  "Undo the dishwasher delay"),
        "customer_event": proposal("p_0005", "customer_event",
                                   {"customers": 40, "duration_min": 60, "start_sim_ts": iso(rep_dt(N) + timedelta(minutes=30))},
                                   "40-person party at 20:00"),
        "resolve_escalation": proposal("p_0006", "resolve_escalation",
                                       {"escalation_id": esc["escalation_id"], "option_id": "deep_reduce_hvac"},
                                       "Claude suggests the deep HVAC cut (outside its authority)", ESC_TICK,
                                       esc["deadline_sim_ts"]),
    }
    awaiting = dict(copy.deepcopy(esc), status="awaiting_owner", resolved_by="claude", chosen_option_id="deep_reduce_hvac",
                    rationale="Deep HVAC cut keeps the cap but is outside my authority, so the owner decides.")
    expired = dict(copy.deepcopy(esc), status="expired_default", resolved_by="default",
                   chosen_option_id=esc["default_option_id"], rationale=None)
    owner_resolved = dict(copy.deepcopy(esc), status="resolved", resolved_by="owner", chosen_option_id="accept_overrun",
                          rationale=None)

    def bill(energy, ecost, peak):
        # the month's highest block fell inside the 16:00-21:00 window, so both demand charges bill the same peak
        dcs = [{"name": c["name"], "peak_kw": peak, "cost_usd": rnd(peak * c["usd_per_kw"], 2)} for c in TARIFF["demand"]]
        return {"period": "2026-07", "energy_kwh": energy, "energy_cost_usd": ecost, "demand_charges": dcs,
                "total_usd": rnd(ecost + sum(d["cost_usd"] for d in dcs), 2), "tariff_id": TARIFF["tariff_id"]}
    bill_without = bill(21840.0, 4210.55, 46.0)
    backtest = {"dataset": "DOE-calibrated restaurant profile (NREL ComStock)", "month": "2026-07",
                "policies": {"without": bill_without, "timer": bill(21840.0, 4206.10, 44.0),
                             "with": bill(21840.0, 4198.20, 40.0)},
                "checks": {"baseline_matches_raw": True, "energy_conserved": True, "rule_violations": 0},
                "assumptions_id": "base"}
    ok = {"ok": True}
    clock_state = {"playing": True, "speed": 120, "sim_ts": iso(START), "tick_id": 0, "paused_reason": None,
                   "slowed_reason": None}
    t50 = 50

    # ---------------- shapes
    S = "shapes/"
    wjson(S + "equipment_catalog.json", CATALOG)
    wjson(S + "kitchen_config.json", CONFIG)
    wjson(S + "kitchen_config_minimize.json", dict(copy.deepcopy(CONFIG), peak_mode="minimize", peak_cap_kw=None))
    wjson(S + "claude_authority.json", AUTHORITY)
    wjson(S + "device.json", next(d for d in rep(t50, "with")["devices"] if d["device_id"] == "hvac_1"))
    wjson(S + "device_measured.json", measured)
    wjson(S + "hub_report_with.json", rep(t50, "with"))
    wjson(S + "hub_report_without.json", rep(t50, "without"))
    wjson(S + "reading.json", reading)
    wjson(S + "command.json", first_cmd)
    wjson(S + "command_ack_ok.json", first_ack)
    wjson(S + "command_ack_rejected.json", owner_ack)
    wjson(S + "command_owner.json", owner_cmd2)
    wjson(S + "command_ack_clamped.json", clamped_ack)
    wjson(S + "tariff.json", TARIFF)
    for kind, p in proposals_by_kind.items():
        if kind != "importance":
            wjson(S + "proposal_%s.json" % kind, p)
    wjson(S + "decision.json", first_dec)
    wjson(S + "context.json", CONTEXT_1)
    wjson(S + "escalation_open.json", esc)
    wjson(S + "escalation_resolved_claude.json", resolved)
    wjson(S + "escalation_awaiting_owner.json", awaiting)
    wjson(S + "escalation_expired_default.json", expired)
    wjson(S + "meter.json", st(ESC_TICK, "with")["meter"])
    wjson(S + "tick_state_with.json", st(ESC_TICK, "with"))
    wjson(S + "tick_state_without.json", st(ESC_TICK, "without"))
    wjson(S + "lane_comparison.json", comparison(st(N, "without"), st(N, "with")))
    wjson(S + "proposal_pending.json", proposal_pending)
    wjson(S + "proposal_confirmed.json", proposal_confirmed)
    wjson(S + "bill.json", bill_without)
    wjson(S + "backtest_result.json", backtest)
    wjson(S + "agent_log.json", logs1[0])

    # ---------------- hub protocol
    P = "hub_protocol/"
    hello = {"type": "hub_hello", "protocol": 1, "hub_id": "sim_hub", "role": "sim_host", "client": "wattwise-web/0.1"}
    welcome = {"type": "hub_welcome", "accepted": True, "reason": None, "tick_id": 0}
    build_devices = [{"device_id": d["device_id"], "type_id": d["type_id"], "name": d["name"], "importance": d["importance"],
                      "state": "off", "power_kw": 0.0, "rated_kw": d["rated_kw"], "power_pct": 0, "source": "simulated"}
                     for d in DEVICES]
    sim_build = {"type": "sim_build", "kitchen_id": "k_01", "config": CONFIG, "catalog": CATALOG, "devices": build_devices,
                 "seed": SEED, "start_sim_ts": iso(START)}

    def sim_tick(n):
        ctx = context_for_tick(n)
        return {"type": "sim_tick", "tick_id": n, "sim_ts": iso(sim_dt(n)), "minutes": 1,
                "surges": [surge] if n == SURGE_START else [],
                "inputs": {"outdoor_temp_c": tout_at(n), "crowd_multiplier": CROWD[ctx["crowd_effect"]["value"]],
                           "is_open": True},
                "commands": T[n - 1]["cmds"], "replay": False}

    def hub_report_msg(n):
        return {"type": "hub_report", "tick_id": n, "reports": {"without": rep(n, "without"), "with": rep(n, "with")}}
    wjson(P + "hub_hello.json", hello)
    wjson(P + "hub_welcome_accepted.json", welcome)
    wjson(P + "hub_welcome_host_taken.json", {"type": "hub_welcome", "accepted": False, "reason": "host_taken", "tick_id": 0})
    wjson(P + "sim_build.json", sim_build)
    wjson(P + "sim_tick.json", sim_tick(SURGE_START + 5))
    wjson(P + "sim_tick_replay.json", dict(sim_tick(36), replay=True))
    wjson(P + "hub_report.json", hub_report_msg(SURGE_START + 5))
    wjson(P + "sim_control.json", {"type": "sim_control", "action": "play", "speed": 120, "paused_reason": None})
    wjsonl(P + "server_to_hub.jsonl", [welcome, sim_build] + [sim_tick(n) for n in range(1, N + 1)])
    wjsonl(P + "hub_to_server.jsonl", [hello] + [hub_report_msg(n) for n in range(1, N + 1)])

    # ---------------- facade
    F = "facade/"
    wjsonl(F + "step_stream.jsonl", [{"args": {"minutes": 1, "hub_report": rep(n, l)}, "returns": st(n, l)}
                                     for n in range(1, N + 1) for l in LANES])
    wjson(F + "kitchen.json", {"call": "Kitchen", "args": {"config": CONFIG, "tariff": TARIFF,
                                                             "control": "with", "seed": SEED}, "returns": None})
    wjson(F + "warm_up.json", {"call": "warm_up", "args": {}, "returns": None})
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
    wjson(F + "set_peak_cap.json", {"call": "set_peak_cap", "args": {"peak_mode": "cap", "peak_cap_kw": 38.0},
                                    "returns": cap38})
    cap_msg = "peak_mode cap needs a peak_cap_kw"
    wjson(F + "set_peak_cap_rule_error.json", {"call": "set_peak_cap", "args": {"peak_mode": "cap", "peak_cap_kw": None},
                                               "returns": None, "raises": {"error": "RuleError", "message": cap_msg}})
    undone = dict(copy.deepcopy(first_dec), status="undone")
    wjson(F + "undo.json", {"call": "undo", "args": {"decision_id": first_dec["decision_id"]}, "returns": undone})
    wjson(F + "set_context.json", {"call": "set_context", "args": {"context": CONTEXT_2}, "returns": None})
    wjson(F + "set_authority.json", {"call": "set_authority", "args": {"authority": AUTHORITY}, "returns": None})
    wjson(F + "set_preferences.json", {"call": "set_preferences", "args": {"text": CONFIG["owner_preferences"]},
                                       "returns": None})
    wjson(F + "open_escalations.json", {"call": "open_escalations", "args": {}, "returns": [esc]})
    wjson(F + "resolve_escalation.json", {"call": "resolve_escalation", "args": {"escalation_id": esc["escalation_id"],
          "option_id": CHOSEN, "resolved_by": "claude", "rationale": resolved["rationale"]}, "returns": resolved})
    wjson(F + "forecast.json", {"call": "forecast", "args": {"horizon_min": 120}, "returns": st(N, "with")["forecast_kw"]})
    # what_if: water heater reduce at tick 80, computed like a decision effect, no state change
    wi_n = 80
    ck = cph_known(wi_n)
    wi_base = committed(W["entries"], wi_n)
    bt, _ = run_plan(wi_base, ck, until=wi_n + 135)
    at, _ = run_plan(wi_base + [(wi_n, "walk_in_cooler_1", "reduce", 50)], ck, until=wi_n + 135)
    pb, pa = max(block_avgs(bt, *horizon_blocks(wi_n))), max(block_avgs(at, *horizon_blocks(wi_n)))
    mp = st(wi_n, "with")["meter"]["month_peak_kw"]
    effect = {"peak_before_kw": pb, "peak_after_kw": pa,
              "saving_usd": rnd(demand_saving(bt, at, wi_n, mp) +
                                horizon_energy_cost(bt, wi_n) - horizon_energy_cost(at, wi_n), 2)}
    wi_args = {"device_id": "walk_in_cooler_1", "action": "reduce", "value": 50, "at": iso(rep_dt(wi_n))}
    wjson(F + "what_if.json", {"call": "what_if", "args": wi_args, "returns": effect})
    wjson(F + "snapshot.json", {"call": "snapshot", "args": {}, "returns": snapshot})
    wjson(F + "run_backtest.json", {"call": "run_backtest", "args": {"months": ["2026-07"], "assumptions_id": "base",
                                    "on_progress": None}, "returns": [backtest]})
    wjson(F + "compare_lanes.json", {"call": "compare_lanes", "args": {"without": st(N, "without"), "with_": st(N, "with")},
                                     "returns": comparison(st(N, "without"), st(N, "with"))})

    # ---------------- ai tools
    A = "ai_tools/"
    offered = [o["option_id"] for o in esc["options"]]
    wjson(A + "get_kitchen_state.json", {"tool": "get_kitchen_state", "input": {}, "output": snapshot})
    wjson(A + "get_forecast.json", {"tool": "get_forecast", "input": {}, "output": st(N, "with")["forecast_kw"]})
    wjson(A + "what_if.json", {"tool": "what_if", "input": wi_args, "output": effect})
    wjson(A + "get_bill.json", {"tool": "get_bill", "input": {"period": "2026-07"}, "output": bill_without})
    wjson(A + "explain_decision.json", {"tool": "explain_decision", "input": {"decision_id": first_dec["decision_id"]},
                                        "output": first_dec})
    for tool, kind in (("propose_importance_change", "importance"), ("propose_peak_cap_change", "peak_cap"),
                       ("propose_escalation_choice", "resolve_escalation"), ("propose_undo", "undo_decision"),
                       ("propose_customer_event", "customer_event")):
        p = proposals_by_kind[kind]
        wjson(A + tool + ".json", {"tool": tool, "input": dict(p["payload"], summary=p["summary"]), "output": p})
    wjson(A + "get_context.json", {"tool": "get_context", "input": {}, "output": CONTEXT_2})
    wjson(A + "get_escalation.json", {"tool": "get_escalation", "input": {}, "output": [esc]})
    wjson(A + "choose_escalation_option.json", {"tool": "choose_escalation_option",
          "input_enum": {"option_id": offered},
          "input": {"option_id": CHOSEN, "rationale": resolved["rationale"]}, "output": resolved})
    wjson(A + "set_crowd_effect.json", {"tool": "set_crowd_effect", "input_enum": {"value": list(CROWD)},
          "input": {"value": "medium", "reason": CONTEXT_1["crowd_effect"]["reason"]}, "output": ok})

    # ---------------- ws (viewer socket)
    Wd = "ws/"
    tick_msg = lambda s: {"type": "tick", "data": s}
    dec_msg = lambda d: {"type": "decision", "data": d, "explanation": W["explain"][d["decision_id"]],
                         "explanation_source": "template"}
    chat_id = "chat_0001"
    wjson(Wd + "tick.json", tick_msg(st(ESC_TICK, "with")))
    wjson(Wd + "decision.json", dec_msg(first_dec))
    wjson(Wd + "clock.json", clock(ESC_TICK, ESCALATION_SPEED, "escalation"))
    wjson(Wd + "warning.json", {"type": "warning", "code": "cap_unreachable",
                                "message": "Your always-on equipment alone needs 44 kW. Raise the cap or change an importance.",
                                "data": {"unavoidable_kw": 44.0, "peak_cap_kw": CAP}})
    wjson(Wd + "chat_delta.json", {"type": "chat_delta", "chat_id": chat_id,
                                   "text": "Tonight I delayed the dishwasher past its deadline instead of cutting HVAC"})
    wjson(Wd + "chat_done.json", {"type": "chat_done", "chat_id": chat_id})
    wjson(Wd + "backtest_progress.json", {"type": "backtest_progress", "run_id": "run_0001", "month": "2026-07", "pct": 40})
    wjson(Wd + "comparison.json", {"type": "comparison", "data": comparison(st(N, "without"), st(N, "with"))})
    wjson(Wd + "proposal.json", {"type": "proposal", "data": proposal_pending})
    wjson(Wd + "escalation.json", {"type": "escalation", "data": esc})
    wjson(Wd + "context.json", {"type": "context", "data": CONTEXT_1})
    wjson(Wd + "agent_log.json", {"type": "agent_log", "data": logs1[0]})
    stream = [clock(0), {"type": "context", "data": CONTEXT_1}] + \
        [{"type": "agent_log", "data": x} for x in logs1]
    for n in range(1, N + 1):
        if n == 61:
            stream += [{"type": "agent_log", "data": x} for x in logs2] + [{"type": "context", "data": CONTEXT_2}]
        stream += [tick_msg(st(n, "without")), tick_msg(st(n, "with")),
                   {"type": "comparison", "data": comparison(st(n, "without"), st(n, "with"))}]
        stream += [dec_msg(d) for d in st(n, "with")["new_decisions"]]
        stream += [{"type": "escalation", "data": e} for e in st(n, "with")["new_escalations"]]
        if n == ESC_TICK:
            # outside demo mode the clock slows to ESCALATION_SPEED while the escalation is open (no pause)
            stream += [clock(n, ESCALATION_SPEED, "escalation"), {"type": "escalation", "data": resolved}, clock(n)]
    wjsonl(Wd + "stream.jsonl", stream)

    # ---------------- rest
    R = "rest/"

    def rest(name, method, path, request, response, status=200):
        wjson(R + name + ".json", {"method": method, "path": path, "status": status, "request": request, "response": response})
    err404 = lambda what: {"detail": "Unknown %s" % what}
    rest("get_catalog", "GET", "/api/catalog", None, CATALOG)
    rest("post_kitchen", "POST", "/api/kitchen", CONFIG, {"kitchen_id": "k_01"})
    bad_cfg = copy.deepcopy(CONFIG)
    for eq in bad_cfg["equipment"]:
        if eq["type_id"] == "walk_in_cooler":
            eq["limits"] = {"min_power_pct": 30, "max_reduce_min": 30}
    rest("post_kitchen_422", "POST", "/api/kitchen", bad_cfg, {"detail": rule_msg}, 422)
    rest("get_kitchen", "GET", "/api/kitchen", None, {"config": CONFIG, "devices": rep(N, "with")["devices"],
                                                     "tariff": TARIFF})
    rest("put_device_importance", "PUT", "/api/kitchen/devices/walk_in_cooler_1/importance",
         {"importance": "always_on", "limits": {}}, dict(copy.deepcopy(wc_dev), importance="always_on"))
    rest("put_device_importance_422", "PUT", "/api/kitchen/devices/walk_in_cooler_1/importance",
         {"importance": "flexible", "limits": {"min_power_pct": 30, "max_reduce_min": 30}}, {"detail": rule_msg}, 422)
    rest("put_device_importance_404", "PUT", "/api/kitchen/devices/pizza_oven_1/importance",
         {"importance": "always_on", "limits": {}}, err404("device pizza_oven_1"), 404)
    rest("put_peak_cap", "PUT", "/api/kitchen/peak-cap", {"peak_mode": "cap", "peak_cap_kw": 38.0}, cap38)
    rest("put_peak_cap_422", "PUT", "/api/kitchen/peak-cap", {"peak_mode": "cap", "peak_cap_kw": None},
         {"detail": cap_msg}, 422)
    rest("post_sim_control", "POST", "/api/sim/control", {"action": "play", "speed": 120}, clock_state)
    rest("post_device_command", "POST", "/api/devices/ice_machine_1/command", {"action": "start"}, owner_cmd)
    rest("post_device_command_404", "POST", "/api/devices/pizza_oven_1/command", {"action": "start"},
         err404("device pizza_oven_1"), 404)
    rest("post_events_customers", "POST", "/api/events/customers", {"customers": 40, "duration_min": 60}, ok)
    rest("post_decision_undo", "POST", "/api/decisions/%s/undo" % first_dec["decision_id"], None, undone)
    rest("post_decision_undo_404", "POST", "/api/decisions/d_9999/undo", None, err404("decision d_9999"), 404)
    rest("get_decisions", "GET", "/api/decisions?limit=50", None, list(reversed(decisions))[:50])
    rest("post_backtest_run", "POST", "/api/backtest/run", {"months": ["2026-07"], "assumptions_id": "base"},
         {"run_id": "run_0001"})
    rest("get_backtest", "GET", "/api/backtest/run_0001", None, [backtest])
    rest("post_chat", "POST", "/api/chat", {"message": "What did you decide about tonight?"}, {"chat_id": chat_id})
    rest("get_proposals", "GET", "/api/proposals?status=pending", None, [proposal_pending])
    rest("post_proposal_confirm", "POST", "/api/proposals/p_0001/confirm", {"confirm": True}, proposal_confirmed)
    rest("put_authority", "PUT", "/api/kitchen/authority", AUTHORITY, ok)
    rest("put_preferences", "PUT", "/api/kitchen/preferences", {"text": CONFIG["owner_preferences"]}, ok)
    rest("get_context", "GET", "/api/context", None, CONTEXT_2)
    rest("post_context", "POST", "/api/context", {"ts": CONTEXT_2["ts"], "weather": CONTEXT_2["weather"]}, ok)
    rest("post_context_crowd_effect", "POST", "/api/context/crowd-effect",
         {"value": "medium", "reason": CONTEXT_1["crowd_effect"]["reason"]}, ok)
    rest("get_escalations", "GET", "/api/escalations?status=open", None, [esc])
    rest("post_escalation_resolve", "POST", "/api/escalations/e_0001/resolve", {"option_id": "accept_overrun"},
         owner_resolved)
    rest("post_agent_log", "POST", "/api/agent-log", logs1[0], ok)
    rest("get_health", "GET", "/api/health", None, {"ok": True, "kitchen_impl": "fake", "live_transport": "spacetime",
                                                     "store": "convex", "hardware": "off", "sim_host": "connected"})

    # ---------------- spacetime
    SP = "spacetime/"

    latest_fc = {}
    for n in range(1, N + 1):
        for l in LANES:
            if st(n, l)["forecast_kw"] is not None:
                latest_fc[(n, l)] = (st(n, l)["forecast_kw"], st(n, l)["ts"])
            else:
                latest_fc[(n, l)] = latest_fc.get((n - 1, l), (None, None))

    def payload(n):
        sw, sv = st(n, "without"), st(n, "with")
        return {"live_tick": [live_tick_row(sw, n, *latest_fc[(n, "without")]), live_tick_row(sv, n, *latest_fc[(n, "with")])],
                "tick_history": [tick_history_row(sw), tick_history_row(sv)],
                "live_device": [live_device_row(l, d) for l in LANES for d in rep(n, l)["devices"]],
                "live_comparison": dict({"id": 0}, **comparison(sw, sv))}
    wjsonl(SP + "rows_stream.jsonl", [payload(n) for n in range(1, N + 1)])
    last = payload(N)
    wjson(SP + "tables/live_tick.json", last["live_tick"])
    wjson(SP + "tables/tick_history.json", [tick_history_row(st(n, l)) for n in range(N - 4, N + 1) for l in LANES])
    wjson(SP + "tables/live_device.json", last["live_device"])
    wjson(SP + "tables/live_comparison.json", [last["live_comparison"]])
    feed = [feed_row(d, W["explain"][d["decision_id"]]) for d in decisions]
    wjson(SP + "tables/live_feed.json", feed)
    clock_row = {"id": 0, "playing": True, "speed": 120, "sim_ts": iso(START + timedelta(minutes=N)), "tick_id": N,
                 "paused_reason": None, "slowed_reason": None, "sim_host": "connected"}
    wjson(SP + "tables/live_clock.json", [clock_row])
    wjson(SP + "tables/live_context.json", [context_row(CONTEXT_2)])
    wjson(SP + "tables/live_escalation.json", [escalation_row(resolved)])
    wjson(SP + "tables/live_agent_log.json", [dict({"id": i + 1}, **x) for i, x in enumerate(all_logs)])
    surge_row = {"id": 1, "customers": SURGE_CUSTOMERS, "duration_min": SURGE_MIN,
                 "requested_by": "c200a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8",
                 "created_at": iso_ms(real_dt(SURGE_REQ_TICK, 120)), "consumed": True}
    wjson(SP + "tables/surge_request.json", [surge_row])
    red = SP + "reducers/"
    wjson(red + "publish_ticks.json", {"reducer": "publish_ticks", "args": [cj(last)]})
    wjson(red + "publish_feed.json", {"reducer": "publish_feed", "args": [cj(feed[0])]})
    wjson(red + "set_clock.json", {"reducer": "set_clock", "args": [clock_row[k] for k in
                                   ("playing", "speed", "sim_ts", "tick_id", "paused_reason",
                                                             "slowed_reason", "sim_host")]})
    wjson(red + "publish_context.json", {"reducer": "publish_context", "args": [cj(context_row(CONTEXT_2))]})
    wjson(red + "publish_escalation.json", {"reducer": "publish_escalation", "args": [cj(escalation_row(resolved))]})
    wjson(red + "log_agent.json", {"reducer": "log_agent", "args": [cj(logs1[0])]})
    wjson(red + "reset_all.json", {"reducer": "reset_all", "args": []})
    wjson(red + "request_surge.json", {"reducer": "request_surge", "args": [SURGE_CUSTOMERS, SURGE_MIN]})
    wjson(red + "consume_surge.json", {"reducer": "consume_surge", "args": [1]})

    # ---------------- convex
    CV = "convex/"
    wjson(CV + "tables/kitchens.json", [{"config": CONFIG, "created_at": iso_ms(real_dt(0, -2000))}])
    wjson(CV + "tables/decisions.json", [dict(copy.deepcopy(d), lane="with", explanation=W["explain"][d["decision_id"]],
                                              explanation_source="template") for d in decisions])
    acks_by = {a["command_id"]: a for t in T for a in t["acks"]}
    wjson(CV + "tables/commands.json", [dict(copy.deepcopy(c), hub_id=None,
                                             delivery="acked" if acks_by[c["command_id"]]["ok"] else "failed")
                                        for c in W["commands"] if c["command_id"] in acks_by])
    wjson(CV + "tables/readings.json", [reading])
    wjson(CV + "tables/device_map.json", [{"hub_id": "esp32_1", "channel": 0, "device_id": "dishwasher_1", "scale": 1000}])
    wjson(CV + "tables/hubs.json", [{"hub_id": "esp32_1", "last_seen": iso_ms(real_dt(115)), "firmware": "convex-esp32/0.1"}])
    wjson(CV + "tables/proposals.json", [proposal_confirmed])
    wjson(CV + "tables/bills.json", [dict(bill_without, lane="without")])
    wjson(CV + "tables/backtest_results.json", [dict(backtest, run_id="run_0001")])
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
                                     "args": {"command_id": first_cmd["command_id"], "ok": True,
                                              "applied_value": first_ack["applied_value"], "reason": first_ack["reason"]},
                                     "returns": None})
    wjson(fn + "commands_enqueue.json", {"function": "commands:enqueue", "type": "mutation",
                                         "args": {"command": first_cmd, "lane": "with", "hub_id": None}, "returns": None})
    wjson(fn + "decisions_record.json", {"function": "decisions:record", "type": "mutation",
                                         "args": {"decisions": [dict(copy.deepcopy(first_dec), lane="with",
                                                                     explanation=W["explain"][first_dec["decision_id"]],
                                                                     explanation_source="template")]}, "returns": None})
    wjson(fn + "proposals_upsert.json", {"function": "proposals:upsert", "type": "mutation",
                                         "args": {"proposal": proposal_confirmed}, "returns": None})
    wjson(fn + "bills_save.json", {"function": "bills:save", "type": "mutation",
                                   "args": {"bill": bill_without, "lane": "without"}, "returns": None})
    wjson(fn + "backtest_save.json", {"function": "backtest:save", "type": "mutation",
                                      "args": {"run_id": "run_0001", "results": [backtest]}, "returns": None})
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

    # ---------------- scenario
    timeline = [{"tick": 0, "what": "sim_build; recorded context posted (Context ts %s), crowd_effect medium" % CONTEXT_1["ts"]},
                {"tick": SURGE_REQ_TICK, "what": "judge calls request_surge(40, 60) (surge_request id 1)"},
                {"tick": SURGE_START, "what": "sim_tick carries surge s_0001 (+40 customers for 60 min)"}]
    for d in decisions:
        timeline.append({"tick": int(next(t["n"] for t in T if d in t["states"]["with"]["new_decisions"])),
                         "what": "%s %s %s %s (%s)" % (d["decision_id"], d["device_id"], d["action"],
                                                        "" if d["value"] is None else d["value"], d["reason_code"])})
    timeline.append({"tick": ESC_TICK, "what": "escalation e_0001 opens (forecast peak %.1f kW > cap); clock slows to %dx (slowed_reason escalation); "
                     "Claude chooses %s within authority" % (esc["problem"]["forecast_peak_kw"], ESCALATION_SPEED, CHOSEN)})
    timeline.append({"tick": 61, "what": "periodic context refresh (Context ts %s)" % CONTEXT_2["ts"]})
    timeline.sort(key=lambda x: x["tick"])
    wjson("scenario/demo_cafe/scenario.json", {
        "name": "Demo Café", "label": "FAKE DATA - not measured, not live", "seed": SEED,
        "timezone": "America/Los_Angeles", "start_sim_ts": iso(START), "start_local": "2026-07-17 17:30 (Friday)",
        "ticks": N, "minutes_per_tick": 1, "speed": 120, "peak_cap_kw": CAP, "kitchen_id": "k_01", "config": CONFIG,
        "tariff": TARIFF,
        "illustrative_constants": {
                                   "initial_meter": {"without": {"energy_kwh_today": 286.4, "cost_usd_today": 72.85,
                                                                 "cost_usd_month": 1907.40, "month_peak_kw": 42.6},
                                                     "with": {"energy_kwh_today": 286.4, "cost_usd_today": 70.12,
                                                              "cost_usd_month": 1835.10, "month_peak_kw": 39.4}}},
        "timeline": timeline})
    wjson("scenario/demo_cafe/index.json", {
        "server_to_hub": "hub_protocol/server_to_hub.jsonl", "hub_to_server": "hub_protocol/hub_to_server.jsonl",
        "engine_steps": "facade/step_stream.jsonl", "spacetime_publish_ticks": "spacetime/rows_stream.jsonl",
        "viewer_ws": "ws/stream.jsonl", "agent_log": "agents/agent_log.jsonl",
        "escalation": {"open": "shapes/escalation_open.json", "resolved": "shapes/escalation_resolved_claude.json"},
        "decision_ids": [d["decision_id"] for d in decisions],
        "command_ids": [c["command_id"] for c in W["commands"]],
        "escalation_option_command_ids": [c["command_id"] for o in W["option_cmds"].values() for c in o]})

    # ---------------- manifest
    files = sorted(set(WRITTEN + ["MANIFEST.json", "README.md", "GAPS.md", "generate.py", "check.py"]))
    wjson("MANIFEST.json", {f: manifest_entry(f) for f in files})


MAN = [
    ("shapes/", "§1 Shared shapes", ["Ashirwad", "Suyog", "Kritazya"], "all"),
    ("hub_protocol/server_to_hub.jsonl", "§8 Hub protocol", ["Ashirwad (src/mocks/mockHubServer.ts)", "Kritazya"], "S6"),
    ("hub_protocol/hub_to_server.jsonl", "§8 Hub protocol", ["Suyog (fakes/fake_hub_client.py)", "Kritazya (engine input)"], "S6"),
    ("hub_protocol/", "§8 Hub protocol", ["Ashirwad", "Suyog", "Kritazya"], "S6"),
    ("rest/", "§2 REST", ["Ashirwad (src/mocks REST handlers)", "Suyog (API tests)"], "S1"),
    ("ws/", "§2 WebSocket /ws", ["Ashirwad (src/mocks, /ws fallback hook)", "Suyog (API tests)"], "S1"),
    ("facade/", "§3 Engine facade (PROVISIONAL)", ["Suyog (fakes/fake_kitchen.py)", "Kritazya (engine tests)"], "S2"),
    ("ai_tools/", "§4 AI tools", ["Suyog (agent/tools.py tests)"], "S2 via API"),
    ("spacetime/", "§5 SpacetimeDB", ["Ashirwad (mock live hook)", "Kritazya (fakes/fake_live.py, spacetime/seed.ts)"], "S3"),
    ("convex/", "§6 Convex", ["Suyog (store/, STORE=memory seed)"], "S4"),
    ("agents/", "§7 Agent messages", ["Suyog (agents --recorded)"], "S5"),
    ("scenario/", "Demo Café scenario (DEMO.md)", ["Kritazya", "Suyog", "Ashirwad"], "all"),
]


def manifest_entry(f):
    for prefix, section, consumers, seam in MAN:
        if f.startswith(prefix):
            return {"contract_section": section, "consumers": consumers, "seam": seam}
    return {"contract_section": "meta", "consumers": ["everyone"], "seam": "-"}


if __name__ == "__main__":
    main()
