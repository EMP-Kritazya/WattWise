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
    def __init__(self, config: dict, tariff: dict, control: str, seed: int, *, fixtures_dir: Path | None = None):
        if control not in LANES:
            raise ValueError(f"control={control!r}; expected one of {LANES}")
        self._rec = _recorded(_fixtures_dir(fixtures_dir))
        self._raise_recorded_rule_errors(config)
        if not any(
            ex["args"]["config"] == config and ex["args"]["tariff"] == tariff for ex in self._rec.calls.get("Kitchen", [])
        ):
            raise NotRecordedError("STUB: FakeKitchen only knows the recorded kitchen config and tariff")
        self.control = control
        self.seed = seed

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

    def warm_up(self, *args: Any, **kwargs: Any) -> None:
        return None

    def step(self, minutes: int, hub_report: dict) -> dict:
        if hub_report["lane"] != self.control:
            raise ValueError(f"{self.control} lane got a {hub_report['lane']} HubReport")
        line = self._rec.steps.get((hub_report["lane"], hub_report["tick_id"]))
        if line is None or line["args"]["minutes"] != minutes:
            raise NotRecordedError(f"STUB: FakeKitchen has no recorded step for {self.control} tick {hub_report['tick_id']}")
        return copy.deepcopy(line["returns"])

    def ingest_reading(self, reading: dict) -> dict:
        return _answer(self._rec, "ingest_reading", {"reading": reading})

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
        return _answer(self._rec, "set_authority", {"authority": authority}, any_args=True)

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
        # STUB: no recording for this choice. Return the recorded open escalation with the choice filled in; the status
        # follows the chosen option's engine-computed `within_authority` (CONTRACTS.md §3). No number is produced.
        escalation = next((e for e in self.open_escalations() if e["escalation_id"] == escalation_id), None)
        if escalation is None:
            raise NotRecordedError(f"STUB: FakeKitchen has no open escalation {escalation_id}")
        option = next((o for o in escalation["options"] if o["option_id"] == option_id), None)
        if option is None:
            raise RuleError(f"{escalation_id}: {option_id} is not one of the offered options")
        awaiting = resolved_by == "claude" and not option["within_authority"]
        escalation.update(
            status="awaiting_owner" if awaiting else "resolved",
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
        return _answer(self._rec, "snapshot", {})


def fake_run_backtest(
    months: list[str],
    assumptions_id: str,
    on_progress: Callable[..., Any] | None = None,
    *,
    fixtures_dir: Path | None = None,
) -> list[dict]:
    # on_progress's signature is TBD (Kritazya); the fake never calls it.
    rec = _recorded(_fixtures_dir(fixtures_dir))
    for example in rec.calls.get("run_backtest", []):
        if example["args"]["months"] == months and example["args"]["assumptions_id"] == assumptions_id:
            return copy.deepcopy(example["returns"])
    raise NotRecordedError(f"STUB: FakeKitchen has no recorded backtest for {months} / {assumptions_id}")


def fake_compare_lanes(without: dict, with_: dict, *, fixtures_dir: Path | None = None) -> dict:
    if without["ts"] != with_["ts"]:
        raise ValueError(f"compare_lanes needs one tick pair; got {without['ts']} and {with_['ts']}")
    comparison = _recorded(_fixtures_dir(fixtures_dir)).comparisons.get(with_["ts"])
    if comparison is None:
        raise NotRecordedError(f"STUB: FakeKitchen has no recorded comparison at {with_['ts']}")
    return copy.deepcopy(comparison)
