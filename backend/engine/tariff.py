"""Tariff lookups in local time (`tariff.timezone`). UTC inside; local time only through this view."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from contracts import DemandCharge, Tariff

BLOCK_MIN = 15
BLOCK = timedelta(minutes=BLOCK_MIN)
MINUTE = timedelta(minutes=1)


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


class TariffView:
    def __init__(self, tariff: Tariff) -> None:
        self.tariff = tariff
        self.tz = ZoneInfo(tariff.timezone)
        self._energy = [(hhmm_to_min(p.start), hhmm_to_min(p.end), p.usd_per_kwh) for p in tariff.energy]
        unwindowed = [c for c in tariff.demand if c.window is None]
        windowed = [c for c in tariff.demand if c.window is not None]
        if len(unwindowed) > 1 or len(windowed) > 1:
            # ENGINE.md section 1: "A tariff with more demand charges needs a contract change first."
            raise ValueError("the engine supports at most one demand charge with window null and one windowed charge")
        self.max_charge: DemandCharge | None = unwindowed[0] if unwindowed else None
        self.window_charge: DemandCharge | None = windowed[0] if windowed else None

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
        """$/kWh of the tariff energy period containing the minute's local start."""
        m = self.minute_of_day(minute_start)
        for start, end, price in self._energy:
            if in_span(m, start, end):
                return price
        raise ValueError(f"tariff {self.tariff.tariff_id}: no energy period covers local {m // 60:02d}:{m % 60:02d}")

    def in_demand_window(self, block_start: datetime) -> bool:
        """The block counts for the windowed charge when its local start is in [start, end)."""
        if self.window_charge is None:
            return False
        w = self.window_charge.window
        return in_span(self.minute_of_day(block_start), hhmm_to_min(w.start), hhmm_to_min(w.end))
