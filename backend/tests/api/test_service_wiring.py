"""REST answers come from FakeKitchen + MemoryStore (not the rest fixtures), and writes land in the store."""

import json
import threading
import time

from api.errors import RuleError
from api.settings import REPO_ROOT

FIXTURES = REPO_ROOT / "contracts" / "fixtures"


def _load(rel):
    return json.loads((FIXTURES / rel).read_text(encoding="utf-8"))


def test_confirm_applies_and_stores_the_proposal(app, client):
    resp = client.post("/api/proposals/p_0001/confirm", json={"confirm": True})
    assert resp.status_code == 200
    # The stored end state is exactly the Convex fixture row.
    assert app.state.store.rows("proposals") == _load("convex/tables/proposals.json")
    assert client.get("/api/proposals?status=pending").json() == []
    again = client.post("/api/proposals/p_0001/confirm", json={"confirm": True})
    assert again.status_code == 422


def test_reject_cancels_without_applying(app, client):
    resp = client.post("/api/proposals/p_0001/confirm", json={"confirm": False})
    assert resp.json()["status"] == "cancelled"
    assert app.state.store.proposal("p_0001")["status"] == "cancelled"


def test_decisions_are_read_from_the_store(app, client):
    newest = {**_load("convex/tables/decisions.json")[-1], "decision_id": "d_0017", "ts": "2026-07-18T02:30:00Z"}
    app.state.store.record_decisions([newest])
    first = client.get("/api/decisions?limit=1").json()[0]
    assert first["decision_id"] == "d_0017"
    assert "lane" not in first and "explanation" not in first


def test_undo_updates_the_stored_decision(app, client):
    assert client.post("/api/decisions/d_0001/undo").status_code == 200
    stored = next(d for d in app.state.store.decisions() if d["decision_id"] == "d_0001")
    assert stored["status"] == "undone"
    assert stored["lane"] == "with" and "explanation" in stored


def test_owner_resolution_is_stored_as_final_state(app, client):
    fx = _load("rest/post_escalation_resolve.json")
    client.post(fx["path"], json=fx["request"])
    assert app.state.store.escalations() == [fx["response"]]


def test_same_backtest_reuses_the_run_and_unrecorded_is_501(app, client):
    assert client.post("/api/backtest/run", json={"months": ["2026-07"], "assumptions_id": "base"}).json() == {
        "run_id": "run_0001"
    }
    assert app.state.store.backtest_run_ids() == ["run_0001"]
    resp = client.post("/api/backtest/run", json={"months": ["2026-08"], "assumptions_id": "base"})
    assert resp.status_code == 501


def test_build_kitchen_records_it(app, client):
    before = len(app.state.store.rows("kitchens"))
    client.post("/api/kitchen", json=_load("rest/post_kitchen.json")["request"])
    assert len(app.state.store.rows("kitchens")) == before + 1
    client.post("/api/kitchen", json=_load("rest/post_kitchen_422.json")["request"])
    assert len(app.state.store.rows("kitchens")) == before + 1


def test_concurrent_confirmations_apply_once(app):
    book = app.state.proposals
    applied, outcomes = [], []
    real_apply = book._apply

    def slow_apply(proposal):
        time.sleep(0.05)  # widen the check-then-write window
        applied.append(proposal["proposal_id"])
        real_apply(proposal)

    book._apply = slow_apply

    def confirm():
        try:
            outcomes.append(book.confirm("p_0001", True)["status"])
        except RuleError:
            outcomes.append("rejected")

    threads = [threading.Thread(target=confirm) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert applied == ["p_0001"]
    assert sorted(outcomes) == ["confirmed", "rejected"]


PAID_AUTHORITY = {"enabled": True, "max_cap_overrun_kw": 3.0, "max_extra_delay_min": 20, "max_extra_reduce_min": 15,
                  "may_go_below_min_power": False}


def test_concierge_proposes_authority_and_the_owner_confirm_applies_it(app, client, agent_token):
    body = {"kind": "authority", "payload": PAID_AUTHORITY, "summary": "Let Claude handle escalations"}
    resp = client.post("/api/proposals", json=body, headers={"X-Agent-Token": agent_token})
    assert resp.status_code == 200, resp.text
    proposal = resp.json()
    assert (proposal["kind"], proposal["payload"], proposal["status"]) == ("authority", PAID_AUTHORITY, "pending")

    applied = []
    real_set = app.state.service.set_authority
    app.state.service.set_authority = lambda payload: (applied.append(payload), real_set(payload))[1]
    done = client.post(f"/api/proposals/{proposal['proposal_id']}/confirm", json={"confirm": True},
                       headers={"X-Agent-Token": agent_token})
    assert done.json()["status"] == "confirmed" and done.json()["confirmed_via"] == "asi_one"
    assert applied == [PAID_AUTHORITY]


def test_create_proposal_needs_the_agent_token_and_only_takes_authority(client, agent_token):
    body = {"kind": "authority", "payload": PAID_AUTHORITY, "summary": "x"}
    assert client.post("/api/proposals", json=body).status_code == 401
    other = {"kind": "peak_cap", "payload": {"peak_mode": "cap", "peak_cap_kw": 40.0}, "summary": "x"}
    assert client.post("/api/proposals", json=other, headers={"X-Agent-Token": agent_token}).status_code == 422
