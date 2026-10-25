"""runtime/loop.py beyond the scenario: pacing, play / pause / speed, owner commands and REST surges at n + 1, physical
input defaults, `/ws` viewers with LIVE_TRANSPORT=ws, and never waiting on the live transport."""

import asyncio
import json

import pytest
import websockets

from api.settings import REPO_ROOT
from runtime import loop as loop_module
from runtime.live_port import LivePublisher, RecordingLive, WsLive
from runtime.loop import tick_interval_s

FIXTURES = REPO_ROOT / "contracts" / "fixtures"
SCENARIO = json.loads((FIXTURES / "scenario" / "demo_cafe" / "scenario.json").read_text(encoding="utf-8"))
SIM_TICKS = {
    m["tick_id"]: m
    for m in map(json.loads, (FIXTURES / "hub_protocol" / "server_to_hub.jsonl").read_text(encoding="utf-8").splitlines())
    if m["type"] == "sim_tick"
}


def load(rel):
    return json.loads((FIXTURES / rel).read_text(encoding="utf-8"))


async def until(predicate, timeout=5.0):
    async def wait():
        while not predicate():
            await asyncio.sleep(0.005)
    await asyncio.wait_for(wait(), timeout)


def sent_ticks(srv):
    return [m for m in srv.hub_client.received if m["type"] == "sim_tick"]


async def built(srv, *, autorun=False):
    srv.runtime.autorun = autorun
    srv.runtime.live.use(RecordingLive())
    await srv.connect_fake_hub()
    assert (await srv.http.post("/api/kitchen", json=SCENARIO["config"])).status_code == 200


def test_speed_sets_the_real_interval():
    assert [tick_interval_s(s) for s in (1, 30, 120, 600)] == [60.0, 2.0, 0.5, 0.1]


async def test_play_paces_ticks_and_pause_stops_them(serve, monkeypatch):
    monkeypatch.setattr(loop_module, "TICK_BASE_S", 0.01)  # 120× → 10 ms per tick
    async with serve() as srv:
        await built(srv, autorun=True)
        clock = (await srv.http.post("/api/sim/control", json={"action": "play", "speed": 120})).json()
        assert clock == {"playing": True, "speed": 120, "sim_ts": SCENARIO["start_sim_ts"], "tick_id": 0,
                         "paused_reason": None, "day_index": 1, "run_days": 1, "phase": "service"}
        await until(lambda: srv.runtime.tick_id >= 5)
        paused = (await srv.http.post("/api/sim/control", json={"action": "pause"})).json()
        assert paused["playing"] is False
        await asyncio.sleep(0.1)
        stopped_at = srv.runtime.tick_id
        assert stopped_at in (paused["tick_id"], paused["tick_id"] + 1)  # a tick in flight completes
        await asyncio.sleep(0.1)
        assert srv.runtime.tick_id == stopped_at
        assert [m["tick_id"] for m in sent_ticks(srv)] == list(range(1, stopped_at + 1))

        # 1×: one tick per 1.2 s here, so nothing more in 0.2 s; switching to 600× wakes the loop at once.
        await srv.http.post("/api/sim/control", json={"action": "play", "speed": 1})
        await until(lambda: srv.runtime.tick_id == stopped_at + 1)
        await asyncio.sleep(0.2)
        assert srv.runtime.tick_id == stopped_at + 1
        await srv.http.post("/api/sim/control", json={"action": "play", "speed": 600})
        await until(lambda: srv.runtime.tick_id >= stopped_at + 10, timeout=2)
        await srv.http.post("/api/sim/control", json={"action": "pause"})


async def test_no_sim_host_stays_paused(serve, monkeypatch):
    monkeypatch.setattr(loop_module, "TICK_BASE_S", 0.01)
    async with serve() as srv:
        assert (await srv.http.post("/api/kitchen", json=SCENARIO["config"])).status_code == 200
        clock = (await srv.http.post("/api/sim/control", json={"action": "play"})).json()
        assert clock["playing"] is True and clock["paused_reason"] == "sim_host_offline"
        await asyncio.sleep(0.1)
        assert srv.runtime.tick_id == 0
        await srv.connect_fake_hub()  # the host arrives: the clock resumes on its own
        await until(lambda: srv.runtime.tick_id >= 3)
        await srv.http.post("/api/sim/control", json={"action": "pause"})


async def test_reset_rebuilds_at_tick_zero(serve):
    async with serve() as srv:
        await built(srv)
        await srv.http.post("/api/sim/control", json={"action": "play"})
        for _ in range(3):
            await srv.runtime.tick_once()
        clock = (await srv.http.post("/api/sim/control", json={"action": "reset"})).json()
        assert clock["tick_id"] == 0 and clock["playing"] is False
        await until(lambda: [m["type"] for m in srv.hub_client.received][-2:] == ["sim_control", "sim_build"])
        assert srv.hub_client.received[-2]["action"] == "reset"
        assert await srv.runtime.tick_once() is True
        no_context = {"outdoor_temp_c": None, "crowd_multiplier": 1.0, "is_open": True}  # none posted in this test
        assert sent_ticks(srv)[-1] == {**SIM_TICKS[1], "inputs": no_context, "fast_forward": False}


async def test_owner_command_and_rest_surge_go_out_in_the_next_tick(serve):
    owner = load("rest/post_device_command.json")
    async with serve() as srv:
        await built(srv)
        await srv.http.post("/api/sim/control", json={"action": "play"})
        for _ in range(118):
            assert await srv.runtime.tick_once() is True
        command = (await srv.http.post(owner["path"], json=owner["request"])).json()
        assert command == owner["response"]
        assert (await srv.http.post("/api/events/customers", json={"customers": 25, "duration_min": 30})).json() == {
            "ok": True}
        await srv.runtime.tick_once()
        await srv.runtime.tick_once()
        tick119, tick120 = sent_ticks(srv)[118:120]
        assert tick119["commands"] == SIM_TICKS[119]["commands"]
        assert command in tick120["commands"]
        assert tick119["surges"] == [{"surge_id": "s_0001", "customers": 25, "duration_min": 30}]
        assert tick120["commands"] == SIM_TICKS[120]["commands"] and tick120["surges"] == []


def test_owner_command_is_not_queued_until_a_following_engine_step():
    rt = loop_module.RunLoop.__new__(loop_module.RunLoop)
    calls = []

    class Service:
        @staticmethod
        def device_command(device_id, body):
            calls.append((device_id, body))
            return {"command_id": "c_0020", "lane": "with"}

    rt.service, rt._commands = Service(), []
    assert rt.owner_command("dishwasher_1", {"action": "delay", "value": 10}) == {
        "command_id": "c_0020", "lane": "with"}
    assert calls == [("dishwasher_1", {"action": "delay", "value": 10})]
    assert rt._commands == []  # the facade records it; `step` emits it next

    owner_without = {"command_id": "c_0019", "lane": "without"}
    owner_with = {"command_id": "c_0020", "lane": "with"}
    rt._queue_commands({"without": {"new_commands": [owner_without]}, "with": {"new_commands": [owner_with]}})
    assert rt._commands == [owner_without, owner_with]


def test_publish_forwards_each_tick_warning_unchanged():
    rt = loop_module.RunLoop.__new__(loop_module.RunLoop)
    live_calls, viewer, escalations = [], [], []

    class Live:
        @staticmethod
        def send(*args):
            live_calls.append(args)

    class Escalations:
        @staticmethod
        def opened(escalation):
            escalations.append(escalation)

    rt.live, rt.escalations, rt._publish_ws = Live(), Escalations(), viewer.append
    rt._publish_clock = lambda: None
    warning = {
        "code": "cap_unreachable", "message": "Engine target cannot be held.",
        "data": {"unavoidable_kw": 44.0, "peak_cap_kw": None, "target_kw": 41.0},
    }
    state = {
        "hub": {"devices": [{"device_id": "hvac_1", "name": "HVAC 1"}]},
        "new_decisions": [], "new_escalations": [], "warnings": [warning],
    }
    rt._publish(1, {"without": state, "with": {**state, "warnings": [warning]}}, {}, ticks=False)
    assert viewer == [{"type": "warning", **warning}, {"type": "warning", **warning}]
    assert live_calls == [] and escalations == []


async def test_inputs_without_context_use_simulation_defaults(serve):
    async with serve() as srv:
        await built(srv)
        rt = srv.runtime
        assert rt.inputs("2026-07-18T00:30:00Z") == {"outdoor_temp_c": None, "crowd_multiplier": 1.0, "is_open": True}
        assert rt.inputs("2026-07-18T05:00:00Z")["is_open"] is False  # 22:00 local, closing time
        assert rt.inputs("2026-07-17T16:59:00Z")["is_open"] is False  # 09:59 local
        rt.post_context({"crowd_effect": {"value": "large", "set_by": "owner", "reason": "test"}})
        assert rt.inputs("2026-07-18T00:30:00Z")["crowd_multiplier"] == 1.40


async def test_concierge_context_reaches_inputs_and_survives_a_rebuild(serve):
    body = load("agents/context_post.json")["body"]
    async with serve() as srv:
        await built(srv)
        rt = srv.runtime
        assert (await srv.http.post("/api/context", json={k: v for k, v in body.items() if k != "ts"})).json() == {"ok": True}
        assert rt.context == {**body, "ts": rt.sim_ts}  # merged unchanged, `ts` stamped in sim time
        # The weather hour of that sim minute and the crowd effect go to the simulation unchanged.
        assert rt.inputs("2026-07-18T02:30:00Z")["outdoor_temp_c"] == 27.2
        assert rt.inputs("2026-07-18T02:30:00Z")["crowd_multiplier"] == 1.25

        handed = []
        post_context = rt.service.post_context
        rt.service.post_context = lambda c: handed.append(c) or post_context(c)
        assert (await srv.http.post("/api/kitchen", json=SCENARIO["config"])).status_code == 200
        assert handed == [rt.context]  # the new lanes get the last known context


async def test_ws_transport_sends_ticks_to_a_browser_viewer(serve, monkeypatch):
    monkeypatch.setattr(loop_module, "TICK_BASE_S", 0.01)
    async with serve(live_transport="ws") as srv:
        srv.runtime.autorun = True
        await srv.connect_fake_hub()
        async with websockets.connect(srv.ws_url) as viewer:
            await until(lambda: srv.app.state.broadcaster.client_count == 1)
            await srv.http.post("/api/kitchen", json=SCENARIO["config"])
            await srv.http.post("/api/sim/control", json={"action": "play", "speed": 600})
            ticks = []
            while len(ticks) < 4:
                message = json.loads(await asyncio.wait_for(viewer.recv(), 3))
                if message["type"] == "tick":
                    ticks.append(message["data"])
            await srv.http.post("/api/sim/control", json={"action": "pause"})
        steps = {(json.loads(l)["returns"]["lane"], json.loads(l)["returns"]["hub"]["tick_id"]): json.loads(l)["returns"]
                 for l in (FIXTURES / "facade" / "step_stream.jsonl").read_text(encoding="utf-8").splitlines()}
        assert ticks == [steps[("without", 1)], steps[("with", 1)], steps[("without", 2)], steps[("with", 2)]]


class SlowLive(RecordingLive):
    async def publish_ticks(self, *args):
        await asyncio.sleep(10)


class BrokenLive(RecordingLive):
    async def set_clock(self, clock, sim_host):
        raise ConnectionError("SpacetimeDB unreachable")


async def test_a_slow_live_transport_never_blocks_the_tick(serve):
    async with serve() as srv:
        await built(srv)
        srv.runtime.live.use(SlowLive())
        await srv.http.post("/api/sim/control", json={"action": "play"})
        for _ in range(3):
            assert await asyncio.wait_for(srv.runtime.tick_once(), 1.0) is True
        await srv.runtime.live.stop()


async def test_failing_live_transport_falls_back_to_ws_with_a_warning():
    viewer = []

    async def collect(message):
        viewer.append(message)

    publisher = LivePublisher(BrokenLive(), fallback=WsLive(collect), on_warning=collect)
    clock = {"playing": True, "speed": 120, "sim_ts": "2026-07-18T00:30:00Z", "tick_id": 0, "paused_reason": None,
             "day_index": 1, "run_days": 1, "phase": "service"}
    publisher.send("set_clock", clock, "connected")
    await publisher.flush()
    assert [m["type"] for m in viewer] == ["warning", "clock"]
    assert viewer[0]["code"] == "live_transport_down" and viewer[0]["data"] == {}
    assert isinstance(publisher.port, WsLive)
    await publisher.stop()


async def test_play_without_a_kitchen_is_404(serve):
    async with serve() as srv:
        srv.app.state.service.lanes._kitchens = {}
        resp = await srv.http.post("/api/sim/control", json={"action": "play"})
        assert resp.status_code == 404


@pytest.mark.parametrize("speed", [0, 60, 1000])
async def test_unknown_speed_is_422(serve, speed):
    async with serve() as srv:
        resp = await srv.http.post("/api/sim/control", json={"action": "play", "speed": speed})
        assert resp.status_code == 422
