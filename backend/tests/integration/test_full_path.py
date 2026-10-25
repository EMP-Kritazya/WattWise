"""Real API/runtime/engine seam with a protocol-level browser hub and viewer.

The test hub supplies measured-shaped simulated readings; browser physics has its
own frontend tests. No canned engine, runtime, transport, or decisions are used.
"""
import copy
import json
from datetime import datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from api.main import create_app
from api.settings import Settings
from contracts import HubReportMessage

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "contracts" / "fixtures"
TOKEN = "integration-agent-token"


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


def report_for(tick, devices):
    ts = (datetime.fromisoformat(tick["sim_ts"].replace("Z", "+00:00")) + timedelta(minutes=1)).isoformat()
    reports = {}
    for lane in ("without", "with"):
        readings = copy.deepcopy(devices)
        acks = []
        for device in readings:
            device.update(state="on", power_kw=device["rated_kw"], power_pct=100)
            for command in tick["commands"]:
                if command["lane"] == lane and command["device_id"] == device["device_id"]:
                    if command["action"] == "reduce":
                        device.update(power_pct=command["value"], power_kw=device["rated_kw"] * command["value"] / 100)
                    acks.append({"command_id": command["command_id"], "lane": lane, "ok": True,
                                 "applied_value": command["value"], "reason": None})
        reports[lane] = {"hub_id": "sim_hub", "lane": lane, "tick_id": tick["tick_id"], "ts": ts,
                         "total_kw": sum(d["power_kw"] for d in readings), "customers_per_hour": 60,
                         "devices": readings, "acks": acks, "source": "simulated"}
    message = {"type": "hub_report", "tick_id": tick["tick_id"], "reports": reports}
    HubReportMessage.model_validate(message)
    return message


def test_authenticated_context_real_engine_commands_and_viewer_updates(monkeypatch):
    app = create_app(Settings(kitchen_impl="real", live_transport="ws", store="memory", agent_token=TOKEN))
    app.state.runtime.autorun = False
    config = fixture("shapes/kitchen_config.json")
    config["equipment"] = [config["equipment"][0], config["equipment"][-1]]
    config["peak_cap_kw"] = 4
    # Every unit at rated_kw against a 4 kW cap: no in-rules move can hold it (a routine reduce has no room to repay), so
    # the engine escalates; this authority lets its fallback take HVAC below min_power_pct (never refrigeration below 50 %).
    config["authority"] = dict(config["authority"], may_go_below_min_power=True)
    with TestClient(app) as client, client.websocket_connect("/ws/hub") as hub, client.websocket_connect("/ws") as viewer:
        hub.send_json({"type": "hub_hello", "protocol": 1, "hub_id": "sim_hub", "role": "sim_host", "client": "integration/1"})
        assert hub.receive_json()["accepted"] is True
        built = client.post("/api/kitchen", json=config)
        assert built.status_code == 200, built.text
        build = hub.receive_json()
        assert build["type"] == "sim_build"
        assert client.get("/api/health").json()["kitchen_impl"] == "real"
        context = fixture("agents/context_post.json")["body"]
        assert client.post("/api/context", json=context).status_code == 401
        # Run the production Concierge reshaping/logging/posting loop. Only
        # external source replies are recorded; API transport is real ASGI.
        monkeypatch.syspath_prepend(str(ROOT / "agents"))
        import httpx
        from context_loop import ApiClient, ContextLoop, Location
        from crowd import recorded_classifier
        from models import EventsResponse, PriceResponse, WeatherResponse

        async def fetch_round():
            replies = {
                "weather": WeatherResponse.model_validate(fixture("agents/weather_response.json")),
                "grid": PriceResponse.model_validate(fixture("agents/price_response.json")),
                "events": EventsResponse.model_validate(fixture("agents/events_response.json")),
            }

            async def ask(name, request):
                assert request.model_dump()  # typed Fetch message contract
                return replies[name]

            async def check_response(response):
                await response.aread()
                assert response.status_code == 200, response.text

            async with httpx.AsyncClient(event_hooks={"response": [check_response]}, transport=httpx.ASGITransport(app=app), base_url="http://testserver") as http:
                loop = ContextLoop(ApiClient(http, TOKEN), recorded_classifier)
                return await loop.run_once(Location(lat=37.8, lon=-122.44), ask)

        context = client.portal.call(fetch_round)
        assert context is not None
        fetched = client.get("/api/context").json()
        for part, value in context.items():
            if part != "ts":
                assert fetched[part] == value
        for lane in app.state.service.lanes:
            assert lane.snapshot()["context"] == fetched

        command_id = None
        sent = []
        for number in range(1, 8):
            if number == 2:
                # The owner request enters the real engine. Its Command appears in the
                # next engine result, then travels to the hub one tick later.
                device = next(d for d in build["devices"] if d["importance"] == "flexible")
                owner = client.post(f"/api/devices/{device['device_id']}/command", json={"action": "reduce", "value": 60})
                assert owner.status_code == 200, owner.text
                command_id = owner.json()["command_id"]

            future = client.portal.start_task_soon(app.state.runtime.tick_once)
            tick = hub.receive_json()
            assert tick["type"] == "sim_tick"
            assert tick["tick_id"] == number
            assert tick["inputs"]["crowd_multiplier"] == 1.25
            sent.append(tick)
            hub.send_json(report_for(tick, build["devices"]))
            assert future.result(timeout=5) is True
        client.portal.call(app.state.runtime.flush)
        assert command_id not in {c["command_id"] for c in sent[1]["commands"]}
        assert command_id in {c["command_id"] for c in sent[2]["commands"]}
        assert all(c["issued_by"] == "owner" for tick in sent[:5] for c in tick["commands"])
        automatic = [c for c in sent[5]["commands"] if c["issued_by"] == "engine"]
        assert automatic, "the real engine's escalation fallback should control the overloaded kitchen on decision tick 5"
        decisions = client.get("/api/decisions").json()
        assert {c["decision_id"] for c in automatic} <= {d["decision_id"] for d in decisions}

        messages = []
        while len([m for m in messages if m["type"] == "tick"]) < 14:
            messages.append(viewer.receive_json())
        assert any(m["type"] == "context" and m["data"] == fetched for m in messages)
        ticks = [m["data"] for m in messages if m["type"] == "tick"]
        assert {t["lane"] for t in ticks} == {"without", "with"}
        assert all(t["meter"]["energy_kwh_today"] > 0 for t in ticks)
        assert any(m["type"] == "agent_log" and m["data"]["kind"] == "post" for m in messages)
        assert any(m["type"] == "comparison" for m in messages)
        assert any(m["type"] == "decision" for m in messages)
