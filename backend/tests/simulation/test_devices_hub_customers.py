"""Simulation skeleton tests. Building devices works now; behaviour tests are Phase 2 (skipped until implemented)."""

import pytest

from engine.devices import build_devices
from engine.hub import Hub

PHASE2 = pytest.mark.skip(reason="Phase 2: power models, commands and customer arrivals not implemented yet")


def test_build_devices_ids_and_defaults(demo_config, catalog):
    devices = build_devices(demo_config, catalog, seed=42)
    assert [d.device_id for d in devices] == [f"{t['type_id']}_1" for t in catalog]
    hvac = next(d for d in devices if d.type_id == "hvac")
    assert hvac.importance == "flexible" and hvac.limits["min_power_pct"] == 40


def test_count_zero_means_absent_and_counts_number_units(demo_config, catalog):
    for e in demo_config["equipment"]:
        e["count"] = 2 if e["type_id"] == "fryer" else 0
    ids = [d.device_id for d in build_devices(demo_config, catalog, seed=1)]
    assert ids == ["fryer_1", "fryer_2"]


def test_hub_reports_over_built_devices(demo_config, catalog):
    hub = Hub(build_devices(demo_config, catalog, seed=42))
    r = hub.report("2026-07-17T19:00:00Z")
    assert len(r["devices"]) == len(catalog) and r["source"] == "simulated"
    assert len(hub.devices()) == len(catalog)


@PHASE2
def test_same_seed_gives_identical_day():
    """Same config + seed + inputs → identical HubReports for a full simulated day."""


@PHASE2
def test_power_never_negative_or_above_rated():
    """Over a full day with surges, every device stays within 0..rated_kw."""


@PHASE2
def test_reduce_never_below_min_power_and_owes_energy():
    """A reduce command keeps a flexible device ≥ min_power_pct and adds the energy not drawn to owed_kwh."""


@PHASE2
def test_delay_waits_then_runs_full_job():
    """A delayed job draws 0 while waiting, then runs its full cycle_min at rated_kw (energy conserved)."""


@PHASE2
def test_customers_are_seeded_and_surges_add_on_top():
    """CustomerSource(seed).events(...) repeats exactly for the same seed; a surge adds its customers over its duration."""
