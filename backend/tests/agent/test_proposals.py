"""Confirming a Proposal applies exactly the matching facade call (by code), once; cancel and expiry apply nothing."""

import pytest

from api.errors import RuleError

from .conftest import load

# kind → (shape fixture, facade method on the `with` kitchen, expected positional args)
APPLY = {
    "importance": ("proposal_pending", "set_importance", ("walk_in_cooler_1", "always_on", {})),
    "peak_cap": ("proposal_peak_cap", "set_peak_cap", ("cap", 38.0)),
    "authority": ("proposal_authority", "set_authority", (load("shapes/proposal_authority.json")["payload"],)),
    "undo_decision": ("proposal_undo_decision", "undo", ("d_0010",)),
}
@pytest.fixture
def pushed(app, monkeypatch):
    messages = []
    monkeypatch.setattr(app.state.proposals, "_publish", messages.append)
    return messages


@pytest.mark.parametrize("kind", APPLY)
def test_confirm_applies_the_facade_call(app, set_clock, facade_calls, pushed, kind):
    shape, method, args = APPLY[kind]
    proposal = load(f"shapes/{shape}.json")
    app.state.store.upsert_proposal(proposal)
    set_clock(proposal["ts"])

    result = app.state.proposals.confirm(proposal["proposal_id"], True, via="asi_one")

    assert facade_calls == [(method, args)]
    assert result == {**proposal, "status": "confirmed", "confirmed_via": "asi_one"}
    assert app.state.store.proposal(proposal["proposal_id"]) == result
    assert pushed == [{"type": "proposal", "data": result}]


def test_confirmed_customer_event_becomes_a_surge_at_its_start(app, set_clock, facade_calls):
    proposal = load("shapes/proposal_customer_event.json")
    app.state.store.upsert_proposal(proposal)
    set_clock(proposal["ts"])
    app.state.proposals.confirm(proposal["proposal_id"], True)

    surges = app.state.runtime.surges
    assert facade_calls == []
    assert surges.drain("2026-07-18T02:59:00Z") == []
    assert surges.drain(proposal["payload"]["start_sim_ts"]) == [
        {"surge_id": "s_0001", "customers": 40, "duration_min": 60}]


def test_cancel_applies_nothing(app, facade_calls):
    result = app.state.proposals.confirm("p_0001", False)
    assert result["status"] == "cancelled" and result["confirmed_via"] is None
    assert facade_calls == []


def test_expired_proposal_cannot_be_confirmed(app, set_clock, facade_calls, pushed):
    set_clock("2026-07-18T03:00:00Z")  # p_0001 expires_at
    assert app.state.proposals.list("pending") == []
    assert app.state.store.proposal("p_0001")["status"] == "expired"
    with pytest.raises(RuleError):
        app.state.proposals.confirm("p_0001", True)
    assert facade_calls == []
    assert [m["data"]["status"] for m in pushed] == ["expired"]


def test_confirm_endpoint_and_ws_push(client):
    with client.websocket_connect("/ws") as ws:
        resp = client.post("/api/proposals/p_0001/confirm", json={"confirm": True})
        assert resp.json() == load("rest/post_proposal_confirm.json")["response"]
        assert ws.receive_json() == {"type": "proposal", "data": resp.json()}
