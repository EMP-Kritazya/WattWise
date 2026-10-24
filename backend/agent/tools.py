"""The AI tools of CONTRACTS.md §4: thin wrappers over the `with`-lane facade, the store and `agent/proposals.py`.

Every number a tool returns is the engine's (or a stored engine record), unchanged. Only two tools change state:
`choose_escalation_option` (an offered option id, validated by the engine against the owner's authority) and
`set_crowd_effect` (a category). Every `propose_*` tool only creates a pending Proposal; code applies it after an owner
confirmation. Inputs are checked here against the same schemas Claude sees (enums included), whatever the model sent.
"""

from __future__ import annotations

import copy
from typing import Any, Callable

from api.errors import NotFoundError, NotRecordedError

from .proposals import ProposalBook

CROWD_EFFECTS = ("none", "small", "medium", "large")
IMPORTANCES = ("always_on", "flexible", "deferrable")
PEAK_MODES = ("cap", "minimize")
COMMAND_ACTIONS = ("on", "off", "start", "delay", "reduce", "restore")
DECISION_EXTRAS = ("lane", "explanation", "explanation_source")
FORECAST_HORIZON_MIN = 120


class ToolInputError(ValueError):
    """The model's tool input does not match the tool's schema."""


def _obj(properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": properties, "required": required or list(properties),
            "additionalProperties": False}


_STR = {"type": "string"}
_SUMMARY = {"type": "string", "description": "One plain sentence for the owner, quoting only tool numbers."}

# name → (description, input_schema). The two bounded tools get their enums per call (see `schemas`).
_TOOLS: dict[str, tuple[str, dict]] = {
    "get_kitchen_state": ("The kitchen now: config, devices, meter (kW, kWh, $), context, recent decisions, open escalations.",
                          _obj({})),
    "get_forecast": ("Forecast kW for the next 2 hours, one value per 15 minutes.", _obj({})),
    "explain_decision": ("The facts of one engine decision: what changed, reason_code and its engine-computed effect.",
                         _obj({"decision_id": _STR})),
    "what_if": ("Engine projection of one device move (no change is made): peak before/after and saving.",
                _obj({"device_id": _STR, "action": {"type": "string", "enum": list(COMMAND_ACTIONS)},
                      "value": {"type": ["number", "null"], "description": "Minutes for delay, percent for reduce."},
                      "at": {"type": "string", "description": "Sim time, ISO 8601 UTC."}})),
    "get_bill": ("The engine's bill for a month (energy, demand charges, total).",
                 _obj({"period": {"type": "string", "description": "YYYY-MM"}})),
    "get_context": ("Live context the agents posted: weather, grid prices, events, crowd effect.", _obj({})),
    "get_escalation": ("Open escalations with every option's engine-computed numbers.", _obj({})),
    "propose_importance_change": (
        "Propose a device importance + limits change. Applies only after the owner confirms.",
        _obj({"device_id": _STR, "importance": {"type": "string", "enum": list(IMPORTANCES)},
              "limits": {"type": "object"}, "summary": _SUMMARY})),
    "propose_peak_cap_change": (
        "Propose a new peak mode / cap. Applies only after the owner confirms.",
        _obj({"peak_mode": {"type": "string", "enum": list(PEAK_MODES)},
              "peak_cap_kw": {"type": ["number", "null"], "description": "Required for cap, null for minimize."},
              "summary": _SUMMARY})),
    "propose_escalation_choice": (
        "Propose an option of an open escalation the owner asked for. Applies only after the owner confirms.",
        _obj({"escalation_id": _STR, "option_id": _STR, "summary": _SUMMARY})),
    "propose_undo": ("Propose undoing one engine decision. Applies only after the owner confirms.",
                     _obj({"decision_id": _STR, "summary": _SUMMARY})),
    "propose_customer_event": (
        "Propose a customer surge (e.g. a party) at a sim time. Applies only after the owner confirms.",
        _obj({"customers": {"type": "integer"}, "duration_min": {"type": "integer"},
              "start_sim_ts": {"type": "string", "description": "Sim time, ISO 8601 UTC."}, "summary": _SUMMARY})),
    "set_crowd_effect": (
        "Set the crowd effect category from the context (events, weather). A category, never a number.",
        _obj({"value": {"type": "string", "enum": list(CROWD_EFFECTS)}, "reason": _STR})),
    "choose_escalation_option": (
        "Resolve the escalation you were given with one of its offered options, and say why in one sentence "
        "quoting the option's numbers. Code checks it against the owner's authority.",
        _obj({"option_id": {"type": "string"}, "rationale": _STR})),
}
READ_TOOLS = ("get_kitchen_state", "get_forecast", "explain_decision", "what_if", "get_bill", "get_context",
              "get_escalation")
PROPOSE_TOOLS = ("propose_importance_change", "propose_peak_cap_change", "propose_escalation_choice", "propose_undo",
                 "propose_customer_event")
CHAT_TOOLS = (*READ_TOOLS, *PROPOSE_TOOLS, "set_crowd_effect")
ESCALATION_TOOLS = (*READ_TOOLS, "choose_escalation_option")

_TYPES: dict[str, Callable[[Any], bool]] = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "object": lambda v: isinstance(v, dict),
    "null": lambda v: v is None,
}


def validate(schema: dict, value: Any) -> None:
    """The subset of JSON Schema the tool schemas use: object properties, required, no extras, type, enum."""
    if not isinstance(value, dict):
        raise ToolInputError("input must be an object")
    props = schema["properties"]
    missing = [k for k in schema.get("required", []) if k not in value]
    extra = [k for k in value if k not in props]
    if missing or extra:
        raise ToolInputError(f"missing {missing}, unexpected {extra}")
    for key, item in value.items():
        spec = props[key]
        types = spec.get("type")
        types = [types] if isinstance(types, str) else (types or [])
        if types and not any(_TYPES[t](item) for t in types):
            raise ToolInputError(f"{key}: expected {' or '.join(types)}")
        if "enum" in spec and item not in spec["enum"]:
            raise ToolInputError(f"{key}: {item!r} is not one of {spec['enum']}")


class AgentTools:
    def __init__(self, service: Any, proposals: ProposalBook, set_crowd_effect: Callable[[dict], dict]):
        self._service = service  # api.service.KitchenService (lanes, store, lock)
        self._proposals = proposals
        self._set_crowd_effect = set_crowd_effect  # RunLoop.set_crowd_effect: the POST /api/context/crowd-effect path

    # ------------------------------------------------------------ schemas + dispatch

    @staticmethod
    def schemas(names: tuple[str, ...] = CHAT_TOOLS, escalation: dict | None = None) -> list[dict]:
        """Anthropic tool definitions. `choose_escalation_option` is offered only with an escalation, its `option_id`
        enum = that escalation's offered ids."""
        out = []
        for name in names:
            description, schema = _TOOLS[name]
            schema = copy.deepcopy(schema)
            if name == "choose_escalation_option":
                if escalation is None:
                    continue
                schema["properties"]["option_id"]["enum"] = [o["option_id"] for o in escalation["options"]]
            out.append({"name": name, "description": description, "input_schema": schema,
                        "eager_input_streaming": True})
        return out

    def call(self, name: str, tool_input: dict, *, allowed: tuple[str, ...] = CHAT_TOOLS,
             escalation: dict | None = None) -> Any:
        """Validate `tool_input` against the schema offered for this call, then run the tool."""
        schema = next((t["input_schema"] for t in self.schemas(allowed, escalation) if t["name"] == name), None)
        if schema is None:
            raise ToolInputError(f"tool {name!r} is not available here")
        validate(schema, tool_input)
        if name == "choose_escalation_option":
            return self.choose_escalation_option(escalation["escalation_id"], **tool_input)
        return getattr(self, name)(**tool_input)

    # ------------------------------------------------------------ helpers

    def _kitchen(self) -> Any:
        self._service.require_kitchen()
        return self._service.lanes["with"]

    def _snapshot(self) -> dict:
        with self._service.lock:
            return self._kitchen().snapshot()

    # ------------------------------------------------------------ read tools

    def get_kitchen_state(self) -> dict:
        return self._snapshot()

    def get_forecast(self) -> list[float]:
        with self._service.lock:
            return self._kitchen().forecast(FORECAST_HORIZON_MIN)

    def explain_decision(self, decision_id: str) -> dict:
        """The Decision itself (facts; the AI writes the sentence): the snapshot's recent decisions, else the store."""
        decision = next((d for d in self._snapshot()["recent_decisions"] if d["decision_id"] == decision_id), None)
        if decision is None:
            stored = next((d for d in self._service.store.decisions() if d["decision_id"] == decision_id), None)
            if stored is None:
                raise NotFoundError("decision", decision_id)
            decision = {k: v for k, v in stored.items() if k not in DECISION_EXTRAS}
        return decision

    def what_if(self, device_id: str, action: str, value: float | None, at: str) -> dict:
        with self._service.lock:
            return self._kitchen().what_if(device_id, action, value, at)

    def get_bill(self, period: str) -> dict:
        """A stored engine Bill for the period (`with` lane first), else the `with` policy of a stored BacktestResult,
        else the live Meter when the period is the current month. Never computed here."""
        store = self._service.store
        bills = sorted((b for b in store.bills() if b["period"] == period), key=lambda b: b["lane"] != "with")
        if bills:
            return {k: v for k, v in bills[0].items() if k != "lane"}
        for run_id in reversed(store.backtest_run_ids()):
            for result in store.backtest(run_id) or []:
                if result["month"] == period:
                    return result["policies"]["with"]
        meter = self._snapshot()["meter"]
        if meter["ts"][:7] == period:
            return meter
        raise NotRecordedError(f"No bill recorded for {period}")

    def get_context(self) -> dict:
        return self._snapshot()["context"]

    def get_escalation(self) -> list[dict]:
        with self._service.lock:
            return self._kitchen().open_escalations()

    # ------------------------------------------------------------ proposals (applied only after owner confirmation)

    def _require_device(self, device_id: str) -> None:
        if device_id not in {d["device_id"] for d in self._snapshot()["devices"]}:
            raise NotFoundError("device", device_id)

    def propose_importance_change(self, device_id: str, importance: str, limits: dict, summary: str) -> dict:
        self._require_device(device_id)
        return self._proposals.create("importance", {"device_id": device_id, "importance": importance,
                                                     "limits": limits}, summary)

    def propose_peak_cap_change(self, peak_mode: str, peak_cap_kw: float | None, summary: str) -> dict:
        return self._proposals.create("peak_cap", {"peak_mode": peak_mode, "peak_cap_kw": peak_cap_kw}, summary)

    def propose_escalation_choice(self, escalation_id: str, option_id: str, summary: str) -> dict:
        return self._proposals.create("resolve_escalation", {"escalation_id": escalation_id, "option_id": option_id},
                                      summary)

    def propose_undo(self, decision_id: str, summary: str) -> dict:
        self.explain_decision(decision_id)  # NotFoundError for an unknown decision
        return self._proposals.create("undo_decision", {"decision_id": decision_id}, summary)

    def propose_customer_event(self, customers: int, duration_min: int, start_sim_ts: str, summary: str) -> dict:
        payload = {"customers": customers, "duration_min": duration_min, "start_sim_ts": start_sim_ts}
        return self._proposals.create("customer_event", payload, summary)

    # ------------------------------------------------------------ the two bounded tools

    def set_crowd_effect(self, value: str, reason: str) -> dict:
        if value not in CROWD_EFFECTS:
            raise ToolInputError(f"value: {value!r} is not one of {list(CROWD_EFFECTS)}")
        return self._set_crowd_effect({"value": value, "reason": reason})

    def choose_escalation_option(self, escalation_id: str, option_id: str, rationale: str) -> dict:
        """`resolve_escalation(..., "claude", rationale)`. Outside the owner's authority the engine answers
        `awaiting_owner`, and Claude's pick becomes a Proposal the owner confirms (or picks another option)."""
        escalation = self._service.resolve_escalation(escalation_id, {"option_id": option_id}, resolved_by="claude",
                                                      rationale=rationale)
        if escalation["status"] == "awaiting_owner":
            option = next(o for o in escalation["options"] if o["option_id"] == option_id)
            self._proposals.create("resolve_escalation", {"escalation_id": escalation_id, "option_id": option_id},
                                   f"{option['summary']} (Claude's pick, outside its authority)")
        return escalation
