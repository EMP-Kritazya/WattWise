"""Lane comparison (ENGINE.md section 10): the only place lane differences are computed."""
from __future__ import annotations

from typing import Any

from contracts import LaneComparison, TickState


def _tick_state(value: Any) -> TickState:
    return value if isinstance(value, TickState) else TickState.model_validate(value)


def compare_lanes(without: Any, with_: Any) -> dict:
    """LaneComparison over the two lanes' TickStates of the same tick."""
    a, b = _tick_state(without), _tick_state(with_)
    if a.lane != "without" or b.lane != "with":
        raise ValueError("compare_lanes(without, with_) needs the without lane first, then the with lane")
    comparison = LaneComparison(
        ts=b.ts,
        saved_today_usd=a.meter.cost_usd_today - b.meter.cost_usd_today,
        peak_avoided_kw=a.meter.month_peak_kw - b.meter.month_peak_kw,
        month_peak_without_kw=a.meter.month_peak_kw,
        month_peak_with_kw=b.meter.month_peak_kw,
    )
    return comparison.model_dump(mode="json")
