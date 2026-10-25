"""Backtest policies (DATA_AND_PROOF.md "Replay and backtest"): `without`, `timer`, `with`. Pure, no I/O.

- `without`: every device exactly as in the data (no Commands).
- `with`: the WattWise Kitchen (control "with"); its Commands go through the replay plant; escalations end on the fallback.
- `timer`: the best **fixed daily schedule** for the deferrable job devices, fitted on the **previous** month (January, which has
  no previous month in the data, on the warm-up weeks). A schedule is one daily hold window per job device, `[start, end)`
  local, inside opening hours, `end - start <= max_delay_min` and `end + 15 min <= min(must_finish_by, close)`: every block of the window
  is held (a `delay` Command at the window start) and released at its end. The fit tries every window on a 15-min grid
  (and "no window") per device, device by device, two passes (coordinate descent, ties -> no window, then earliest start,
  then shortest), and keeps the one with the lowest bill on the fit period; a window that would leave job energy unfinished
  at the deadline, or force it above `rated_kw` at close, on any fit day is rejected. Billing during the fit uses `block_bill` (the replay's reported bills always
  come from the Kitchen's Meter).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Mapping, Optional, Sequence

import numpy as np

from contracts import Tariff

from .block_bill import BlockCalendar
from .replay_plant import BlockInfo, PlantDevice, ReplayPlant

GRID_MIN = 15


def _hm(v: str) -> int:
    h, m = v.split(":")
    return int(h) * 60 + int(m)


def timer_commands(schedule: Mapping[str, tuple[int, int]], info: BlockInfo, lane: str = "timer") -> list[dict]:
    """The timer's Commands delivered at the start of this block: a `delay` for every window starting here."""
    out = []
    for d in sorted(schedule):
        a, b = schedule[d]
        if info.minute_of_day == a:
            out.append({"command_id": f"timer_{d}_{info.block_start.strftime('%Y%m%dT%H%M')}", "lane": lane,
                        "ts": info.block_start, "device_id": d, "action": "delay", "value": b - a,
                        "decision_id": None, "issued_by": "engine"})
    return out


def candidate_windows(dev: PlantDevice, open_min: int, close_min: int) -> list[tuple[int, int]]:
    max_delay = int(dev.limits.get("max_delay_min", 0))
    deadline = min(dev.deadline_min if dev.deadline_min is not None else close_min, close_min)
    out = []
    a = open_min
    while a < deadline:
        length = GRID_MIN
        while length <= max_delay and a + length + GRID_MIN <= deadline:  # the released block must end by the deadline
            out.append((a, a + length))
            length += GRID_MIN
        a += GRID_MIN
    return out


def _simulate_device(dev: PlantDevice, col: np.ndarray, infos: Sequence[BlockInfo],
                     window: Optional[tuple[int, int]]) -> tuple[np.ndarray, int]:
    """Run ONE job device through the same replay plant code with a fixed daily window.
    Returns (kW per block, number of rule violations + blocks pushed above rated_kw by a forced placement)."""
    plant = ReplayPlant("timer", [dev])
    out = np.empty(len(col))
    sched = {} if window is None else {dev.device_id: window}
    for i, info in enumerate(infos):
        plant.deliver(timer_commands(sched, info), info.block_start, internal=True)
        out[i] = plant.block({dev.device_id: col[i]}, info)[dev.device_id][0]
    return out, plant.violations + plant.over_rated_blocks


def _cost(cal: BlockCalendar, tariff: Tariff, total_kw: np.ndarray) -> float:
    """Energy + demand charges of the fit period, each billing month separately (fixed charges are equal for all)."""
    cost = float((total_kw * cal.price_kwh_per_kw).sum())
    months = sorted(set(cal.local_month))
    month_arr = np.array(cal.local_month)
    for m in months:
        sel = month_arr == m
        mo = int(m[5:])
        for c in tariff.demand:
            if c.months is not None and mo not in c.months:
                continue
            mask = cal.counts[c.name] & sel
            if mask.any():
                cost += c.usd_per_kw * float(total_kw[mask].max())
    return cost


def fit_timer(fit_kw: np.ndarray, device_ids: Sequence[str], devices: Mapping[str, PlantDevice], infos: Sequence[BlockInfo],
              cal: BlockCalendar, tariff: Tariff, open_min: int, close_min: int) -> dict[str, tuple[int, int]]:
    """Best fixed daily hold windows on the fit period (`fit_kw`: blocks x devices, raw data before the scored month)."""
    jobs = [d for d in device_ids if devices[d].importance == "deferrable" and devices[d].power_model == "job"]
    if not jobs or len(fit_kw) == 0:
        return {}
    col = {d: j for j, d in enumerate(device_ids)}
    base_total = fit_kw.sum(axis=1)
    placed = {d: fit_kw[:, col[d]].copy() for d in jobs}
    chosen: dict[str, Optional[tuple[int, int]]] = {d: None for d in jobs}
    cache: dict[tuple[str, Optional[tuple[int, int]]], tuple[np.ndarray, int]] = {}
    for _ in range(2):
        for d in jobs:
            others = base_total - fit_kw[:, col[d]] + sum(placed[o] - fit_kw[:, col[o]] for o in jobs if o != d)
            best_key, best_val = None, None
            for w in [None] + candidate_windows(devices[d], open_min, close_min):
                key = (d, w)
                if key not in cache:
                    cache[key] = _simulate_device(devices[d], fit_kw[:, col[d]], infos, w)
                kw_d, viol = cache[key]
                if viol and w is not None:
                    continue
                val = _cost(cal, tariff, others + kw_d)
                rank = (round(val, 6), 0 if w is None else 1, (w or (0, 0))[0], (w or (0, 0))[1])
                if best_val is None or rank < best_val:
                    best_key, best_val = w, rank
            chosen[d] = best_key
            placed[d] = cache[(d, best_key)][0]
    return {d: w for d, w in chosen.items() if w is not None}
