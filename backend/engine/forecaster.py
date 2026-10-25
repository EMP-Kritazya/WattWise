"""Forecaster (ENGINE.md section 3): kW per device per 15-min block for the next 120 min (8 blocks).

Block 0 is the block in progress: its metered minutes plus the forecast for the rest of the block.

- **Base** (per device, per block): mean `avg_kw` of that device at the same local weekday and local block time over the
  previous 4 weeks (warm-up + the engine's own closed blocks; only blocks that ended before now). Same local wall-clock
  time, so a week across a DST change still lines up. Fewer weeks -> mean of what exists; none -> the device's last closed
  block; none -> its current `power_kw`.
- **Live ratio** = Σ actual / Σ base of the `always_on` devices together over the last 2 closed blocks (the base of a past
  block uses only what was closed before it), clamped 0.5-2.0; applied to `always_on` and `flexible` forecasts for the next
  hour (blocks 0-3), fading linearly to 1.0 over the second hour: block i = 4..7 gets `r + (1 - r)(i - 3)/4`, so block 7 is
  at 1.0. No closed block (or no always_on device, or a zero base) -> 1.0.
- **Crowd multiplier** (context.py) on `demand_driven` devices; it is not part of the ratio's base.
- **Reduced flexible device**: `min(forecast, value% × rated_kw)` for blocks starting before `restore_at`; the first block
  starting at or after `restore_at` gets `forecast + owed_kwh × 4`, capped at `rated_kw`.
- `unavoidable_kw` per block = always_on forecast + each flexible device at `min(forecast, min_power_pct% × rated_kw)` +
  running jobs (deferrable devices in `running_job`). In block 0 the metered minutes count in full.

No peeking: every history read goes through `HistoryView`, which raises for a block ending after now; candidates that would
end after now are never asked for. No I/O, deterministic (devices in sorted id order).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Mapping, Optional

from .history import HistoryView
from .tariff import BLOCK, MINUTE, TariffView, block_start_of

FORECAST_BLOCKS = 8
HORIZON_MIN = FORECAST_BLOCKS * 15
WEEKS_BACK = 4
RATIO_MIN, RATIO_MAX = 0.5, 2.0
RATIO_BLOCKS = 2
FULL_RATIO_BLOCKS = 4  # the next hour
BLOCK_H = 0.25


def same_slot_weeks_back(tariff: TariffView, block_start: datetime, weeks: int) -> datetime:
    """The block at the same local weekday and local clock time `weeks` weeks earlier (aware UTC)."""
    loc = tariff.local(block_start)
    day = loc.date() - timedelta(days=7 * weeks)
    then = datetime(day.year, day.month, day.day, loc.hour, loc.minute, tzinfo=tariff.tz)
    return block_start_of(then.astimezone(timezone.utc))


def base_kw(view: HistoryView, tariff: TariffView, device_id: str, block_start: datetime, current_kw: float) -> float:
    """ENGINE.md section 3 base of one device for one block (closed history only)."""
    values = []
    for k in range(1, WEEKS_BACK + 1):
        slot = same_slot_weeks_back(tariff, block_start, k)
        if slot + BLOCK > view.now:
            continue  # not closed yet: never read (no peeking)
        kw = view.device_block_kw(device_id, slot)
        if kw is not None:
            values.append(kw)
    if values:
        return sum(values) / len(values)
    last = view.last_closed_device_kw(device_id, end_by=min(block_start, view.now))
    if last is not None:
        return last
    return current_kw


def live_ratio(view: HistoryView, tariff: TariffView, devices: list[dict], block0: datetime) -> float:
    """Σ actual / Σ base of the always_on devices over the last 2 closed blocks before block 0, clamped 0.5-2.0."""
    always_on = [d for d in devices if d["importance"] == "always_on"]
    if not always_on:
        return 1.0
    actual = base = 0.0
    seen = False
    for k in range(1, RATIO_BLOCKS + 1):
        slot = block0 - k * BLOCK
        if slot + BLOCK > view.now:
            continue
        kws = [view.device_block_kw(d["device_id"], slot) for d in always_on]
        if all(kw is None for kw in kws):
            continue  # nothing metered in that block
        seen = True
        for d, kw in zip(always_on, kws):
            actual += kw or 0.0
            base += base_kw(view, tariff, d["device_id"], slot, d["power_kw"])
    if not seen or base <= 0.0:
        return 1.0
    return min(RATIO_MAX, max(RATIO_MIN, actual / base))


def ratio_factor(ratio: float, block_index: int) -> float:
    if block_index < FULL_RATIO_BLOCKS:
        return ratio
    return ratio + (1.0 - ratio) * (block_index - FULL_RATIO_BLOCKS + 1) / (FORECAST_BLOCKS - FULL_RATIO_BLOCKS)


def forecast_devices(*, now: datetime, history: HistoryView, tariff: TariffView, devices: list[dict],
                     block0_metered_kwh: Mapping[str, float], crowd_multiplier: float = 1.0,
                     reductions: Optional[Mapping[str, dict]] = None) -> dict:
    """Per-device and total forecast for the 8 blocks from the block in progress.

    `devices`: Device dicts + `power_model` + `limits`. `block0_metered_kwh`: energy already metered per device in block 0.
    `reductions`: active reduce per flexible device `{"value_pct", "restore_at", "owed_kwh"}`.
    Returns `{"block_starts", "device_kw", "total_kw", "unavoidable_kw"}`."""
    reductions = reductions or {}
    devices = sorted(devices, key=lambda d: d["device_id"])
    block0 = block_start_of(now)
    starts = [block0 + i * BLOCK for i in range(FORECAST_BLOCKS)]
    remaining_min = (block0 + BLOCK - now) / MINUTE
    ratio = live_ratio(history, tariff, devices, block0)

    device_kw: dict[str, list[float]] = {}
    unavoidable = [0.0] * FORECAST_BLOCKS
    for d in devices:
        did, importance = d["device_id"], d["importance"]
        rated = d["rated_kw"]
        red = reductions.get(did) if importance == "flexible" else None
        rates: list[float] = []
        caught_up = False
        for i, start in enumerate(starts):
            kw = base_kw(history, tariff, did, start, d["power_kw"])
            if importance in ("always_on", "flexible"):
                kw *= ratio_factor(ratio, i)
            if d.get("power_model") == "demand_driven":
                kw *= crowd_multiplier
            if red is not None:
                if start < red["restore_at"]:
                    kw = min(kw, red["value_pct"] / 100.0 * rated)
                elif not caught_up:
                    kw = min(rated, kw + red["owed_kwh"] * 4.0)
                    caught_up = True
            rates.append(kw)

        if importance == "always_on":
            unav = list(rates)
        elif importance == "flexible":
            floor = d.get("limits", {}).get("min_power_pct", 0) / 100.0 * rated
            unav = [min(kw, floor) for kw in rates]
        else:
            unav = list(rates) if d.get("state") == "running_job" else [0.0] * FORECAST_BLOCKS

        metered = block0_metered_kwh.get(did, 0.0)
        series = [(metered + rates[0] * remaining_min / 60.0) / BLOCK_H] + rates[1:]
        unav_series = [(metered + unav[0] * remaining_min / 60.0) / BLOCK_H] + unav[1:]
        device_kw[did] = series
        for i in range(FORECAST_BLOCKS):
            unavoidable[i] += unav_series[i]

    total = [sum(device_kw[d["device_id"]][i] for d in devices) for i in range(FORECAST_BLOCKS)]
    return {"block_starts": starts, "device_kw": device_kw, "total_kw": total, "unavoidable_kw": unavoidable}
