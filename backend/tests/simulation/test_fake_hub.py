"""FakeHub honours the hub interface (CONTRACTS.md section 8) so the brain can be built against it."""

from engine.fake_hub import FakeHub
from engine.hub import UnknownDevice

LUNCH = "2026-07-17T19:45:00Z"  # 12:45 local
LATER = "2026-07-17T20:30:00Z"


def cmd(device_id, action, value=None, ts=LUNCH):
    return {"command_id": "c_1", "ts": ts, "device_id": device_id, "action": action, "value": value,
            "decision_id": None, "issued_by": "engine"}


def test_report_shape_and_total(demo_config, catalog):
    hub = FakeHub(demo_config, catalog)
    r = hub.report(LUNCH)
    assert r["ts"] == LUNCH and r["source"] == "simulated"
    assert len(r["devices"]) == len(catalog)
    assert abs(r["total_kw"] - sum(d["power_kw"] for d in r["devices"])) < 1e-6
    ids = {d["device_id"] for d in r["devices"]}
    assert "hvac_1" in ids and "dishwasher_1" in ids


def test_deterministic(demo_config, catalog):
    assert FakeHub(demo_config, catalog).report(LUNCH) == FakeHub(demo_config, catalog).report(LUNCH)


def test_power_within_bounds(demo_config, catalog):
    hub = FakeHub(demo_config, catalog)
    rated = {d["device_id"]: d["rated_kw"] for d in hub.devices()}
    for hour in range(24):
        ts = f"2026-07-17T{hour:02d}:00:00Z"
        for d in hub.report(ts)["devices"]:
            assert 0 <= d["power_kw"] <= rated[d["device_id"]] + 1e-9


def test_commands_change_power_and_state(demo_config, catalog):
    hub = FakeHub(demo_config, catalog)
    before = {d["device_id"]: d for d in hub.report(LUNCH)["devices"]}

    hub.deliver(cmd("hvac_1", "reduce", 50))
    hub.deliver(cmd("dishwasher_1", "delay", 20))
    hub.deliver(cmd("lights_1", "off"))
    after = {d["device_id"]: d for d in hub.report(LUNCH)["devices"]}

    assert after["hvac_1"]["state"] == "reduced"
    assert abs(after["hvac_1"]["power_kw"] - before["hvac_1"]["power_kw"] * 0.5) < 1e-6
    assert after["dishwasher_1"]["state"] == "waiting" and after["dishwasher_1"]["power_kw"] == 0
    assert after["lights_1"]["state"] == "off" and after["lights_1"]["power_kw"] == 0
    assert [c["device_id"] for c in hub.log] == ["hvac_1", "dishwasher_1", "lights_1"]


def test_delay_ends_and_restore_clears(demo_config, catalog):
    hub = FakeHub(demo_config, catalog)
    hub.deliver(cmd("dishwasher_1", "delay", 20))
    hub.deliver(cmd("hvac_1", "reduce", 40))
    hub.deliver(cmd("hvac_1", "restore"))
    r = {d["device_id"]: d for d in hub.report(LATER)["devices"]}  # 45 min later: delay is over
    assert r["dishwasher_1"]["state"] == "on"
    assert r["hvac_1"]["state"] == "on"


def test_unknown_device_is_rejected(demo_config, catalog):
    hub = FakeHub(demo_config, catalog)
    try:
        hub.deliver(cmd("toaster_9", "off"))
    except UnknownDevice:
        return
    raise AssertionError("expected UnknownDevice")
