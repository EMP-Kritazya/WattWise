"""Shared, minimal helpers for engine tests (owner: Kritazya).

Only builders of contract shapes live here: tariff / config / catalog loaders (`catalog()` = the Kitchen argument),
the device roster, HubReport and WarmUpHistory builders, and local-time conversion. Module-specific stepping helpers belong in each test_<module>.py.

Inputs are contract models from `backend/contracts/` (they win over prose). Shape fixtures come from
`contracts/fixtures/shapes/` (stable single-shape files); stream fixtures are not used here.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Optional
from zoneinfo import ZoneInfo

import pytest

from contracts import (
    Device,
    EquipmentType,
    HistoryBlock,
    HubReport,
    KitchenConfig,
    Meter,
    MonthToDate,
    Tariff,
    TickState,
    WarmUpHistory,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = REPO_ROOT / "contracts" / "fixtures"
SHAPES = FIXTURES / "shapes"

LOCAL_TZ = ZoneInfo("America/Los_Angeles")  # demo_tariff_v1.timezone


# ---------------------------------------------------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------------------------------------------------


def load_json(relative: str):
    return json.loads((FIXTURES / relative).read_text())


def load_tariff() -> Tariff:
    """demo_tariff_v1: energy 0.22 off-peak / 0.38 16:00-21:00; demand $20/kW max + $8/kW in 16:00-21:00."""
    return Tariff.model_validate(load_json("shapes/tariff.json"))


def load_config() -> KitchenConfig:
    """Demo Café, peak_mode cap at 40 kW."""
    return KitchenConfig.model_validate(load_json("shapes/kitchen_config.json"))


CATALOG_PATH = SHAPES / "equipment_catalog.json"  # loaded by path, never hardcoded (texts may be regenerated)


def catalog() -> list[dict]:
    """The `catalog` argument of `Kitchen(config, tariff, catalog, control, seed, ids=None)` and
    `Kitchen.build_lanes(config, tariff, catalog, seed)` (CONTRACTS.md section 3): list[EquipmentType], each entry
    validated against the contract model, passed as plain JSON-ready dicts (golden rule 7: plain objects in).
    A fresh copy on every call, so a test may edit it."""
    return [EquipmentType.model_validate(t).model_dump(mode="json") for t in json.loads(CATALOG_PATH.read_text())]


def load_catalog() -> dict[str, EquipmentType]:
    """Same catalog keyed by type_id, as contract models (roster / rated_kw lookups in tests)."""
    return {t["type_id"]: EquipmentType.model_validate(t) for t in catalog()}


@pytest.fixture
def tariff() -> Tariff:
    return load_tariff()


@pytest.fixture
def kitchen_config() -> KitchenConfig:
    return load_config()


@pytest.fixture
def catalog_by_type() -> dict[str, EquipmentType]:
    return load_catalog()


# ---------------------------------------------------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------------------------------------------------


def local_ts(year: int, month: int, day: int, hour: int = 0, minute: int = 0, *, fold: int = 0) -> datetime:
    """Local wall clock in the tariff timezone -> aware UTC datetime (what every contract timestamp carries)."""
    return datetime(year, month, day, hour, minute, tzinfo=LOCAL_TZ, fold=fold).astimezone(timezone.utc)


# ---------------------------------------------------------------------------------------------------------------------
# Roster, HubReport, WarmUpHistory
# ---------------------------------------------------------------------------------------------------------------------


def roster(config: KitchenConfig, catalog: Mapping[str, EquipmentType]) -> list[dict]:
    """Device ids `<type_id>_<n>` in config order (CONTRACTS.md KitchenConfig), with catalog rated_kw."""
    out = []
    for entry in config.equipment:
        etype = catalog[entry.type_id]
        for n in range(1, entry.count + 1):
            out.append(
                {
                    "device_id": f"{entry.type_id}_{n}",
                    "type_id": entry.type_id,
                    "name": f"{etype.name} {n}",
                    "importance": entry.importance,
                    "rated_kw": etype.rated_kw,
                    "power_model": etype.power_model,
                }
            )
    return out


def split_kw(total_kw: float, devices: list[dict]) -> dict[str, float]:
    """Spread a kitchen total over the roster in proportion to rated_kw (no device above its rating while
    total_kw <= sum of rated_kw = 76.2 kW for the Demo Café). The meter only reads the sum."""
    rated_sum = sum(d["rated_kw"] for d in devices)
    assert total_kw <= rated_sum + 1e-9, "test load above the kitchen's rated sum"
    return {d["device_id"]: total_kw * d["rated_kw"] / rated_sum for d in devices}


def hub_report(
    *,
    lane: str,
    tick_id: int,
    ts: datetime,
    total_kw: float,
    devices: list[dict],
    customers_per_hour: int = 0,
    indoor_temp_c: float = 22.0,
    acks: Optional[list] = None,
    power_by_device: Optional[Mapping[str, float]] = None,
) -> HubReport:
    """A HubReport whose devices sum to `total_kw` (or use `power_by_device` as given)."""
    powers = dict(power_by_device) if power_by_device is not None else split_kw(total_kw, devices)
    devs = []
    for d in devices:
        p = powers.get(d["device_id"], 0.0)
        devs.append(
            Device(
                device_id=d["device_id"],
                type_id=d["type_id"],
                name=d["name"],
                importance=d["importance"],
                state="on" if p > 0 else "off",
                power_kw=p,
                rated_kw=d["rated_kw"],
                power_pct=round(100 * p / d["rated_kw"]),
                source="simulated",
                physical={"indoor_temp_c": indoor_temp_c} if d["power_model"] == "thermal" else None,
            )
        )
    return HubReport(
        hub_id="sim_hub",
        lane=lane,
        tick_id=tick_id,
        ts=ts,
        total_kw=sum(dv.power_kw for dv in devs),
        customers_per_hour=customers_per_hour,
        devices=devs,
        acks=list(acks or []),
        source="simulated",
    )


def warmup_history(
    *,
    start: datetime,
    end: datetime,
    block_totals_kw: Iterable[tuple[datetime, float]],
    devices: list[dict],
    month_to_date: Optional[MonthToDate] = None,
) -> WarmUpHistory:
    """WarmUpHistory (fixture_synthetic / simulated) with each block's kitchen total spread over the roster."""
    blocks = []
    for block_start, total in block_totals_kw:
        for device_id, kw in split_kw(total, devices).items():
            blocks.append(HistoryBlock(block_start=block_start, device_id=device_id, avg_kw=kw))
    return WarmUpHistory(
        source="fixture_synthetic",
        label="simulated",
        dataset_id="test_inline",
        scale=1.0,
        day_offset=0,
        start=start,
        end=end,
        blocks=blocks,
        month_to_date=month_to_date,
    )


def warmup_history_per_device(
    *,
    start: datetime,
    end: datetime,
    blocks: Iterable[tuple[datetime, str, float]],
    month_to_date: Optional[MonthToDate] = None,
) -> WarmUpHistory:
    """WarmUpHistory (fixture_synthetic / simulated) from explicit (block_start, device_id, avg_kw) rows, so each device's
    history value is hand-chosen (the forecaster works per device). Rows are sorted by (block_start, device_id)."""
    rows = sorted(blocks, key=lambda b: (b[0], b[1]))
    return WarmUpHistory(
        source="fixture_synthetic",
        label="simulated",
        dataset_id="test_inline",
        scale=1.0,
        day_offset=0,
        start=start,
        end=end,
        blocks=[HistoryBlock(block_start=b, device_id=d, avg_kw=kw) for b, d, kw in rows],
        month_to_date=month_to_date,
    )


# ---------------------------------------------------------------------------------------------------------------------
# Output normalisation
# ---------------------------------------------------------------------------------------------------------------------


def as_tick_state(result) -> TickState:
    """`step()` returns a TickState (model or plain dict); validate it against the contract either way."""
    if isinstance(result, TickState):
        return result
    return TickState.model_validate(result)


def meter_of(result) -> Meter:
    return as_tick_state(result).meter
