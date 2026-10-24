"""Route table, agent token, error bodies and the viewer /ws, beyond the per-fixture replay in test_rest.py."""

import json

import pytest
from pydantic import TypeAdapter

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
    ("POST", "/api/proposals"),
    ("POST", "/api/proposals/{proposal_id}/confirm"),
    ("PUT", "/api/kitchen/authority"),
    ("PUT", "/api/kitchen/preferences"),
    ("GET", "/api/context"),
    ("POST", "/api/context"),
    ("POST", "/api/context/crowd-effect"),
    ("GET", "/api/escalations"),
    ("POST", "/api/escalations/{escalation_id}/resolve"),
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
        ("POST", "/api/escalations/e_9999/resolve", {"option_id": "ask_owner"}, "Unknown escalation e_9999"),
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


def test_every_ws_fixture_matches_the_models():
    adapter = TypeAdapter(m.WsMessage)
    lines = (FIXTURES / "ws" / "stream.jsonl").read_text(encoding="utf-8").splitlines()
    messages = [json.loads(line) for line in lines if line.strip()]
    messages += [_load(f"ws/{p.name}") for p in sorted((FIXTURES / "ws").glob("*.json"))]
    for msg in messages:
        parsed = adapter.validate_python(msg)
        assert parsed.model_dump(mode="json", by_alias=True, exclude_unset=True) == msg


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
