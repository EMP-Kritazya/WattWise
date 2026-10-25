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
from datetime import datetime, timedelta, timezone
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
    def __init__(self, fixtures_dir: Path, engine: EngineApi, store: Store, *,
                 start_sim_ts: str = "2026-07-18T00:30:00Z"):
        self._engine = engine
        self._store = store
        self._fixtures_dir = fixtures_dir
        self._start_sim_ts = datetime.fromisoformat(start_sim_ts.replace("Z", "+00:00"))
        self._real = getattr(engine, "impl", "fake") == "real"
        # One lock for every facade call and check-then-write (e.g. confirming a proposal from UI + ASI:One at once).
        # runtime/loop.py takes the same lock around step().
        self.lock = threading.RLock()
        self._tariff = self._load_tariff("demo_tariff_v1")
        self._catalog = _load(Path(__file__).resolve().parents[1] / "data" / "equipment_catalog.json"
                              if self._real else fixtures_dir / "shapes" / "equipment_catalog.json")
        self.lanes = self._new_lanes(self._tariff)
        self.on_escalation: Callable[[dict], None] | None = None  # every resolve, from any thread (runtime/escalations.py)
        kitchen = store.latest_kitchen()
        if kitchen is not None:
            config = self._normalized_config(kitchen["config"])
            self._build_lanes(config)

    def _load_tariff(self, tariff_id: str) -> dict:
        if not self._real:
            return _load(self._fixtures_dir / "shapes" / "tariff.json")
        from data.tariffs import load_tariff

        selectors = {"demo_tariff_v1": "demo", "pge_b19_secondary_voluntary": "pge_b19"}
        if tariff_id not in selectors:
            raise self._engine.RuleError(f"Unknown tariff_id: {tariff_id}")
        return load_tariff(selectors[tariff_id])

    def _new_lanes(self, tariff: dict) -> Lanes:
        return Lanes(self._engine, tariff, self._catalog if self._real else None)

    def _build_lanes(self, config: dict) -> None:
        tariff = self._load_tariff(config["tariff_id"])
        lanes = self._new_lanes(tariff)
        history = self._warm_up_history(config["tariff_id"])
        if self._real and history is not None:
            history_end = datetime.fromisoformat(history["end"].replace("Z", "+00:00"))
            if history_end > self._start_sim_ts:
                blocks = [block for block in history["blocks"]
                          if datetime.fromisoformat(block["block_start"].replace("Z", "+00:00"))
                          + timedelta(minutes=15) <= self._start_sim_ts]
                history = {**history, "blocks": blocks, "end": self._start_sim_ts.isoformat(),
                           "month_to_date": None} if blocks else None
        if self._real and history is not None:
            roster = {f"{entry['type_id']}_{n}" for entry in config["equipment"]
                      for n in range(1, entry["count"] + 1)}
            blocks = [block for block in history["blocks"] if block["device_id"] in roster]
            if len(blocks) != len(history["blocks"]):
                # Never carry a different kitchen's aggregate bill into this roster.
                history = {**history, "blocks": blocks, "month_to_date": None} if blocks else None
        lanes.build(config, config.get("seed", SEED), history)
        self.lanes, self._tariff = lanes, tariff

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
        if device_id not in {d["device_id"] for d in self.get_kitchen()["devices"]}:
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

    def _warm_up_history(self, tariff_id: str = "demo_tariff_v1") -> dict | None:
        """Use calibrated history for real lanes; retain fixture-backed fake behavior."""
        try:
            build_warmup = importlib.import_module("data.warmup").build_warmup
        except (ImportError, AttributeError) as exc:
            log.info("warm_up skipped from data.warmup: %s", exc)
        else:
            if self._real:
                from data.recipe import RatedKwExceeded

                try:
                    return build_warmup(self._start_sim_ts, tariff="demo" if tariff_id == "demo_tariff_v1" else "pge_b19")
                except FileNotFoundError:
                    log.info("Calibrated warm-up dataset unavailable")
                    return None
                except RatedKwExceeded:
                    log.warning("Calibrated warm-up exceeds the current catalog ratings; using explicitly labelled "
                                "fixture_synthetic history", exc_info=True)
                    return _load(self._fixtures_dir / "history" / "warmup_demo_cafe.json")
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
        self._build_lanes(normalized)
        self._store.record_kitchen(normalized, self._now_utc())
        return {"kitchen_id": KITCHEN_ID}

    @_serialized
    def get_kitchen(self) -> dict:
        snap = self._lane().snapshot()
        devices = snap["devices"]
        if self._real and not devices:
            # Before the first report the engine has no appliance observations.
            # The hub still needs the build roster, with the contract's off/zero placeholders.
            catalog = {entry["type_id"]: entry for entry in self._catalog}
            devices = [
                {"device_id": f"{entry['type_id']}_{n}", "type_id": entry["type_id"],
                 "name": f"{catalog[entry['type_id']]['name']} {n}", "importance": entry["importance"],
                 "state": "off", "power_kw": 0.0, "rated_kw": catalog[entry["type_id"]]["rated_kw"],
                 "power_pct": 0, "source": "simulated"}
                for entry in snap["config"]["equipment"] for n in range(1, entry["count"] + 1)
            ]
        return {"config": snap["config"], "devices": devices, "tariff": copy.deepcopy(self._tariff)}

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
        if self._engine.impl == "real" and self._lane().snapshot()["tick_id"] == 0:
            raise self._engine.RuleError("Wait for the first hub reading before sending a device command")
        commands = {
            lane: self._lane(lane).owner_command(device_id, body["action"], body.get("value"))
            for lane in LANES
        }
        return commands["with"]

    # ------------------------------------------------------------ decisions, escalations

    @_serialized
    def decisions(self, limit: int) -> list[dict]:
        records = sorted(self._store.decisions(), key=lambda d: (d["ts"], d["decision_id"]), reverse=True)
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
    def resolve_escalation(self, escalation_id: str, body: dict, resolved_by: str = "claude",
                           rationale: str | None = None) -> dict:
        """Validate Claude's chosen option through the engine facade."""
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
        if self._real:
            from data.backtest_inputs import load_backtest_inputs

            inputs = load_backtest_inputs(months, assumptions_id)
            results = self._engine.run_backtest(inputs, months, assumptions_id)
        else:
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
