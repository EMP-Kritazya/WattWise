"""Service layer behind every REST endpoint: engine facade calls (via `runtime/kitchen_factory.py`) + the Store.

Computes nothing. Every number comes from the engine (FakeKitchen in fake mode) or a stored record:
- an unknown id (device, decision, proposal, escalation, backtest run) → NotFoundError (404);
- engine RuleError → 422; a call fake mode has no recording for → NotRecordedError (501), never a made-up answer.
The clock, surges, owner commands, context stamping and agent logs live in `runtime/loop.py`, which calls in here.
Proposals live in `agent/proposals.py` and chat in `agent/claude_agent.py`; both call back in here to apply changes.
"""

from __future__ import annotations

import copy
import functools
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from runtime.kitchen_factory import EngineApi
from runtime.lanes import LANES, Lanes
from store import Store

from .errors import NoKitchenError, NotFoundError

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
        # runtime/loop.py takes the same lock around step().
        self.lock = threading.RLock()
        # STUB: tariff and catalog come from backend/data/ (Kritazya / Ashirwad) once it exists on this branch.
        self._tariff = _load(fixtures_dir / "shapes" / "tariff.json")
        self._catalog = _load(fixtures_dir / "shapes" / "equipment_catalog.json")
        self.lanes = Lanes(engine, self._tariff)
        self.on_escalation: Callable[[dict], None] | None = None  # every resolve, from any thread (runtime/escalations.py)
        kitchen = store.latest_kitchen()
        if kitchen is not None:
            self.lanes.build(kitchen["config"], SEED)

    @property
    def tariff(self) -> dict:
        return self._tariff

    @property
    def store(self) -> Store:
        return self._store

    # ------------------------------------------------------------ helpers

    def require_kitchen(self) -> None:
        if not self.lanes:
            raise NoKitchenError()

    def _lane(self, lane: str = "with") -> Any:
        self.require_kitchen()
        return self.lanes[lane]

    def _require_device(self, device_id: str) -> None:
        if device_id not in {d["device_id"] for d in self._lane().snapshot()["devices"]}:
            raise NotFoundError("device", device_id)

    @staticmethod
    def _now_utc() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    # ------------------------------------------------------------ kitchen

    @_serialized
    def catalog(self) -> list[dict]:
        return copy.deepcopy(self._catalog)

    @_serialized
    def build_kitchen(self, config: dict) -> dict:
        """Both lanes + the `kitchens` record. Called by `RunLoop.build`, which then sends `sim_build`."""
        self.lanes.build(config, SEED)  # RuleError leaves the lanes and the store untouched
        self._store.record_kitchen(config, self._now_utc())
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

    # ------------------------------------------------------------ devices

    @_serialized
    def device_command(self, device_id: str, body: dict) -> dict:
        """The owner Command; `RunLoop.owner_command` queues it for the next sim_tick."""
        self._require_device(device_id)
        return self._lane().owner_command(device_id, body["action"], body.get("value"))

    # ------------------------------------------------------------ decisions, escalations

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
    def resolve_escalation(self, escalation_id: str, body: dict, resolved_by: str = "owner",
                           rationale: str | None = None) -> dict:
        """Owner choice (REST, or a confirmed proposal) or Claude's choice (`choose_escalation_option`)."""
        if escalation_id not in {e["escalation_id"] for e in self._all_escalations()}:
            raise NotFoundError("escalation", escalation_id)
        escalation = self._lane().resolve_escalation(escalation_id, body["option_id"], resolved_by, rationale)
        if escalation["status"] in FINAL_ESCALATION_STATUSES:
            self._store.record_escalation(escalation)
        if self.on_escalation is not None:
            self.on_escalation(copy.deepcopy(escalation))  # runtime/escalations.py publishes it
        return escalation

    @_serialized
    def expire_escalation(self, last_known: dict) -> dict:
        """Past its deadline the engine has applied its default itself (CONTRACTS.md §1 Escalation, §3). Stores and
        returns the final state: the engine's when it lists one. STUB (contract question): the facade has no call that
        returns an expired escalation, so otherwise it is the last known state with the engine's default filled in."""
        escalation_id = last_known["escalation_id"]
        engine = next((e for e in self._lane().open_escalations() if e["escalation_id"] == escalation_id), None)
        if engine is not None and engine["status"] in FINAL_ESCALATION_STATUSES:
            final = engine
        else:
            final = {**copy.deepcopy(last_known), "status": "expired_default", "resolved_by": "default",
                     "chosen_option_id": last_known["default_option_id"], "rationale": None}
        self._store.record_escalation(final)
        return final

    # ------------------------------------------------------------ backtest

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

    # ------------------------------------------------------------ context + agents

    @_serialized
    def get_context(self) -> dict:
        return self._lane().snapshot()["context"]

    @_serialized
    def post_context(self, body: dict) -> dict:
        """Both lanes; `RunLoop.post_context` has stamped `ts` in sim time."""
        for lane in LANES:
            self._lane(lane).set_context(body)
        return {"ok": True}

    @_serialized
    def set_crowd_effect(self, body: dict) -> dict:
        crowd_effect = {"value": body["value"], "set_by": "claude", "reason": body["reason"]}
        for lane in LANES:
            self._lane(lane).set_context({"crowd_effect": crowd_effect})
        return crowd_effect
