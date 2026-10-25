"""WarmUpHistory from NREL ComStock (CONTRACTS.md section 1; DATA_AND_PROOF.md "Warm-up = the restaurant's last 4 weeks").

`warmup_from_series(series, end)` cuts the 4 weeks before `end` out of a BacktestInputs-style series (the backtest uses the
series' first 28 days). `build_warmup(start_sim_ts, ...)` is the live product's call: the same ComStock restaurant, the same
recipe and the same weekday- and DST-aligned `day_offset` (assumptions.yaml), the 28 days before the run's start.
Returns None when the dataset file is absent (the engine then runs without warm-up; nothing blocks). Labels:
`nrel_comstock` / `calibrated_model`. `scale` is 1.0: the Demo Café is matched to bldg 5847 (`live_scale` is not decided yet).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Mapping, Optional
from zoneinfo import ZoneInfo

from .backtest_inputs import iso_z

WARMUP = timedelta(days=28)


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def warmup_from_series(series: Mapping, end: datetime, days: int = 28) -> dict:
    """The blocks of `series` in [end - days, end) as a WarmUpHistory (month_to_date null)."""
    start = end - timedelta(days=days)
    a, b = iso_z(start), iso_z(end)
    last = iso_z(end - timedelta(minutes=15))  # every block must end at or before `end` (no peeking)
    blocks = [blk for blk in series["blocks"] if a <= blk["block_start"] <= last]  # ISO Z strings sort chronologically
    if not blocks:
        raise ValueError(f"series has no blocks in [{a}, {b})")
    return {**{k: series[k] for k in ("source", "label", "dataset_id", "scale", "day_offset")},
            "start": a, "end": b, "blocks": blocks, "month_to_date": None}


def build_warmup(start_sim_ts: datetime, assumptions_id: str = "base", tariff: str = "pge_b19") -> Optional[dict]:
    """Live warm-up: the 28 days of ComStock (replay calendar) before `start_sim_ts`. None if dataset/ is absent."""
    from .backtest_inputs import load_backtest_inputs

    start_sim_ts = start_sim_ts.astimezone(timezone.utc)
    month = start_sim_ts.astimezone(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m")  # the PG&E tariff's zone
    try:
        inputs = load_backtest_inputs([month], assumptions_id, tariff=tariff)
    except FileNotFoundError:
        return None
    return warmup_from_series(inputs["series"], start_sim_ts)
