"""Liveness decided in Convex (convex/liveness.ts, crons.ts) and mirrored by the memory store: a hub's command still queued
15 s after enqueue → failed, a hub not seen for 30 s → offline in hubs:status. The device bridge (esp32) turns these into
hub_offline warnings, one retry of a failed command, then simulated for that device."""

import json

from api.settings import REPO_ROOT
from runtime.device_bridge import DeviceBridge, hub_offline_warning
from store import ConvexStore, MemoryStore

FIXTURES = REPO_ROOT / "contracts" / "fixtures"
COMMAND = json.loads((FIXTURES / "convex" / "functions" / "commands_enqueue.json").read_text(encoding="utf-8"))["args"]
DEVICE_MAP = json.loads((FIXTURES / "convex" / "tables" / "device_map.json").read_text(encoding="utf-8"))
T0 = 1_792_843_200.0  # 2026-10-24T12:00:00Z, real epoch seconds


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now


class Kitchen:
    def __init__(self):
        self.ingested = []

    def ingest_reading(self, reading):
        self.ingested.append(reading)


def command(command_id="c_0001", device_id="dishwasher_1"):
    return {**COMMAND["command"], "command_id": command_id, "device_id": device_id}


# ---------------------------------------------------------------- memory store mirrors convex/liveness.ts


def test_a_hub_command_not_acked_for_15_s_is_failed():
    clock = Clock()
    store = MemoryStore(clock=clock)
    store.record_command(command(), "with", "esp32_1")
    store.record_command(command("c_0002"), "with", None)  # simulated only: never waits on a hub
    clock.now += 15
    assert [c["delivery"] for c in store.rows("commands")] == ["queued", "queued"]
    clock.now += 0.1
    assert [c["delivery"] for c in store.rows("commands")] == ["failed", "queued"]
    assert store.commands_for_hub("esp32_1") == []
    assert [c["command_id"] for c in store.failed_commands("esp32_1", T0 * 1000)] == ["c_0001"]


def test_an_acked_command_is_never_failed_and_a_late_ack_still_wins():
    clock = Clock()
    store = MemoryStore(clock=clock)
    store.record_command(command(), "with", "esp32_1")
    store.record_command(command("c_0002"), "with", "esp32_1")
    store.ack_command("c_0001", True, 40.0, None)
    clock.now += 20
    assert [c["delivery"] for c in store.rows("commands")] == ["acked", "failed"]
    store.ack_command("c_0002", True, 40.0, None)
    assert [c["delivery"] for c in store.rows("commands")] == ["acked", "acked"]


def test_failed_commands_since_a_build_one_per_row():
    clock = Clock()
    store = MemoryStore(clock=clock)
    store.record_command(command(), "with", "esp32_1")  # previous kitchen build
    clock.now += 100
    since_ms = clock.now * 1000
    store.record_command(command(), "with", "esp32_1")
    store.ack_command("c_0001", False, None, "relay stuck")
    store.record_command(command(), "with", "esp32_1")  # the retry
    clock.now += 16
    failed = store.failed_commands("esp32_1", since_ms)
    assert [c["command_id"] for c in failed] == ["c_0001", "c_0001"]
    assert "hub_id" not in failed[0] and "delivery" not in failed[0]
    assert store.failed_commands("esp32_2", since_ms) == []


def test_hub_status_offline_after_30_s_without_heartbeat():
    clock = Clock()
    store = MemoryStore(clock=clock)
    store.heartbeat("esp32_1")
    assert store.hub_status() == [{"hub_id": "esp32_1", "last_seen": "2026-10-24T12:00:00.000Z", "firmware": None,
                                   "status": "online"}]
    clock.now += 30
    assert store.hub_status()[0]["status"] == "online"
    clock.now += 0.5
    assert store.hub_status()[0]["status"] == "offline"
    store.heartbeat("esp32_1")
    assert store.hub_status()[0]["status"] == "online"


# ---------------------------------------------------------------- convex store reads Convex's view


class Double:
    def __init__(self, answers=None, fail=None):
        self.calls, self.answers, self.fail = [], answers or {}, fail

    def mutation(self, name, args=None):
        self.calls.append(("mutation", name, args))

    def query(self, name, args=None):
        self.calls.append(("query", name, args))
        if self.fail:
            raise self.fail
        return self.answers.get(name, [])


def test_convex_store_reads_liveness_from_convex():
    view = [{"hub_id": "esp32_1", "last_seen": "2026-10-24T12:00:00.000Z", "firmware": None, "status": "offline"}]
    client = Double({"hubs:status": view, "commands:failed": [command()]})
    store = ConvexStore(client=client, autostart=False)
    assert store.hub_status() == view
    assert store.failed_commands("esp32_1", 123.0) == [command()]
    (_, status_name, status_args), (_, failed_name, failed_args) = client.calls
    assert status_name == "hubs:status" and set(status_args) == {"at"} and status_args["at"] % 5 == 0
    assert (failed_name, failed_args) == ("commands:failed", {"hub_id": "esp32_1", "since_ms": 123.0})


def test_convex_store_down_falls_back_to_the_mirror_rules():
    store = ConvexStore(client=Double(fail=httpx_error()), autostart=False)
    store.mirror.heartbeat("esp32_1")
    assert [h["status"] for h in store.hub_status()] == ["online"]
    assert store.kind == "memory"
    assert store.failed_commands("esp32_1", 0) == []


def httpx_error():
    import httpx
    return httpx.ConnectError("unreachable")


# ---------------------------------------------------------------- device bridge (esp32)


def esp32_bridge(mode="esp32"):
    clock, warnings = Clock(), []
    store = MemoryStore(clock=clock)
    for row in DEVICE_MAP:
        store.map_channel(row)
    bridge = DeviceBridge(mode, store, on_warning=warnings.append, clock=clock, wall_clock=clock)
    bridge.load_map(store.device_map())
    return bridge, store, clock, warnings


def reading(clock, raw_w=5.8):
    return {"hub_id": "esp32_1", "channel": 0, "device_id": "dishwasher_1", "ts": f"t{clock.now}", "raw_w": raw_w,
            "scale": 1000, "power_kw": raw_w}


def test_hub_status_offline_is_hub_offline_once_and_readings_bring_it_back():
    bridge, store, clock, warnings = esp32_bridge()
    store.heartbeat("esp32_1")
    store.report_reading(reading(clock))
    bridge.poll_once()
    assert bridge.measured_kw() == {"dishwasher_1": 5.8}
    clock.now += 31  # unplugged: no heartbeat (the reading timeout is pushed out so only hubs:status speaks)
    bridge._last_seen["dishwasher_1"] = clock.now
    bridge.poll_once()
    bridge.poll_once()
    assert warnings == [hub_offline_warning("dishwasher_1", "esp32_1", "hub")]
    assert bridge.measured_kw() == {}
    store.heartbeat("esp32_1")
    store.report_reading(reading(clock, 6.0))
    clock.now += 5
    bridge.poll_once()
    assert bridge.measured_kw() == {"dishwasher_1": 6.0} and len(warnings) == 1


def test_a_failed_command_is_retried_once_then_the_device_is_simulated():
    bridge, store, clock, warnings = esp32_bridge()
    store.heartbeat("esp32_1")
    store.report_reading(reading(clock))
    bridge.poll_once()
    assert bridge.track_command(command(), "with") == "esp32_1"
    store.record_command(command(), "with", "esp32_1")  # what the loop's store buffer does

    clock.now += 16  # not acked in 15 s → failed (in Convex: liveness:sweep)
    store.heartbeat("esp32_1")
    bridge.poll_once()
    rows = store.rows("commands")
    assert [(c["command_id"], c["delivery"]) for c in rows] == [("c_0001", "failed"), ("c_0001", "queued")]
    assert warnings == []
    bridge.poll_once()  # the same failure is not retried twice
    assert len(store.rows("commands")) == 2

    clock.now += 16
    store.heartbeat("esp32_1")
    store.report_reading(reading(clock, 6.0))
    bridge.poll_once()
    assert [c["delivery"] for c in store.rows("commands")] == ["failed", "failed"]
    assert warnings == [hub_offline_warning("dishwasher_1", "esp32_1", "command")]
    assert bridge.hub_id_for("with", "dishwasher_1") is None  # its Commands stay with the browser hub
    kitchen = Kitchen()
    report = {"reports": {"with": {"source": "simulated"}}}
    assert bridge.before_step(report, kitchen) == report and kitchen.ingested == []
    assert bridge.measured_kw() == {}

    bridge.load_map(store.device_map())  # next kitchen build: bridged again
    assert bridge.hub_id_for("with", "dishwasher_1") == "esp32_1"


def test_a_nack_counts_as_failed_at_once():
    bridge, store, clock, warnings = esp32_bridge()
    store.heartbeat("esp32_1")
    bridge.track_command(command(), "with")
    store.record_command(command(), "with", "esp32_1")
    store.ack_command("c_0001", False, None, "relay stuck")
    bridge.poll_once()
    assert [c["delivery"] for c in store.rows("commands")] == ["failed", "queued"]


def test_liveness_is_polled_every_5_s():
    bridge, store, clock, warnings = esp32_bridge()
    calls = []
    store.hub_status = lambda: calls.append(clock.now) or []
    for _ in range(21):
        bridge.poll_once()
        clock.now += 0.5
    assert calls == [T0, T0 + 5, T0 + 10]


def test_sim_bridge_does_not_read_liveness():
    bridge, store, clock, warnings = esp32_bridge("sim_bridge")
    store.hub_status = lambda: (_ for _ in ()).throw(AssertionError("polled"))
    bridge.track_command(command(), "with")
    store.record_command(command(), "with", "esp32_1")
    clock.now += 20
    bridge.poll_once()
    assert warnings == [] and len(store.rows("commands")) == 1
