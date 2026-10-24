"""Simulation behaviour: determinism, power bounds, commands, owed energy, jobs, customers, measured readings."""

from datetime import datetime, timedelta, timezone

import pytest

from engine.customers import CustomerSource
from engine.devices import build_devices
from engine.hub import Hub

DAY_START = datetime(2026, 7, 17, 14, 0, tzinfo=timezone.utc)  # 07:00 local (PDT)
MINUTES = 16 * 60  # until 23:00 local


def iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def cmd(device_id, action, value=None, ts="2026-07-17T19:00:00Z"):
    return {"command_id": "c", "ts": ts, "device_id": device_id, "action": action, "value": value,
            "decision_id": None, "issued_by": "engine"}


def run_day(config, catalog, seed=42, surges=(), commands=None, outdoor=None):
    """Minute steps over a day. `commands`: {minute: [command, ...]} delivered before that minute's step.
    Returns (hub, reports)."""
    hub = Hub(build_devices(config, catalog, seed))
    customers = CustomerSource(seed)
    reports = []
    for m in range(MINUTES):
        ts = iso(DAY_START + timedelta(minutes=m))
        for c in (commands or {}).get(m, []):
            hub.deliver({**c, "ts": ts})
        ev = customers.events(ts, 1, list(surges))[0]
        hub.advance(ts, 1, ev["orders"], outdoor)
        reports.append(hub.report(ts))
    return hub, reports


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


def test_same_seed_gives_identical_day(demo_config, catalog):
    surge = [{"customers": 40, "duration_min": 60, "start_ts": "2026-07-17T19:00:00Z"}]
    _, a = run_day(demo_config, catalog, seed=7, surges=surge)
    _, b = run_day(demo_config, catalog, seed=7, surges=surge)
    _, c = run_day(demo_config, catalog, seed=8, surges=surge)
    assert a == b
    assert a != c


def test_power_never_negative_or_above_rated(demo_config, catalog):
    surge = [{"customers": 80, "duration_min": 120, "start_ts": "2026-07-17T19:00:00Z"}]
    hub, reports = run_day(demo_config, catalog, surges=surge, outdoor=35.0)
    rated = {d["device_id"]: d["rated_kw"] for d in hub.devices()}
    for r in reports:
        assert abs(r["total_kw"] - sum(d["power_kw"] for d in r["devices"])) < 1e-6
        for d in r["devices"]:
            assert 0 <= d["power_kw"] <= rated[d["device_id"]] + 1e-9


def test_the_kitchen_is_busier_at_lunch_than_mid_morning(demo_config, catalog):
    _, reports = run_day(demo_config, catalog)
    by_ts = {r["ts"]: r["total_kw"] for r in reports}
    morning = sum(by_ts[iso(DAY_START + timedelta(minutes=m))] for m in range(180, 210)) / 30  # 10:00–10:30
    lunch = sum(by_ts[iso(DAY_START + timedelta(minutes=m))] for m in range(330, 360)) / 30  # 12:30–13:00
    night = by_ts[iso(DAY_START + timedelta(minutes=MINUTES - 1))]
    assert lunch > morning > night


def test_reduce_never_below_min_power_and_owed_energy_is_repaid_by_close(demo_config, catalog):
    """HVAC reduced to 20 % (below its 40 % minimum) for 30 min at lunch: it stays at ≥ 40 % of what it would draw,
    owes the energy it skipped, and has repaid it all by close."""
    reduce_at, restore_at = 330, 360  # 12:30 → 13:00 local
    _, base = run_day(demo_config, catalog)
    hub, red = run_day(demo_config, catalog, commands={reduce_at: [cmd("hvac_1", "reduce", 20)], restore_at: [cmd("hvac_1", "restore")]})

    def hvac(reports, m):
        return next(d for d in reports[m]["devices"] if d["device_id"] == "hvac_1")

    for m in range(reduce_at, restore_at):
        assert hvac(red, m)["state"] == "reduced"
        assert hvac(red, m)["power_kw"] >= 0.4 * hvac(base, m)["power_kw"] - 1e-5  # readings are rounded to 6 dp

    hvac_dev = next(d for d in hub._devices.values() if d.device_id == "hvac_1")
    assert hvac_dev.owed_kwh < 1e-9  # repaid by the end of the day


def test_food_safety_floor_holds_for_refrigeration(demo_config, catalog):
    hub = Hub(build_devices(demo_config, catalog, seed=1))
    hub.deliver(cmd("walk_in_cooler_1", "reduce", 10))
    cooler = hub._devices["walk_in_cooler_1"]
    assert cooler._reduce_pct == 50


def test_delay_waits_then_runs_full_job(demo_config, catalog):
    """A dishwasher job delayed 20 min draws nothing while waiting, then runs its full 30-minute cycle at rated kW."""
    for e in demo_config["equipment"]:
        e["count"] = 1 if e["type_id"] == "dishwasher" else 0
    hub = Hub(build_devices(demo_config, catalog, seed=1))
    dw = hub._devices["dishwasher_1"]
    t0 = datetime(2026, 7, 17, 19, 0, tzinfo=timezone.utc)
    hub.deliver(cmd("dishwasher_1", "start", ts=iso(t0)))
    hub.deliver(cmd("dishwasher_1", "delay", 20, ts=iso(t0)))
    states, energy = [], 0.0
    for m in range(60):
        ts = iso(t0 + timedelta(minutes=m))
        hub.advance(ts, 1, 0, None)
        states.append(dw.state)
        energy += dw.power_kw / 60
    assert states[:20] == ["waiting"] * 20
    assert states[20:50] == ["running_job"] * 30
    assert abs(energy - dw.rated_kw * 30 / 60) < 1e-9  # 6 kW × 0.5 h = 3 kWh, all of it, just later


def test_off_and_on(demo_config, catalog):
    hub = Hub(build_devices(demo_config, catalog, seed=1))
    hub.deliver(cmd("lights_1", "off"))
    hub.advance("2026-07-17T19:00:00Z", 1, 1, None)
    assert hub._devices["lights_1"].state == "off" and hub._devices["lights_1"].power_kw == 0
    hub.deliver(cmd("lights_1", "on"))
    hub.advance("2026-07-17T19:01:00Z", 1, 1, None)
    assert hub._devices["lights_1"].state == "on" and hub._devices["lights_1"].power_kw == 3.0


def test_measured_reading_overrides_one_step(demo_config, catalog):
    hub = Hub(build_devices(demo_config, catalog, seed=1))
    hub.ingest_reading("dishwasher_1", 6.2)
    hub.advance("2026-07-17T19:00:00Z", 1, 0, None)
    r = hub.report("2026-07-17T19:00:00Z")
    dw = next(d for d in r["devices"] if d["device_id"] == "dishwasher_1")
    assert dw["source"] == "measured" and dw["power_kw"] == 6.0  # capped at rated
    assert r["source"] == "mixed"
    hub.advance("2026-07-17T19:01:00Z", 1, 0, None)
    assert hub.report("2026-07-17T19:01:00Z")["source"] == "simulated"


def test_customers_are_seeded_and_surges_add_on_top():
    ts = "2026-07-17T19:00:00Z"  # 12:00 local
    a = [CustomerSource(3).events(ts, 1, [])[0]["arrivals"] for _ in range(1)]
    s1, s2 = CustomerSource(3), CustomerSource(3)
    assert [s1.events(ts, 1, [])[0]["arrivals"] for _ in range(50)] == [s2.events(ts, 1, [])[0]["arrivals"] for _ in range(50)]
    assert a  # draws happen
    surge = [{"customers": 40, "duration_min": 60, "start_ts": ts}]
    src = CustomerSource(3)
    assert src.rate_per_hour(ts, surge) == pytest.approx(src.rate_per_hour(ts, []) + 40)
    assert src.rate_per_hour("2026-07-17T20:30:00Z", surge) == pytest.approx(src.rate_per_hour("2026-07-17T20:30:00Z", []))
    assert src.rate_per_hour("2026-07-17T15:00:00Z", []) == 0  # 08:00 local: closed


def test_hub_reports_over_built_devices(demo_config, catalog):
    hub = Hub(build_devices(demo_config, catalog, seed=42))
    hub.advance("2026-07-17T19:00:00Z", 1, 1, None)
    r = hub.report("2026-07-17T19:00:00Z")
    assert len(r["devices"]) == len(catalog) and r["source"] == "simulated"
    assert len(hub.devices()) == len(catalog)
