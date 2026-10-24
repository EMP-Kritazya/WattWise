"""runtime/device_bridge.py: HARDWARE=sim_bridge relays the browser hub's mapped devices through the store (devices:report
→ devices:latest → ingest_reading; with-lane Commands → commands:enqueue with hub_id; acks → commands:ack), a 30 s gap →
hub_offline, and every closed 15-min block → device_blocks exactly as `contracts/fixtures/convex/tables/device_blocks.json`."""

import copy
import json

import pytest

from api.settings import REPO_ROOT
from runtime.device_bridge import BlockAverager, DeviceBridge, hub_offline_warning
from runtime.live_port import RecordingLive
from store import MemoryStore

FIXTURES = REPO_ROOT / "contracts" / "fixtures"
TABLES = FIXTURES / "convex" / "tables"
SCENARIO = json.loads((FIXTURES / "scenario" / "demo_cafe" / "scenario.json").read_text(encoding="utf-8"))
REPORTS = [
    m for m in map(json.loads, (FIXTURES / "hub_protocol" / "hub_to_server.jsonl").read_text(encoding="utf-8").splitlines())
    if m["type"] == "hub_report"
]
DEVICE_MAP = json.loads((TABLES / "device_map.json").read_text(encoding="utf-8"))
DEVICE_BLOCKS = json.loads((TABLES / "device_blocks.json").read_text(encoding="utf-8"))
MAPPED = DEVICE_MAP[0]  # esp32_1 channel 0 → dishwasher_1, scale 1000


def power_of(report, device_id, lane="with"):
    return next(d["power_kw"] for d in report["reports"][lane]["devices"] if d["device_id"] == device_id)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class Kitchen:
    def __init__(self):
        self.ingested = []

    def ingest_reading(self, reading):
        self.ingested.append(reading)


def bridge_with_map(mode="sim_bridge"):
    store, clock, warnings = MemoryStore(), Clock(), []
    for row in DEVICE_MAP:
        store.map_channel(row)
    bridge = DeviceBridge(mode, store, on_warning=warnings.append, clock=clock)
    bridge.load_map(store.device_map())
    return bridge, store, clock, warnings


# ---------------------------------------------------------------- 15-min blocks


def test_first_closed_block_equals_the_fixture():
    averager = BlockAverager()
    for report in REPORTS[:15]:  # minutes 00:30 … 00:44
        assert averager.add(report) == []
    assert averager.add(REPORTS[15]) == DEVICE_BLOCKS  # the 00:45 minute closes the 00:30 block


def test_block_of_uses_the_minute_just_stepped():
    assert BlockAverager.block_of("2026-07-18T00:45:00Z") == "2026-07-18T00:30:00Z"
    assert BlockAverager.block_of("2026-07-18T00:46:00Z") == "2026-07-18T00:45:00Z"


def test_measured_minutes_use_the_reading_and_label_the_block():
    averager = BlockAverager()
    for report in REPORTS[:15]:
        averager.add(report, measured={"dishwasher_1": 5.0})
    rows = {(r["lane"], r["device_id"]): r for r in averager.add(REPORTS[15])}
    assert rows[("with", "dishwasher_1")] == {"lane": "with", "device_id": "dishwasher_1",
                                              "block_start": "2026-07-18T00:30:00Z", "avg_kw": 5.0,
                                              "source": "measured"}
    assert rows[("without", "dishwasher_1")]["source"] == "simulated"


# ---------------------------------------------------------------- bridge unit


def test_off_bridges_nothing():
    bridge = DeviceBridge("off", MemoryStore(TABLES))
    assert bridge.hub_id_for("with", "dishwasher_1") is None
    report = REPORTS[0]
    assert bridge.before_step(report, Kitchen()) is report
    assert bridge.ack_writes(report) == []


def test_sim_bridge_reading_round_trip():
    bridge, store, clock, warnings = bridge_with_map()
    kitchen = Kitchen()
    report = REPORTS[0]
    bridge.before_step(report, kitchen)
    bridge.after_step(report)
    kw = power_of(report, "dishwasher_1")
    reading = {"hub_id": "esp32_1", "channel": 0, "device_id": "dishwasher_1", "ts": report["reports"]["with"]["ts"],
               "raw_w": kw * 1000 / MAPPED["scale"], "scale": MAPPED["scale"], "power_kw": kw}
    assert store.rows("readings") == [reading]
    assert kitchen.ingested == []  # not read back yet
    bridge.poll_once()
    clock.now += 0.5
    stepped = bridge.before_step(REPORTS[1], kitchen)
    assert kitchen.ingested == [reading]
    assert stepped is REPORTS[1]  # sim_bridge numbers stay simulated: no "mixed"
    bridge.before_step(REPORTS[2], kitchen)
    assert kitchen.ingested == [reading]  # each Reading once
    assert warnings == []


def test_only_with_lane_mapped_commands_are_bridged():
    bridge, *_ = bridge_with_map()
    assert bridge.hub_id_for("with", "dishwasher_1") == "esp32_1"
    assert bridge.hub_id_for("without", "dishwasher_1") is None
    assert bridge.hub_id_for("with", "hvac_1") is None


def test_acks_of_bridged_commands_go_to_the_store():
    bridge, store, *_ = bridge_with_map()
    report = next(r for r in REPORTS if r["tick_id"] == 36)  # acks c_0001 (dishwasher_1 delay 50)
    ack = report["reports"]["with"]["acks"][0]
    command = {"command_id": ack["command_id"], "lane": "with", "ts": "2026-07-18T01:05:00Z",
               "device_id": "dishwasher_1", "action": "delay", "value": 50, "decision_id": "d_0001",
               "issued_by": "engine"}
    store.record_command(command, "with", bridge.track_command(command, "with"))
    writes = bridge.ack_writes(report)
    assert len(writes) == 1
    for write in writes:
        write()
    assert store.rows("commands")[0]["hub_id"] == "esp32_1"
    assert store.rows("commands")[0]["delivery"] == "acked"
    assert bridge.ack_writes(report) == []  # relayed once


def test_no_reading_for_30_s_is_hub_offline():
    bridge, store, clock, warnings = bridge_with_map()
    kitchen = Kitchen()
    bridge.after_step(REPORTS[0])
    bridge.poll_once()
    for report in REPORTS[1:61]:  # 30 real seconds of ticks at 0.5 s, and no new reading read back
        clock.now += 0.5
        bridge.before_step(report, kitchen)
    assert warnings == []
    clock.now += 0.6
    bridge.before_step(REPORTS[61], kitchen)
    assert warnings == [hub_offline_warning("dishwasher_1", "esp32_1")]
    assert warnings[0]["data"] == {"device_id": "dishwasher_1", "hub_id": "esp32_1"}
    # Back to simulated: a reading already read back is no longer handed to the engine; one warning only.
    ingested = len(kitchen.ingested)
    clock.now += 0.5
    bridge.before_step(REPORTS[62], kitchen)
    assert len(kitchen.ingested) == ingested and len(warnings) == 1


def test_a_device_that_never_reports_goes_offline():
    bridge, store, clock, warnings = bridge_with_map()
    for report in REPORTS[:62]:
        clock.now += 0.5
        bridge.before_step(report, Kitchen())
    assert warnings == [hub_offline_warning("dishwasher_1", "esp32_1")]


def test_a_paused_clock_is_not_a_hub_gap():
    bridge, store, clock, warnings = bridge_with_map()
    bridge.after_step(REPORTS[0])
    bridge.poll_once()
    bridge.before_step(REPORTS[1], Kitchen())
    clock.now += 120  # paused for two minutes
    bridge.before_step(REPORTS[2], Kitchen())
    assert warnings == []


def test_readings_coming_back_make_the_device_live_again():
    bridge, store, clock, warnings = bridge_with_map()
    kitchen = Kitchen()
    for report in REPORTS[:62]:
        clock.now += 0.5
        bridge.before_step(report, kitchen)
    assert len(warnings) == 1
    bridge.after_step(REPORTS[62])
    bridge.poll_once()
    clock.now += 0.5
    bridge.before_step(REPORTS[63], kitchen)
    assert [r["ts"] for r in kitchen.ingested] == [REPORTS[62]["reports"]["with"]["ts"]]


def test_esp32_marks_the_with_report_mixed():
    bridge, store, clock, warnings = bridge_with_map("esp32")
    reading = json.loads((TABLES / "readings.json").read_text(encoding="utf-8"))[0]
    store.report_reading(reading)  # the ESP32 reports itself
    bridge.after_step(REPORTS[0])  # esp32 mode relays nothing
    assert store.rows("readings") == [reading]
    bridge.poll_once()
    kitchen = Kitchen()
    stepped = bridge.before_step(REPORTS[1], kitchen)
    assert kitchen.ingested == [reading]
    assert stepped["reports"]["with"]["source"] == "mixed"
    assert stepped["reports"]["without"]["source"] == "simulated"
    assert REPORTS[1]["reports"]["with"]["source"] == "simulated"  # the hub's report is not mutated
    assert bridge.measured_kw() == {"dishwasher_1": reading["power_kw"]}


def test_unmapped_kitchen_devices_are_ignored():
    bridge, *_ = bridge_with_map()
    bridge.load_map(DEVICE_MAP, device_ids={"hvac_1"})
    assert bridge.mapped() == {}


def test_unknown_hardware_mode():
    with pytest.raises(ValueError):
        DeviceBridge("zigbee", MemoryStore())


# ---------------------------------------------------------------- through the run loop (fake kitchen + fake hub)


async def built(srv):
    srv.runtime.autorun = False
    srv.runtime.live.use(RecordingLive())
    await srv.connect_fake_hub()
    assert (await srv.http.post("/api/kitchen", json=SCENARIO["config"])).status_code == 200
    await srv.http.post("/api/sim/control", json={"action": "play"})


async def test_loop_sim_bridge_round_trip(serve, monkeypatch):
    async with serve(hardware="sim_bridge") as srv:
        await built(srv)
        rt, store = srv.runtime, srv.app.state.store
        seeded_readings = len(store.rows("readings"))
        seeded_blocks = len(store.rows("device_blocks"))
        seeded_commands = len(store.rows("commands"))
        kitchen = srv.app.state.service.lanes["with"]
        ingested = []
        original = kitchen.ingest_reading
        monkeypatch.setattr(kitchen, "ingest_reading", lambda r: (ingested.append(copy.deepcopy(r)), original(r))[1])
        assert rt.bridge.hub_id_for("with", "dishwasher_1") == "esp32_1"
        for _ in range(37):
            assert await rt.tick_once() is True
            rt.bridge.poll_once()  # what the background task does every 0.5 s
        await rt.flush()

        reports = {r["tick_id"]: r for r in REPORTS}
        readings = store.rows("readings")[seeded_readings:]
        assert [r["ts"] for r in readings] == [reports[t]["reports"]["with"]["ts"] for t in range(1, 38)]
        assert all(r["power_kw"] == power_of(reports[i + 1], "dishwasher_1") for i, r in enumerate(readings))
        # Read back and handed to the with lane's engine, one tick later, each once.
        assert ingested == readings[:-1]

        commands = store.rows("commands")[seeded_commands:]
        dishwasher = [c for c in commands if c["device_id"] == "dishwasher_1" and c["lane"] == "with"]
        assert [(c["command_id"], c["hub_id"], c["delivery"]) for c in dishwasher] == [("c_0001", "esp32_1", "acked")]
        assert all(c["hub_id"] is None for c in commands if c not in dishwasher)

        blocks = store.rows("device_blocks")[seeded_blocks:]
        assert blocks[: len(DEVICE_BLOCKS)] == DEVICE_BLOCKS  # the 00:30 block, closed at tick 16
        assert len(blocks) == 2 * len(DEVICE_BLOCKS)  # and 00:45, closed at tick 31


async def test_loop_off_still_writes_blocks_and_bridges_nothing(serve):
    async with serve() as srv:
        await built(srv)
        rt, store = srv.runtime, srv.app.state.store
        seeded_readings, seeded_blocks = len(store.rows("readings")), len(store.rows("device_blocks"))
        for _ in range(16):
            await rt.tick_once()
        await rt.flush()
        assert store.rows("readings")[seeded_readings:] == []
        assert store.rows("device_blocks")[seeded_blocks:] == DEVICE_BLOCKS


async def test_hub_offline_reaches_viewers(serve, monkeypatch):
    async with serve(hardware="sim_bridge") as srv:
        await built(srv)
        monkeypatch.setattr(srv.app.state.store, "latest_readings", lambda hub_id: [])  # nothing ever comes back
        sent = []
        srv.runtime.bridge._on_warning = sent.append
        clock = Clock()
        srv.runtime.bridge._clock = clock
        srv.runtime.bridge.load_map(DEVICE_MAP)
        for _ in range(62):
            clock.now += 0.5
            await srv.runtime.tick_once()
        assert sent == [hub_offline_warning("dishwasher_1", "esp32_1")]
