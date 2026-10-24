"""fake_hub_client answers a server that plays `server_to_hub.jsonl` with exactly `hub_to_server.jsonl`."""

import asyncio
import json

import websockets

from api.settings import REPO_ROOT
from fakes.fake_hub_client import FakeHubClient

HUB = REPO_ROOT / "contracts" / "fixtures" / "hub_protocol"


def _jsonl(name):
    return [json.loads(line) for line in (HUB / name).read_text(encoding="utf-8").splitlines() if line.strip()]


def _load(name):
    return json.loads((HUB / name).read_text(encoding="utf-8"))


async def _run_against(handler):
    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        return await asyncio.wait_for(FakeHubClient(f"ws://127.0.0.1:{port}/ws/hub").run(), 10)


async def test_answers_every_sim_tick_with_the_recorded_report():
    received = []

    async def handler(ws):
        received.append(json.loads(await ws.recv()))  # hub_hello
        for msg in _jsonl("server_to_hub.jsonl"):
            await ws.send(json.dumps(msg))
            if msg["type"] == "sim_tick":
                received.append(json.loads(await ws.recv()))
        await ws.close()

    answered = await _run_against(handler)
    assert received == _jsonl("hub_to_server.jsonl")
    assert answered == list(range(1, 121))


async def test_second_host_stops_on_host_taken():
    async def handler(ws):
        assert json.loads(await ws.recv()) == _load("hub_hello.json")
        await ws.send(json.dumps(_load("hub_welcome_host_taken.json")))
        await ws.wait_closed()

    assert await _run_against(handler) == []


async def test_replay_burst_is_answered_only_for_its_last_tick():
    ticks = [m for m in _jsonl("server_to_hub.jsonl") if m["type"] == "sim_tick"]
    received = []

    async def handler(ws):
        await ws.recv()  # hub_hello
        await ws.send(json.dumps(_load("sim_build.json")))
        for msg in ticks[:5]:
            await ws.send(json.dumps({**msg, "replay": True}))
        received.append(json.loads(await ws.recv()))
        await ws.send(json.dumps(ticks[5]))
        received.append(json.loads(await ws.recv()))
        await ws.close()

    answered = await _run_against(handler)
    assert answered == [5, 6]
    assert [r["tick_id"] for r in received] == [5, 6]


async def test_unrecorded_tick_gets_no_invented_report():
    async def handler(ws):
        await ws.recv()
        await ws.send(json.dumps({**_load("sim_tick.json"), "tick_id": 9999}))
        await asyncio.sleep(0.3)
        await ws.close()

    assert await _run_against(handler) == []
