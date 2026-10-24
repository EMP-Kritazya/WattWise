"""runtime/hub_link.py against the real `/ws/hub` route, driven by fake_hub_client and raw protocol clients (CONTRACTS.md §8)."""

import asyncio
import json
from contextlib import asynccontextmanager

import pytest
import uvicorn
import websockets

from api.main import create_app
from api.models import WarningMessage
from api.settings import REPO_ROOT, Settings
from fakes.fake_hub_client import FakeHubClient
from runtime.hub_link import HubLink

FIXTURES = REPO_ROOT / "contracts" / "fixtures"
HUB = FIXTURES / "hub_protocol"
TIMEOUT_S = 0.3  # stands in for the 2 real s


def _load(name):
    return json.loads((HUB / name).read_text(encoding="utf-8"))


def _jsonl(name):
    return [json.loads(line) for line in (HUB / name).read_text(encoding="utf-8").splitlines() if line.strip()]


SERVER_TO_HUB = _jsonl("server_to_hub.jsonl")
TICKS = {m["tick_id"]: m for m in SERVER_TO_HUB if m["type"] == "sim_tick"}
REPORTS = {m["tick_id"]: m for m in _jsonl("hub_to_server.jsonl") if m["type"] == "hub_report"}
BUILD = _load("sim_build.json")


class Rig:
    def __init__(self, hub, url):
        self.hub, self.url = hub, url
        self.statuses, self.warnings = [], []

    async def build(self, devices=None):
        return await self.hub.send_build(
            BUILD["kitchen_id"], BUILD["config"], BUILD["catalog"], devices or BUILD["devices"], BUILD["seed"],
            BUILD["start_sim_ts"],
        )

    async def tick(self, tick_id):
        m = TICKS[tick_id]
        return await self.hub.tick(tick_id, m["sim_ts"], m["surges"], m["inputs"], m["commands"])

    def fake_client(self):
        return asyncio.create_task(FakeHubClient(self.url, FIXTURES).run())


@asynccontextmanager
async def rig(app_hub=False):
    """A real server on a free port. `app_hub=True` keeps the HubLink create_app wired (health), with the real 2 s timeout."""
    app = create_app(Settings(kitchen_impl="fake", store="memory", fixtures_dir=FIXTURES))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", lifespan="off"))
    task = asyncio.create_task(server.serve())
    await _until(lambda: server.started)
    port = server.servers[0].sockets[0].getsockname()[1]
    r = Rig(None, f"ws://127.0.0.1:{port}/ws/hub")
    r.app = app
    if app_hub:
        r.hub = app.state.hub
    else:
        r.hub = app.state.hub = HubLink(
            report_timeout_s=TIMEOUT_S, on_status=r.statuses.append, on_warning=r.warnings.append
        )
    try:
        yield r
    finally:
        server.should_exit = True
        await task


async def _until(predicate, timeout=3.0):
    async def wait():
        while not predicate():
            await asyncio.sleep(0.01)
    await asyncio.wait_for(wait(), timeout)


async def _recv(ws, timeout=2.0):
    return json.loads(await asyncio.wait_for(ws.recv(), timeout))


async def _silent(ws, for_s=0.2):
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(ws.recv(), for_s)


@asynccontextmanager
async def host(url):
    """A raw protocol client that has said hub_hello as sim_host."""
    async with websockets.connect(url) as ws:
        await ws.send(json.dumps(_load("hub_hello.json")))
        yield ws


# ---------------------------------------------------------------- welcome

async def test_first_host_accepted_second_gets_host_taken_and_stays_a_viewer():
    async with rig() as r, host(r.url) as first:
        assert await _recv(first) == _load("hub_welcome_accepted.json")
        async with host(r.url) as second:
            assert await _recv(second) == _load("hub_welcome_host_taken.json")
            await second.send(json.dumps(REPORTS[1]))  # a viewer's frames are ignored
            await _silent(second)  # still open, nothing more sent
            assert await asyncio.wait_for(FakeHubClient(r.url, FIXTURES).run(), 3) == []
        assert r.hub.connected and r.hub.paused_reason is None


async def test_health_follows_the_sim_host():
    async with rig(app_hub=True) as r:
        assert r.app.state.sim_host_connected is False
        async with host(r.url) as ws:
            await _recv(ws)
            assert r.app.state.sim_host_connected is True
        await _until(lambda: r.app.state.sim_host_connected is False)


async def test_non_host_hello_is_refused():
    async with rig() as r, websockets.connect(r.url) as ws:
        await ws.send(json.dumps({**_load("hub_hello.json"), "role": "viewer"}))
        with pytest.raises(websockets.ConnectionClosed) as closed:
            await _recv(ws)
        assert closed.value.rcvd.code == 1008
        assert not r.hub.connected


# ---------------------------------------------------------------- build + handshake

async def test_sim_build_is_the_roster_only():
    live_devices = _load("hub_report.json")["reports"]["with"]["devices"]  # on, kW > 0, physical
    async with rig() as r, host(r.url) as ws:
        await _recv(ws)
        assert await r.build(live_devices) is True
        assert await _recv(ws) == BUILD


async def test_build_made_before_the_host_connects_is_sent_on_hello():
    async with rig() as r:
        assert await r.build() is False
        async with host(r.url) as ws:
            assert await _recv(ws) == _load("hub_welcome_accepted.json")
            assert await _recv(ws) == BUILD


async def test_scenario_stream_equals_server_to_hub_fixture():
    async with rig() as r:
        await r.build()
        received = []

        async def hub_side():
            async with host(r.url) as ws:
                while len(received) < len(SERVER_TO_HUB):
                    msg = await _recv(ws)
                    received.append(msg)
                    if msg["type"] == "sim_tick":
                        await ws.send(json.dumps(REPORTS[msg["tick_id"]]))

        client = asyncio.create_task(hub_side())
        await _until(lambda: r.hub.connected)
        reports = [await r.tick(t) for t in sorted(TICKS)]
        await asyncio.wait_for(client, 3)
        assert received == SERVER_TO_HUB
        assert reports == [REPORTS[t] for t in sorted(TICKS)]
        assert r.statuses == [None, "sim_host_offline"]  # never hub_waiting; offline once the client leaves


async def test_fake_hub_client_handshake():
    async with rig() as r:
        await r.build()
        client = r.fake_client()
        await _until(lambda: r.hub.connected)
        for t in range(1, 11):
            assert await r.tick(t) == REPORTS[t]
        client.cancel()


async def test_never_sends_tick_n_plus_1_before_report_n():
    async with rig() as r, host(r.url) as ws:
        await _recv(ws)
        await r.build()
        await _recv(ws)
        t1 = asyncio.create_task(r.tick(1))
        assert (await _recv(ws))["tick_id"] == 1
        with pytest.raises(RuntimeError):
            await r.tick(2)
        await _silent(ws)
        await ws.send(json.dumps(REPORTS[1]))
        assert await t1 == REPORTS[1]


# ---------------------------------------------------------------- pauses

async def test_no_report_within_timeout_pauses_hub_waiting_then_resumes():
    async with rig() as r, host(r.url) as ws:
        await _recv(ws)
        await r.build()
        await _recv(ws)
        t1 = asyncio.create_task(r.tick(1))
        await _recv(ws)
        await asyncio.sleep(TIMEOUT_S * 1.5)
        assert r.hub.paused_reason == "hub_waiting" and not t1.done()
        await ws.send(json.dumps(REPORTS[1]))
        assert await t1 == REPORTS[1]
        assert r.hub.paused_reason is None
        assert r.statuses == [None, "hub_waiting", None]


async def test_killing_the_host_pauses_sim_host_offline_with_warning():
    async with rig() as r:
        await r.build()
        client = r.fake_client()
        await _until(lambda: r.hub.connected)
        for t in (1, 2, 3):
            await r.tick(t)
        client.cancel()
        await _until(lambda: r.hub.paused_reason == "sim_host_offline")
        assert not r.hub.connected
        assert len(r.warnings) == 1
        warning = WarningMessage.model_validate(r.warnings[0])
        assert warning.code == "sim_host_offline" and warning.data == {"last_tick_id": 3}


# ---------------------------------------------------------------- reconnect

async def test_reconnect_resends_build_and_replays_every_past_tick():
    replay_shape = _load("sim_tick_replay.json")
    async with rig() as r:
        await r.build()
        client = r.fake_client()
        await _until(lambda: r.hub.connected)
        for t in range(1, 37):
            await r.tick(t)
        client.cancel()
        await _until(lambda: not r.hub.connected)

        async with host(r.url) as ws:
            assert (await _recv(ws))["tick_id"] == 36
            assert await _recv(ws) == BUILD
            replayed = [await _recv(ws) for _ in range(36)]
            assert all(m.keys() == replay_shape.keys() and m["replay"] is True for m in replayed)
            assert replayed == [{**TICKS[t], "replay": True} for t in range(1, 37)]
            assert replayed[-1] == replay_shape
            assert r.hub.paused_reason is None

            # A tick issued during the burst waits for the burst's answer, which is a duplicate and is dropped.
            t37 = asyncio.create_task(r.tick(37))
            await _silent(ws)
            await ws.send(json.dumps(REPORTS[36]))
            live = await _recv(ws)
            assert live == TICKS[37]
            await asyncio.sleep(0.05)
            assert not t37.done()  # report 36 did not complete tick 37: the engine is not re-stepped
            await ws.send(json.dumps(REPORTS[37]))
            assert await t37 == REPORTS[37]


async def test_tick_pending_across_a_disconnect_completes_from_the_replay():
    async with rig() as r:
        await r.build()
        async with host(r.url) as ws:
            await _recv(ws), await _recv(ws)
            for t in (1, 2):
                task = asyncio.create_task(r.tick(t))
                await _recv(ws)
                await ws.send(json.dumps(REPORTS[t]))
                await task
            t3 = asyncio.create_task(r.tick(3))
            await _recv(ws)
        await _until(lambda: r.hub.paused_reason == "sim_host_offline")
        await asyncio.sleep(TIMEOUT_S * 1.5)
        assert r.hub.paused_reason == "sim_host_offline" and not t3.done()  # offline is not overwritten by hub_waiting

        client = r.fake_client()  # replay 1..3; the fake answers only tick 3
        assert await asyncio.wait_for(t3, 3) == REPORTS[3]
        assert r.hub.paused_reason is None
        assert await r.tick(4) == REPORTS[4]
        client.cancel()


async def test_rebuild_forgets_past_ticks():
    async with rig() as r:
        await r.build()
        client = r.fake_client()
        await _until(lambda: r.hub.connected)
        await r.tick(1)
        await r.build()
        assert r.hub.tick_id == 0
        assert await r.tick(1) == REPORTS[1]
        client.cancel()


async def test_send_control():
    async with rig() as r:
        assert await r.hub.send_control("play", 120) is False
        async with host(r.url) as ws:
            await _recv(ws)
            assert await r.hub.send_control("play", 120) is True
            assert await _recv(ws) == _load("sim_control.json")
