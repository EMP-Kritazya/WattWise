"""Route table, agent token, error bodies and the viewer /ws, beyond the per-fixture replay in test_rest.py."""

import json
from copy import deepcopy

import pytest
from pydantic import TypeAdapter, ValidationError

from api import models as m
from api.settings import REPO_ROOT
from api.ws import replay_fixture_stream

FIXTURES = REPO_ROOT / "contracts" / "fixtures"

# CONTRACTS.md §2 REST table, all 25 rows.
CONTRACT_ROUTES = {
    ("GET", "/api/catalog"),
    ("POST", "/api/kitchen"),
    ("GET", "/api/kitchen"),
    ("PUT", "/api/kitchen/devices/{device_id}/importance"),
    ("PUT", "/api/kitchen/peak-cap"),
    ("POST", "/api/sim/control"),
    ("POST", "/api/devices/{device_id}/command"),
    ("POST", "/api/events/customers"),
    ("POST", "/api/decisions/{decision_id}/undo"),
    ("GET", "/api/decisions"),
    ("POST", "/api/backtest/run"),
    ("GET", "/api/backtest/{run_id}"),
    ("POST", "/api/chat"),
    ("GET", "/api/proposals"),
    ("POST", "/api/proposals/{proposal_id}/confirm"),
    ("PUT", "/api/kitchen/authority"),
    ("PUT", "/api/kitchen/preferences"),
    ("GET", "/api/context"),
    ("POST", "/api/context"),
    ("POST", "/api/context/crowd-effect"),
    ("GET", "/api/escalations"),
    ("POST", "/api/agent-log"),
    ("GET", "/api/health"),
}

AGENT_POSTS = ["post_context.json", "post_context_crowd_effect.json", "post_agent_log.json"]


def _load(rel):
    return json.loads((FIXTURES / rel).read_text(encoding="utf-8"))


def test_openapi_lists_every_contract_route(client):
    spec = client.get("/openapi.json").json()
    served = {(method.upper(), path) for path, ops in spec["paths"].items() for method in ops}
    assert served == CONTRACT_ROUTES


def test_docs_served(client):
    assert client.get("/docs").status_code == 200


def test_health_reports_settings_not_fixture(app, client):
    app.state.sim_host_connected = False
    assert client.get("/api/health").json()["sim_host"] == "offline"


@pytest.mark.parametrize("name", AGENT_POSTS)
@pytest.mark.parametrize("headers", [{}, {"X-Agent-Token": "wrong"}], ids=["missing", "wrong"])
def test_agent_endpoints_need_token(client, name, headers):
    fx = _load(f"rest/{name}")
    resp = client.post(fx["path"], json=fx["request"], headers=headers)
    assert resp.status_code == 401
    assert isinstance(resp.json()["detail"], str)


def test_invalid_body_is_422_with_text_detail(client):
    resp = client.put("/api/kitchen/peak-cap", json={"peak_mode": "lowest", "peak_cap_kw": 40})
    assert resp.status_code == 422
    assert isinstance(resp.json()["detail"], str)
    assert "peak_mode" in resp.json()["detail"]


def test_crowd_effect_is_a_category_never_a_number(client, agent_token):
    resp = client.post(
        "/api/context/crowd-effect", json={"value": 1.25, "reason": "x"}, headers={"X-Agent-Token": agent_token}
    )
    assert resp.status_code == 422


@pytest.mark.parametrize(
    "method, path, body, detail",
    [
        ("POST", "/api/proposals/p_9999/confirm", {"confirm": True}, "Unknown proposal p_9999"),
        ("GET", "/api/backtest/run_9999", None, "Unknown backtest run run_9999"),
    ],
)
def test_unknown_ids_are_404(client, method, path, body, detail):
    resp = client.request(method, path, json=body)
    assert resp.status_code == 404
    assert resp.json() == {"detail": detail}


def test_unrecorded_body_dependent_request_is_501_not_faked(client):
    resp = client.put("/api/kitchen/peak-cap", json={"peak_mode": "cap", "peak_cap_kw": 42.0})
    assert resp.status_code == 501


def test_queries_filter_recorded_lists(client):
    assert len(client.get("/api/decisions?limit=3").json()) == 3
    assert client.get("/api/proposals?status=confirmed").json() == []
    assert client.get("/api/escalations?status=resolved").json() == []


def _ws_fixture_messages():
    lines = (FIXTURES / "ws" / "stream.jsonl").read_text(encoding="utf-8").splitlines()
    messages = [json.loads(line) for line in lines if line.strip()]
    return messages + [_load(f"ws/{p.name}") for p in sorted((FIXTURES / "ws").glob("*.json"))]


def test_current_ws_fixtures_match_the_models():
    """Every regenerated WebSocket fixture is an executable contract example."""
    adapter = TypeAdapter(m.WsMessage)
    for msg in _ws_fixture_messages():
        parsed = adapter.validate_python(msg)
        # ISO timestamps can normalize fractional precision during serialization.
        dumped = parsed.model_dump(mode="json", by_alias=True, exclude_unset=True)
        assert adapter.validate_python(dumped) == parsed


def test_missing_required_meter_field_is_rejected():
    adapter = TypeAdapter(m.WsMessage)
    message = _load("ws/tick.json")
    message["data"]["meter"].pop("demand_peaks")
    with pytest.raises(ValidationError):
        adapter.validate_python(message)


def test_current_tick_models_include_escalation_and_meter_contract_fields():
    state = deepcopy(_load("ws/tick.json")["data"])
    state["meter"].update(on_peak_month_peak_kw=38.4, energy_kwh_month=7712.4)
    state["warnings"] = [{
        "code": "cap_unreachable", "message": "Engine target cannot be held.",
        "data": {"unavoidable_kw": 44.0, "peak_cap_kw": None, "target_kw": 41.0},
    }]
    escalation = state["new_escalations"][0]
    escalation.update(updated_ts=escalation["ts"], active_option_id="extend_delay_dishwasher")
    for index, option in enumerate(escalation["options"], start=1):
        option.update(harm_score=None if option["option_id"] == "ask_owner" else float(index),
                      rank=None if option["option_id"] == "ask_owner" else index)

    parsed = m.TickState.model_validate(state)
    assert parsed.meter.energy_kwh_month == 7712.4
    assert parsed.new_escalations[0].model_dump(mode="json")["updated_ts"] == escalation["ts"]
    assert parsed.warnings[0].data.peak_cap_kw is None


def test_snapshot_model_has_every_facade_field():
    assert set(m.KitchenSnapshot.model_fields) == {
        "tick_id", "sim_ts", "lane", "control", "peak_mode", "config", "meter", "forecast_kw", "forecast_ts",
        "devices", "active_commands", "owed_kwh", "open_escalations", "warnings", "recent_decisions", "context",
        "id_counters",
    }


def test_ws_replays_fixture_stream_to_every_viewer(app, client):
    stream = FIXTURES / "ws" / "stream.jsonl"
    expected = [json.loads(line) for line in stream.read_text(encoding="utf-8").splitlines() if line.strip()]
    broadcaster = app.state.broadcaster

    with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
        assert broadcaster.client_count == 2
        sent = client.portal.call(replay_fixture_stream, broadcaster, stream)
        assert sent == len(expected)
        for viewer in (a, b):
            assert [viewer.receive_json() for _ in expected] == expected
