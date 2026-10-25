"""`load_backtest_inputs(months, assumptions_id)` -> BacktestInputs (CONTRACTS.md section 1), the caller's half of
`engine.run_backtest(inputs, months, assumptions_id, on_progress)`. All file reading happens here; the engine opens no file.

Series window: the replay calendar is the dataset shifted by `day_offset` days (assumptions.yaml). The series starts
`warmup_days` (28) before the first requested month's 1st, but never before the data (so the year run's January is partial:
its first 28 days are the warm-up), and ends at the end of the last requested month or of the data. The engine scores from
`series.start + 28 days` (the first 4 weeks of the series are the warm-up history, DATA_AND_PROOF.md).
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping, Optional, Sequence
from zoneinfo import ZoneInfo

import numpy as np

from backtest import assumptions as assumptions_mod

from .comstock import COMSTOCK_FILE, DATASET_ID, ComStockRows, load_comstock
from .recipe import DeviceSeries, distribute
from .tariffs import load_tariff

CATALOG_FILE = Path(__file__).resolve().parent / "equipment_catalog.json"


def iso_z(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_catalog(path: Path = CATALOG_FILE) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _month_bounds_utc(month: str, tz: ZoneInfo) -> tuple[datetime, datetime]:
    y, m = int(month[:4]), int(month[5:])
    a = datetime(y, m, 1, tzinfo=tz)
    b = datetime(y + m // 12, m % 12 + 1, 1, tzinfo=tz)
    return a.astimezone(timezone.utc), b.astimezone(timezone.utc)


def open_mask(rows: ComStockRows, operating_hours: Mapping, tz: ZoneInfo) -> np.ndarray:
    """One bool per row: the block starts inside `[open, close)` local time. The day_offset keeps weekday and DST, so a
    dataset row's local time is also its replay-calendar local time."""
    def minute(hm: str) -> int:
        h, m = hm.split(":")
        return int(h) * 60 + int(m)

    a, b = minute(operating_hours["open"]), minute(operating_hours["close"])
    local = np.array([(lambda t: t.hour * 60 + t.minute)(s.astimezone(tz)) for s in rows.start_utc])
    return (local >= a) & (local < b)


def kitchen_config(doc: Mapping, tariff_id: str) -> dict:
    cfg = json.loads(json.dumps(doc["kitchen"]))
    cfg["tariff_id"] = tariff_id
    return cfg


def build_backtest_inputs(rows: ComStockRows, devices: DeviceSeries, months: Sequence[str], resolved: Mapping,
                          doc: Mapping, tariff: Mapping, catalog: list[dict]) -> dict:
    """Pure: rows already distributed onto devices -> BacktestInputs dict (JSON-ready)."""
    if not months:
        raise ValueError("months is empty")
    if list(months) != sorted(set(months)):
        raise ValueError(f"months must be sorted and unique: {months}")
    tz = ZoneInfo(tariff["timezone"])
    shift = timedelta(days=int(doc["dataset"]["day_offset"]))
    warmup = timedelta(days=int(doc["dataset"]["warmup_days"]))
    starts = [s + shift for s in rows.start_utc]
    data_start, data_end = starts[0], starts[-1] + timedelta(minutes=15)

    first_a, _ = _month_bounds_utc(months[0], tz)
    _, last_b = _month_bounds_utc(months[-1], tz)
    series_start = max(data_start, first_a - warmup)
    series_end = min(data_end, last_b)
    score_start = series_start + warmup
    for m in months:
        a, b = _month_bounds_utc(m, tz)
        if b <= score_start or a >= series_end:
            raise ValueError(f"month {m} has no scored days: data {iso_z(data_start)} .. {iso_z(data_end)}, "
                             f"scoring from {iso_z(score_start)}")

    blocks = []
    ids = devices.device_ids
    for i, s in enumerate(starts):
        if s < series_start or s >= series_end:
            continue
        bs = iso_z(s)
        row = devices.kw[i]
        for j, d in enumerate(ids):
            v = float(row[j])
            if v < 0:
                raise ValueError(f"negative device load {d} {bs}: {v}")
            blocks.append({"block_start": bs, "device_id": d, "avg_kw": v})

    series = {
        "source": "nrel_comstock",
        "label": "calibrated_model",
        "dataset_id": rows.dataset_id,
        "scale": 1.0,
        "day_offset": int(doc["dataset"]["day_offset"]),
        "start": iso_z(series_start),
        "end": iso_z(series_end),
        "blocks": blocks,
        "month_to_date": None,
    }
    return {
        "config": kitchen_config(doc, tariff["tariff_id"]),
        "tariff": dict(tariff),
        "catalog": catalog,
        "seed": int(doc["kitchen"]["seed"]),
        "series": series,
        "assumptions": assumptions_mod.knobs(resolved),
    }


def load_backtest_inputs(months: Sequence[str], assumptions_id: str, *, tariff: str = "pge_b19",
                         comstock_path: Optional[Path] = None, doc: Optional[Mapping] = None) -> dict:
    """Read the ComStock year, the tariff, the catalog and assumptions.yaml; distribute; return BacktestInputs.

    Raises FileNotFoundError when dataset/ is absent and `RatedKwExceeded` when the recipe would put a device above its
    catalog rated_kw (never clipped)."""
    doc = doc if doc is not None else assumptions_mod.load_file()
    resolved = assumptions_mod.resolve(assumptions_id, doc)
    tariff_obj = load_tariff(tariff, assumptions_mod.repo_path(doc["tariff"]["file"])) if tariff == "pge_b19" \
        else load_tariff(tariff)
    catalog = load_catalog()
    path = comstock_path or assumptions_mod.repo_path(doc["dataset"]["file"]) or COMSTOCK_FILE
    rows = load_comstock(path, DATASET_ID)
    is_open = open_mask(rows, doc["kitchen"]["operating_hours"], ZoneInfo(tariff_obj["timezone"]))
    devices = distribute(rows, doc["kitchen"]["equipment"], catalog, doc["step1"], resolved, is_open)
    return build_backtest_inputs(rows, devices, months, resolved, doc, tariff_obj, catalog)


def replay_months(doc: Optional[Mapping] = None, tariff_tz: str = "America/Los_Angeles") -> list[str]:
    """Every replay-calendar month with scored days for the full dataset year (2026-01 .. 2026-12 for day_offset 2919)."""
    doc = doc if doc is not None else assumptions_mod.load_file()
    shift = timedelta(days=int(doc["dataset"]["day_offset"]))
    warmup = timedelta(days=int(doc["dataset"]["warmup_days"]))
    tz = ZoneInfo(tariff_tz)
    # the dataset year is 2018 standard time; compute from its first/last interval without reading the file
    first = datetime(2018, 1, 1, 8, 0, tzinfo=timezone.utc) + shift + warmup
    last = datetime(2019, 1, 1, 8, 0, tzinfo=timezone.utc) + shift - timedelta(minutes=15)
    out, d = [], first.astimezone(tz).date().replace(day=1)
    end = last.astimezone(tz).date()
    while d <= end:
        out.append(f"{d.year:04d}-{d.month:02d}")
        d = date(d.year + d.month // 12, d.month % 12 + 1, 1)
    return out
