"""Tariffs the backend can load: the real PG&E B-19 (URDB, `label: "urdb"`) and the made-up demo rate (`illustrative`).

`DEMO_TARIFF` is the CONTRACTS.md section 1 example `demo_tariff_v1`, written with every optional field. No number billed on it
is ever shown as a real saving.
"""
from __future__ import annotations

import copy
from pathlib import Path

from .tariff_urdb import B19_FILE, load_urdb_tariff

DEMO_TARIFF = {
    "tariff_id": "demo_tariff_v1",
    "name": "WattWise demo commercial rate",
    "label": "illustrative",
    "currency": "USD",
    "timezone": "America/Los_Angeles",
    "energy": [
        {"name": "off_peak", "start": "00:00", "end": "16:00", "usd_per_kwh": 0.22, "months": None, "days": "all"},
        {"name": "peak", "start": "16:00", "end": "21:00", "usd_per_kwh": 0.38, "months": None, "days": "all"},
        {"name": "off_peak", "start": "21:00", "end": "24:00", "usd_per_kwh": 0.22, "months": None, "days": "all"},
    ],
    "demand": [
        {"name": "max_demand", "windows": None, "months": None, "days": "all", "usd_per_kw": 20.0},
        {"name": "peak_demand", "windows": [{"start": "16:00", "end": "21:00"}], "months": None, "days": "all",
         "usd_per_kw": 8.0},
    ],
    "fixed_charges": [],
}


def load_tariff(which: str = "pge_b19", path: Path = B19_FILE) -> dict:
    """`"pge_b19"` -> the URDB file (FileNotFoundError if dataset/ is absent) · `"demo"` -> demo_tariff_v1."""
    if which == "demo":
        return copy.deepcopy(DEMO_TARIFF)
    if which == "pge_b19":
        return load_urdb_tariff(path)
    raise ValueError(f"unknown tariff {which!r} (pge_b19 | demo)")
