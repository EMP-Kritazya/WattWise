"""Simulated devices: one object per unit, power from its power model each step (design/SIMULATION.md).

Physical, not clever: no optimisation here. Deterministic (each device has its own seeded RNG), no clock, no I/O.
Power is never negative and never above `rated_kw`. Commands arrive only through the hub.

Power models (per step, `minutes` long):
  fixed          rated_kw while the restaurant is open, else 0.
  cycling        compressor/element on or idling; the on-share (duty) rises with how busy the kitchen is. Runs 24 h.
  thermal        HVAC holding a setpoint: simple RC room model, electrical power = cooling needed / COP.
  demand_driven  idle_kw + kw_per_order × orders being cooked, capped at rated_kw; off when closed.
  job            runs rated_kw for cycle_min when triggered (dirty racks for the dishwasher, low ice for the ice machine).

Commands (from the hub): off · on / restore (back to normal) · reduce (value = % of the power it would otherwise draw;
never below the device's min_power_pct) · delay (value = minutes; a pending or running job waits, then runs in full) ·
start (a job device starts a job now).

Owed energy (ENGINE.md 6b): while reduced, a flexible device adds the energy it didn't draw to `owed_kwh`. Once restored
it recovers like real equipment does, drawing up to 25 % of rated extra until the debt is repaid; the decider controls
*when* by choosing when to restore. Anything still owed 30 min before close is repaid regardless, so the ledger is 0 at close.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from engine.hub import Command, DeviceReading, DeviceState, DeviceView, Importance

POWER_MODELS = ("fixed", "cycling", "thermal", "demand_driven", "job")
LOCAL_TZ = ZoneInfo("America/Los_Angeles")  # restaurant time for opening hours and daily curves
FOOD_SAFETY_MIN_PCT = 50  # refrigeration can never be reduced below this
CATCH_UP_SHARE = 0.25  # extra draw while repaying owed energy, as a share of rated_kw
BUSY_REF_CPH = 70.0  # customers/hour that counts as "fully busy" for duty cycles
HVAC_COP = 3.0


def parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def local_hour(ts: str) -> float:
    t = parse_ts(ts).astimezone(LOCAL_TZ)
    return t.hour + t.minute / 60 + t.second / 3600


def hhmm(s: str) -> float:
    h, m = s.split(":")
    return int(h) + int(m) / 60


def summer_outdoor_c(hour: float) -> float:
    """Fixed summer-day curve used when context gives no outdoor temperature: ~17 °C at night, ~27 °C at 3 PM."""
    return 22.0 + 5.0 * math.sin(math.pi * (hour - 9.0) / 12.0)


@dataclass
class SimDevice:
    """One unit, e.g. `hvac_1`. Built from a KitchenConfig entry plus its EquipmentType."""

    device_id: str
    type_id: str
    name: str
    category: str
    importance: Importance
    limits: dict
    rated_kw: float
    power_model: str
    params: dict
    open_h: float
    close_h: float
    rng: random.Random = field(repr=False)
    # share of the restaurant's food orders this device cooks (set by the hub for demand_driven devices)
    cook_share: float = 0.0

    # live state
    state: DeviceState = "off"
    power_kw: float = 0.0
    source: str = "simulated"
    owed_kwh: float = 0.0
    measured_kw: float | None = None  # a real reading for the next step only

    # command state
    _off: bool = False
    _reduce_pct: float | None = None
    _delay_until: datetime | None = None

    # model state
    _busy_cph: float = 0.0  # smoothed customers/hour
    _cooking: list[float] = field(default_factory=list)  # minutes left per order in progress
    _indoor_c: float | None = None
    _job_left_min: float = 0.0  # minutes of the current job still to run
    _job_pending: bool = False  # a job is due but hasn't started (e.g. delayed)
    _dirty_racks: float = 0.0
    _ice_level: float = 1.0

    # ---------------------------------------------------------------- commands

    def apply(self, command: Command) -> None:
        action, value = command["action"], command["value"]
        at = parse_ts(command["ts"])
        if action == "off":
            self._off = True
        elif action in ("on", "restore"):
            self._off = False
            self._reduce_pct = None
            self._delay_until = None
        elif action == "reduce":
            self._reduce_pct = max(float(value if value is not None else 100), self.min_power_pct())
        elif action == "delay":
            self._delay_until = at + timedelta(minutes=float(value or 0))
            if self._job_left_min > 0:  # a running job pauses and resumes later, in full
                self._job_pending = True
        elif action == "start":
            self._off = False
            self._delay_until = None
            if self.power_model == "job" and self._job_left_min <= 0:
                self._job_left_min = float(self.params.get("cycle_min", 30))
            self._job_pending = False

    def min_power_pct(self) -> float:
        floor = float(self.limits.get("min_power_pct", 0) or 0)
        if self.category == "refrigeration":
            floor = max(floor, FOOD_SAFETY_MIN_PCT)
        return floor

    # ---------------------------------------------------------------- step

    def step(self, *, ts: str, minutes: int, orders: float, outdoor_temp_c: float | None) -> None:
        """Advance `minutes` starting at `ts`. `orders`: new food orders this step (whole restaurant)."""
        hours = minutes / 60
        hour = local_hour(ts)
        is_open = self.open_h <= hour < self.close_h
        now = parse_ts(ts)

        # Smoothed busyness from customer orders (orders ≈ customers), time constant ~30 min.
        cph = orders / hours if hours else 0.0
        alpha = min(1.0, minutes / 30)
        self._busy_cph += (cph - self._busy_cph) * alpha
        busy = min(1.5, self._busy_cph / BUSY_REF_CPH)

        natural, state = self._natural(now, hour, hours, minutes, is_open, orders, busy, outdoor_temp_c)

        power = natural
        if self._off:
            power, state = 0.0, "off"
        elif self._reduce_pct is not None and self.power_model != "job":
            power = natural * self._reduce_pct / 100
            if power < natural:
                state = "reduced"
                if self.importance == "flexible":
                    self.owed_kwh += (natural - power) * hours
        elif self.owed_kwh > 1e-12 and natural > 0:
            # Recovery after a reduction: repay owed energy (faster near close so the ledger is 0 by then).
            near_close = self.close_h - 0.5 <= hour < self.close_h
            rate = self.rated_kw - natural if near_close else min(self.rated_kw - natural, CATCH_UP_SHARE * self.rated_kw)
            extra = max(0.0, min(rate, self.owed_kwh / hours if hours else 0.0))
            power = natural + extra
            self.owed_kwh = max(0.0, self.owed_kwh - extra * hours)

        if self.measured_kw is not None:  # a real ESP32 reading overrides the model for this step
            power, self.source = self.measured_kw, "measured"
            self.measured_kw = None
        else:
            self.source = "simulated"

        self.power_kw = min(self.rated_kw, max(0.0, power))
        self.state = state

    def _natural(self, now, hour, hours, minutes, is_open, orders, busy, outdoor_temp_c) -> tuple[float, DeviceState]:
        rated, p = self.rated_kw, self.params
        model = self.power_model

        if model == "fixed":
            return (rated, "on") if is_open else (0.0, "off")

        if model == "cycling":
            duty_idle = float(p.get("duty_idle", 0.3))
            duty_busy = float(p.get("duty_busy", 0.6))
            duty = duty_idle + (duty_busy - duty_idle) * min(1.0, busy)
            on = self.rng.random() < duty
            return (rated if on else rated * 0.1), "on"

        if model == "thermal":
            setpoint = float(p.get("setpoint_c", 22.0))
            r = float(p.get("r_c_per_kw", 0.25))  # °C per kW of heat flow through the envelope
            c = float(p.get("c_kwh_per_c", 3.0))  # kWh of heat per °C of room temperature
            gain = float(p.get("internal_gain_kw", 6.0))  # heat from diners and cooking when fully busy
            t_out = outdoor_temp_c if outdoor_temp_c is not None else summer_outdoor_c(hour)
            if self._indoor_c is None:
                self._indoor_c = setpoint
            if not is_open:
                # Setback overnight: unit off, room drifts toward outdoors.
                self._indoor_c += (t_out - self._indoor_c) / (r * c) * hours
                return 0.0, "off"
            gains_kw = (t_out - self._indoor_c) / r + gain * min(1.0, busy)  # envelope + people/cooking heat
            cooling_needed = max(0.0, gains_kw + (self._indoor_c - setpoint) * c / 0.25)  # pull back within ~15 min
            power = min(rated, cooling_needed / HVAC_COP)
            self._indoor_c += (gains_kw - power * HVAC_COP) / c * hours
            return power, "on"

        if model == "demand_driven":
            if not is_open:
                self._cooking.clear()
                return 0.0, "off"
            per_order_min = float(p.get("minutes_per_order", 5))
            self._cooking = [m - minutes for m in self._cooking if m - minutes > 0]
            mine = orders * self.cook_share
            whole = int(mine) + (1 if self.rng.random() < mine - int(mine) else 0)
            self._cooking.extend([per_order_min] * whole)
            power = float(p.get("idle_kw", 0.1 * rated)) + float(p.get("kw_per_order", 0.1 * rated)) * len(self._cooking)
            return min(rated, power), "on"

        # job
        return self._job(now, minutes, is_open, orders)

    def _job(self, now, minutes, is_open, orders) -> tuple[float, DeviceState]:
        p = self.params
        cycle = float(p.get("cycle_min", 30))
        if p.get("trigger") == "ice_low":
            self._ice_level = max(0.0, self._ice_level - orders * float(p.get("ice_used_per_customer", 0.02)))
            due = self._ice_level < 0.3
        else:
            self._dirty_racks += orders * float(p.get("racks_per_customer", 0.15))
            due = self._dirty_racks >= float(p.get("racks_per_cycle", 6))

        if self._job_left_min <= 0 and due and (is_open or self._dirty_racks > 0):
            self._job_left_min = cycle
            self._job_pending = True
            if p.get("trigger") == "ice_low":
                self._ice_level = min(1.0, self._ice_level + 0.5)
            else:
                self._dirty_racks = max(0.0, self._dirty_racks - float(p.get("racks_per_cycle", 6)))

        if self._delay_until is not None and now < self._delay_until:
            return 0.0, ("waiting" if self._job_left_min > 0 else "off")
        self._delay_until = None

        if self._job_left_min > 0:
            self._job_pending = False
            run = min(minutes, self._job_left_min)
            self._job_left_min -= run
            return self.rated_kw * run / minutes, "running_job"
        return 0.0, "off"

    # ---------------------------------------------------------------- views

    def reading(self) -> DeviceReading:
        return {"device_id": self.device_id, "power_kw": round(self.power_kw, 6), "state": self.state, "source": self.source}  # type: ignore[typeddict-item]

    def view(self) -> DeviceView:
        return {
            "device_id": self.device_id,
            "type_id": self.type_id,
            "name": self.name,
            "importance": self.importance,
            "state": self.state,
            "power_kw": round(self.power_kw, 6),
            "rated_kw": self.rated_kw,
            "source": self.source,  # type: ignore[typeddict-item]
        }


def build_devices(config: dict, catalog: list[dict], seed: int) -> list[SimDevice]:
    """One SimDevice per unit in `config["equipment"]` (count 0 = absent). Ids are `<type_id>_<n>`.
    Each device gets its own RNG derived from `seed` and its id, so adding a device never changes another's run."""
    types = {t["type_id"]: t for t in catalog}
    hours = config.get("operating_hours") or {"open": "10:00", "close": "22:00"}
    out: list[SimDevice] = []
    for entry in config["equipment"]:
        t = types[entry["type_id"]]
        if t["power_model"] not in POWER_MODELS:
            raise ValueError(f"unknown power_model {t['power_model']!r} for {t['type_id']}")
        for n in range(1, entry["count"] + 1):
            device_id = f"{t['type_id']}_{n}"
            out.append(
                SimDevice(
                    device_id=device_id,
                    type_id=t["type_id"],
                    name=f"{t['name']} {n}",
                    category=t["category"],
                    importance=entry["importance"],
                    limits=dict(entry.get("limits") or t.get("default_limits") or {}),
                    rated_kw=float(t["rated_kw"]),
                    power_model=t["power_model"],
                    params=dict(t.get("params") or {}),
                    open_h=hhmm(hours["open"]),
                    close_h=hhmm(hours["close"]),
                    rng=random.Random(f"{seed}:{device_id}"),
                )
            )
    return out
