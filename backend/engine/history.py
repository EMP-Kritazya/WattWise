"""Rolling 4-week block history and the no-peeking view (ENGINE.md sections 0, 3; golden rule 8).

Every read goes through `HistoryView(now)`, which raises `PeekError` for any block that ends after `now`.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Mapping, Optional

from .tariff import BLOCK

RETENTION = timedelta(days=29)  # 4 weeks of same-weekday look-back + the local day in progress


class PeekError(ValueError):
    """A history read touched a block that ends after now."""


class BlockHistory:
    """Closed 15-min blocks per device (avg kW) and per kitchen (total avg kW), kept in chronological insertion order."""

    def __init__(self) -> None:
        self._device: dict[datetime, dict[str, float]] = {}
        self._total: dict[datetime, float] = {}

    def add(self, block_start: datetime, device_avg_kw: Mapping[str, float], total_avg_kw: float) -> None:
        if self._total and block_start <= next(reversed(self._total)):
            raise ValueError(f"history block {block_start.isoformat()} is not after the last stored block")
        self._device[block_start] = {d: device_avg_kw[d] for d in sorted(device_avg_kw)}
        self._total[block_start] = total_avg_kw

    def prune(self, now: datetime) -> None:
        cutoff = now - RETENTION
        while self._total:
            oldest = next(iter(self._total))
            if oldest >= cutoff:
                break
            del self._total[oldest]
            del self._device[oldest]

    def view(self, now: datetime) -> "HistoryView":
        return HistoryView(self, now)


class HistoryView:
    def __init__(self, history: BlockHistory, now: datetime) -> None:
        self._history = history
        self.now = now

    def _guard(self, block_start: datetime) -> None:
        if block_start + BLOCK > self.now:
            raise PeekError(f"block {block_start.isoformat()} ends after now {self.now.isoformat()} (no peeking)")

    def device_block_kw(self, device_id: str, block_start: datetime) -> Optional[float]:
        self._guard(block_start)
        return self._history._device.get(block_start, {}).get(device_id)

    def last_closed_device_kw(self, device_id: str, end_by: datetime) -> Optional[float]:
        """avg kW of the device's most recent stored block that ends at or before `end_by` (and before now)."""
        limit = min(end_by, self.now)
        for block_start in reversed(self._history._device):
            if block_start + BLOCK > limit:
                continue  # not closed by then (never read)
            kw = self._history._device[block_start].get(device_id)
            if kw is not None:
                return kw
        return None

    def total_block_kw(self, block_start: datetime) -> Optional[float]:
        self._guard(block_start)
        return self._history._total.get(block_start)

    def total_blocks_between(self, start: datetime, end: datetime) -> list[tuple[datetime, float]]:
        """Closed total blocks in [start, end), `start` block-aligned (end must not be after now)."""
        if end > self.now:
            raise PeekError(f"range end {end.isoformat()} is after now {self.now.isoformat()} (no peeking)")
        out = []
        block = start
        while block + BLOCK <= end:
            kw = self._history._total.get(block)
            if kw is not None:
                out.append((block, kw))
            block += BLOCK
        return out
