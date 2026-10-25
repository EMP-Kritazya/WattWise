"""FakeKitchen: every engine facade call of CONTRACTS.md §3 with the same signatures, answered from
`contracts/fixtures/facade/`. Computes nothing (FAKE DATA, not engine output).

- `step(minutes, hub_report)` → the TickState in `facade/step_stream.jsonl` for (hub_report lane, tick_id).
- Every other call → its `facade/<call>.json` `returns` when the arguments equal the recorded ones; the recorded
  `raises` examples raise RuleError. Calls whose answer does not depend on the arguments (`warm_up`, `set_context`,
  `set_authority`, `set_preferences`, `snapshot`, `open_escalations`) always answer. Anything else raises
  NotRecordedError: fake mode never invents an answer.
- `fake_compare_lanes` / `fake_run_backtest` stand in for the module-level `compare_lanes` / `run_backtest`.
Selected by `runtime/kitchen_factory.py` (`KITCHEN_IMPL=fake`); the optional keyword `fixtures_dir` is fake-only.
"""

from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from runtime.kitchen_factory import NotRecordedError, RuleError

DEFAULT_FIXTURES_DIR = Path(__file__).resolve().parents[2] / "contracts" / "fixtures"
LANES = ("without", "with")


def _fixtures_dir(fixtures_dir: Path | None) -> Path:
    return Path(fixtures_dir or os.environ.get("FIXTURES_DIR") or DEFAULT_FIXTURES_DIR)


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@dataclass
class _Recorded:
    calls: dict[str, list[dict]] = field(default_factory=dict)  # call name → [{call, args, returns, raises?}]
    steps: dict[tuple[str, int], dict] = field(default_factory=dict)  # (lane, tick_id) → {args, returns}
    comparisons: dict[str, dict] = field(default_factory=dict)  # TickState ts → LaneComparison


@dataclass
class _FakeIdAllocator:
    """Identity-only stand-in for the engine's shared id allocator.

    Fixture responses already contain their engine-computed ids, so fake mode
    deliberately does not manufacture ids.  The object still lets tests prove
    that both lanes were created with one allocator, as the real facade does.
    """

    decisions: int = 0
    commands: int = 0
    escalations: int = 0


@lru_cache(maxsize=4)
def _recorded(fixtures_dir: Path) -> _Recorded:
    rec = _Recorded()
    facade = fixtures_dir / "facade"
    for file in sorted(facade.glob("*.json")):
        example = json.loads(file.read_text(encoding="utf-8"))
        rec.calls.setdefault(example["call"], []).append(example)
    for line in _read_jsonl(facade / "step_stream.jsonl"):
        report = line["args"]["hub_report"]
        rec.steps[(report["lane"], report["tick_id"])] = line
    # One recorded compare_lanes call (facade/) plus the per-tick comparisons the scenario streams (ws/stream.jsonl).
    for msg in _read_jsonl(fixtures_dir / "ws" / "stream.jsonl"):
        if msg["type"] == "comparison":
            rec.comparisons[msg["data"]["ts"]] = msg["data"]
    for example in rec.calls.get("compare_lanes", []):
        rec.comparisons[example["args"]["with_"]["ts"]] = example["returns"]
    # Negative REST examples also record facade rule rejections; reuse their
    # exact text rather than inventing behavior for an unrecorded fake call.
    for file in sorted((fixtures_dir / "rest").glob("*.json")):
        example = json.loads(file.read_text(encoding="utf-8"))
        path = example["path"].split("/")
        if (example["method"] == "POST" and example["status"] == 422
                and len(path) == 5 and path[2] == "decisions" and path[4] == "undo"):
            rec.calls.setdefault("undo", []).append({"args": {"decision_id": path[3]},
                                                      "raises": {"message": example["response"]["detail"]}})
    return rec


def _answer(rec: _Recorded, call: str, args: dict[str, Any], *, any_args: bool = False) -> Any:
    examples = rec.calls.get(call, [])
    for example in examples:
        if example["args"] == args:
            if example.get("raises"):
                raise RuleError(example["raises"]["message"])
            return copy.deepcopy(example["returns"])
    if any_args:
        for example in examples:
            if not example.get("raises"):
                return copy.deepcopy(example["returns"])
    raise NotRecordedError(f"STUB: FakeKitchen has no recorded {call}({json.dumps(args, sort_keys=True)})")


class FakeKitchen:
    def __init__(self, config: dict, tariff: dict, control: str, seed: int, ids: Any | None = None,
                 *, fixtures_dir: Path | None = None, catalog: list[dict] | None = None):
        if control not in LANES:
            raise ValueError(f"control={control!r}; expected one of {LANES}")
        self._rec = _recorded(_fixtures_dir(fixtures_dir))
        self._raise_recorded_rule_errors(config)
        if not any(
            self._matches_recorded_kitchen(ex, config, tariff) for ex in self._rec.calls.get("Kitchen", [])
        ):
            raise NotRecordedError("STUB: FakeKitchen only knows the recorded kitchen config and tariff")
        self.control = control
        self.seed = seed
        self.config = copy.deepcopy(config)
        # Match ``Kitchen(..., ids=None)``: individual lanes receive their own
        # allocator, while ``build_lanes`` passes the same object to both.
        self.ids = ids if ids is not None else _FakeIdAllocator()
        self.warm_up_calls: list[Any] = []
        self.warm_up_history: Any | None = None

    @staticmethod
    def _matches_recorded_kitchen(example: dict, config: dict, tariff: dict) -> bool:
        """Authority is owner input, not fixture-owned fake data.

        The recordings predate the Builder's full-authority default.  The fake
        can therefore reuse the same simulated kitchen for a config that only
        differs in authority, while preserving strict matching for its roster,
        tariff, rules, and every other setting.
        """
        if example["args"]["tariff"] != tariff:
            return False
        recorded, requested = copy.deepcopy(example["args"]["config"]), copy.deepcopy(config)
        recorded.pop("authority", None)
        requested.pop("authority", None)
        return recorded == requested

    @classmethod
    def build_lanes(cls, config: dict, tariff: dict, seed: int, *, fixtures_dir: Path | None = None) -> dict[str, "FakeKitchen"]:
        """Build the contract's two lanes with one shared fake allocator."""
        ids = _FakeIdAllocator()
        return {
            lane: cls(config, tariff, lane, seed, ids, fixtures_dir=fixtures_dir)
            for lane in LANES
        }

    def _raise_recorded_rule_errors(self, config: dict) -> None:
        """A config entry that sets a device to a recorded unsafe importance raises that recorded RuleError."""
        for example in self._rec.calls.get("set_importance", []):
            if not example.get("raises"):
                continue
            bad = example["args"]
            for entry in config.get("equipment", []):
                device_ids = {f"{entry['type_id']}_{n}" for n in range(1, entry.get("count", 0) + 1)}
                if (
                    bad["device_id"] in device_ids
                    and entry.get("importance") == bad["importance"]
                    and entry.get("limits", {}) == bad["limits"]
                ):
                    raise RuleError(example["raises"]["message"])

    # ------------------------------------------------------------ run

    def warm_up(self, history: Any = None, *args: Any, **kwargs: Any) -> None:
        """Record the contract warm-up call without producing fixture data.

        ``None`` remains accepted only for the stale, argument-free facade
        fixture; runtime construction never calls this method without history.
        """
        recorded = copy.deepcopy(history)
        self.warm_up_calls.append(recorded)
        self.warm_up_history = recorded
        return None

    def step(self, minutes: int, hub_report: dict) -> dict:
        if hub_report["lane"] != self.control:
            raise ValueError(f"{self.control} lane got a {hub_report['lane']} HubReport")
        line = self._rec.steps.get((hub_report["lane"], hub_report["tick_id"]))
        if line is None or line["args"]["minutes"] != minutes:
            raise NotRecordedError(f"STUB: FakeKitchen has no recorded step for {self.control} tick {hub_report['tick_id']}")
        return copy.deepcopy(line["returns"])

    def ingest_reading(self, reading: dict) -> dict:
        # STUB: any Reading is accepted (the device bridge relays a new one every tick); the recorded Device is returned
        # for the recorded Reading, and as a stand-in otherwise. The runtime does not use the return value.
        return _answer(self._rec, "ingest_reading", {"reading": reading}, any_args=True)

    def set_context(self, context: dict) -> None:
        return _answer(self._rec, "set_context", {"context": context}, any_args=True)

    # ------------------------------------------------------------ owner

    def owner_command(self, device_id: str, action: str, value: float | None) -> dict:
        return _answer(self._rec, "owner_command", {"device_id": device_id, "action": action, "value": value})

    def set_importance(self, device_id: str, importance: str, limits: dict) -> dict:
        return _answer(self._rec, "set_importance", {"device_id": device_id, "importance": importance, "limits": limits})

    def set_peak_cap(self, peak_mode: str, peak_cap_kw: float | None) -> dict:
        return _answer(self._rec, "set_peak_cap", {"peak_mode": peak_mode, "peak_cap_kw": peak_cap_kw})

    def undo(self, decision_id: str) -> dict:
        return _answer(self._rec, "undo", {"decision_id": decision_id})

    def set_authority(self, authority: dict) -> None:
        _answer(self._rec, "set_authority", {"authority": authority}, any_args=True)
        # Authority is owner input rather than a fixture-derived engine value.
        # Keep the fake snapshot in step with the real facade after a PUT.
        self.config["authority"] = copy.deepcopy(authority)
        return None

    def set_preferences(self, text: str) -> None:
        return _answer(self._rec, "set_preferences", {"text": text}, any_args=True)

    # ------------------------------------------------------------ escalations

    def open_escalations(self) -> list[dict]:
        return _answer(self._rec, "open_escalations", {})

    def resolve_escalation(self, escalation_id: str, option_id: str, resolved_by: str, rationale: str | None) -> dict:
        args = {"escalation_id": escalation_id, "option_id": option_id, "resolved_by": resolved_by, "rationale": rationale}
        try:
            return _answer(self._rec, "resolve_escalation", args)
        except NotRecordedError:
            pass
        # STUB: no recording for this choice. Return the recorded open escalation with the choice filled in, but do
        # not manufacture the legacy ``awaiting_owner`` handoff.  Claude is never offered an outside-authority id;
        # a direct invalid call is rejected here too, while the owner can still select any offered option.
        escalation = next((e for e in self.open_escalations() if e["escalation_id"] == escalation_id), None)
        if escalation is None:
            raise NotRecordedError(f"STUB: FakeKitchen has no open escalation {escalation_id}")
        option = next((o for o in escalation["options"] if o["option_id"] == option_id), None)
        if option is None:
            raise RuleError(f"{escalation_id}: {option_id} is not one of the offered options")
        if resolved_by == "claude" and not option["within_authority"]:
            raise RuleError(f"{escalation_id}: {option_id} is outside Claude authority")
        escalation.update(
            status="resolved",
            resolved_by=resolved_by,
            chosen_option_id=option_id,
            rationale=rationale,
        )
        return escalation

    # ------------------------------------------------------------ read only

    def forecast(self, horizon_min: int) -> list[float]:
        return _answer(self._rec, "forecast", {"horizon_min": horizon_min})

    def what_if(self, device_id: str, action: str, value: float | None, at: str) -> dict:
        return _answer(self._rec, "what_if", {"device_id": device_id, "action": action, "value": value, "at": at})

    def snapshot(self) -> dict:
        snapshot = _answer(self._rec, "snapshot", {})
        # The configuration is owner input, so keeping the normalized request
        # here does not manufacture an engine number and lets the API expose
        # the Builder's implicit FULL_AUTHORITY accurately in fake mode.
        snapshot["config"] = copy.deepcopy(self.config)
        return snapshot


def fake_run_backtest(
    months: list[str],
    assumptions_id: str,
    on_progress: Callable[..., Any] | None = None,
    *,
    fixtures_dir: Path | None = None,
    inputs: dict | None = None,
) -> list[dict]:
    # on_progress's signature is TBD (Kritazya); the fake never calls it.
    rec = _recorded(_fixtures_dir(fixtures_dir))
    for example in rec.calls.get("run_backtest", []):
        if (example["args"]["months"] == months and example["args"]["assumptions_id"] == assumptions_id
                and (inputs is None or example["args"].get("inputs") == inputs)):
            return copy.deepcopy(example["returns"])
    raise NotRecordedError(f"STUB: FakeKitchen has no recorded backtest for {months} / {assumptions_id}")


def fake_compare_lanes(without: dict, with_: dict, *, fixtures_dir: Path | None = None) -> dict:
    if without["ts"] != with_["ts"]:
        raise ValueError(f"compare_lanes needs one tick pair; got {without['ts']} and {with_['ts']}")
    comparison = _recorded(_fixtures_dir(fixtures_dir)).comparisons.get(with_["ts"])
    if comparison is None:
        raise NotRecordedError(f"STUB: FakeKitchen has no recorded comparison at {with_['ts']}")
    return copy.deepcopy(comparison)
