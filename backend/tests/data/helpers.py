"""Synthetic ComStock-shaped rows and paths shared by the data / backtest tests (no dataset needed)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from backtest.assumptions import load_file, resolve
from data.comstock import COMSTOCK_FILE, END_USES, TOTAL, ComStockRows
from data.backtest_inputs import load_catalog

needs_comstock = pytest.mark.skipif(not COMSTOCK_FILE.exists(),
                                    reason=f"dataset/ is gitignored: {COMSTOCK_FILE} is absent")


def synthetic_rows(start: datetime, days: int, *, interior_peak_kw: float = 14.0, residual_kw: float = 0.0,
                   hvac_kw: float = 6.0, lights_kw: float = 1.0) -> ComStockRows:
    """A restaurant-like day repeated: interior equipment ramps to a 19:00 peak (local standard time), constant HVAC split
    as cooling + fans, constant lights. `residual_kw` is added to `total` only (like the file's float32 residual)."""
    n = days * 96
    starts = [start + timedelta(minutes=15 * i) for i in range(n)]
    hour = np.array([((s - timedelta(hours=8)).hour + (s.minute / 60.0)) for s in starts])
    interior = 2.0 + (interior_peak_kw - 2.0) * np.exp(-((hour - 19.0) ** 2) / 8.0) + 6.0 * np.exp(-((hour - 12.5) ** 2) / 3.0)
    kw = {e: np.zeros(n) for e in END_USES}
    kw["cooling"] = np.full(n, hvac_kw * 0.4)
    kw["fans"] = np.full(n, hvac_kw * 0.6)
    kw["interior_equipment"] = interior
    kw["interior_lighting"] = np.full(n, lights_kw * 0.4)
    kw["exterior_lighting"] = np.full(n, lights_kw * 0.6)
    kw[TOTAL] = sum(kw[e] for e in END_USES) + residual_kw
    return ComStockRows(dataset_id="synthetic", start_utc=starts, kw=kw)


def doc_and_base():
    doc = load_file()
    return doc, resolve("base", doc)


def catalog():
    return load_catalog()


UTC = timezone.utc
