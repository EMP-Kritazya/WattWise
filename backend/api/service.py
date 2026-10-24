"""Service layer behind every REST endpoint: engine facade calls (via `runtime/kitchen_factory.py`) + the Store.

Computes nothing. Every number comes from the engine (FakeKitchen in fake mode) or a stored record:
- an unknown id (device, decision, proposal, escalation, backtest run) → NotFoundError (404);
- engine RuleError → 422; a call fake mode has no recording for → NotRecordedError (501), never a made-up answer.
The clock (`/api/sim/control`) and chat still replay `contracts/fixtures/rest/` until the runtime and agent exist.
"""

from __future__ import annotations

import copy
import functools
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runtime.kitchen_factory import EngineApi
from store import Store

from .errors import NoKitchenError, NotFoundError, NotRecordedError, RuleError

LANES = ("without", "with")
KITCHEN_ID = "k_01"  # one kitchen per process (demo)
SEED = 42
DECISION_EXTRAS = ("lane", "explanation", "explanation_source")
FINAL_ESCALATION_STATUSES = ("resolved", "expired_default")


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _serialized(method):
    """Run under the service lock: REST endpoints run in a threadpool and every call touches the shared lanes/store."""

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self.lock:
            return method(self, *args, **kwargs)

    return wrapper


def seed_fake_scenario(store: Store, fixtures_dir: Path) -> None:
    """STUB (fake mode): `convex/tables/` holds p_0001 after the owner confirmed it, while the REST fixtures show it still
    pending. Overlay the pending proposal so the confirm flow runs from the start (contract question for Kritazya)."""
    store.upsert_proposal(_load(fixtures_dir / "shapes" / "proposal_pending.json"))


class KitchenService:
    def __init__(self, fixtures_dir: Path, engine: EngineApi, store: Store):
        self._engine = engine
        self._store = store
        # One lock for every facade call and check-then-write (e.g. confirming a proposal from UI + ASI:One at once).
        # runtime/loop.py must take the same lock around step() in Phase B.
        self.lock = threading.RLock()
        # STUB: tariff and catalog come from backend/data/ (Kritazya / Ashirwad) once it exists on this branch.
        self._tariff = _load(fixtures_dir / "shapes" / "tariff.json")
        self._catalog = _load(fixtures_dir / "shapes" / "equipment_catalog.json")
        # STUB: answered from rest fixtures until runtime/loop.py (clock) and agent/ (chat) exist.
        self._rest = [_load(f) for f in sorted((fixtures_dir / "rest").glob("*.json"))]
        self._lanes: dict[str, Any] = {}
        kitchen = store.latest_kitchen()
        if kitchen is not None:
            self._lanes = self._build_lanes(kitchen["config"])

    # ------------------------------------------------------------ helpers

    def _build_lanes(self, config: dict) -> dict[str, Any]:
        # warm_up(...) is TBD (CONTRACTS.md §3); not called until its signature exists.
        return {lane: self._engine.Kitchen(config, self._tariff, lane, SEED) for lane in LANES}

    def _lane(self, lane: str = "with") -> Any:
        if not self._lanes:
            raise NoKitchenError()
        return self._lanes[lane]

    def _require_device(self, device_id: str) -> None:
        if device_id not in {d["device_id"] for d in self._lane().snapshot()["devices"]}:
            raise NotFoundError("device", device_id)

    def _rest_replay(self, method: str, path: str, body: Any, *, body_independent: bool = False) -> Any:
        for ex in self._rest:
            same_body = body_independent or ex["request"] == body
            if ex["method"] == method and ex["path"] == path and same_body and ex["status"] == 200:
                return copy.deepcopy(ex["response"])
        raise NotRecordedError(f"STUB: no fixture answer for {method} {path} with this body")

    @staticmethod
    def _now_utc() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    # ------------------------------------------------------------ kitchen

    @_serialized
    def catalog(self) -> list[dict]:
        return copy.deepcopy(self._catalog)

    @_serialized
    def build_kitchen(self, config: dict) -> dict:
        self._lanes = self._build_lanes(config)  # RuleError leaves the store untouched
        self._store.record_kitchen(config, self._now_utc())
        # STUB: runtime/hub_link.py sends sim_build to the sim host (Phase B).
        return {"kitchen_id": KITCHEN_ID}

    @_serialized
    def get_kitchen(self) -> dict:
        snap = self._lane().snapshot()
        return {"config": snap["config"], "devices": snap["devices"], "tariff": copy.deepcopy(self._tariff)}

    @_serialized
    def set_importance(self, device_id: str, body: dict) -> dict:
        self._require_device(device_id)
        return self._lane().set_importance(device_id, body["importance"], body.get("limits", {}))

    @_serialized
    def set_peak_cap(self, body: dict) -> dict:
        return self._lane().set_peak_cap(body["peak_mode"], body.get("peak_cap_kw"))

    @_serialized
    def set_authority(self, body: dict) -> dict:
        self._lane().set_authority(body)
        return {"ok": True}

    @_serialized
    def set_preferences(self, body: dict) -> dict:
        self._lane().set_preferences(body["text"])
        return {"ok": True}

    # ------------------------------------------------------------ clock, devices, events

    @_serialized
    def sim_control(self, body: dict) -> dict:
        return self._rest_replay("POST", "/api/sim/control", body)

    @_serialized
    def device_command(self, device_id: str, body: dict) -> dict:
        self._require_device(device_id)
        return self._lane().owner_command(device_id, body["action"], body.get("value"))

    @_serialized
    def customer_event(self, body: dict) -> dict:
        # STUB: runtime/loop.py queues the surge into the next sim_tick (Phase B).
        return {"ok": True}

    # ------------------------------------------------------------ decisions, escalations, proposals

    @_serialized
    def decisions(self, limit: int) -> list[dict]:
        records = sorted(self._store.decisions(lane="with"), key=lambda d: (d["ts"], d["decision_id"]), reverse=True)
        return [{k: v for k, v in d.items() if k not in DECISION_EXTRAS} for d in records[:limit]]

    @_serialized
    def undo_decision(self, decision_id: str) -> dict:
        record = next((d for d in self._store.decisions() if d["decision_id"] == decision_id), None)
        if record is None:
            raise NotFoundError("decision", decision_id)
        decision = self._lane().undo(decision_id)
        self._store.record_decisions([{**record, **decision}])
        return decision

    def _all_escalations(self) -> list[dict]:
        """Stored final states, overridden by the engine's live open escalations."""
        merged = {e["escalation_id"]: e for e in self._store.escalations()}
        merged.update({e["escalation_id"]: e for e in self._lane().open_escalations()})
        return sorted(merged.values(), key=lambda e: (e["ts"], e["escalation_id"]))

    @_serialized
    def escalations(self, status: str | None) -> list[dict]:
        return [e for e in self._all_escalations() if status is None or e["status"] == status]

    @_serialized
    def resolve_escalation(self, escalation_id: str, body: dict) -> dict:
        if escalation_id not in {e["escalation_id"] for e in self._all_escalations()}:
            raise NotFoundError("escalation", escalation_id)
        escalation = self._lane().resolve_escalation(escalation_id, body["option_id"], "owner", None)
        if escalation["status"] in FINAL_ESCALATION_STATUSES:
            self._store.record_escalation(escalation)
        return escalation

    @_serialized
    def proposals(self, status: str | None) -> list[dict]:
        return self._store.proposals(status)

    @_serialized
    def confirm_proposal(self, proposal_id: str, body: dict) -> dict:
        proposal = self._store.proposal(proposal_id)
        if proposal is None:
            raise NotFoundError("proposal", proposal_id)
        if proposal["status"] != "pending":
            raise RuleError(f"{proposal_id} is {proposal['status']}, not pending")
        if body["confirm"]:
            self._apply(proposal)  # applied by code, never by the model
            proposal.update(status="confirmed", confirmed_via="ui")
        else:
            proposal["status"] = "cancelled"
        self._store.upsert_proposal(proposal)
        return proposal

    def _apply(self, proposal: dict) -> None:
        kind, payload = proposal["kind"], proposal["payload"]
        if kind == "importance":
            self.set_importance(payload["device_id"], payload)
        elif kind == "peak_cap":
            self.set_peak_cap(payload)
        elif kind == "authority":
            self.set_authority(payload)
        elif kind == "undo_decision":
            self.undo_decision(payload["decision_id"])
        elif kind == "resolve_escalation":
            self.resolve_escalation(payload["escalation_id"], payload)
        else:
            # STUB: customer_event proposals carry start_sim_ts; scheduling needs runtime/loop.py (Phase B).
            raise NotRecordedError(f"STUB: confirming a {kind} proposal is not built yet")

    # ------------------------------------------------------------ backtest, chat

    @_serialized
    def run_backtest(self, body: dict) -> dict:
        months, assumptions_id = body["months"], body["assumptions_id"]
        # The engine is deterministic: the same months + assumptions give the same results, so reuse that run.
        for run_id in self._store.backtest_run_ids():
            results = self._store.backtest(run_id) or []
            if [r["month"] for r in results] == months and all(r["assumptions_id"] == assumptions_id for r in results):
                return {"run_id": run_id}
        # STUB: synchronous for now; the real backtest moves to a background task with progress (Phase B).
        results = self._engine.run_backtest(months, assumptions_id, None)
        run_id = f"run_{len(self._store.backtest_run_ids()) + 1:04d}"
        self._store.save_backtest(run_id, results)
        return {"run_id": run_id}

    @_serialized
    def backtest(self, run_id: str) -> list[dict]:
        results = self._store.backtest(run_id)
        if results is None:
            raise NotFoundError("backtest run", run_id)
        return results

    @_serialized
    def chat(self, body: dict) -> dict:
        # STUB: agent/claude_agent.py streams the reply over /ws (Phase C).
        return self._rest_replay("POST", "/api/chat", body, body_independent=True)

    # ------------------------------------------------------------ context + agents

    @_serialized
    def get_context(self) -> dict:
        return self._lane().snapshot()["context"]

    @_serialized
    def post_context(self, body: dict) -> dict:
        # STUB: `ts` is stamped in sim time by the API once the clock exists (Phase B); forwarded unchanged for now.
        for lane in LANES:
            self._lane(lane).set_context(body)
        return {"ok": True}

    @_serialized
    def set_crowd_effect(self, body: dict) -> dict:
        crowd_effect = {"value": body["value"], "set_by": "claude", "reason": body["reason"]}
        for lane in LANES:
            self._lane(lane).set_context({"crowd_effect": crowd_effect})
        return {"ok": True}

    @_serialized
    def post_agent_log(self, body: dict) -> dict:
        # STUB: runtime broadcasts it as a /ws agent_log message (Phase B).
        return {"ok": True}
