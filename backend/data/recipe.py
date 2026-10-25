"""Distribution recipe (DATA_AND_PROOF.md "Distributing historical load onto devices"): fixed, deterministic, no AI.

Step 1 (ComStock end uses -> groups, `assumptions.yaml` `step1`):
  hvac group   = cooling + fans + heating + pumps + heat_rejection + heat_recovery -> split equally over the hvac units
  lights group = interior_lighting + exterior_lighting                              -> split equally over the lights units
  interior_equipment (+ the file's float32 residual `total - sum(end uses)`)        -> step 2
  `must_be_zero` end uses (refrigeration, water_systems, pv) must be 0 in every row, else ValueError (no mapping exists).
Step 2: interior_equipment -> the kitchen devices by the `interior_equipment` shares of the assumption set (percent, sum 100);
  a type with count n splits its share equally; the last device takes the remainder so every row sums exactly.

Every row's device kW sum to the dataset's `total` kW (float64, |error| <= 1e-9). No device may exceed its catalog `rated_kw`:
`overflow: "raise"` (base) raises `RatedKwExceeded` naming the device, its worst block and how many blocks are over; nothing is
ever clipped. `overflow: "redistribute"` (a labelled proposal only) caps an over-rated interior device at rated_kw and spreads
the excess over the other interior devices in proportion to their shares; the row total is unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Mapping, Sequence

import numpy as np

from .comstock import END_USES, TOTAL, ComStockRows

SUM_TOLERANCE_KW = 1e-9


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
               assumptions: Mapping) -> DeviceSeries:
    """The recipe with both guards: rows sum exactly to `total`, and no device above its catalog rated_kw (raises)."""
    series = split(rows, equipment, catalog, step1, assumptions)
    rated = {c["type_id"]: float(c["rated_kw"]) for c in catalog}
    check_sum(series.kw, rows.kw[TOTAL])
    check_rated(series.kw, series.device_ids, {d: rated[series.type_of[d]] for d in series.device_ids}, rows.start_utc)
    return series


def split(rows: ComStockRows, equipment: Sequence[Mapping], catalog: Sequence[Mapping], step1: Mapping,
          assumptions: Mapping) -> DeviceSeries:
    """Steps 1 + 2 only (no rated_kw guard; `distribute` adds it). Never alters a value: no clipping, no filling."""
    rated = {c["type_id"]: float(c["rated_kw"]) for c in catalog}
    units = roster(equipment)
    by_type: dict[str, list[str]] = {}
    for d, t in units.items():
        by_type.setdefault(t, []).append(d)
    unknown = [t for t in by_type if t not in rated]
    if unknown:
        raise ValueError(f"equipment types not in the catalog: {unknown}")

    kw = rows.kw
    for end_use in step1["must_be_zero"]:
        if np.any(kw[end_use] != 0.0):
            raise ValueError(f"end use {end_use!r} is non-zero in this file but has no device mapping (step 1)")
    mapped = set(step1["hvac"]) | set(step1["lights"]) | set(step1["interior_equipment"]) | set(step1["must_be_zero"])
    missing = [e for e in END_USES if e not in mapped]
    if missing:
        raise ValueError(f"step 1 does not map end uses {missing}")

    n = len(rows)
    hvac_kw = np.zeros(n)
    for e in step1["hvac"]:
        hvac_kw = hvac_kw + kw[e]
    lights_kw = np.zeros(n)
    for e in step1["lights"]:
        lights_kw = lights_kw + kw[e]
    # interior equipment absorbs the float32 residual so the devices sum to the file's total exactly
    interior_kw = kw[TOTAL] - hvac_kw - lights_kw

    shares = {t: float(s) for t, s in assumptions["interior_equipment"].items()}
    if abs(sum(shares.values()) - 100.0) > 1e-9:
        raise ValueError(f"interior_equipment shares sum to {sum(shares.values())}, expected 100")
    for t in shares:
        if t not in by_type:
            raise ValueError(f"share for {t!r} but the kitchen has no {t}")
    for group, types in (("hvac", ["hvac"]), ("lights", ["lights"])):
        if not all(t in by_type for t in types):
            raise ValueError(f"the kitchen has no {group} unit for step 1 group {group!r}")
    leftover = [t for t in by_type if t not in shares and t not in ("hvac", "lights")]
    if leftover:
        raise ValueError(f"no step-2 share for kitchen types {leftover}")

    if np.any(interior_kw < 0) or np.any(hvac_kw < 0) or np.any(lights_kw < 0):
        raise ValueError("negative group load in the data")

    device_ids = list(units)
    col = {d: i for i, d in enumerate(device_ids)}
    out = np.zeros((n, len(device_ids)))
    for group_kw, t in ((hvac_kw, "hvac"), (lights_kw, "lights")):
        _split_equal(out, col, by_type[t], group_kw)

    interior_types = list(shares)
    type_kw = {t: interior_kw * (shares[t] / 100.0) for t in interior_types[:-1]}
    type_kw[interior_types[-1]] = interior_kw - sum(type_kw[t] for t in interior_types[:-1])
    if assumptions.get("overflow", "raise") == "redistribute":
        type_kw = _redistribute(type_kw, shares, {t: rated[t] * len(by_type[t]) for t in interior_types}, interior_kw)
    for t in interior_types:
        _split_equal(out, col, by_type[t], type_kw[t])
    return DeviceSeries(device_ids=device_ids, type_of=dict(units), kw=out)


def _split_equal(out: np.ndarray, col: Mapping[str, int], devices: list[str], group_kw: np.ndarray) -> None:
    k = len(devices)
    acc = np.zeros_like(group_kw)
    for d in devices[:-1]:
        out[:, col[d]] = group_kw / k
        acc = acc + out[:, col[d]]
    out[:, col[devices[-1]]] = group_kw - acc


def _redistribute(type_kw: dict[str, np.ndarray], shares: Mapping[str, float], cap_kw: Mapping[str, float],
                  interior_kw: np.ndarray) -> dict[str, np.ndarray]:
    """PROPOSAL only (`overflow: redistribute`): water-fill the excess over rated onto the uncapped types by share."""
    types = list(type_kw)
    m = np.stack([type_kw[t] for t in types], axis=1)
    caps = np.array([cap_kw[t] for t in types])
    w = np.array([shares[t] for t in types])
    if np.any(interior_kw > caps.sum() + 1e-9):
        raise RatedKwExceeded("interior_equipment exceeds the sum of the interior devices' rated_kw: cannot redistribute")
    for _ in range(len(types) + 1):
        over = np.clip(m - caps, 0.0, None)
        excess = over.sum(axis=1)
        if not np.any(excess > 0):
            break
        m = m - over
        free = (m < caps - 1e-12).astype(float) * w
        denom = free.sum(axis=1, keepdims=True)
        m = m + np.where(denom > 0, free / np.where(denom > 0, denom, 1.0), 0.0) * excess[:, None]
    # exact row total: the remainder goes to the type with the most headroom in that row
    resid = interior_kw - m.sum(axis=1)
    j = np.argmax(caps - m, axis=1)
    m[np.arange(len(m)), j] += resid
    return {t: m[:, i] for i, t in enumerate(types)}


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
