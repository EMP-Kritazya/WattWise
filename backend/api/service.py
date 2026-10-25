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
import importlib
import inspect
import json
import logging
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
FULL_AUTHORITY = {
    "enabled": True,
    "max_cap_overrun_kw": 1000,
    "max_extra_delay_min": 0,
    "max_extra_reduce_min": 1440,
    "may_go_below_min_power": False,
}
DECISION_EXTRAS = ("lane", "explanation", "explanation_source")
FINAL_ESCALATION_STATUSES = ("resolved", "expired_default", "obsolete")

log = logging.getLogger(__name__)


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
        self._fixtures_dir = fixtures_dir
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
            config = self._normalized_config(kitchen["config"])
            self.lanes.build(config, config.get("seed", SEED), self._warm_up_history())

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

    @staticmethod
    def _normalized_config(config: dict) -> dict:
        """Copy the caller's config and fill the Builder's implicit authority."""
        normalized = copy.deepcopy(config)
        if normalized.get("authority") is None:
            normalized["authority"] = copy.deepcopy(FULL_AUTHORITY)
        return normalized

    def _warm_up_history(self) -> dict | None:
        """Return optional history without guessing the unshipped data helper's API.

        ``data.warmup.build_warmup`` is owned by the data workstream and its
        call signature is not part of the runtime contract yet.  When it is
        available and explicitly accepts a zero-argument call, use it.  A
        builder requiring inputs is left alone rather than inventing an
        interface; the checked-in fixture is the next fallback.
        """
        try:
            build_warmup = importlib.import_module("data.warmup").build_warmup
        except (ImportError, AttributeError) as exc:
            log.info("warm_up skipped from data.warmup: %s", exc)
        else:
            try:
                signature = inspect.signature(build_warmup)
                signature.bind()
            except (TypeError, ValueError) as exc:
                log.warning("warm_up skipped: data.warmup.build_warmup has no documented zero-argument call (%s)", exc)
            else:
                try:
                    history = build_warmup()
                except Exception:  # Optional calibrated data must never block a kitchen build.
                    log.warning("warm_up from data.warmup failed; trying fixture history", exc_info=True)
                else:
                    if history is not None:
                        return history
                    log.info("warm_up skipped: data.warmup.build_warmup returned no history")

        fixture = self._fixtures_dir / "history" / "warmup_demo_cafe.json"
        if fixture.is_file():
            try:
                return _load(fixture)
            except (OSError, json.JSONDecodeError):
                log.warning("warm_up fixture could not be read: %s", fixture, exc_info=True)
        else:
            log.info("warm_up skipped: no data.warmup history or fixture at %s", fixture)
        return None

    # ------------------------------------------------------------ kitchen

    @_serialized
    def catalog(self) -> list[dict]:
        return copy.deepcopy(self._catalog)

    @_serialized
    def build_kitchen(self, config: dict) -> dict:
        """Both lanes + the `kitchens` record. Called by `RunLoop.build`, which then sends `sim_build`."""
        normalized = self._normalized_config(config)
        self.lanes.build(normalized, normalized.get("seed", SEED), self._warm_up_history())
        self._store.record_kitchen(normalized, self._now_utc())
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
        # Keep the build configuration in sync with the engine's with-lane
        # state so a later reset/rebuild preserves the owner's authority.
        if self.lanes.config is not None:
            self.lanes.config["authority"] = copy.deepcopy(body)
        return {"ok": True}

    @_serialized
    def set_preferences(self, body: dict) -> dict:
        self._lane().set_preferences(body["text"])
        return {"ok": True}

    # ------------------------------------------------------------ devices

    @_serialized
    def device_command(self, device_id: str, body: dict) -> dict:
        """Record the same owner command in both lanes; delivery stays with the loop."""
        self._require_device(device_id)
        commands = {
            lane: self._lane(lane).owner_command(device_id, body["action"], body.get("value"))
            for lane in LANES
        }
        return commands["with"]

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
