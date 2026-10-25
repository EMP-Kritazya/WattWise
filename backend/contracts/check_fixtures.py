"""Validate every shared fixture in `contracts/fixtures/` against these models.

    cd backend && python -m contracts.check_fixtures            # summary, exit 1 if anything fails
    cd backend && python -m contracts.check_fixtures --verbose  # first errors per failing file

Complements `contracts/fixtures/check.py` (invariants, determinism): this one checks the shapes only.
Files whose shape is not modelled yet are reported as SKIP, never as OK.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable, Optional

from pydantic import TypeAdapter, ValidationError

from . import api, hub, live, shapes, ws

ROOT = Path(__file__).resolve().parents[2] / "contracts" / "fixtures"

# Facade snapshot() keys (CONTRACTS.md section 3). `owed_kwh` and `id_counters` have no element shape in the prose, so
# snapshot is checked by key set + the typed parts only.
SNAPSHOT_KEYS = [
    "tick_id", "sim_ts", "lane", "control", "peak_mode", "config", "meter", "forecast_kw", "forecast_ts", "devices",
    "active_commands", "owed_kwh", "open_escalations", "warnings", "recent_decisions", "context", "id_counters",
]

Check = Callable[[Any], None]
_adapters: dict[Any, TypeAdapter] = {}


def _ta(tp: Any) -> TypeAdapter:
    if tp not in _adapters:
        _adapters[tp] = TypeAdapter(tp)
    return _adapters[tp]


def v(tp: Any) -> Check:
    return lambda obj: _ta(tp).validate_python(obj)


def at(key: str, tp: Any) -> Check:
    return lambda obj: _ta(tp).validate_python(obj[key])


def strip(tp: Any, *keys: str) -> Check:
    def check(obj: Any) -> None:
        rows = obj if isinstance(obj, list) else [obj]
        for row in rows:
            _ta(tp).validate_python({k: val for k, val in row.items() if k not in keys})
    return check


def each(check: Check) -> Check:
    return lambda obj: [check(o) for o in obj]


def all_of(*checks: Check) -> Check:
    def check(obj: Any) -> None:
        for c in checks:
            c(obj)
    return check


Forecast = list[float]


def forecast8(obj: Any) -> None:
    _ta(Forecast).validate_python(obj)
    if len(obj) != 8:
        raise ValueError(f"forecast must have 8 values, got {len(obj)}")


def snapshot(obj: Any) -> None:
    missing = [k for k in SNAPSHOT_KEYS if k not in obj]
    extra = [k for k in obj if k not in SNAPSHOT_KEYS]
    if missing or extra:
        raise ValueError(f"snapshot keys: missing {missing}, unexpected {extra}")
    _ta(shapes.KitchenConfig).validate_python(obj["config"])
    _ta(shapes.Meter).validate_python(obj["meter"])
    _ta(list[shapes.Device]).validate_python(obj["devices"])
    _ta(list[shapes.Command]).validate_python(obj["active_commands"])
    _ta(list[shapes.Escalation]).validate_python(obj["open_escalations"])
    _ta(list[shapes.WarningShape]).validate_python(obj["warnings"])
    _ta(list[shapes.Decision]).validate_python(obj["recent_decisions"])


def set_clock_args(obj: Any) -> None:
    names = ["playing", "speed", "sim_ts", "tick_id", "paused_reason", "day_index", "run_days", "phase", "sim_host"]
    args = obj["args"]
    if len(args) != len(names):
        raise ValueError(f"set_clock takes {len(names)} args {names}, got {len(args)}")
    _ta(live.LiveClockRow).validate_python({"id": 0, **dict(zip(names, args))})


def reducer_json(tp: Any) -> Check:
    return lambda obj: _ta(tp).validate_python(json.loads(obj["args"][0]))


def request_surge_args(obj: Any) -> None:
    customers, duration_min = obj["args"]
    if not (1 <= customers <= 80 and 15 <= duration_min <= 120):
        raise ValueError("request_surge: customers 1..80, duration 15..120 min")


# REST: (method, path prefix) -> (request check or None, response check for 2xx)
REST: list[tuple[str, str, Optional[Check], Check]] = [
    ("GET", "/api/catalog", None, v(list[shapes.EquipmentType])),
    ("POST", "/api/kitchen", v(shapes.KitchenConfig), v(api.KitchenCreated)),
    ("GET", "/api/kitchen", None, v(api.KitchenView)),
    ("PUT", "/api/kitchen/devices/", v(api.ImportanceUpdate), v(shapes.Device)),
    ("PUT", "/api/kitchen/peak-cap", v(api.PeakCapUpdate), v(shapes.Meter)),
    ("POST", "/api/sim/control", v(api.SimControlRequest), v(api.ClockState)),
    ("POST", "/api/devices/", v(api.DeviceCommandRequest), v(shapes.Command)),
    ("POST", "/api/events/customers", v(api.CustomerEventRequest), v(api.Ok)),
    ("POST", "/api/decisions/", None, v(shapes.Decision)),
    ("GET", "/api/decisions", None, v(list[shapes.Decision])),
    ("POST", "/api/backtest/run", v(api.BacktestRunRequest), v(api.BacktestRunCreated)),
    ("GET", "/api/backtest/", None, v(list[shapes.BacktestResult])),
    ("POST", "/api/chat", v(api.ChatRequest), v(api.ChatCreated)),
    ("GET", "/api/proposals", None, v(list[shapes.Proposal])),
    ("POST", "/api/proposals/", v(api.ProposalConfirmRequest), v(shapes.Proposal)),
    ("PUT", "/api/kitchen/authority", v(shapes.ClaudeAuthority), v(api.Ok)),
    ("PUT", "/api/kitchen/preferences", v(api.PreferencesUpdate), v(api.Ok)),
    ("GET", "/api/context", None, v(shapes.Context)),
    ("POST", "/api/context/crowd-effect", v(api.CrowdEffectRequest), v(api.Ok)),
    ("POST", "/api/context", v(shapes.PartialContext), v(api.Ok)),
    ("GET", "/api/escalations", None, v(list[shapes.Escalation])),
    ("POST", "/api/agent-log", v(shapes.AgentLog), v(api.Ok)),
    ("GET", "/api/health", None, v(api.Health)),
]

# Error examples whose request is *meant* to be invalid at the schema level (Pydantic rejects it, API answers 422).
EXPECTED_INVALID_REQUESTS = {"rest/put_peak_cap_422.json"}


def rest_check(path: str) -> Check:
    def check(obj: Any) -> None:
        for method, prefix, req, resp in REST:
            if obj["method"] == method and obj["path"].split("?")[0].startswith(prefix):
                break
        else:
            raise ValueError(f"no REST route for {obj['method']} {obj['path']}")
        if req is not None and path not in EXPECTED_INVALID_REQUESTS:
            req(obj["request"])
        if req is not None and path in EXPECTED_INVALID_REQUESTS:
            try:
                req(obj["request"])
            except (ValidationError, ValueError):
                pass
            else:
                raise ValueError("error example request unexpectedly valid")
        if obj["status"] >= 400:
            v(api.ErrorDetail)(obj["response"])
        else:
            resp(obj["response"])
    return check


TOOLS: dict[str, Check] = {
    "choose_escalation_option": at("output", shapes.Escalation),
    "explain_decision": at("output", shapes.Decision),
    "get_bill": at("output", shapes.Bill),
    "get_context": at("output", shapes.Context),
    "get_escalation": at("output", list[shapes.Escalation]),
    "get_forecast": lambda o: forecast8(o["output"]),
    "get_kitchen_state": lambda o: snapshot(o["output"]),
    "propose_customer_event": at("output", shapes.Proposal),
    "propose_importance_change": at("output", shapes.Proposal),
    "propose_peak_cap_change": at("output", shapes.Proposal),
    "propose_undo": at("output", shapes.Proposal),
    "set_crowd_effect": all_of(at("input", api.CrowdEffectRequest), at("output", api.Ok)),
    "what_if": at("output", shapes.Effect),
}


def ret(tp: Any) -> Check:
    return at("returns", tp)


FACADE: dict[str, Check] = {
    "compare_lanes": all_of(
        lambda o: _ta(shapes.TickState).validate_python(o["args"]["without"]),
        lambda o: _ta(shapes.TickState).validate_python(o["args"]["with_"]),
        ret(shapes.LaneComparison),
    ),
    "forecast": lambda o: forecast8(o["returns"]),
    "ingest_reading": all_of(lambda o: _ta(shapes.Reading).validate_python(o["args"]["reading"]), ret(shapes.Device)),
    "kitchen": lambda o: (
        _ta(shapes.KitchenConfig).validate_python(o["args"]["config"]),
        _ta(shapes.Tariff).validate_python(o["args"]["tariff"]),
    ),
    "open_escalations": ret(list[shapes.Escalation]),
    "owner_command": ret(shapes.Command),
    "resolve_escalation": ret(shapes.Escalation),
    "run_backtest": all_of(
        # `inputs` (BacktestInputs) is checked when the fixture carries it inline (it may be a file reference)
        lambda o: _ta(shapes.BacktestInputs).validate_python(o["args"]["inputs"])
        if isinstance(o["args"].get("inputs"), dict) else None,
        ret(list[shapes.BacktestResult]),
    ),
    "set_authority": lambda o: _ta(shapes.ClaudeAuthority).validate_python(o["args"]["authority"]),
    "set_context": lambda o: _ta(shapes.Context).validate_python(o["args"]["context"]),
    "set_importance": ret(shapes.Device),
    "set_importance_rule_error": lambda o: None,  # unsafe limits are a RuleError (engine), shape-valid by design
    "set_peak_cap": ret(shapes.Meter),
    "set_peak_cap_rule_error": lambda o: None,
    "set_preferences": lambda o: None,
    "snapshot": lambda o: snapshot(o["returns"]),
    "undo": ret(shapes.Decision),
    "warm_up": lambda o: _ta(shapes.WarmUpHistory).validate_python(o["args"]["history"]),
    "what_if": ret(shapes.Effect),
}

SPACETIME_TABLES: dict[str, Any] = {
    "backtest_month": live.BacktestMonthRow,
    "backtest_point": live.BacktestPointRow,
    "live_agent_log": live.LiveAgentLogRow,
    "live_clock": live.LiveClockRow,
    "live_comparison": live.LiveComparisonRow,
    "live_context": live.LiveContextRow,
    "live_device": live.LiveDeviceRow,
    "live_escalation": live.LiveEscalationRow,
    "live_feed": live.LiveFeedRow,
    "live_tick": live.LiveTickRow,
    "surge_request": live.SurgeRequestRow,
    "tick_history": live.TickHistoryRow,
}

REDUCERS: dict[str, Check] = {
    "consume_surge": lambda o: _ta(int).validate_python(o["args"][0]),
    "log_agent": reducer_json(shapes.AgentLog),
    "publish_backtest_month": reducer_json(live.BacktestMonthRow),
    "publish_backtest_point": reducer_json(live.BacktestPointRow),
    "publish_context": reducer_json(live.LiveContextRow),
    "publish_escalation": reducer_json(live.LiveEscalationRow),
    "publish_feed": reducer_json(live.LiveFeedRow),
    "publish_ticks": reducer_json(live.PublishTicksPayload),
    "request_surge": request_surge_args,
    "reset_backtest": lambda o: _ta(tuple[str]).validate_python(o["args"]),
    "reset_all": lambda o: None if o["args"] == [] else (_ for _ in ()).throw(ValueError("reset_all takes no args")),
    "set_clock": set_clock_args,
}

CONVEX: dict[str, Check] = {
    "functions/backtest_save": lambda o: _ta(list[shapes.BacktestResult]).validate_python(o["args"]["results"]),
    "functions/bills_save": lambda o: _ta(shapes.Bill).validate_python(o["args"]["bill"]),
    "functions/commands_enqueue": lambda o: _ta(shapes.Command).validate_python(o["args"]["command"]),
    "functions/decisions_record": lambda o: strip(shapes.Decision, "lane", "explanation", "explanation_source")(
        o["args"]["decisions"]
    ),
    "functions/devices_report": lambda o: _ta(shapes.Reading).validate_python(o["args"]["reading"]),
    "functions/proposals_upsert": lambda o: _ta(shapes.Proposal).validate_python(o["args"]["proposal"]),
    "tables/backtest_results": strip(shapes.BacktestResult, "run_id"),
    "tables/bills": strip(shapes.Bill, "lane"),
    "tables/commands": strip(shapes.Command, "hub_id", "delivery"),
    "tables/context_snapshots": each(v(shapes.Context)),
    "tables/decisions": strip(shapes.Decision, "lane", "explanation", "explanation_source"),
    "tables/escalations": each(v(shapes.Escalation)),
    "tables/kitchens": each(at("config", shapes.KitchenConfig)),
    "tables/proposals": each(v(shapes.Proposal)),
    "tables/readings": each(v(shapes.Reading)),
}


def checker_for(rel: str) -> Optional[Check]:
    p = Path(rel)
    stem, top = p.stem, p.parts[0]
    if top == "shapes":
        table: dict[str, Any] = {
            "agent_log": shapes.AgentLog, "backtest_result": shapes.BacktestResult, "bill": shapes.Bill,
            "backtest_point": shapes.BacktestPoint, "backtest_inputs": shapes.BacktestInputs,
            "claude_authority": shapes.ClaudeAuthority, "context": shapes.Context, "decision": shapes.Decision,
            "equipment_catalog": list[shapes.EquipmentType], "lane_comparison": shapes.LaneComparison,
            "meter": shapes.Meter, "reading": shapes.Reading, "tariff": shapes.Tariff,
        }
        prefixes: list[tuple[str, Any]] = [
            ("command_ack", shapes.CommandAck), ("command", shapes.Command), ("device", shapes.Device),
            ("escalation", shapes.Escalation), ("hub_report", shapes.HubReport), ("kitchen_config", shapes.KitchenConfig),
            ("proposal", shapes.Proposal), ("tick_state", shapes.TickState), ("warm_up_history", shapes.WarmUpHistory),
            ("warning", shapes.WarningShape),
        ]
        if stem in table:
            return v(table[stem])
        for prefix, tp in prefixes:
            if stem.startswith(prefix):
                return v(tp)
        return None
    if top == "hub_protocol":
        if stem in ("hub_hello", "hub_report", "hub_to_server"):
            return v(hub.HubToServerMessage)
        return v(hub.ServerToHubMessage)
    if top == "ws":
        return v(ws.ViewerMessage)
    if top == "rest":
        return rest_check(rel)
    if top == "ai_tools":
        return TOOLS.get(stem)
    if top == "facade":
        if stem == "step_stream":
            return all_of(
                lambda o: _ta(shapes.HubReport).validate_python(o["args"]["hub_report"]), ret(shapes.TickState)
            )
        return FACADE.get(stem)
    if top == "spacetime":
        if stem == "rows_stream":
            return v(live.PublishTicksPayload)
        if p.parts[1] == "tables":
            return each(v(SPACETIME_TABLES[stem])) if stem in SPACETIME_TABLES else None
        return REDUCERS.get(stem)
    if top == "convex":
        return CONVEX.get(f"{p.parts[1]}/{stem}")
    if top == "agents":
        return {
            "agent_log": v(shapes.AgentLog),
            "context_post": at("body", shapes.PartialContext),
            "weather_response": at("hourly", list[shapes.HourlyTemp]),
            "price_response": at("hourly", list[shapes.HourlyPrice]),
            "events_response": at("items", list[shapes.EventItem]),
        }.get(stem)
    if top == "scenario":
        if stem == "scenario":
            return all_of(at("config", shapes.KitchenConfig), at("tariff", shapes.Tariff))
        return None
    if top == "history":
        return v(shapes.WarmUpHistory) if p.stem.startswith("warmup_") else None
    return None


def _short(exc: Exception, limit: int = 4) -> list[str]:
    if isinstance(exc, ValidationError):
        out = []
        for err in exc.errors()[:limit]:
            loc = ".".join(str(x) for x in err["loc"])
            out.append(f"{loc}: {err['msg']}")
        if exc.error_count() > limit:
            out.append(f"... {exc.error_count() - limit} more")
        return out
    return [f"{type(exc).__name__}: {exc}"]


def run(verbose: bool) -> int:
    results: dict[str, list[str]] = {"OK": [], "FAIL": [], "SKIP": []}
    details: dict[str, list[str]] = {}
    meta = {"MANIFEST.json", "README.md", "GAPS.md", "check.py", "generate.py"}
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or path.suffix not in (".json", ".jsonl"):
            continue
        rel = path.relative_to(ROOT).as_posix()
        if rel in meta:
            continue
        check = checker_for(rel)
        if check is None:
            results["SKIP"].append(rel)
            continue
        try:
            if path.suffix == ".jsonl":
                for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                    try:
                        check(json.loads(line))
                    except (ValidationError, ValueError, KeyError) as exc:
                        raise type(exc)(f"line {n}: {exc}") if not isinstance(exc, ValidationError) else exc
            else:
                check(json.loads(path.read_text(encoding="utf-8")))
            results["OK"].append(rel)
        except (ValidationError, ValueError, KeyError, TypeError) as exc:
            results["FAIL"].append(rel)
            details[rel] = _short(exc)
    for status in ("OK", "FAIL", "SKIP"):
        print(f"{status} ({len(results[status])})")
        for rel in results[status]:
            print(f"  {rel}")
            if verbose and rel in details:
                for line in details[rel]:
                    print(f"      {line}")
    return 1 if results["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(run("--verbose" in sys.argv[1:]))
