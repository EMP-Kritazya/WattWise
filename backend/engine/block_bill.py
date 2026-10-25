"""Block-level bill on a Tariff (backtest helper; pure, no I/O).

Used for two things only: (1) the `baseline_matches_raw` check, an independent path from the Meter (it bills the raw 15-min
series directly instead of metering minute by minute through the Kitchen), and (2) the `timer` policy's fit objective.
Reported bills and month-to-date costs always come from the Kitchen's Meter (the same tariff function for every policy).

Rules (CONTRACTS.md section 1 Tariff): energy price of each minute = the one period matching its local month, day type and
time; a block's energy cost is the sum over its 15 minutes. A demand charge applies in a month if `months` is null or holds it;
a block counts for it when its local start matches the day type and (windows null or) lies in any window; cost = rate x the
highest counting block of the billing month. Fixed charges: `per: day` x local days with metered blocks, `per: month` once.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Mapping, Optional, Sequence
from zoneinfo import ZoneInfo

import numpy as np

from contracts import Tariff

MIN = timedelta(minutes=1)


def _hm(v: str) -> int:
    h, m = v.split(":")
    return int(h) * 60 + int(m)


def _in(minute: int, a: int, b: int) -> bool:
    if a < b:
        return a <= minute < b
    if a > b:
        return minute >= a or minute < b
    return False


def _day_ok(days: str, local_day: date) -> bool:
    weekend = local_day.weekday() >= 5
    return days == "all" or (days == "weekends") == weekend


@dataclass
class BlockCalendar:
    """Per-block local facts and tariff lookups, computed once for a sequence of block starts."""

    starts: list[datetime]
    local_date: list[date]
    local_month: list[str]  # "YYYY-MM"
    minute_of_day: np.ndarray  # local minute of the block start
    price_kwh_per_kw: np.ndarray  # energy cost of 1 kW held for the whole block (sum over its 15 minutes of price / 60)
    counts: dict[str, np.ndarray]  # charge name -> bool mask (applies in the block's month, day type, window)


def calendar(tariff: Tariff, starts: Sequence[datetime]) -> BlockCalendar:
    tz = ZoneInfo(tariff.timezone)
    energy = [(_hm(p.start), _hm(p.end), p.usd_per_kwh, p.months, p.days) for p in tariff.energy]
    cache: dict[tuple[int, bool, int], float] = {}

    def price(loc: datetime) -> float:
        key = (loc.month, loc.weekday() >= 5, loc.hour * 60 + loc.minute)
        if key not in cache:
            m = key[2]
            hits = [p for p in energy if (p[3] is None or loc.month in p[3]) and _day_ok(p[4], loc.date()) and _in(m, p[0], p[1])]
            if len(hits) != 1:
                raise ValueError(f"tariff {tariff.tariff_id}: {len(hits)} energy periods at {loc.isoformat()}")
            cache[key] = hits[0][2]
        return cache[key]

    n = len(starts)
    local_date, local_month = [], []
    mod = np.zeros(n, dtype=np.int64)
    p15 = np.zeros(n)
    counts = {c.name: np.zeros(n, dtype=bool) for c in tariff.demand}
    for i, s in enumerate(starts):
        loc = s.astimezone(tz)
        local_date.append(loc.date())
        local_month.append(f"{loc.year:04d}-{loc.month:02d}")
        mod[i] = loc.hour * 60 + loc.minute
        p15[i] = sum(price((s + k * MIN).astimezone(tz)) for k in range(15)) / 60.0
        for c in tariff.demand:
            if c.months is not None and loc.month not in c.months:
                continue
            if not _day_ok(c.days, loc.date()):
                continue
            if c.windows is None or any(_in(int(mod[i]), _hm(w.start), _hm(w.end)) for w in c.windows):
                counts[c.name][i] = True
    return BlockCalendar(list(starts), local_date, local_month, mod, p15, counts)


def month_bill(tariff: Tariff, cal: BlockCalendar, total_kw: np.ndarray, month: str,
               mask: Optional[np.ndarray] = None) -> dict:
    """Unrounded bill parts for the blocks of `month` (optionally restricted by `mask`)."""
    sel = np.array([m == month for m in cal.local_month])
    if mask is not None:
        sel &= mask
    kw = total_kw[sel]
    energy_kwh = float(kw.sum() * 0.25)
    energy_cost = float((kw * cal.price_kwh_per_kw[sel]).sum())
    y, mo = int(month[:4]), int(month[5:])
    charges = []
    for c in tariff.demand:
        if c.months is not None and mo not in c.months:
            continue
        m = cal.counts[c.name][sel]
        peak = float(kw[m].max()) if m.any() else 0.0
        charges.append({"name": c.name, "peak_kw": peak, "usd_per_kw": c.usd_per_kw, "cost_usd": c.usd_per_kw * peak})
    days = len({d for d, s in zip(cal.local_date, sel) if s})
    fixed = sum(f.usd * (days if f.per == "day" else (1 if days else 0)) for f in tariff.fixed_charges)
    total = energy_cost + sum(c["cost_usd"] for c in charges) + fixed
    return {"period": month, "energy_kwh": energy_kwh, "energy_cost_usd": energy_cost, "demand_charges": charges,
            "fixed_usd": fixed, "total_usd": total, "days": days}


def bill_total_fast(cal: BlockCalendar, tariff: Tariff, total_kw: np.ndarray, month_num: int) -> float:
    """Total of a bill over ALL blocks in `cal` (one billing month); fixed charges excluded (identical across candidates)."""
    cost = float((total_kw * cal.price_kwh_per_kw).sum())
    for c in tariff.demand:
        if c.months is not None and month_num not in c.months:
            continue
        m = cal.counts[c.name]
        if m.any():
            cost += c.usd_per_kw * float(total_kw[m].max())
    return cost


def slice_calendar(cal: BlockCalendar, a: int, b: int) -> BlockCalendar:
    return BlockCalendar(cal.starts[a:b], cal.local_date[a:b], cal.local_month[a:b], cal.minute_of_day[a:b],
                         cal.price_kwh_per_kw[a:b], {k: v[a:b] for k, v in cal.counts.items()})


def _r(x: float, n: int) -> float:
    v = round(x + 0.0, n)
    return 0.0 if v == 0 else v


def rounded(parts: dict, tariff_id: Optional[str] = None) -> dict:
    """Bill shape with the backtest rounding (GAPS 26): peaks to 0.001 kW, each demand cost = round(rate x peak, 2),
    energy kWh to 0.001, energy cost and fixed to the cent, total = their sum to the cent (the engine meter's `bill()` rule)."""
    lines = []
    for c in parts["demand_charges"]:
        peak = _r(c["peak_kw"], 3)
        lines.append({"name": c["name"], "peak_kw": peak, "cost_usd": _r(c["usd_per_kw"] * peak, 2)})
    energy_cost = _r(parts["energy_cost_usd"], 2)
    fixed = _r(parts["fixed_usd"], 2)
    out = {"period": parts["period"], "energy_kwh": _r(parts["energy_kwh"], 3), "energy_cost_usd": energy_cost,
           "demand_charges": lines, "fixed_usd": fixed,
           "total_usd": _r(energy_cost + sum(c["cost_usd"] for c in lines) + fixed, 2)}
    if tariff_id is not None:
        out["tariff_id"] = tariff_id
    return out


def same_to_the_cent(a: Mapping, b: Mapping) -> bool:
    """Two rounded bills agree: every $ part within half a cent, kWh / kW within half of their last digit, same charges."""
    if [c["name"] for c in a["demand_charges"]] != [c["name"] for c in b["demand_charges"]]:
        return False
    usd = [("energy_cost_usd",), ("fixed_usd",), ("total_usd",)]
    if any(abs(a[k[0]] - b[k[0]]) >= 0.005 for k in usd):
        return False
    if abs(a["energy_kwh"] - b["energy_kwh"]) >= 0.0005:
        return False
    for x, y in zip(a["demand_charges"], b["demand_charges"]):
        if abs(x["peak_kw"] - y["peak_kw"]) >= 0.0005 or abs(x["cost_usd"] - y["cost_usd"]) >= 0.005:
            return False
    return True
