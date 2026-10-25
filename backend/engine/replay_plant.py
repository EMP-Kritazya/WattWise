"""Replay plant (ENGINE.md section 11): stands in for the browser hub during a backtest. Backtest code, not decision code.

It turns one 15-min dataset row (per-device kW from the distribution recipe) into a HubReport-shaped object, after applying
the Commands delivered for that block; every Command is acked `ok` with `applied_value = value`.

- `reduce v`: the device draws at most `v % x rated_kw`; the shortfall is owed and goes back into the same device in the first
  later block with room under `rated_kw` (owed energy is repaid, never deleted; golden rule 5). `restore` lifts the cap.
- `delay m`: holds the job device's energy (dishwasher, ice machine share of a row) from the block it is applied in until
  `applied + m` minutes; `delay 0` / `start` release it. Released energy is placed whole in the release block, as far as
  `rated_kw` allows; the rest spills into the next blocks (first room first).
- `off` caps a device at 0 (energy owed like a reduce), `on` lifts the cap.
- Anything still owed, held or spilled at the **last block before close** is put there; anything left at the local day's last
  block is put there (so every local day keeps exactly its own energy: conservation is checked per day to 1e-6 kWh).

Rule counters (`violations`): an always_on device commanded · a reduce below the device's `min_power_pct` · job energy still
held or unplaced at the device's effective deadline `min(must_finish_by, close)` (one per device per day) · a hold longer than
`max_delay_min`. Rows are fed one at a time (`block(i, ...)`), so the plant never sees a later row either.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Mapping, Optional, Sequence

BLOCK_H = 0.25
EPS = 1e-12


@dataclass
class PlantDevice:
    device_id: str
    type_id: str
    name: str
    importance: str
    power_model: str
    rated_kw: float
    limits: dict
    deadline_min: Optional[int] = None  # job devices: min(must_finish_by, close), local minutes


@dataclass
class _State:
    cap_pct: Optional[float] = None  # active reduce / off
    owed_kwh: float = 0.0  # flexible: reduced energy still to repay
    hold_until: Optional[datetime] = None  # job: hold end (UTC)
    hold_first: Optional[datetime] = None  # job: when the current hold was first applied
    held_kwh: float = 0.0  # job: energy waiting for the release
    spill_kwh: float = 0.0  # job: released energy that did not fit yet
    flagged_day: Optional[date] = None  # deadline violation already counted for this local day


@dataclass
class BlockInfo:
    """Local facts of one block, supplied by the caller (tariff timezone)."""

    block_start: datetime
    block_end: datetime
    local_day: date
    minute_of_day: int  # local minute of the block start
    last_before_close: bool  # the block ending at the local closing time
    last_of_day: bool  # the block ending at local midnight


class ReplayPlant:
    def __init__(self, lane: str, devices: Sequence[PlantDevice], hub_id: str = "replay_plant") -> None:
        self.lane = lane
        self.hub_id = hub_id
        self.devices = {d.device_id: d for d in sorted(devices, key=lambda x: x.device_id)}
        self.state = {d: _State() for d in self.devices}
        self._acks: list[dict] = []
        self.violations = 0
        self.violation_log: list[str] = []
        self.over_rated_blocks = 0  # end-of-day / close dumps that pushed a device above rated_kw (diagnostic)

    # commands ---------------------------------------------------------------------------------------------------------
    def deliver(self, commands: Sequence[Mapping], at: datetime, internal: bool = False) -> None:
        """Commands delivered at `at` (= the start of the next block), applied before that block; acked in its report.
        `internal=True`: the timer policy's own schedule (no Kitchen issued it, so nothing is acked back)."""
        for c in commands:
            if c.get("lane", self.lane) != self.lane:
                continue
            d = c["device_id"]
            dev = self.devices.get(d)
            if dev is None:
                if not internal:
                    self._acks.append(self._ack(c, ok=False, reason="unknown_device"))
                continue
            st = self.state[d]
            action, value = c["action"], c.get("value")
            if dev.importance == "always_on":
                self._violate(f"{at.isoformat()} {d}: always_on device commanded ({action})")
            if action == "reduce":
                floor = dev.limits.get("min_power_pct")
                if floor is not None and value is not None and value < floor:
                    self._violate(f"{at.isoformat()} {d}: reduce {value} % below min_power_pct {floor}")
                st.cap_pct = float(value)
            elif action == "restore" or action == "on":
                st.cap_pct = None
            elif action == "off":
                st.cap_pct = 0.0
            elif action == "delay":
                if value == 0:
                    st.hold_until = None
                    st.hold_first = None
                else:
                    if st.hold_first is None:
                        st.hold_first = at
                    st.hold_until = at + timedelta(minutes=int(value))
                    max_delay = dev.limits.get("max_delay_min")
                    if max_delay is not None and (st.hold_until - st.hold_first) > timedelta(minutes=max_delay):
                        self._violate(f"{at.isoformat()} {d}: hold beyond max_delay_min {max_delay}")
            elif action == "start":
                st.hold_until = None
                st.hold_first = None
            if not internal:
                self._acks.append(self._ack(c, ok=True))

    def _ack(self, c: Mapping, ok: bool, reason: Optional[str] = None) -> dict:
        return {"command_id": c["command_id"], "lane": "with" if self.lane == "with" else "without", "ok": ok,
                "applied_value": c.get("value") if ok else None, "reason": reason}

    def _violate(self, text: str) -> None:
        self.violations += 1
        self.violation_log.append(text)

    # one block --------------------------------------------------------------------------------------------------------
    def block(self, raw_kw: Mapping[str, float], info: BlockInfo) -> dict[str, tuple[float, str]]:
        """Apply the plant to one dataset row. Returns {device_id: (kW, state)}."""
        out: dict[str, tuple[float, str]] = {}
        for d, dev in self.devices.items():
            st = self.state[d]
            v = float(raw_kw[d])
            state = "on" if v > EPS else "off"
            if dev.power_model == "job":
                v, state = self._job(dev, st, v, info)
            else:
                v, state = self._flex(dev, st, v, info)
            if info.last_of_day:  # nothing crosses local midnight
                left = st.owed_kwh + st.held_kwh + st.spill_kwh
                if left > EPS:
                    v += left / BLOCK_H
                    st.owed_kwh = st.held_kwh = st.spill_kwh = 0.0
                    if v > dev.rated_kw + 1e-9:
                        self.over_rated_blocks += 1
                st.hold_until = None
                st.hold_first = None
            out[d] = (v, state if v > EPS or state == "waiting" else "off")
        return out

    def _flex(self, dev: PlantDevice, st: _State, v: float, info: BlockInfo) -> tuple[float, str]:
        if st.cap_pct is not None:
            cap_kw = st.cap_pct / 100.0 * dev.rated_kw
            if v > cap_kw:
                st.owed_kwh += (v - cap_kw) * BLOCK_H
                return cap_kw, "reduced"
            return v, "reduced" if st.cap_pct < 100 else "on"
        if st.owed_kwh > EPS:
            if info.last_before_close:
                v += st.owed_kwh / BLOCK_H
                st.owed_kwh = 0.0
                if v > dev.rated_kw + 1e-9:
                    self.over_rated_blocks += 1
            else:
                room = max(0.0, dev.rated_kw - v)
                repay = min(room, st.owed_kwh / BLOCK_H)
                v += repay
                st.owed_kwh -= repay * BLOCK_H
                if st.owed_kwh < EPS:
                    st.owed_kwh = 0.0
        return v, "on" if v > EPS else "off"

    def _job(self, dev: PlantDevice, st: _State, v: float, info: BlockInfo) -> tuple[float, str]:
        holding = st.hold_until is not None and info.block_start < st.hold_until
        if holding:
            st.held_kwh += v * BLOCK_H
            self._check_deadline(dev, st, info)
            return 0.0, "waiting"
        if st.hold_until is not None:  # hold ended: release
            st.hold_until = None
            st.hold_first = None
        if st.held_kwh > EPS:
            st.spill_kwh += st.held_kwh
            st.held_kwh = 0.0
        if st.spill_kwh > EPS:
            if info.last_before_close:
                v += st.spill_kwh / BLOCK_H
                st.spill_kwh = 0.0
                if v > dev.rated_kw + 1e-9:
                    self.over_rated_blocks += 1
            else:
                room = max(0.0, dev.rated_kw - v)
                place = min(room, st.spill_kwh / BLOCK_H)
                v += place
                st.spill_kwh -= place * BLOCK_H
                if st.spill_kwh < EPS:
                    st.spill_kwh = 0.0
            self._check_deadline(dev, st, info)
        return v, "running_job" if v > EPS else "off"

    def _check_deadline(self, dev: PlantDevice, st: _State, info: BlockInfo) -> None:
        """Energy still waiting at the end of a block that ends at or after the effective deadline (it can only run later)
        -> one violation per device-day."""
        if dev.deadline_min is None or st.held_kwh + st.spill_kwh <= EPS:
            return
        if info.minute_of_day + 15 >= dev.deadline_min and st.flagged_day != info.local_day:
            st.flagged_day = info.local_day
            self._violate(f"{info.block_start.isoformat()} {dev.device_id}: job energy not finished by the deadline")

    # report -----------------------------------------------------------------------------------------------------------
    def report(self, placed: Mapping[str, tuple[float, str]], info: BlockInfo, tick_id: int) -> dict:
        """HubReport (CONTRACTS.md section 1) for the block just replayed; carries the acks of this block's commands."""
        devices = []
        total = 0.0
        for d, dev in self.devices.items():
            kw, state = placed[d]
            total += kw
            devices.append({"device_id": d, "type_id": dev.type_id, "name": dev.name, "importance": dev.importance,
                            "state": state, "power_kw": kw, "rated_kw": dev.rated_kw,
                            "power_pct": int(round(100 * kw / dev.rated_kw)), "source": "simulated"})
        acks, self._acks = self._acks, []
        return {"hub_id": self.hub_id, "lane": "with" if self.lane == "with" else "without", "tick_id": tick_id,
                "ts": info.block_end, "total_kw": total, "customers_per_hour": 0, "devices": devices, "acks": acks,
                "source": "simulated"}
