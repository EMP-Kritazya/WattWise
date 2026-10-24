"""Durable records behind one interface: `STORE=convex|memory`."""

from __future__ import annotations

import logging
from pathlib import Path

from .base import Store
from .memory import MemoryStore

log = logging.getLogger(__name__)


def create_store(kind: str, seed_dir: Path | None = None) -> Store:
    """`seed_dir` (fake mode only) seeds the memory store with `contracts/fixtures/convex/tables/`."""
    if kind == "convex":
        # STUB: Convex store not built yet (Phase E); same fallback as Convex being unreachable.
        log.warning("store_down: Convex store not available, using the in-memory store")
    elif kind != "memory":
        raise ValueError(f"STORE={kind!r}; expected 'convex' or 'memory'")
    return MemoryStore(seed_dir)


__all__ = ["MemoryStore", "Store", "create_store"]
