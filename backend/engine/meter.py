"""Meter (ENGINE.md section 1): energy, 15-min blocks, one month peak per demand charge, today / month cost, bills.

Everything is metered one minute at a time (a `step(15, ...)` is 15 minutes of the same power), so tariff periods, block
closes, local midnight and the 1st of the month are handled the same way at every cadence. A minute belongs to the local
day and month of its start; a block belongs to the day and month of its local start (the 23:45 block closing at 00:00 is
billed to the previous day and month).

The one per-charge billing function is `demand_lines` (and its sum `demand_usd`): the Meter's `demand_peaks` and costs,
`bill()`, `MonthBill` (backtest) and, later, decision effects all price demand through it, so every charge weighs in exactly
as it bills. Readings of contracts/fixtures/GAPS.md: fixed daily charges accrue from the first metered minute of each local
day, a monthly charge on the 1st (in the month cost whenever the month is metered) (25); the Meter prices demand on the
published 0.01 kW peaks, bills on 3-decimal peaks (26); on-peak tie -> first in tariff order (27, `TariffView.on_peak_charge`).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Mapping, Optional

from contracts import MonthToDate

from .tariff import BLOCK, MINUTE, TariffView, block_start_of

BLOCK_H = 0.25
METER_PEAK_NDIGITS = 2  # Meter `demand_peaks.peak_kw` is published to 0.01 kW; costs use the published peak (GAPS 26)
BILL_PEAK_NDIGITS = 3  # Bill / backtest `demand_charges.peak_kw` (GAPS 26)


def _rnd(x: float, ndigits: int) -> float:
    v = round(x + 0.0, ndigits)
    return 0.0 if v == 0 else v


def month_number(period: str) -> int:
    """"YYYY-MM" -> 1..12."""
    return int(period[5:7])


# ---------------------------------------------------------------------------------------------------------------------
# The per-charge billing function (pure)
# ---------------------------------------------------------------------------------------------------------------------


def demand_lines(tariff: TariffView, month: int, peaks_kw: Mapping[str, float],
                 ndigits: int = METER_PEAK_NDIGITS) -> list[dict]:
    """Every demand charge that applies in local `month` (1..12), tariff order:
    `{name, peak_kw, usd_per_kw, cost_usd}` with `peak_kw` = the charge's month peak rounded to `ndigits` and
    `cost_usd = round(usd_per_kw × peak_kw, 2)` (the Meter's DemandPeak shape; a missing peak counts as 0)."""
    out = []
    for c in tariff.applicable(month):
        peak = _rnd(peaks_kw.get(c.name, 0.0), ndigits)
        out.append({"name": c.name, "peak_kw": peak, "usd_per_kw": c.usd_per_kw, "cost_usd": _rnd(c.usd_per_kw * peak, 2)})
    return out


def demand_usd(tariff: TariffView, month: int, peaks_kw: Mapping[str, float], ndigits: int = METER_PEAK_NDIGITS) -> float:
    """Σ over the charges applicable in `month` of usd_per_kw × peak (peak rounded to `ndigits`, the sum not rounded)."""
    return sum(c.usd_per_kw * _rnd(peaks_kw.get(c.name, 0.0), ndigits) for c in tariff.applicable(month))


def fixed_usd(tariff: TariffView, days_metered: int, month_metered: bool = True) -> float:
    """Fixed charges of a billing month: per-day charges × local days metered + per-month charges once (if metered)."""
    return tariff.fixed_usd_per_day * days_metered + (tariff.fixed_usd_per_month if month_metered else 0.0)


def bill(tariff: TariffView, period: str, *, energy_kwh: float, energy_cost_usd: float, peaks_kw: Mapping[str, float],
         days_metered: int, peak_ndigits: int = BILL_PEAK_NDIGITS) -> dict:
    """Bill (CONTRACTS.md section 1) of one local billing month `period` ("YYYY-MM") from its totals:
    `energy_kwh` and `energy_cost_usd` (energy at each minute's tariff price), `peaks_kw` {charge name: month peak kW}
    (charges not applicable in the month are ignored) and `days_metered` (local days with at least one metered minute).
    `total_usd = round(energy_cost_usd, 2) + Σ demand cost_usd + fixed_usd`, rounded to the cent."""
    lines = demand_lines(tariff, month_number(period), peaks_kw, peak_ndigits)
    fixed = _rnd(fixed_usd(tariff, days_metered, days_metered > 0), 2)
    energy_cost = _rnd(energy_cost_usd, 2)
    return {
        "period": period,
        "energy_kwh": _rnd(energy_kwh, 3),
        "energy_cost_usd": energy_cost,
        "demand_charges": [{"name": l["name"], "peak_kw": l["peak_kw"], "cost_usd": l["cost_usd"]} for l in lines],
        "fixed_usd": fixed,
        "total_usd": _rnd(energy_cost + sum(l["cost_usd"] for l in lines) + fixed, 2),
        "tariff_id": tariff.tariff.tariff_id,
    }


class MonthBill:
    """Accumulates one billing month from closed 15-min blocks (replay / backtest) and bills it with `bill()`.

    `add_block(block_start, avg_kw)` meters the block minute by minute at each minute's tariff price (as the live Meter does),
    updates every applicable charge's month peak and the set of local days. `bill()` at any point = the month to date (the
    BacktestPoint `cost_to_date_usd` is `bill()["total_usd"]` after a day's last block). Blocks must be block-aligned, in the
    period's local month, and each added once."""

    def __init__(self, tariff: TariffView, period: str) -> None:
        self.tariff = tariff
        self.period = period
        self.month = month_number(period)
        self.energy_kwh = 0.0
        self.energy_cost_usd = 0.0
        self.peaks_kw: dict[str, float] = {c.name: 0.0 for c in tariff.applicable(self.month)}
        self.days: set[date] = set()
        self._last_block: Optional[datetime] = None

    def add_block(self, block_start: datetime, avg_kw: float) -> None:
        if block_start_of(block_start) != block_start:
            raise ValueError(f"block {block_start.isoformat()} is not on a 15-min boundary")
        if self.tariff.local_month(block_start) != self.period:
            raise ValueError(f"block {block_start.isoformat()} is not in local month {self.period}")
        if self._last_block is not None and block_start <= self._last_block:
            raise ValueError(f"block {block_start.isoformat()} is not after the last added block")
        self._last_block = block_start
        for i in range(15):
            minute = block_start + i * MINUTE
            kwh = avg_kw / 60.0
            self.energy_kwh += kwh
            self.energy_cost_usd += kwh * self.tariff.energy_price(minute)
        self.days.add(self.tariff.local_date(block_start))
        for c in self.tariff.applicable(self.month):
            if self.tariff.counts(c, block_start):
                self.peaks_kw[c.name] = max(self.peaks_kw[c.name], avg_kw)

    def bill(self, peak_ndigits: int = BILL_PEAK_NDIGITS) -> dict:
        return bill(self.tariff, self.period, energy_kwh=self.energy_kwh, energy_cost_usd=self.energy_cost_usd,
                    peaks_kw=self.peaks_kw, days_metered=len(self.days), peak_ndigits=peak_ndigits)


# ---------------------------------------------------------------------------------------------------------------------
# Live meter state (one per lane)
# ---------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ClosedBlock:
    block_start: datetime
    avg_kw: float
    device_avg_kw: dict[str, float]


class MeterState:
    def __init__(self, tariff: TariffView) -> None:
        self.tariff = tariff
        # local day and month the running totals belong to (None until the first minute)
        self.day: Optional[date] = None
        self.month: Optional[str] = None
        self.energy_kwh_today = 0.0
        self.energy_cost_today_usd = 0.0
        self.energy_kwh_month = 0.0
        self.energy_cost_month_usd = 0.0
        self.month_peak_kw = 0.0  # highest closed block of the month, any hour
        self.peaks_kw: dict[str, float] = {c.name: 0.0 for c in tariff.charges}  # one month peak per demand charge
        self.day_start_peaks_kw: dict[str, float] = dict(self.peaks_kw)
        self.fixed_days = 0  # local days of this month with a metered minute (fixed per-day charges)
        # open block
        self.block_start: Optional[datetime] = None
        self.block_energy_kwh = 0.0
        self.block_device_kwh: dict[str, float] = {}
        # display block: the block of the last metered minute
        self.last_block_start: Optional[datetime] = None
        self.last_block_energy_kwh = 0.0

    # ------------------------------------------------------------------------------------------------------------------
    def meter_minute(self, minute_start: datetime, device_kw: Mapping[str, float]) -> list[ClosedBlock]:
        """Meter one minute [minute_start, +1 min) of per-device power; returns the blocks this closed (0, 1 or 2)."""
        closed: list[ClosedBlock] = []
        block = block_start_of(minute_start)
        if self.block_start is not None and self.block_start != block:
            closed.append(self._close_block())  # a gap: unmetered minutes count as 0
        self._roll_calendar(minute_start)

        total_kw = sum(device_kw[d] for d in sorted(device_kw))
        kwh = total_kw / 60.0
        cost = kwh * self.tariff.energy_price(minute_start)
        self.energy_kwh_today += kwh
        self.energy_cost_today_usd += cost
        self.energy_kwh_month += kwh
        self.energy_cost_month_usd += cost

        if self.block_start is None:
            self.block_start = block
            self.block_energy_kwh = 0.0
            self.block_device_kwh = {}
        self.block_energy_kwh += kwh
        for d in sorted(device_kw):
            self.block_device_kwh[d] = self.block_device_kwh.get(d, 0.0) + device_kw[d] / 60.0
        self.last_block_start = block
        self.last_block_energy_kwh = self.block_energy_kwh

        if minute_start + MINUTE >= block + BLOCK:
            closed.append(self._close_block())
        return closed

    def _roll_calendar(self, minute_start: datetime) -> None:
        day = self.tariff.local_date(minute_start)
        month = self.tariff.local_month(minute_start)
        if month != self.month:
            self.month = month
            self.energy_kwh_month = 0.0
            self.energy_cost_month_usd = 0.0
            self.month_peak_kw = 0.0
            self.peaks_kw = {c.name: 0.0 for c in self.tariff.charges}
            self.fixed_days = 0
        if day != self.day:
            self.day = day
            self.energy_kwh_today = 0.0
            self.energy_cost_today_usd = 0.0
            self.day_start_peaks_kw = dict(self.peaks_kw)
            self.fixed_days += 1

    def _close_block(self) -> ClosedBlock:
        start = self.block_start
        avg_kw = self.block_energy_kwh / BLOCK_H
        self.month_peak_kw = max(self.month_peak_kw, avg_kw)
        for c in self.tariff.charges:
            if self.tariff.counts(c, start):
                self.peaks_kw[c.name] = max(self.peaks_kw[c.name], avg_kw)
        devices = {d: self.block_device_kwh[d] / BLOCK_H for d in sorted(self.block_device_kwh)}
        self.block_start = None
        self.block_energy_kwh = 0.0
        self.block_device_kwh = {}
        return ClosedBlock(start, avg_kw, devices)

    # ------------------------------------------------------------------------------------------------------------------
    def restore_month_to_date(self, mtd: MonthToDate, start: datetime) -> None:
        """A non-null WarmUpHistory.month_to_date is used as given (reserved for a restart; unused in this build).
        `demand_peaks` restores every charge's peak by name; without it, unwindowed charges take `month_peak_kw` and the
        on-peak charge takes `on_peak_month_peak_kw`. The fixed charges of the days 1..today are taken as included."""
        if mtd.month != self.tariff.local_month(start):
            raise ValueError(f"month_to_date.month {mtd.month} is not the start's local month")
        month = month_number(mtd.month)
        self.month = mtd.month
        self.day = self.tariff.local_date(start)
        self.month_peak_kw = mtd.month_peak_kw
        self.peaks_kw = {c.name: 0.0 for c in self.tariff.charges}
        if mtd.demand_peaks is not None:
            known = {c.name for c in self.tariff.charges}
            for dp in mtd.demand_peaks:
                if dp.name not in known:
                    raise ValueError(f"month_to_date.demand_peaks names unknown charge {dp.name!r}")
                self.peaks_kw[dp.name] = dp.peak_kw
        else:
            on_peak = self.tariff.on_peak_charge(month)
            for c in self.tariff.applicable(month):
                if c.windows is None:
                    self.peaks_kw[c.name] = mtd.month_peak_kw
                elif on_peak is not None and c.name == on_peak.name:
                    self.peaks_kw[c.name] = mtd.on_peak_month_peak_kw or 0.0
        self.fixed_days = self.day.day
        self.energy_kwh_month = mtd.energy_kwh_month
        # cost_usd_month bundles energy, demand and fixed; keep its energy part so the month formula continues
        self.energy_cost_month_usd = (mtd.cost_usd_month - demand_usd(self.tariff, month, self.peaks_kw)
                                      - fixed_usd(self.tariff, self.fixed_days))
        self.energy_kwh_today = 0.0
        self.energy_cost_today_usd = 0.0
        self.day_start_peaks_kw = dict(self.peaks_kw)

    # ------------------------------------------------------------------------------------------------------------------
    def _month_int(self, now: datetime) -> int:
        return month_number(self.month or self.tariff.local_month(now))

    def on_peak_month_peak_kw(self, now: datetime) -> Optional[float]:
        charge = self.tariff.on_peak_charge(self._month_int(now))
        return None if charge is None else self.peaks_kw[charge.name]

    def demand_peaks(self, now: datetime) -> list[dict]:
        return demand_lines(self.tariff, self._month_int(now), self.peaks_kw)

    def cost_usd_today(self, now: datetime) -> float:
        """Energy today + demand added since local midnight (published peaks) + today's fixed charges."""
        if self.day is None:
            return 0.0
        month = self._month_int(now)
        added = demand_usd(self.tariff, month, self.peaks_kw) - demand_usd(self.tariff, month, self.day_start_peaks_kw)
        fixed_today = self.tariff.fixed_usd_per_day + (self.tariff.fixed_usd_per_month if self.day.day == 1 else 0.0)
        return self.energy_cost_today_usd + added + fixed_today

    def cost_usd_month(self, now: datetime) -> float:
        """Energy month to date + every applicable charge on its (published) peak + fixed charges to date."""
        if self.month is None:
            return 0.0
        month = self._month_int(now)
        return self.energy_cost_month_usd + demand_usd(self.tariff, month, self.peaks_kw) + fixed_usd(self.tariff, self.fixed_days)

    def month_bill(self, now: datetime) -> dict:
        """Bill of the current billing month so far, `demand_charges` straight from the Meter's `demand_peaks` (GAPS 26)."""
        period = self.month or self.tariff.local_month(now)
        b = bill(self.tariff, period, energy_kwh=self.energy_kwh_month, energy_cost_usd=self.energy_cost_month_usd,
                 peaks_kw=self.peaks_kw, days_metered=self.fixed_days, peak_ndigits=METER_PEAK_NDIGITS)
        return b

    def block_in_progress(self, now: datetime) -> tuple[datetime, float]:
        """(block_start, block_avg_kw) of the block of the last metered minute (so a just-closed block still shows its
        full average at the boundary tick); the block containing `now` with 0 kW before anything is metered."""
        if self.last_block_start is None:
            return block_start_of(now), 0.0
        return self.last_block_start, self.last_block_energy_kwh / BLOCK_H

    def metered_device_kwh(self, block_start: datetime) -> dict[str, float]:
        """Energy already metered per device in `block_start` (open block), {} if none."""
        return dict(self.block_device_kwh) if self.block_start == block_start else {}

    def metered_in_block_kwh(self, block_start: datetime) -> float:
        """Energy already metered in `block_start` (open block), 0 if none."""
        return self.block_energy_kwh if self.block_start == block_start else 0.0

    def reading(self, *, ts: datetime, total_kw: float, peak_mode: str, peak_cap_kw: Optional[float],
                target_kw: float) -> dict:
        """Meter shape (CONTRACTS.md section 1), JSON-ready."""
        block_start, block_avg_kw = self.block_in_progress(ts)
        return {
            "ts": ts,
            "total_kw": total_kw,
            "block_avg_kw": block_avg_kw,
            "block_start": block_start,
            "month_peak_kw": self.month_peak_kw,
            "on_peak_month_peak_kw": self.on_peak_month_peak_kw(ts),
            "peak_mode": peak_mode,
            "peak_cap_kw": peak_cap_kw,
            "target_kw": target_kw,
            "energy_kwh_today": self.energy_kwh_today,
            "energy_kwh_month": self.energy_kwh_month,
            "price_usd_per_kwh_now": self.tariff.energy_price(ts),
            "cost_usd_today": self.cost_usd_today(ts),
            "cost_usd_month": self.cost_usd_month(ts),
            "demand_peaks": self.demand_peaks(ts),
        }
