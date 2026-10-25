"""Meter (ENGINE.md section 1): energy, 15-min blocks, the two G36 month peaks, today / month cost.

Everything is metered one minute at a time (a `step(15, ...)` is 15 minutes of the same power), so tariff periods, block
closes, local midnight and the 1st of the month are handled the same way at every cadence. A minute belongs to the local
day and month of its start; a block belongs to the day and month of its local start (the 23:45 block closing at 00:00 is
billed to the previous day and month).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Mapping, Optional

from contracts import DemandCharge, MonthToDate

from .tariff import BLOCK, MINUTE, TariffView, block_start_of

BLOCK_H = 0.25


@dataclass(frozen=True)
class ClosedBlock:
    block_start: datetime
    avg_kw: float
    device_avg_kw: dict[str, float]


def charge_peak_kw(charge: DemandCharge, month_peak_kw: float, on_peak_month_peak_kw: Optional[float]) -> float:
    """The month peak a demand charge bills: window null -> month peak, windowed -> on-peak month peak."""
    if charge.window is None:
        return month_peak_kw
    return on_peak_month_peak_kw or 0.0


def demand_charges_usd(tariff: TariffView, month_peak_kw: float, on_peak_month_peak_kw: Optional[float]) -> list[tuple[str, float, float]]:
    """Per tariff demand charge: (name, peak_kw, cost_usd). The one per-charge function for meter, bills and projections."""
    out = []
    for charge in tariff.tariff.demand:
        peak = charge_peak_kw(charge, month_peak_kw, on_peak_month_peak_kw)
        out.append((charge.name, peak, charge.usd_per_kw * peak))
    return out


def bill(tariff: TariffView, period: str, energy_kwh: float, energy_cost_usd: float, month_peak_kw: float,
         on_peak_month_peak_kw: Optional[float]) -> dict:
    """Bill shape (CONTRACTS.md section 1) from month totals and peaks."""
    charges = demand_charges_usd(tariff, month_peak_kw, on_peak_month_peak_kw)
    return {
        "period": period,
        "energy_kwh": energy_kwh,
        "energy_cost_usd": energy_cost_usd,
        "demand_charges": [{"name": n, "peak_kw": p, "cost_usd": c} for n, p, c in charges],
        "total_usd": energy_cost_usd + sum(c for _, _, c in charges),
        "tariff_id": tariff.tariff.tariff_id,
    }


class MeterState:
    def __init__(self, tariff: TariffView) -> None:
        self.tariff = tariff
        self.has_window = tariff.window_charge is not None
        # local day and month the running totals belong to (None until the first minute)
        self.day: Optional[date] = None
        self.month: Optional[str] = None
        self.energy_kwh_today = 0.0
        self.energy_cost_today_usd = 0.0
        self.energy_kwh_month = 0.0
        self.energy_cost_month_usd = 0.0
        self.month_peak_kw = 0.0
        self.on_peak_month_peak_kw: Optional[float] = 0.0 if self.has_window else None
        self.day_start_peaks: tuple[float, Optional[float]] = (0.0, self.on_peak_month_peak_kw)
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
            self.on_peak_month_peak_kw = 0.0 if self.has_window else None
        if day != self.day:
            self.day = day
            self.energy_kwh_today = 0.0
            self.energy_cost_today_usd = 0.0
            self.day_start_peaks = (self.month_peak_kw, self.on_peak_month_peak_kw)

    def _close_block(self) -> ClosedBlock:
        start = self.block_start
        avg_kw = self.block_energy_kwh / BLOCK_H
        self.month_peak_kw = max(self.month_peak_kw, avg_kw)
        if self.has_window and self.tariff.in_demand_window(start):
            self.on_peak_month_peak_kw = max(self.on_peak_month_peak_kw or 0.0, avg_kw)
        devices = {d: self.block_device_kwh[d] / BLOCK_H for d in sorted(self.block_device_kwh)}
        self.block_start = None
        self.block_energy_kwh = 0.0
        self.block_device_kwh = {}
        return ClosedBlock(start, avg_kw, devices)

    # ------------------------------------------------------------------------------------------------------------------
    def restore_month_to_date(self, mtd: MonthToDate, start: datetime) -> None:
        """A non-null WarmUpHistory.month_to_date is used as given (reserved for a restart; unused in this build)."""
        if mtd.month != self.tariff.local_month(start):
            raise ValueError(f"month_to_date.month {mtd.month} is not the start's local month")
        self.month = mtd.month
        self.day = self.tariff.local_date(start)
        self.month_peak_kw = mtd.month_peak_kw
        self.on_peak_month_peak_kw = (mtd.on_peak_month_peak_kw or 0.0) if self.has_window else None
        self.energy_kwh_month = mtd.energy_kwh_month
        # cost_usd_month bundles energy and demand; keep its energy part so the month formula continues
        demand = sum(c for _, _, c in demand_charges_usd(self.tariff, self.month_peak_kw, self.on_peak_month_peak_kw))
        self.energy_cost_month_usd = mtd.cost_usd_month - demand
        self.energy_kwh_today = 0.0
        self.energy_cost_today_usd = 0.0
        self.day_start_peaks = (self.month_peak_kw, self.on_peak_month_peak_kw)

    # ------------------------------------------------------------------------------------------------------------------
    def cost_usd_today(self) -> float:
        added = 0.0
        day_max, day_on = self.day_start_peaks
        for charge in self.tariff.tariff.demand:
            now_peak = charge_peak_kw(charge, self.month_peak_kw, self.on_peak_month_peak_kw)
            start_peak = charge_peak_kw(charge, day_max, day_on)
            added += charge.usd_per_kw * (now_peak - start_peak)
        return self.energy_cost_today_usd + added

    def cost_usd_month(self) -> float:
        demand = sum(c for _, _, c in demand_charges_usd(self.tariff, self.month_peak_kw, self.on_peak_month_peak_kw))
        return self.energy_cost_month_usd + demand

    def block_in_progress(self, now: datetime) -> tuple[datetime, float]:
        """(block_start, block_avg_kw) of the block of the last metered minute (so a just-closed block still shows its
        full average at the boundary tick); the block containing `now` with 0 kW before anything is metered."""
        if self.last_block_start is None:
            return block_start_of(now), 0.0
        return self.last_block_start, self.last_block_energy_kwh / BLOCK_H

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
            "on_peak_month_peak_kw": self.on_peak_month_peak_kw,
            "peak_mode": peak_mode,
            "peak_cap_kw": peak_cap_kw,
            "target_kw": target_kw,
            "energy_kwh_today": self.energy_kwh_today,
            "energy_kwh_month": self.energy_kwh_month,
            "price_usd_per_kwh_now": self.tariff.energy_price(ts),
            "cost_usd_today": self.cost_usd_today(),
            "cost_usd_month": self.cost_usd_month(),
        }
