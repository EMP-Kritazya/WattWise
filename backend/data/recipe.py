"""Distribution recipe (DATA_AND_PROOF.md "Distributing historical load onto devices"): fixed, deterministic, no AI.

Step 1 (ComStock end uses -> groups, `assumptions.yaml` `step1`):
  hvac group    = cooling + heating + pumps + heat_rejection + heat_recovery -> split equally over the hvac units
  exhaust group = fans (a constant 5.74 kW in bldg 5847)                      -> split equally over the kitchen_exhaust units
  lights group  = interior_lighting + exterior_lighting                       -> split equally over the lights units
  interior_equipment (+ the file's float32 residual `total - sum(end uses)`)  -> step 2
  `must_be_zero` end uses (refrigeration, water_systems, pv) must be 0 in every row, else ValueError (no mapping exists).
Step 2 is two-part (decided 2026-10-25), on interior_equipment:
  2a. base: each `base_duty` type draws `rated_kw x duty` (`open_pct` while the kitchen is open, `closed_pct` while closed),
      all scaled down together in a row where interior_equipment is smaller than their sum (the data never gets more).
  2b. variable: the rest (interior_equipment - base, never negative) goes to the `variable_shares` types (percent, sum 100).
  A type with count n splits its part equally; the last device takes the remainder so every row sums exactly.

Every row's device kW sum to the dataset's `total` kW (float64, |error| <= 1e-9). No device may exceed its catalog `rated_kw`:
`distribute` raises `RatedKwExceeded` naming the device, its worst block and how many blocks are over; nothing is ever clipped.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Mapping, Sequence

import numpy as np

from .comstock import END_USES, TOTAL, ComStockRows

SUM_TOLERANCE_KW = 1e-9
GROUPS = (("hvac", "hvac"), ("exhaust", "kitchen_exhaust"), ("lights", "lights"))  # step-1 group -> the type it feeds


class RatedKwExceeded(ValueError):
    """A device's distributed load is above its catalog rated_kw (the loader never clips)."""


@dataclass(frozen=True)
class DeviceSeries:
    device_ids: list[str]  # sorted, `<type_id>_<n>`
    type_of: dict[str, str]
    kw: np.ndarray  # shape (rows, devices), float64

    def column(self, device_id: str) -> np.ndarray:
        return self.kw[:, self.device_ids.index(device_id)]


def roster(equipment: Iterable[Mapping]) -> dict[str, str]:
    """device_id -> type_id for every unit (count 0 = absent), sorted by device_id like the engine's roster."""
    out: dict[str, str] = {}
    for entry in equipment:
        for n in range(1, int(entry["count"]) + 1):
            out[f"{entry['type_id']}_{n}"] = entry["type_id"]
    return {d: out[d] for d in sorted(out)}


def distribute(rows: ComStockRows, equipment: Sequence[Mapping], catalog: Sequence[Mapping], step1: Mapping,
               assumptions: Mapping, is_open: np.ndarray) -> DeviceSeries:
    """The recipe with both guards: rows sum exactly to `total`, and no device above its catalog rated_kw (raises)."""
    series = split(rows, equipment, catalog, step1, assumptions, is_open)
    rated = {c["type_id"]: float(c["rated_kw"]) for c in catalog}
    check_sum(series.kw, rows.kw[TOTAL])
    check_rated(series.kw, series.device_ids, {d: rated[series.type_of[d]] for d in series.device_ids}, rows.start_utc)
    return series


def split(rows: ComStockRows, equipment: Sequence[Mapping], catalog: Sequence[Mapping], step1: Mapping,
          assumptions: Mapping, is_open: np.ndarray) -> DeviceSeries:
    """Steps 1 + 2 only (no rated_kw guard; `distribute` adds it). Never alters a value: no clipping, no filling.

    `is_open`: one bool per row, the kitchen's operating hours at that row's local time (the caller's calendar)."""
    rated = {c["type_id"]: float(c["rated_kw"]) for c in catalog}
    units = roster(equipment)
    by_type: dict[str, list[str]] = {}
    for d, t in units.items():
        by_type.setdefault(t, []).append(d)
    unknown = [t for t in by_type if t not in rated]
    if unknown:
        raise ValueError(f"equipment types not in the catalog: {unknown}")

    kw = rows.kw
    n = len(rows)
    is_open = np.asarray(is_open, dtype=bool)
    if is_open.shape != (n,):
        raise ValueError(f"is_open has shape {is_open.shape}, expected ({n},)")
    for end_use in step1["must_be_zero"]:
        if np.any(kw[end_use] != 0.0):
            raise ValueError(f"end use {end_use!r} is non-zero in this file but has no device mapping (step 1)")
    mapped = set(step1["must_be_zero"]) | set(step1["interior_equipment"])
    for group, _ in GROUPS:
        mapped |= set(step1[group])
    missing = [e for e in END_USES if e not in mapped]
    if missing:
        raise ValueError(f"step 1 does not map end uses {missing}")

    group_kw = {}
    for group, t in GROUPS:
        if t not in by_type:
            raise ValueError(f"the kitchen has no {t} unit for step 1 group {group!r}")
        acc = np.zeros(n)
        for e in step1[group]:
            acc = acc + kw[e]
        group_kw[group] = acc
    # interior equipment absorbs the float32 residual so the devices sum to the file's total exactly
    interior_kw = kw[TOTAL] - sum(group_kw.values())
    if np.any(interior_kw < 0) or any(np.any(v < 0) for v in group_kw.values()):
        raise ValueError("negative group load in the data")

    base_duty = {t: (float(p["open_pct"]), float(p["closed_pct"])) for t, p in assumptions["base_duty"].items()}
    shares = {t: float(s) for t, s in assumptions["variable_shares"].items()}
    if abs(sum(shares.values()) - 100.0) > 1e-9:
        raise ValueError(f"variable_shares sum to {sum(shares.values())}, expected 100")
    both = set(base_duty) & set(shares)
    if both:
        raise ValueError(f"types in both base_duty and variable_shares: {sorted(both)}")
    for t in list(base_duty) + list(shares):
        if t not in by_type:
            raise ValueError(f"step-2 entry for {t!r} but the kitchen has no {t}")
    leftover = [t for t in by_type if t not in base_duty and t not in shares and t not in dict(GROUPS).values()]
    if leftover:
        raise ValueError(f"no step-2 part for kitchen types {leftover}")

    device_ids = list(units)
    col = {d: i for i, d in enumerate(device_ids)}
    out = np.zeros((n, len(device_ids)))
    for group, t in GROUPS:
        _split_equal(out, col, by_type[t], group_kw[group])

    # 2a. base: duty-average draw per type, scaled down together where the data has less
    want = {t: np.where(is_open, o, c) / 100.0 * rated[t] * len(by_type[t]) for t, (o, c) in base_duty.items()}
    want_sum = sum(want.values(), np.zeros(n))
    scale = np.where(want_sum > interior_kw, interior_kw / np.where(want_sum > 0, want_sum, 1.0), 1.0)
    base_kw = {t: v * scale for t, v in want.items()}
    # 2b. variable: the rest by shares; the last type takes the remainder so the row sums exactly
    rest_kw = np.maximum(interior_kw - sum(base_kw.values(), np.zeros(n)), 0.0)  # negative only by float rounding
    types = list(shares)
    part = {t: rest_kw * (shares[t] / 100.0) for t in types[:-1]}
    remainder = interior_kw - sum(base_kw.values(), np.zeros(n)) - sum(part.values(), np.zeros(n))
    part[types[-1]] = np.maximum(remainder, 0.0)  # a -1e-16 kW float residue would fail the loader's no-negative check
    for t, v in {**base_kw, **part}.items():
        _split_equal(out, col, by_type[t], v)
    return DeviceSeries(device_ids=device_ids, type_of=dict(units), kw=out)


def _split_equal(out: np.ndarray, col: Mapping[str, int], devices: list[str], group_kw: np.ndarray) -> None:
    k = len(devices)
    acc = np.zeros_like(group_kw)
    for d in devices[:-1]:
        out[:, col[d]] = group_kw / k
        acc = acc + out[:, col[d]]
    out[:, col[devices[-1]]] = group_kw - acc


def check_sum(device_kw: np.ndarray, total_kw: np.ndarray) -> None:
    err = np.abs(device_kw.sum(axis=1) - total_kw)
    if np.any(err > SUM_TOLERANCE_KW):
        i = int(np.argmax(err))
        raise AssertionError(f"device blocks do not sum to the dataset total at row {i}: error {err[i]:.3e} kW")


def check_rated(device_kw: np.ndarray, device_ids: Sequence[str], rated_kw: Mapping[str, float],
                starts: Sequence[datetime]) -> None:
    problems = []
    for j, d in enumerate(device_ids):
        over = device_kw[:, j] > rated_kw[d] + 1e-12
        if np.any(over):
            i = int(np.argmax(device_kw[:, j]))
            problems.append(f"{d}: max {device_kw[i, j]:.3f} kW at {starts[i].isoformat()} (dataset time, UTC) > rated_kw {rated_kw[d]} "
                            f"({int(over.sum())} of {len(over)} blocks over)")
    if problems:
        raise RatedKwExceeded("distributed load exceeds catalog rated_kw (never clipped): " + "; ".join(problems))
