"""Durable records behind one interface: `STORE=convex|memory`."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from .base import Store
from .convex_store import STORE_DOWN_WARNING, ConvexHttp, ConvexRejected, ConvexStore
from .memory import MemoryStore

log = logging.getLogger(__name__)


def create_store(
    kind: str,
    seed_dir: Path | None = None,
    *,
    convex_url: str | None = None,
    on_warning: Callable[[dict], Any] | None = None,
) -> Store:
    """`seed_dir` (fake mode only) seeds the memory store, or the Convex store's mirror, with
    `contracts/fixtures/convex/tables/`. `on_warning` gets the `store_down` warning when Convex is unreachable."""
    if kind == "convex":
        if convex_url:
            return ConvexStore(convex_url, seed_dir=seed_dir, on_warning=on_warning)
        log.warning("store_down: STORE=convex without CONVEX_URL, using the in-memory store")
    elif kind != "memory":
        raise ValueError(f"STORE={kind!r}; expected 'convex' or 'memory'")
    return MemoryStore(seed_dir)


__all__ = ["ConvexHttp", "ConvexRejected", "ConvexStore", "MemoryStore", "STORE_DOWN_WARNING", "Store", "create_store"]
