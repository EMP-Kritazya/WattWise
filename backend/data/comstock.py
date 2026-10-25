"""NREL ComStock per-building 15-min time series (DATA_AND_PROOF.md "Data").

Verified convention for `comstock_amy2018_release_3` (checked 2026-10-24 on `5847-45.parquet`, recorded in DATA_AND_PROOF.md):
- `timestamp` is **local standard time all year** (UTC-8 for California, no DST shift in the stamps) and marks the **end** of the
  15-min interval (first row `2018-01-01 00:15:00`, last `2019-01-01 00:00:00`, 35,040 rows, no gaps or duplicates).
  Evidence: the kitchen's daily peak moves from 20:30 to 19:30 standard time when DST starts (11 Mar 2018) and back after it
  ends (4 Nov 2018), so the building follows the wall clock while the stamps stay on standard time.
- So the UTC **start** of each interval is `timestamp - 15 min + 8 h`.
- Energy columns are kWh per 15 min; `power_kw = kwh x 4`. Only electricity columns are read.

Returns plain numpy arrays (float64); the loader never alters a value (no clipping, no filling).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET_DIR = REPO_ROOT / "dataset"
COMSTOCK_FILE = DATASET_DIR / "comstock" / "timeseries" / "5847-45.parquet"

DATASET_ID = "comstock_amy2018_release_3/upgrade=45/bldg_id=5847"
DATASET_LABEL = "DOE-calibrated restaurant profile (NREL ComStock)"
STANDARD_UTC_OFFSET_H = -8  # San Francisco County, local standard time (PST) all year
INTERVAL = timedelta(minutes=15)
ROWS_PER_YEAR = 35040

END_USES = (
    "cooling",
    "fans",
    "heating",
    "pumps",
    "heat_rejection",
    "heat_recovery",
    "interior_equipment",
    "interior_lighting",
    "exterior_lighting",
    "refrigeration",
    "water_systems",
    "pv",
)
TOTAL = "total"


def column(end_use: str) -> str:
    return f"out.electricity.{end_use}.energy_consumption"


@dataclass(frozen=True)
class ComStockRows:
    """One building year. `start_utc[i]` = UTC start of row i (naive datetimes are never used)."""

    dataset_id: str
    start_utc: list[datetime]
    kw: dict[str, np.ndarray]  # end use (and "total") -> kW per row, float64

    def __len__(self) -> int:
        return len(self.start_utc)


def utc_start_of(stamp_local_standard_end: datetime) -> datetime:
    """Interval-ending local-standard-time stamp (naive) -> aware UTC interval start."""
    return (stamp_local_standard_end - INTERVAL - timedelta(hours=STANDARD_UTC_OFFSET_H)).replace(tzinfo=timezone.utc)


def load_comstock(path: Path = COMSTOCK_FILE, dataset_id: str = DATASET_ID) -> ComStockRows:
    """Read the electricity columns of one ComStock building file. Raises FileNotFoundError if the file is absent."""
    import pandas as pd  # local import: tests that never touch the dataset do not need pyarrow

    if not Path(path).exists():
        raise FileNotFoundError(f"ComStock file not found: {path} (dataset/ is gitignored; download it, see DATA_AND_PROOF.md)")
    cols = ["timestamp"] + [column(e) for e in END_USES + (TOTAL,)]
    df = pd.read_parquet(path, columns=cols)
    stamps = df["timestamp"].dt.to_pydatetime()
    starts = [utc_start_of(s) for s in stamps]
    for a, b in zip(starts, starts[1:]):
        if b - a != INTERVAL:
            raise ValueError(f"ComStock rows are not contiguous 15-min intervals at {a.isoformat()} -> {b.isoformat()}")
    kw = {e: df[column(e)].to_numpy(dtype=np.float64) * 4.0 for e in END_USES + (TOTAL,)}
    return ComStockRows(dataset_id=dataset_id, start_utc=starts, kw=kw)
