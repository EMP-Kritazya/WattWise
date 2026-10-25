"""Replay and backtest (ENGINE.md section 11; DATA_AND_PROOF.md "Replay and backtest"; CONTRACTS.md section 3 `run_backtest`).

`run_backtest(inputs, months, assumptions_id, on_progress=None)` is pure: `inputs` is a BacktestInputs built by the caller
(`data.backtest_inputs.load_backtest_inputs`); nothing here opens a file, sleeps or reads a clock.

The loop, identical for every policy:
- The first 28 days of `inputs.series` are the warm-up history (`Kitchen.warm_up`, the same for every lane); scoring starts
  at `series.start + 28 days` (the year run's January is therefore partial) and runs to `series.end`.
- Three Kitchens on the same tariff: `without` (control "without", no Commands), `timer` (control "without"; the replay plant
  applies the fitted fixed daily schedule) and `with` (control "with": the engine decides on every 15-min step; its Commands
  go through the replay plant and are acked `ok` in the next report; escalations end on the engine's fallback, no Claude).
- Each 15-min row is fed once, in order: plant(row) -> HubReport -> `Kitchen.step(15, report)` (no peeking by construction;
  the Kitchen's history view raises if anything reads ahead).
- Money: every lane's month to date is billed by `engine.meter.MonthBill` from the very HubReports its Kitchen metered
  (energy at each minute's price + every applicable demand charge on its month peak so far + fixed charges so far, the Meter
  `cost_usd_month` definition; 3-decimal peaks, GAPS 26). Only scored blocks are billed, so January's bill covers 26-31 Jan.
  A BacktestPoint after each local day's last block (`cost_to_date_usd[p]` = that bill's `total_usd`); a BacktestResult at
  each month end with the same bills, so the month's last point equals its mark to the cent.
- Checks per month: `baseline_matches_raw` (the `without` bill equals the raw series billed independently by
  `block_bill`, every part to the cent) · `energy_conserved` (every lane's metered daily kWh equals the raw day's kWh within
  1e-6 kWh, every day of the month) · `rule_violations` (replay plant counters of the `timer` and `with` lanes in the month).
- Sensitivity knobs (`inputs.assumptions`): `draw_scale` scales every device's kW (a device pushed above `rated_kw` raises,
  never clips) · `flex_scale` scales the owner's limits (0 = every device always_on: the zero-flexibility check) ·
  `forecast_noise_pct` > 0 is not supported yet (STUB, raises).
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Optional, Sequence
from zoneinfo import ZoneInfo

import numpy as np

from contracts import BacktestInputs, BacktestPoint, BacktestResult

from . import block_bill
from .ids import IdAllocator
from .kitchen import Kitchen
from .meter import MonthBill
from .policies import fit_timer, timer_commands
from .replay_plant import BlockInfo, PlantDevice, ReplayPlant
from .tariff import TariffView

WARMUP_DAYS = 28
BLOCK = timedelta(minutes=15)
POLICIES = ("without", "timer", "with")
ENERGY_TOL_KWH = 1e-6
USD_TOL = 0.005  # "to the cent": two cent-rounded values must be equal (half a cent of float slack)
TIMER_MIN_FIT_DAYS = 7  # fewer days of the previous month in the series -> the timer is fitted on the warm-up weeks
DATASET_LABELS = {
    "nrel_comstock": "DOE-calibrated restaurant profile (NREL ComStock)",
    "fixture_synthetic": "Simulated",
}


def _plain(value: Any) -> Any:
    return value.model_dump(mode="json", by_alias=True) if hasattr(value, "model_dump") else value


def _iso(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _r(x: float, n: int) -> float:
    v = round(x + 0.0, n)
    return 0.0 if v == 0 else v


# ---------------------------------------------------------------------------------------------------------------------
# inputs -> matrix, config transforms
# ---------------------------------------------------------------------------------------------------------------------


def apply_flex_scale(config: dict, flex_scale: float) -> dict:
    """Scale the owner's flexibility. 0 -> every device always_on (no move possible). Otherwise flexible:
    `min_power_pct' = round(100 - (100 - min) x s)`, `max_reduce_min' = max(1, round(max_reduce x s))`; deferrable:
    `max_delay_min' = round(max_delay x s)`. The engine's rules validate the result."""
    cfg = copy.deepcopy(config)
    for entry in cfg["equipment"]:
        lim = entry.get("limits") or {}
        if flex_scale == 0:
            entry["importance"], entry["limits"] = "always_on", {}
        elif flex_scale != 1.0:
            if entry["importance"] == "flexible":
                lim["min_power_pct"] = int(round(100 - (100 - lim["min_power_pct"]) * flex_scale))
                lim["max_reduce_min"] = max(1, int(round(lim["max_reduce_min"] * flex_scale)))
            elif entry["importance"] == "deferrable":
                lim["max_delay_min"] = int(round(lim["max_delay_min"] * flex_scale))
            entry["limits"] = lim
    return cfg


@dataclass
class _Series:
    starts: list[datetime]
    device_ids: list[str]
    kw: np.ndarray  # blocks x devices (draw_scale applied)


def _series_matrix(series: Mapping, device_ids: Sequence[str]) -> _Series:
    start = datetime.fromisoformat(series["start"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(series["end"].replace("Z", "+00:00"))
    n = int((end - start) / BLOCK)
    if n <= 0 or start + n * BLOCK != end:
        raise ValueError("series start/end must span a whole number of 15-min blocks")
    col = {d: j for j, d in enumerate(device_ids)}
    kw = np.full((n, len(device_ids)), np.nan)
    index: dict[str, int] = {}
    for blk in series["blocks"]:
        bs = blk["block_start"]
        i = index.get(bs)
        if i is None:
            t = datetime.fromisoformat(bs.replace("Z", "+00:00"))
            q, rem = divmod((t - start).total_seconds(), 900)
            if rem or not 0 <= q < n:
                raise ValueError(f"series block {bs} is outside [start, end) or off the 15-min grid")
            i = index[bs] = int(q)
        j = col.get(blk["device_id"])
        if j is None:
            raise ValueError(f"series block for unknown device {blk['device_id']!r}")
        if not np.isnan(kw[i, j]):
            raise ValueError(f"duplicate series block {blk['device_id']} {bs}")
        kw[i, j] = blk["avg_kw"]
    if np.isnan(kw).any():
        i, j = np.argwhere(np.isnan(kw))[0]
        raise ValueError(f"series is missing {device_ids[j]} at {_iso(start + int(i) * BLOCK)} (every device, every block)")
    return _Series([start + i * BLOCK for i in range(n)], list(device_ids), kw)


# ---------------------------------------------------------------------------------------------------------------------
# the run
# ---------------------------------------------------------------------------------------------------------------------


@dataclass
class Diagnostics:
    """Not part of the contract: what the CLI / checks print (timer schedules, plant counters, meter cross-check)."""

    timer_schedules: dict[str, dict[str, tuple[str, str]]] = field(default_factory=dict)
    violation_log: list[str] = field(default_factory=list)
    over_rated_blocks: dict[str, int] = field(default_factory=dict)
    raw_bills: dict[str, dict] = field(default_factory=dict)
    kitchen_meter_max_gap_usd: dict[str, float] = field(default_factory=dict)  # |Kitchen cost_usd_month - MonthBill|
    commands_issued: dict[str, int] = field(default_factory=dict)
    peek_errors: int = 0  # a PeekError (history read ahead of now) aborts the run, so a finished run reports 0
    scored_days: dict[str, int] = field(default_factory=dict)


def run_backtest(inputs: Any, months: Sequence[str], assumptions_id: str,
                 on_progress: Optional[Callable[[dict], None]] = None) -> list[dict]:
    """CONTRACTS.md section 3. Returns list[BacktestResult] (JSON-ready dicts) for `months`, in order."""
    results, _ = run_backtest_with_diagnostics(inputs, months, assumptions_id, on_progress)
    return results


def run_backtest_with_diagnostics(inputs: Any, months: Sequence[str], assumptions_id: str,
                                  on_progress: Optional[Callable[[dict], None]] = None) -> tuple[list[dict], Diagnostics]:
    raw_inputs = _plain(inputs)
    inp = BacktestInputs.model_validate(raw_inputs)
    knobs = inp.assumptions
    if knobs.assumptions_id != assumptions_id:
        raise ValueError(f"assumptions_id {assumptions_id!r} != inputs.assumptions.assumptions_id {knobs.assumptions_id!r}")
    if knobs.forecast_noise_pct > 0:
        # STUB: forecast noise needs a seeded noise hook in the forecaster (engine/forecaster.py, not in this module).
        raise NotImplementedError("STUB: forecast_noise_pct > 0 (bad_forecast) needs a forecaster noise hook")
    months = list(months)
    if not months or months != sorted(set(months)):
        raise ValueError(f"months must be a non-empty sorted list without duplicates: {months}")

    tariff = inp.tariff
    tv = TariffView(tariff)
    tz = ZoneInfo(tariff.timezone)
    config = apply_flex_scale(_plain(inp.config), knobs.flex_scale)
    catalog = [c.model_dump(mode="json") for c in inp.catalog]
    facts = {c["type_id"]: c for c in catalog}
    series_d = raw_inputs["series"] if isinstance(raw_inputs, dict) else _plain(inp.series)

    # roster (the engine's device ids) -------------------------------------------------------------------------------
    open_min = block_bill._hm(config["operating_hours"]["open"])
    close_min = block_bill._hm(config["operating_hours"]["close"])
    devices: dict[str, PlantDevice] = {}
    for entry in config["equipment"]:
        f = facts[entry["type_id"]]
        for n in range(1, entry["count"] + 1):
            d = f"{entry['type_id']}_{n}"
            lim = dict(entry.get("limits") or {})
            deadline = None
            if entry["importance"] == "deferrable" and "must_finish_by" in lim:
                deadline = min(block_bill._hm(lim["must_finish_by"]), close_min)
            devices[d] = PlantDevice(d, f["type_id"], f"{f['name']} {n}", entry["importance"], f["power_model"],
                                     float(f["rated_kw"]), lim, deadline)
    device_ids = sorted(devices)

    s = _series_matrix(series_d, device_ids)
    if knobs.draw_scale != 1.0:
        s.kw = s.kw * knobs.draw_scale
    rated = np.array([devices[d].rated_kw for d in device_ids])
    over = s.kw > rated + 1e-12
    if over.any():
        j = int(np.argmax(over.any(axis=0)))
        raise ValueError(f"draw_scale {knobs.draw_scale}: {device_ids[j]} reaches {s.kw[:, j].max():.3f} kW > rated_kw "
                         f"{rated[j]} ({int(over[:, j].sum())} blocks); never clipped")

    n_blocks = len(s.starts)
    score_start = s.starts[0] + timedelta(days=WARMUP_DAYS)
    i0 = int((score_start - s.starts[0]) / BLOCK)
    if i0 >= n_blocks:
        raise ValueError("series is shorter than the 28-day warm-up")

    # block calendar ---------------------------------------------------------------------------------------------------
    cal = block_bill.calendar(tariff, s.starts)
    infos: list[BlockInfo] = []
    for i, bs in enumerate(s.starts):
        end_loc = (bs + BLOCK).astimezone(tz)
        end_min = end_loc.hour * 60 + end_loc.minute
        infos.append(BlockInfo(bs, bs + BLOCK, cal.local_date[i], int(cal.minute_of_day[i]),
                               last_before_close=(end_min == close_min and end_loc.date() == cal.local_date[i]),
                               last_of_day=(end_min == 0)))
    month_of = cal.local_month
    scored_months = sorted({month_of[i] for i in range(i0, n_blocks)})
    for m in months:
        if m not in scored_months:
            raise ValueError(f"month {m} has no scored blocks in the series ({_iso(score_start)} .. {series_d['end']})")
    last_needed = max(i for i in range(i0, n_blocks) if month_of[i] == months[-1])
    days_in_month: dict[str, list[date]] = {}
    for i in range(i0, last_needed + 1):
        lst = days_in_month.setdefault(month_of[i], [])
        if not lst or lst[-1] != cal.local_date[i]:
            lst.append(cal.local_date[i])

    dataset = DATASET_LABELS.get(series_d["source"], series_d["source"])

    # warm-up (same history for every lane) -----------------------------------------------------------------------------
    hist_blocks = [{"block_start": _iso(s.starts[i]), "device_id": d, "avg_kw": float(s.kw[i, j])}
                   for i in range(i0) for j, d in enumerate(device_ids)]
    history = {k: series_d[k] for k in ("source", "label", "dataset_id", "scale", "day_offset")}
    history.update({"start": _iso(s.starts[0]), "end": _iso(score_start), "blocks": hist_blocks, "month_to_date": None})

    kitchens = {
        "without": Kitchen(config, tariff, catalog, "without", inp.seed, ids=IdAllocator()),
        "timer": Kitchen(config, tariff, catalog, "without", inp.seed, ids=IdAllocator()),
        "with": Kitchen(config, tariff, catalog, "with", inp.seed, ids=IdAllocator()),
    }
    for k in kitchens.values():
        k.warm_up(history)
    plants = {p: ReplayPlant(p, list(devices.values())) for p in POLICIES}
    pending: dict[str, list[dict]] = {p: [] for p in POLICIES}
    diag = Diagnostics(commands_issued={p: 0 for p in POLICIES})

    # loop -------------------------------------------------------------------------------------------------------------
    results: list[dict] = []
    saved_before = 0.0
    emit = on_progress or (lambda event: None)
    cur_month: Optional[str] = None
    bills: dict[str, MonthBill] = {}
    schedule: dict[str, tuple[int, int]] = {}
    day_energy_raw = 0.0
    month_energy_ok = True
    viol_at_month_start = 0
    gap = 0.0
    scored_mask = np.zeros(n_blocks, dtype=bool)
    scored_mask[i0:] = True

    for i in range(i0, last_needed + 1):
        info = infos[i]
        m = month_of[i]
        if m != cur_month:
            cur_month = m
            bills = {p: MonthBill(tv, m) for p in POLICIES}
            schedule = _fit_timer_for_month(i, i0, s, cal, month_of, infos, devices, device_ids, tariff, open_min, close_min)
            diag.timer_schedules[m] = {d: (f"{a // 60:02d}:{a % 60:02d}", f"{b // 60:02d}:{b % 60:02d}")
                                       for d, (a, b) in schedule.items()}
            month_energy_ok = True
            viol_at_month_start = plants["timer"].violations + plants["with"].violations
            gap = 0.0
        raw = {d: float(s.kw[i, j]) for j, d in enumerate(device_ids)}
        day_energy_raw += float(s.kw[i].sum()) * 0.25

        states = {}
        for p in POLICIES:
            plant = plants[p]
            plant.deliver(pending[p], info.block_start)
            if p == "timer":
                plant.deliver(timer_commands(schedule, info), info.block_start, internal=True)
            placed = plant.block(raw, info)
            report = plant.report(placed, info, tick_id=i)
            st = kitchens[p].step(15, report)
            pending[p] = list(st["new_commands"])
            diag.commands_issued[p] += len(st["new_commands"])
            bills[p].add_block(info.block_start, report["total_kw"])
            states[p] = st

        end_of_data = i == last_needed
        if info.last_of_day or end_of_data:
            day = info.local_day
            for p in POLICIES:
                if abs(states[p]["meter"]["energy_kwh_today"] - day_energy_raw) > ENERGY_TOL_KWH:
                    month_energy_ok = False
            day_energy_raw = 0.0
            mtd = {p: bills[p].bill() for p in POLICIES}
            for p in POLICIES:
                gap = max(gap, abs(states[p]["meter"]["cost_usd_month"] - mtd[p]["total_usd"]))
            month_done = end_of_data or month_of[i + 1] != m
            if m in months:
                cost = {p: mtd[p]["total_usd"] for p in POLICIES}
                saved = _r(cost["without"] - cost["with"], 2)
                partial = len(days_in_month[m]) < _days_in_calendar_month(m)
                point = {
                    "dataset": dataset, "assumptions_id": assumptions_id, "tariff_id": tariff.tariff_id,
                    "month": m, "day": day.isoformat(),
                    "ts": _iso(_local_midnight_after(day, tz)),
                    "partial": partial, "cost_to_date_usd": cost, "saved_month_to_date_usd": saved,
                    "saved_vs_timer_month_to_date_usd": _r(cost["timer"] - cost["with"], 2),
                    "saved_year_to_date_usd": _r(saved_before + saved, 2),
                }
                point = BacktestPoint.model_validate(point).model_dump(mode="json", by_alias=True)
                emit({"type": "backtest_point", "data": point})
                if month_done:
                    raw_bill = block_bill.rounded(block_bill.month_bill(tariff, cal, s.kw.sum(axis=1), m, scored_mask))
                    diag.raw_bills[m] = raw_bill
                    res = {
                        "dataset": dataset, "month": m,
                        "policies": {p: mtd[p] for p in POLICIES},
                        "checks": {
                            "baseline_matches_raw": block_bill.same_to_the_cent(raw_bill, mtd["without"]),
                            "energy_conserved": month_energy_ok,
                            "rule_violations": plants["timer"].violations + plants["with"].violations - viol_at_month_start,
                        },
                        "assumptions_id": assumptions_id, "tariff_id": tariff.tariff_id, "partial": partial,
                        "saved_usd": saved, "saved_vs_timer_usd": _r(cost["timer"] - cost["with"], 2),
                    }
                    res = BacktestResult.model_validate(res).model_dump(mode="json", by_alias=True)
                    results.append(res)
                    emit({"type": "backtest_month", "data": res})
                    diag.kitchen_meter_max_gap_usd[m] = gap
                    diag.scored_days[m] = len(days_in_month[m])
                    saved_before = _r(saved_before + saved, 2)
                k = days_in_month[m].index(day)
                n_days = len(days_in_month[m])
                pct = int(100 * (k + 1) // n_days)
                if pct // 25 > int(100 * k // n_days) // 25:  # progress every quarter of the month (GAPS 28)
                    emit({"type": "backtest_progress", "month": m, "pct": pct})

    diag.violation_log = plants["timer"].violation_log + plants["with"].violation_log
    diag.over_rated_blocks = {p: plants[p].over_rated_blocks for p in POLICIES}
    return results, diag


def _local_midnight_after(day: date, tz: ZoneInfo) -> datetime:
    nxt = day + timedelta(days=1)
    return datetime(nxt.year, nxt.month, nxt.day, tzinfo=tz).astimezone(timezone.utc)


def _days_in_calendar_month(month: str) -> int:
    y, m = int(month[:4]), int(month[5:])
    return (date(y + m // 12, m % 12 + 1, 1) - date(y, m, 1)).days


def _fit_timer_for_month(i: int, i0: int, s: _Series, cal: block_bill.BlockCalendar, month_of: Sequence[str],
                         infos: Sequence[BlockInfo], devices: Mapping[str, PlantDevice], device_ids: Sequence[str],
                         tariff, open_min: int, close_min: int) -> dict[str, tuple[int, int]]:
    """Timer schedule for the month starting at block i: fitted on the previous calendar month's blocks in the series
    (all before block i), or on the 28 warm-up days when fewer than 7 days of the previous month are available."""
    m = month_of[i]
    y, mo = int(m[:4]), int(m[5:])
    prev = f"{y - 1:04d}-12" if mo == 1 else f"{y:04d}-{mo - 1:02d}"
    idx = [k for k in range(i) if month_of[k] == prev]
    if len({cal.local_date[k] for k in idx}) < TIMER_MIN_FIT_DAYS:
        idx = list(range(0, i0))
    if not idx:
        return {}
    a, b = idx[0], idx[-1] + 1
    sub = block_bill.slice_calendar(cal, a, b)
    return fit_timer(s.kw[a:b], device_ids, devices, infos[a:b], sub, tariff, open_min, close_min)
