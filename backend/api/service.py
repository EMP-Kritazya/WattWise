# STUB: fixture replay service; replace with facade + runtime calls (FakeKitchen / engine via KITCHEN_IMPL)
"""Service layer behind every REST endpoint.

For now each method answers from `contracts/fixtures/rest/*.json` and computes nothing:
- an unknown id (device, decision, proposal, escalation, backtest run) → NotFoundError (404);
- a request recorded in a fixture → that fixture's answer (its 404 / 422 examples raise NotFoundError / RuleError);
- a request with no recorded answer → the recorded success when the answer does not depend on the body
  (`ok`, ids), otherwise NotRecordedError (501). Rule checks belong to the engine, not here.
Requests are compared as parsed JSON, never raw bytes.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import NotFoundError, NotRecordedError, RuleError


@dataclass(frozen=True)
class Example:
    method: str
    path: str
    status: int
    request: Any
    response: Any


class FixtureService:
    def __init__(self, fixtures_dir: Path):
        self._examples: list[Example] = []
        for file in sorted((fixtures_dir / "rest").glob("*.json")):
            raw = json.loads(file.read_text(encoding="utf-8"))
            self._examples.append(Example(raw["method"], raw["path"], raw["status"], raw["request"], raw["response"]))
        kitchen = self._success("GET", "/api/kitchen")
        self._device_ids = {d["device_id"] for d in kitchen["devices"]}
        self._decision_ids = {d["decision_id"] for d in self._success("GET", "/api/decisions?limit=50")}
        self._proposal_ids = {p["proposal_id"] for p in self._success("GET", "/api/proposals?status=pending")}
        self._escalation_ids = {e["escalation_id"] for e in self._success("GET", "/api/escalations?status=open")}
        self._run_ids = {e.path.rsplit("/", 1)[1] for e in self._examples if e.path.startswith("/api/backtest/run_")}

    # ------------------------------------------------------------ replay helpers

    def _success(self, method: str, path: str) -> Any:
        for ex in self._examples:
            if ex.method == method and ex.path == path and ex.status == 200:
                return copy.deepcopy(ex.response)
        raise NotRecordedError(f"STUB: no fixture for {method} {path}")

    def _replay(self, method: str, path: str, body: Any, *, body_independent: bool = False) -> Any:
        for ex in self._examples:
            if ex.method == method and ex.path == path and ex.request == body:
                if ex.status == 200:
                    return copy.deepcopy(ex.response)
                if ex.status == 422:
                    raise RuleError(ex.response["detail"])
                # 404 examples are covered by _require (unknown ids) before any replay
        if body_independent:
            return self._success(method, path)
        raise NotRecordedError(f"STUB: no fixture answer for {method} {path} with this body")

    @staticmethod
    def _require(kind: str, item_id: str, known: set[str]) -> None:
        if item_id not in known:
            raise NotFoundError(kind, item_id)

    # ------------------------------------------------------------ kitchen

    def catalog(self) -> list[dict]:
        return self._success("GET", "/api/catalog")

    def build_kitchen(self, config: dict) -> dict:
        return self._replay("POST", "/api/kitchen", config, body_independent=True)

    def get_kitchen(self) -> dict:
        return self._success("GET", "/api/kitchen")

    def set_importance(self, device_id: str, body: dict) -> dict:
        self._require("device", device_id, self._device_ids)
        return self._replay("PUT", f"/api/kitchen/devices/{device_id}/importance", body)

    def set_peak_cap(self, body: dict) -> dict:
        return self._replay("PUT", "/api/kitchen/peak-cap", body)

    def set_authority(self, body: dict) -> dict:
        return self._replay("PUT", "/api/kitchen/authority", body, body_independent=True)

    def set_preferences(self, body: dict) -> dict:
        return self._replay("PUT", "/api/kitchen/preferences", body, body_independent=True)

    # ------------------------------------------------------------ clock, devices, events

    def sim_control(self, body: dict) -> dict:
        return self._replay("POST", "/api/sim/control", body)

    def device_command(self, device_id: str, body: dict) -> dict:
        self._require("device", device_id, self._device_ids)
        return self._replay("POST", f"/api/devices/{device_id}/command", body)

    def customer_event(self, body: dict) -> dict:
        return self._replay("POST", "/api/events/customers", body, body_independent=True)

    # ------------------------------------------------------------ decisions, escalations, proposals

    def decisions(self, limit: int) -> list[dict]:
        return self._success("GET", "/api/decisions?limit=50")[:limit]

    def undo_decision(self, decision_id: str) -> dict:
        self._require("decision", decision_id, self._decision_ids)
        return self._replay("POST", f"/api/decisions/{decision_id}/undo", None)

    def escalations(self, status: str | None) -> list[dict]:
        items = self._success("GET", "/api/escalations?status=open")
        return [e for e in items if status is None or e["status"] == status]

    def resolve_escalation(self, escalation_id: str, body: dict) -> dict:
        self._require("escalation", escalation_id, self._escalation_ids)
        return self._replay("POST", f"/api/escalations/{escalation_id}/resolve", body)

    def proposals(self, status: str | None) -> list[dict]:
        items = self._success("GET", "/api/proposals?status=pending")
        return [p for p in items if status is None or p["status"] == status]

    def confirm_proposal(self, proposal_id: str, body: dict) -> dict:
        self._require("proposal", proposal_id, self._proposal_ids)
        return self._replay("POST", f"/api/proposals/{proposal_id}/confirm", body)

    # ------------------------------------------------------------ backtest, chat

    def run_backtest(self, body: dict) -> dict:
        return self._replay("POST", "/api/backtest/run", body, body_independent=True)

    def backtest(self, run_id: str) -> list[dict]:
        self._require("backtest run", run_id, self._run_ids)
        return self._success("GET", f"/api/backtest/{run_id}")

    def chat(self, body: dict) -> dict:
        return self._replay("POST", "/api/chat", body, body_independent=True)

    # ------------------------------------------------------------ context + agents

    def get_context(self) -> dict:
        return self._success("GET", "/api/context")

    def post_context(self, body: dict) -> dict:
        return self._replay("POST", "/api/context", body, body_independent=True)

    def set_crowd_effect(self, body: dict) -> dict:
        return self._replay("POST", "/api/context/crowd-effect", body, body_independent=True)

    def post_agent_log(self, body: dict) -> dict:
        return self._replay("POST", "/api/agent-log", body, body_independent=True)
