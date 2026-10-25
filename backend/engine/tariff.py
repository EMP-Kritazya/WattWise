"""Tariff lookups in local time (`tariff.timezone`). UTC inside; local time only through this view.

CONTRACTS.md section 1 Tariff, "Seasons, days and windows" (2026-10-24): every energy period and demand charge may carry
`months` (null = every month) and `days` ("all" | "weekdays" | "weekends"); spans are `[start, end)` on the local clock and
wrap past midnight when `end` < `start`; the month and day type are those of the minute itself (of the block's local start for
demand). Exactly one energy period matches every local minute of the year (checked at construction, `ValueError` otherwise).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from contracts import Tariff

BLOCK_MIN = 15
BLOCK = timedelta(minutes=BLOCK_MIN)
MINUTE = timedelta(minutes=1)
MINUTES_PER_DAY = 1440
DAY_TYPES = ("weekdays", "weekends")


def hhmm_to_min(value: str) -> int:
    """"HH:MM" (or "24:00") -> minutes after local midnight."""
    hours, minutes = value.split(":")
    return int(hours) * 60 + int(minutes)


def in_span(minute_of_day: int, start_min: int, end_min: int) -> bool:
    """[start, end) on the local clock; a span with end < start wraps midnight; start == end is empty."""
    if start_min < end_min:
        return start_min <= minute_of_day < end_min
    if start_min > end_min:
        return minute_of_day >= start_min or minute_of_day < end_min
    return False


def block_start_of(ts: datetime) -> datetime:
    """Start of the 15-min block containing `ts`. Every UTC offset in use is a multiple of 15 min, so local :00/:15/:30/:45
    alignment equals UTC alignment (and stays correct across DST changes)."""
    ts = ts.astimezone(timezone.utc)
    floored = ts.replace(second=0, microsecond=0)
    return floored - timedelta(minutes=floored.minute % BLOCK_MIN)


def day_type_of(day: date) -> str:
    """Mon-Fri -> "weekdays", Sat-Sun -> "weekends" (holidays are not modelled)."""
    return "weekends" if day.weekday() >= 5 else "weekdays"


def _matches(months: Optional[list[int]], days: str, month: int, day_type: str) -> bool:
    return (months is None or month in months) and (days == "all" or days == day_type)


@dataclass(frozen=True)
class Charge:
    """One tariff demand charge, pre-parsed. `windows` None = every hour."""

    index: int  # position in tariff.demand (tariff order)
    name: str
    usd_per_kw: float
    months: Optional[tuple[int, ...]]
    days: str
    windows: Optional[tuple[tuple[int, int], ...]]

    def applies_in_month(self, month: int) -> bool:
        return self.months is None or month in self.months


class TariffView:
    def __init__(self, tariff: Any) -> None:
        if not isinstance(tariff, Tariff):
            tariff = Tariff.model_validate(tariff.model_dump(mode="json") if hasattr(tariff, "model_dump") else tariff)
        self.tariff = tariff
        self.tz = ZoneInfo(tariff.timezone)
        self.charges: tuple[Charge, ...] = tuple(
            Charge(
                index=i,
                name=c.name,
                usd_per_kw=c.usd_per_kw,
                months=None if c.months is None else tuple(c.months),
                days=c.days,
                windows=None if c.windows is None else tuple((hhmm_to_min(w.start), hhmm_to_min(w.end)) for w in c.windows),
            )
            for i, c in enumerate(tariff.demand)
        )
        names = [c.name for c in self.charges]
        if len(set(names)) != len(names):
            raise ValueError(f"tariff {tariff.tariff_id}: demand charge names must be unique (one month peak per name)")
        self.fixed_usd_per_day = sum(f.usd for f in tariff.fixed_charges if f.per == "day")
        self.fixed_usd_per_month = sum(f.usd for f in tariff.fixed_charges if f.per == "month")
        self._price_table = self._build_price_table()

    def _build_price_table(self) -> dict[tuple[int, str], list[float]]:
        """{(month, day type): [price of each local minute 0..1439]}; raises unless exactly one period matches each minute."""
        periods = [(hhmm_to_min(p.start), hhmm_to_min(p.end), p.usd_per_kwh, p.months, p.days, p.name)
                   for p in self.tariff.energy]
        table: dict[tuple[int, str], list[float]] = {}
        for month in range(1, 13):
            for dtype in DAY_TYPES:
                active = [p for p in periods if _matches(p[3], p[4], month, dtype)]
                row = []
                for m in range(MINUTES_PER_DAY):
                    hits = [p for p in active if in_span(m, p[0], p[1])]
                    if len(hits) != 1:
                        what = "no energy period" if not hits else f"{len(hits)} energy periods ({', '.join(h[5] for h in hits)})"
                        raise ValueError(f"tariff {self.tariff.tariff_id}: {what} at month {month} {dtype} "
                                         f"{m // 60:02d}:{m % 60:02d} (exactly one must match)")
                    row.append(hits[0][2])
                table[(month, dtype)] = row
        return table

    # local calendar ---------------------------------------------------------------------------------------------------
    def local(self, ts: datetime) -> datetime:
        return ts.astimezone(self.tz)

    def minute_of_day(self, ts: datetime) -> int:
        loc = self.local(ts)
        return loc.hour * 60 + loc.minute

    def local_date(self, ts: datetime) -> date:
        return self.local(ts).date()

    def local_month(self, ts: datetime) -> str:
        return self.local(ts).strftime("%Y-%m")

    def local_midnight_utc(self, day: date) -> datetime:
        return datetime(day.year, day.month, day.day, tzinfo=self.tz).astimezone(timezone.utc)

    # prices -----------------------------------------------------------------------------------------------------------
    def energy_price(self, minute_start: datetime) -> float:
        """$/kWh of the one tariff energy period matching the minute's local start (month, day type, time)."""
        loc = self.local(minute_start)
        return self._price_table[(loc.month, day_type_of(loc.date()))][loc.hour * 60 + loc.minute]

    # demand -----------------------------------------------------------------------------------------------------------
    def applicable(self, month: int) -> tuple[Charge, ...]:
        """Demand charges that apply in a local month (1..12), tariff order."""
        return tuple(c for c in self.charges if c.applies_in_month(month))

    def counts(self, charge: Charge, block_start: datetime) -> bool:
        """A closed block counts for a charge when the charge applies in the block's local month, its day type matches and
        (windows null, or) the block's local start is in any window."""
        loc = self.local(block_start)
        if not _matches(None if charge.months is None else list(charge.months), charge.days, loc.month, day_type_of(loc.date())):
            return False
        if charge.windows is None:
            return True
        m = loc.hour * 60 + loc.minute
        return any(in_span(m, a, b) for a, b in charge.windows)

    def on_peak_charge(self, month: int) -> Optional[Charge]:
        """The highest-rate windowed charge that applies in the month (first in tariff order on a tie), or None."""
        best: Optional[Charge] = None
        for c in self.applicable(month):
            if c.windows is not None and (best is None or c.usd_per_kw > best.usd_per_kw):
                best = c
        return best
