"""REST answers come from FakeKitchen + MemoryStore (not the rest fixtures), and writes land in the store."""

import copy
import json
import sys
import threading
import time
import types

from api.errors import RuleError
from api.service import FULL_AUTHORITY, KitchenService
from api.settings import REPO_ROOT
from store.memory import MemoryStore

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
    assert client.post("/api/decisions/d_0010/undo").status_code == 200
    stored = next(d for d in app.state.store.decisions() if d["decision_id"] == "d_0010")
    assert stored["status"] == "undone"
    assert stored["lane"] == "with" and "explanation" in stored


def test_escalation_resolution_has_no_owner_rest_route(client):
    response = client.post("/api/escalations/e_0001/resolve", json={"option_id": "accept_overrun"})
    assert response.status_code == 404


def test_same_backtest_reuses_the_run_and_unrecorded_is_501(app, client):
    assert client.post("/api/backtest/run", json={"months": ["2026-06", "2026-07"], "assumptions_id": "base"}).json() == {
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


def test_post_kitchen_requires_contract_authority(app, client):
    config = copy.deepcopy(_load("rest/post_kitchen.json")["request"])
    config.pop("authority")

    response = client.post("/api/kitchen", json=config)

    assert response.status_code == 422
    assert "authority" in response.json()["detail"]


def test_authority_update_is_visible_to_escalation_gating(app, client):
    disabled = {**FULL_AUTHORITY, "enabled": False}

    response = client.put("/api/kitchen/authority", json=disabled)

    assert response.status_code == 200
    assert app.state.service.get_kitchen()["config"]["authority"] == disabled
    assert app.state.service.lanes.config["authority"] == disabled
    # The runtime reads the live with-lane snapshot, rather than the config
    # captured when the lanes were built, before it decides whether to call
    # Claude for an escalation.
    assert app.state.runtime.escalations._authority() == disabled


def test_build_injects_full_authority_and_warms_both_lanes_from_the_data_builder(monkeypatch):
    history = {"source": "test", "blocks": []}
    builder_calls, warm_ups, engine_configs = [], [], []

    class Lane:
        def __init__(self, lane):
            self.lane = lane

        def warm_up(self, received):
            warm_ups.append((self.lane, received))

    def build_lanes(config, tariff, seed):
        engine_configs.append((copy.deepcopy(config), tariff, seed))
        return {"without": Lane("without"), "with": Lane("with")}

    data = types.ModuleType("data")
    data.__path__ = []
    warmup = types.ModuleType("data.warmup")

    def build_warmup():
        builder_calls.append(True)
        return history

    warmup.build_warmup = build_warmup
    monkeypatch.setitem(sys.modules, "data", data)
    monkeypatch.setitem(sys.modules, "data.warmup", warmup)

    service = KitchenService(FIXTURES, types.SimpleNamespace(build_lanes=build_lanes), MemoryStore())
    config = _load("rest/post_kitchen.json")["request"]
    config.pop("authority")
    original = copy.deepcopy(config)

    assert service.build_kitchen(config) == {"kitchen_id": "k_01"}

    assert config == original  # service defaults are not written back into the request body
    assert builder_calls == [True]
    assert engine_configs[0][0]["authority"] == FULL_AUTHORITY
    assert engine_configs[0][2] == config["seed"]
    assert warm_ups == [("without", history), ("with", history)]
    assert service.store.latest_kitchen()["config"]["authority"] == FULL_AUTHORITY


def test_owner_command_reaches_both_lanes_without_then_with(app, monkeypatch):
    service = app.state.service
    calls = []
    without = {"command_id": "c_0019", "lane": "without"}
    with_ = {"command_id": "c_0020", "lane": "with"}

    def command_for(lane, result):
        def owner_command(device_id, action, value):
            calls.append((lane, device_id, action, value))
            return result
        return owner_command

    monkeypatch.setattr(service.lanes["without"], "owner_command", command_for("without", without))
    monkeypatch.setattr(service.lanes["with"], "owner_command", command_for("with", with_))

    assert service.device_command("ice_machine_1", {"action": "start"}) == with_
    assert calls == [
        ("without", "ice_machine_1", "start", None),
        ("with", "ice_machine_1", "start", None),
    ]


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


def test_proposals_cannot_be_created_through_an_extra_rest_route(client, agent_token):
    body = {"kind": "authority", "payload": FULL_AUTHORITY, "summary": "Upgrade"}
    response = client.post("/api/proposals", json=body, headers={"X-Agent-Token": agent_token})
    assert response.status_code == 405
