"""Target (ENGINE.md section 4) and decider (section 5).

Only the target is built so far; the planner is a later module.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from .history import HistoryView
from .tariff import TariffView

SAME_WEEKDAYS = 4


def minimize_target_kw(view: HistoryView, tariff: TariffView, now: datetime, month_peak_kw: float) -> float:
    """Highest closed-block avg kW over the 4 most recent same-weekday local days before today (history, no peeking).
    Past days never change, so the value is fixed for the whole local day. No history for those days -> month peak so
    far (0 while nothing has closed this month: no reductions until a block closes)."""
    today = tariff.local_date(now)
    peak: Optional[float] = None
    for k in range(1, SAME_WEEKDAYS + 1):
        day = today - timedelta(days=7 * k)
        start = tariff.local_midnight_utc(day)
        end = tariff.local_midnight_utc(day + timedelta(days=1))
        for _, kw in view.total_blocks_between(start, end):
            peak = kw if peak is None else max(peak, kw)
    return month_peak_kw if peak is None else peak


def target_kw(peak_mode: str, peak_cap_kw: Optional[float], view: HistoryView, tariff: TariffView, now: datetime,
              month_peak_kw: float) -> float:
    if peak_mode == "cap":
        return float(peak_cap_kw)
    return minimize_target_kw(view, tariff, now, month_peak_kw)


def plan(*args, **kwargs):
    # STUB: ENGINE.md section 5 decider (holds, reductions, releases, restores, effects) not built yet.
    raise NotImplementedError("STUB: decider.plan (ENGINE.md section 5)")
