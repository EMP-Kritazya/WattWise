#!/usr/bin/env python3
"""Validates every WattWise fixture against CONTRACTS.md (prose; backend/contracts/ does not exist yet).

Usage: python3 contracts/fixtures/check.py        exits non-zero on any failure.
Checks: exact field sets + enums per shape, sums/averages (tol 0.01), tick ordering, the n -> n + 1 command rule,
hard rules (always_on, min power, food-safety floor, deadlines), escalation/authority logic, cross-references,
SpacetimeDB rows = TickState values re-keyed, and determinism (regenerates into a temp dir and compares bytes).
"""
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
TOL = 0.01
FAIL = []
COUNT = {"files": 0, "objects": 0}


def fail(where, msg):
    FAIL.append("%s: %s" % (where, msg))


# ----------------------------------------------------------------------------- schema DSL
TS_RE = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d{3})?Z$")
HM_RE = re.compile(r"^\d\d:\d\d$")
NUM, INT, STR, BOOL, TS, HM, ANY, DICT = "num", "int", "str", "bool", "ts", "hm", "any", "dict"


def E(*vals):
    return ("enum", vals)


def L(spec):
    return ("list", spec)


def Nl(spec):
    return ("null", spec)


def O(fields, optional=()):
    return ("obj", fields, set(optional))


def R(name):
    return ("ref", name)


IMPORTANCE = E("always_on", "flexible", "deferrable")
ACTION = E("on", "off", "start", "delay", "reduce", "restore")
LANE = E("without", "with")
AGENT = E("concierge", "weather", "grid", "events", "claude", "engine")
PARAMS_BY_MODEL = {"fixed": set(), "cycling": {"duty_idle_pct", "duty_busy_pct"}, "thermal": {"setpoint_c"},
                   "demand_driven": {"idle_kw", "kw_per_order"}, "job": {"cycle_min"}}
PROPOSAL_PAYLOAD = {"importance": {"device_id", "importance", "limits"}, "peak_cap": {"peak_mode", "peak_cap_kw"},
                    "undo_decision": {"decision_id"}, "customer_event": {"customers", "duration_min", "start_sim_ts"},
                    "resolve_escalation": {"escalation_id", "option_id"},
                    "authority": {"enabled", "max_cap_overrun_kw", "max_extra_delay_min", "max_extra_reduce_min",
                                  "may_go_below_min_power"}}
PHYSICAL_KEYS = {"indoor_temp_c", "box_temp_c", "dirty_racks", "ice_level_pct", "job_remaining_min", "orders_in_progress"}

SHAPES = {
    "EquipmentType": O({"type_id": STR, "name": STR,
                        "category": E("cooling", "refrigeration", "cooking", "water_heating", "lighting", "other"),
                        "default_importance": IMPORTANCE, "rated_kw": NUM,
                        "power_model": E("fixed", "cycling", "thermal", "demand_driven", "job"), "params": DICT,
                        "default_limits": R("ImportanceLimits"), "source_note": STR}),
    "Tariff": O({"tariff_id": STR, "name": STR, "label": E("illustrative", "urdb"), "currency": STR, "timezone": STR,
                 "energy": L(O({"name": STR, "start": HM, "end": HM, "usd_per_kwh": NUM})),
                 "demand": L(O({"name": STR, "window": Nl(O({"start": HM, "end": HM})), "usd_per_kw": NUM}))}),
    "ClaudeAuthority": O({"enabled": BOOL, "max_cap_overrun_kw": NUM, "max_extra_delay_min": NUM,
                          "max_extra_reduce_min": NUM, "may_go_below_min_power": BOOL}),
    "KitchenConfig": O({"name": STR,
                        "equipment": L(O({"type_id": STR, "count": INT, "importance": IMPORTANCE,
                                          "limits": R("ImportanceLimits")})),
                        "peak_mode": E("minimize", "cap"), "peak_cap_kw": Nl(NUM), "operating_hours": O({"open": HM, "close": HM}),
                        "location": O({"lat": NUM, "lon": NUM, "label": STR}), "owner_preferences": STR,
                        "authority": R("ClaudeAuthority"), "tariff_id": STR, "seed": INT}),
    "Device": O({"device_id": STR, "type_id": STR, "name": STR, "importance": IMPORTANCE,
                 "state": E("off", "on", "reduced", "waiting", "running_job"), "power_kw": NUM, "rated_kw": NUM,
                 "power_pct": INT, "source": E("simulated", "measured"), "physical": DICT}, optional=("physical",)),
    "HubReport": O({"hub_id": STR, "lane": LANE, "tick_id": INT, "ts": TS, "total_kw": NUM, "customers_per_hour": INT,
                    "devices": L(R("Device")), "acks": L(R("CommandAck")), "source": E("simulated", "mixed")}),
    "Reading": O({"hub_id": STR, "channel": INT, "device_id": STR, "ts": TS, "raw_w": NUM, "scale": NUM, "power_kw": NUM}),
    "Command": O({"command_id": STR, "lane": LANE, "ts": TS, "device_id": STR, "action": ACTION, "value": Nl(NUM),
                  "decision_id": Nl(STR), "issued_by": E("engine", "owner")}),
    "CommandAck": O({"command_id": STR, "lane": LANE, "ok": BOOL, "applied_value": Nl(NUM),
                     "reason": Nl(E("job_running", "already_off", "out_of_range", "unknown_device"))}),
    "Effect": O({"peak_before_kw": NUM, "peak_after_kw": NUM, "saving_usd": NUM}),
    "Decision": O({"decision_id": STR, "ts": TS, "device_id": STR, "action": ACTION, "value": Nl(NUM),
                   "reason_code": E("avoid_new_peak", "stay_under_cap", "release_into_valley", "catch_up",
                                    "owner_override", "escalation_choice"),
                   "inside_rules": BOOL, "status": E("executed", "undone"), "effect": R("Effect")}),
    "Context": O({"ts": TS,
                  "weather": O({"label": E("live_api", "recorded"), "source": STR,
                                "hourly": L(O({"ts": TS, "temp_c": NUM}))}),
                  "prices": O({"label": E("live_api", "recorded"), "source": STR,
                               "hourly": L(O({"ts": TS, "usd_per_kwh": NUM})), "stress": E("low", "normal", "high")}),
                  "events": O({"label": E("live_api", "recorded"), "source": STR,
                               "items": L(O({"name": STR, "venue": STR, "start": TS, "distance_km": NUM,
                                             "expected_attendance": INT}))}),
                  "crowd_effect": O({"value": E("none", "small", "medium", "large"), "set_by": E("claude", "owner", "default"),
                                     "reason": STR})}),
    "RuleBreak": O({"kind": E("cap_overrun", "below_min_power", "past_deadline", "over_max_reduce", "over_max_delay"), "device_id": STR, "amount": NUM, "unit": STR}, optional=("device_id",)),
    "EscalationOption": O({"option_id": STR, "summary": STR, "actions": L(R("Command")),
                           "projected": Nl(O({"peak_kw": NUM, "cost_delta_usd": NUM, "max_indoor_temp_change_c": NUM})),
                           "rule_breaks": L(R("RuleBreak")), "within_authority": BOOL}),
    "Escalation": O({"escalation_id": STR, "lane": LANE, "ts": TS, "block_start": TS,
                     "problem": O({"forecast_peak_kw": NUM, "target_kw": NUM, "excess_kw": NUM, "reason": STR}),
                     "options": L(R("EscalationOption")), "default_option_id": STR, "deadline_sim_ts": TS,
                     "status": E("open", "resolved", "awaiting_owner", "expired_default"),
                     "resolved_by": Nl(E("claude", "owner", "default")), "chosen_option_id": Nl(STR),
                     "rationale": Nl(STR)}),
    "Meter": O({"ts": TS, "total_kw": NUM, "block_avg_kw": NUM, "block_start": TS, "month_peak_kw": NUM,
                "peak_mode": E("minimize", "cap"), "peak_cap_kw": Nl(NUM), "target_kw": NUM, "energy_kwh_today": NUM, "price_usd_per_kwh_now": NUM, "cost_usd_today": NUM,
                "cost_usd_month": NUM}),
    "TickState": O({"lane": LANE, "ts": TS, "hub": R("HubReport"), "meter": R("Meter"), "customers_per_hour": INT,
                    "new_decisions": L(R("Decision")), "new_commands": L(R("Command")),
                    "new_escalations": L(R("Escalation")), "indoor_temp_c": Nl(NUM), "forecast_kw": Nl(L(NUM))}),
    "LaneComparison": O({"ts": TS, "saved_today_usd": NUM, "peak_avoided_kw": NUM, "month_peak_without_kw": NUM,
                         "month_peak_with_kw": NUM}),
    "Proposal": O({"proposal_id": STR, "ts": TS,
                   "kind": E("importance", "peak_cap", "authority", "undo_decision", "customer_event", "resolve_escalation"),
                   "payload": DICT, "summary": STR, "status": E("pending", "confirmed", "cancelled", "expired"),
                   "created_by": E("ai"), "confirmed_via": Nl(E("ui", "asi_one")), "expires_at": TS}),
    "Bill": O({"period": STR, "energy_kwh": NUM, "energy_cost_usd": NUM,
               "demand_charges": L(O({"name": STR, "peak_kw": NUM, "cost_usd": NUM})), "total_usd": NUM, "tariff_id": STR}),
    "BacktestResult": O({"dataset": STR, "month": STR,
                         "policies": O({"without": R("Bill"), "timer": R("Bill"), "with": R("Bill")}),
                         "checks": O({"baseline_matches_raw": BOOL, "energy_conserved": BOOL, "rule_violations": INT}),
                         "assumptions_id": STR}),
    "AgentLog": O({"ts_real": TS, "from_agent": AGENT, "to_agent": AGENT, "kind": E("request", "response", "post", "error"),
                   "summary": STR}),
    "Snapshot": O({"config": R("KitchenConfig"), "devices": L(R("Device")), "meter": R("Meter"), "context": R("Context"),
                   "recent_decisions": L(R("Decision")), "open_escalations": L(R("Escalation"))}),
    "Ok": O({"ok": BOOL}),
    "ClockState": O({"playing": BOOL, "speed": NUM, "sim_ts": TS, "tick_id": INT,
                     "paused_reason": Nl(E("escalation", "approval", "hub_waiting", "sim_host_offline")),
                     "slowed_reason": Nl(E("escalation"))}),
    "ErrorBody": O({"detail": STR}),
}
LIMITS_BY_IMP = {"always_on": O({}), "flexible": O({"min_power_pct": NUM, "max_reduce_min": NUM}),
                 "deferrable": O({"max_delay_min": NUM, "must_finish_by": HM})}

# ws messages (section 2)
PAUSED = Nl(E("escalation", "approval", "hub_waiting", "sim_host_offline"))
SLOWED = Nl(E("escalation"))
WS = {
    "tick": O({"type": STR, "data": R("TickState")}),
    "decision": O({"type": STR, "data": R("Decision"), "explanation": STR, "explanation_source": E("ai", "template")}),
    "clock": O({"type": STR, "playing": BOOL, "speed": NUM, "sim_ts": TS, "tick_id": INT, "paused_reason": PAUSED,
               "slowed_reason": SLOWED}),
    "warning": O({"type": STR, "code": E("cap_unreachable", "sim_host_offline", "hub_offline", "live_transport_down",
                                         "store_down"), "message": STR, "data": DICT}),
    "chat_delta": O({"type": STR, "chat_id": STR, "text": STR}),
    "chat_done": O({"type": STR, "chat_id": STR}),
    "backtest_progress": O({"type": STR, "run_id": STR, "month": STR, "pct": NUM}),
    "comparison": O({"type": STR, "data": R("LaneComparison")}),
    "proposal": O({"type": STR, "data": R("Proposal")}),
    "escalation": O({"type": STR, "data": R("Escalation")}),
    "context": O({"type": STR, "data": R("Context")}),
    "agent_log": O({"type": STR, "data": R("AgentLog")}),
}
# hub protocol (section 8)
HUB = {
    "hub_hello": O({"type": STR, "protocol": INT, "hub_id": STR, "role": E("sim_host"), "client": STR}),
    "hub_report": O({"type": STR, "tick_id": INT, "reports": O({"without": R("HubReport"), "with": R("HubReport")})}),
    "hub_welcome": O({"type": STR, "accepted": BOOL, "reason": Nl(E("host_taken")), "tick_id": INT}),
    "sim_build": O({"type": STR, "kitchen_id": STR, "config": R("KitchenConfig"), "catalog": L(R("EquipmentType")),
                    "devices": L(R("Device")), "seed": INT, "start_sim_ts": TS}),
    "sim_tick": O({"type": STR, "tick_id": INT, "sim_ts": TS, "minutes": INT,
                   "surges": L(O({"surge_id": STR, "customers": INT, "duration_min": INT})),
                   "inputs": O({"outdoor_temp_c": NUM, "crowd_multiplier": NUM, "is_open": BOOL}),
                   "commands": L(R("Command")), "replay": BOOL}),
    "sim_control": O({"type": STR, "action": E("play", "pause", "reset"), "speed": NUM, "paused_reason": PAUSED}),
}
# SpacetimeDB rows (section 5)
ST = {
    "live_tick": O({"lane": LANE, "ts": TS, "tick_id": INT, "total_kw": NUM, "block_avg_kw": NUM, "month_peak_kw": NUM,
                    "peak_mode": E("minimize", "cap"), "peak_cap_kw": Nl(NUM), "target_kw": NUM, "energy_kwh_today": NUM, "price_usd_per_kwh_now": NUM, "cost_usd_today": NUM,
                    "cost_usd_month": NUM, "customers_per_hour": INT, "indoor_temp_c": Nl(NUM),
                    "forecast_kw_json": Nl(STR), "forecast_ts": Nl(TS)}),
    "tick_history": O({"lane": LANE, "ts": TS, "total_kw": NUM, "block_avg_kw": NUM}),
    "live_device": O({"key": STR, "lane": LANE, "device_id": STR, "type_id": STR, "name": STR, "importance": IMPORTANCE,
                      "state": E("off", "on", "reduced", "waiting", "running_job"), "power_kw": NUM, "rated_kw": NUM,
                      "power_pct": INT, "source": E("simulated", "measured"), "physical_json": Nl(STR)}),
    "live_comparison": O({"id": INT, "ts": TS, "saved_today_usd": NUM, "peak_avoided_kw": NUM,
                          "month_peak_without_kw": NUM, "month_peak_with_kw": NUM}),
    "live_feed": O({"decision_id": STR, "lane": LANE, "ts": TS, "device_id": STR, "action": ACTION, "value": Nl(NUM),
                    "status": E("executed", "escalated", "undone"), "reason_code": STR, "effect_json": STR,
                    "explanation": STR, "explanation_source": E("ai", "template")}),
    "live_clock": O({"id": INT, "playing": BOOL, "speed": NUM, "sim_ts": TS, "tick_id": INT, "paused_reason": PAUSED,
                     "slowed_reason": SLOWED, "sim_host": E("connected", "offline")}),
    "live_context": O({"id": INT, "weather_summary": STR, "weather_label": STR, "prices_summary": STR, "prices_label": STR,
                       "events_summary": STR, "events_label": STR, "crowd_effect": E("none", "small", "medium", "large")}),
    "live_escalation": O({"escalation_id": STR, "lane": LANE, "status": E("open", "resolved", "awaiting_owner",
                                                                           "expired_default"),
                          "problem_json": STR, "options_json": STR, "chosen_option_id": Nl(STR),
                          "resolved_by": Nl(E("claude", "owner", "default")), "rationale": Nl(STR)}),
    "live_agent_log": O({"id": INT, "ts_real": TS, "from_agent": STR, "to_agent": STR, "kind": STR, "summary": STR}),
    "surge_request": O({"id": INT, "customers": INT, "duration_min": INT, "requested_by": STR, "created_at": TS,
                        "consumed": BOOL}),
}


def with_extra(shape, extra):
    base = SHAPES[shape]
    f = dict(base[1])
    f.update(extra)
    return O(f, base[2])


CONVEX = {
    "kitchens": O({"config": R("KitchenConfig"), "created_at": TS}),
    "decisions": with_extra("Decision", {"lane": LANE, "explanation": STR, "explanation_source": E("ai", "template")}),
    "commands": with_extra("Command", {"hub_id": Nl(STR), "delivery": E("queued", "sent", "acked", "failed")}),
    "readings": R("Reading"),
    "device_map": O({"hub_id": STR, "channel": INT, "device_id": STR, "scale": NUM}),
    "hubs": O({"hub_id": STR, "last_seen": TS, "firmware": STR}),
    "proposals": R("Proposal"),
    "bills": with_extra("Bill", {"lane": LANE}),
    "backtest_results": with_extra("BacktestResult", {"run_id": STR}),
    "device_blocks": O({"lane": LANE, "device_id": STR, "block_start": TS, "avg_kw": NUM,
                        "source": E("simulated", "measured")}),
    "escalations": R("Escalation"),
    "context_snapshots": R("Context"),
}
AGENT_MSG = {
    "weather_request": O({"lat": NUM, "lon": NUM, "hours": INT}),
    "weather_response": O({"hourly": L(O({"ts": TS, "temp_c": NUM})), "source": STR, "label": E("live_api", "recorded")}),
    "price_request": O({"region": STR, "hours": INT}),
    "price_response": O({"hourly": L(O({"ts": TS, "usd_per_kwh": NUM})), "stress": E("low", "normal", "high"),
                         "source": STR, "label": E("live_api", "recorded")}),
    "events_request": O({"lat": NUM, "lon": NUM, "radius_km": NUM, "window_h": NUM}),
    "events_response": O({"items": SHAPES["Context"][1]["events"][1]["items"], "source": STR,
                          "label": E("live_api", "recorded")}),
}


def validate(v, spec, where):
    COUNT["objects"] += 1
    if isinstance(spec, str):
        ok = {"num": lambda x: isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x),
              "int": lambda x: isinstance(x, int) and not isinstance(x, bool),
              "str": lambda x: isinstance(x, str), "bool": lambda x: isinstance(x, bool),
              "ts": lambda x: isinstance(x, str) and bool(TS_RE.match(x)),
              "hm": lambda x: isinstance(x, str) and bool(HM_RE.match(x)),
              "dict": lambda x: isinstance(x, dict), "any": lambda x: True}[spec](v)
        if not ok:
            fail(where, "expected %s, got %r" % (spec, v if not isinstance(v, (dict, list)) else type(v).__name__))
        return
    kind = spec[0]
    if kind == "ref":
        name = spec[1]
        if name == "ImportanceLimits":
            if not isinstance(v, dict):
                return fail(where, "limits must be an object")
            # importance comes from context; accept the one whose key set matches exactly
            for imp, s in LIMITS_BY_IMP.items():
                if set(v) == set(s[1]):
                    return validate(v, s, where)
            return fail(where, "limits %r match no importance" % (v,))
        return validate(v, SHAPES[name], where)
    if kind == "enum":
        if v not in spec[1]:
            fail(where, "%r not in %s" % (v, list(spec[1])))
        return
    if kind == "null":
        if v is not None:
            validate(v, spec[1], where)
        return
    if kind == "list":
        if not isinstance(v, list):
            return fail(where, "expected list")
        for i, x in enumerate(v):
            validate(x, spec[1], "%s[%d]" % (where, i))
        return
    if kind == "obj":
        if not isinstance(v, dict):
            return fail(where, "expected object")
        fields, optional = spec[1], spec[2]
        extra = set(v) - set(fields)
        missing = set(fields) - set(v) - optional
        if extra:
            fail(where, "extra fields %s" % sorted(extra))
        if missing:
            fail(where, "missing fields %s" % sorted(missing))
        for k, s in fields.items():
            if k in v:
                validate(v[k], s, "%s.%s" % (where, k))
        return
    raise ValueError(spec)


# ----------------------------------------------------------------------------- loading
def load(rel):
    COUNT["files"] += 1
    p = os.path.join(HERE, rel)
    with open(p, encoding="utf-8") as f:
        if rel.endswith(".jsonl"):
            return [json.loads(line) for line in f if line.strip()]
        return json.load(f)


def files_under(folder):
    out = []
    for root, _, fs in os.walk(os.path.join(HERE, folder)):
        for f in fs:
            out.append(os.path.relpath(os.path.join(root, f), HERE))
    return sorted(out)


def parse_ts(s):
    return datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)


def near(a, b, tol=TOL):
    return abs(a - b) <= tol + 1e-9


def hm_min(hm):
    h, m = hm.split(":")
    return int(h) * 60 + int(m)


def tariff_price(tariff, dt_utc):
    local = dt_utc - timedelta(hours=7)          # America/Los_Angeles in July (PDT)
    lm = local.hour * 60 + local.minute
    for e in tariff["energy"]:
        if hm_min(e["start"]) <= lm < hm_min(e["end"]):
            return e["usd_per_kwh"]
    return None


def half_up(x):
    return int(math.floor(x + 0.5))


# ----------------------------------------------------------------------------- per-file shape validation
SHAPE_FILES = {
    "equipment_catalog.json": L(R("EquipmentType")), "kitchen_config.json": R("KitchenConfig"),
    "kitchen_config_minimize.json": R("KitchenConfig"),
    "claude_authority.json": R("ClaudeAuthority"), "device.json": R("Device"), "device_measured.json": R("Device"),
    "hub_report_with.json": R("HubReport"), "hub_report_without.json": R("HubReport"), "reading.json": R("Reading"),
    "command.json": R("Command"), "command_ack_ok.json": R("CommandAck"), "command_ack_clamped.json": R("CommandAck"),
    "command_ack_rejected.json": R("CommandAck"), "command_owner.json": R("Command"), "tariff.json": R("Tariff"),
    "proposal_peak_cap.json": R("Proposal"), "proposal_authority.json": R("Proposal"),
    "proposal_undo_decision.json": R("Proposal"), "proposal_customer_event.json": R("Proposal"),
    "proposal_resolve_escalation.json": R("Proposal"),
    "decision.json": R("Decision"), "context.json": R("Context"), "escalation_open.json": R("Escalation"),
    "escalation_resolved_claude.json": R("Escalation"), "escalation_awaiting_owner.json": R("Escalation"),
    "escalation_expired_default.json": R("Escalation"), "meter.json": R("Meter"), "tick_state_with.json": R("TickState"),
    "tick_state_without.json": R("TickState"), "lane_comparison.json": R("LaneComparison"),
    "proposal_pending.json": R("Proposal"), "proposal_confirmed.json": R("Proposal"), "bill.json": R("Bill"),
    "backtest_result.json": R("BacktestResult"), "agent_log.json": R("AgentLog"),
}
PARTIAL_CONTEXT = ("partial", "Context")


def validate_partial_context(v, where):
    full = SHAPES["Context"][1]
    if not isinstance(v, dict) or "ts" not in v:
        return fail(where, "partial Context needs ts")
    for k in v:
        if k not in full:
            fail(where, "extra field %s" % k)
        else:
            validate(v[k], full[k], "%s.%s" % (where, k))


REST_SPECS = {   # file -> (method, path regex, request spec, response spec)
    "get_catalog": ("GET", r"^/api/catalog$", None, L(R("EquipmentType"))),
    "post_kitchen": ("POST", r"^/api/kitchen$", R("KitchenConfig"), O({"kitchen_id": STR})),
    "post_kitchen_422": ("POST", r"^/api/kitchen$", R("KitchenConfig"), R("ErrorBody")),
    "get_kitchen": ("GET", r"^/api/kitchen$", None, O({"config": R("KitchenConfig"), "devices": L(R("Device")),
                                                        "tariff": R("Tariff")})),
    "put_device_importance": ("PUT", r"^/api/kitchen/devices/[a-z_]+_\d+/importance$",
                              O({"importance": IMPORTANCE, "limits": R("ImportanceLimits")}), R("Device")),
    "put_device_importance_422": ("PUT", r"^/api/kitchen/devices/[a-z_]+_\d+/importance$",
                                  O({"importance": IMPORTANCE, "limits": R("ImportanceLimits")}), R("ErrorBody")),
    "put_device_importance_404": ("PUT", r"^/api/kitchen/devices/[a-z_]+_\d+/importance$",
                                  O({"importance": IMPORTANCE, "limits": R("ImportanceLimits")}), R("ErrorBody")),
    "put_peak_cap": ("PUT", r"^/api/kitchen/peak-cap$", O({"peak_mode": E("minimize", "cap"), "peak_cap_kw": Nl(NUM)}),
                     R("Meter")),
    "put_peak_cap_422": ("PUT", r"^/api/kitchen/peak-cap$", O({"peak_mode": E("minimize", "cap"),
                                                                "peak_cap_kw": Nl(NUM)}), R("ErrorBody")),
    "post_sim_control": ("POST", r"^/api/sim/control$", O({"action": E("play", "pause", "reset"), "speed": NUM},
                                                          optional=("speed",)), R("ClockState")),
    "post_device_command": ("POST", r"^/api/devices/[a-z_]+_\d+/command$", O({"action": ACTION, "value": NUM},
                                                                              optional=("value",)), R("Command")),
    "post_device_command_404": ("POST", r"^/api/devices/[a-z_]+_\d+/command$", O({"action": ACTION, "value": NUM},
                                                                                  optional=("value",)), R("ErrorBody")),
    "post_events_customers": ("POST", r"^/api/events/customers$", O({"customers": INT, "duration_min": INT}), R("Ok")),
    "post_decision_undo": ("POST", r"^/api/decisions/d_\d{4}/undo$", None, R("Decision")),
    "post_decision_undo_404": ("POST", r"^/api/decisions/d_\d{4}/undo$", None, R("ErrorBody")),
    "get_decisions": ("GET", r"^/api/decisions\?limit=\d+$", None, L(R("Decision"))),
    "post_backtest_run": ("POST", r"^/api/backtest/run$", O({"months": L(STR), "assumptions_id": STR}),
                          O({"run_id": STR})),
    "get_backtest": ("GET", r"^/api/backtest/[a-z0-9_]+$", None, L(R("BacktestResult"))),
    "post_chat": ("POST", r"^/api/chat$", O({"message": STR}), O({"chat_id": STR})),
    "get_proposals": ("GET", r"^/api/proposals\?status=pending$", None, L(R("Proposal"))),
    "post_proposal_confirm": ("POST", r"^/api/proposals/p_\d{4}/confirm$", O({"confirm": BOOL}), R("Proposal")),
    "put_authority": ("PUT", r"^/api/kitchen/authority$", R("ClaudeAuthority"), R("Ok")),
    "put_preferences": ("PUT", r"^/api/kitchen/preferences$", O({"text": STR}), R("Ok")),
    "get_context": ("GET", r"^/api/context$", None, R("Context")),
    "post_context": ("POST", r"^/api/context$", PARTIAL_CONTEXT, R("Ok")),
    "post_context_crowd_effect": ("POST", r"^/api/context/crowd-effect$",
                                  O({"value": E("none", "small", "medium", "large"), "reason": STR}), R("Ok")),
    "get_escalations": ("GET", r"^/api/escalations\?status=open$", None, L(R("Escalation"))),
    "post_escalation_resolve": ("POST", r"^/api/escalations/e_\d{4}/resolve$", O({"option_id": STR}), R("Escalation")),
    "post_agent_log": ("POST", r"^/api/agent-log$", R("AgentLog"), R("Ok")),
    "get_health": ("GET", r"^/api/health$", None,
                   O({"ok": BOOL, "kitchen_impl": E("fake", "real"), "live_transport": E("spacetime", "ws"),
                      "store": E("convex", "memory"), "hardware": E("off", "sim_bridge", "esp32"),
                      "sim_host": E("connected", "offline")})),
}

FACADE_SPECS = {   # file -> (call, args spec, returns spec)
    "kitchen.json": ("Kitchen", O({"config": R("KitchenConfig"), "tariff": R("Tariff"), "control": LANE, "seed": INT}), None),
    "warm_up.json": ("warm_up", O({}), None),
    "ingest_reading.json": ("ingest_reading", O({"reading": R("Reading")}), R("Device")),
    "owner_command.json": ("owner_command", O({"device_id": STR, "action": ACTION, "value": Nl(NUM)}), R("Command")),
    "set_importance.json": ("set_importance", O({"device_id": STR, "importance": IMPORTANCE,
                                                 "limits": R("ImportanceLimits")}), R("Device")),
    "set_importance_rule_error.json": ("set_importance", O({"device_id": STR, "importance": IMPORTANCE,
                                                            "limits": R("ImportanceLimits")}), None),
    "set_peak_cap.json": ("set_peak_cap", O({"peak_mode": E("minimize", "cap"), "peak_cap_kw": Nl(NUM)}), R("Meter")),
    "set_peak_cap_rule_error.json": ("set_peak_cap", O({"peak_mode": E("minimize", "cap"), "peak_cap_kw": Nl(NUM)}), None),
    "undo.json": ("undo", O({"decision_id": STR}), R("Decision")),
    "set_context.json": ("set_context", O({"context": R("Context")}), None),
    "set_authority.json": ("set_authority", O({"authority": R("ClaudeAuthority")}), None),
    "set_preferences.json": ("set_preferences", O({"text": STR}), None),
    "open_escalations.json": ("open_escalations", O({}), L(R("Escalation"))),
    "resolve_escalation.json": ("resolve_escalation", O({"escalation_id": STR, "option_id": STR,
                                                         "resolved_by": E("claude", "owner", "default"),
                                                         "rationale": Nl(STR)}), R("Escalation")),
    "forecast.json": ("forecast", O({"horizon_min": INT}), L(NUM)),
    "what_if.json": ("what_if", O({"device_id": STR, "action": ACTION, "value": Nl(NUM), "at": TS}), R("Effect")),
    "snapshot.json": ("snapshot", O({}), R("Snapshot")),
    "run_backtest.json": ("run_backtest", O({"months": L(STR), "assumptions_id": STR, "on_progress": Nl(ANY)}),
                          L(R("BacktestResult"))),
    "compare_lanes.json": ("compare_lanes", O({"without": R("TickState"), "with_": R("TickState")}), R("LaneComparison")),
}
AI_SPECS = {
    "get_kitchen_state.json": (O({}), R("Snapshot")),
    "get_forecast.json": (O({}), L(NUM)),
    "what_if.json": (O({"device_id": STR, "action": ACTION, "value": Nl(NUM), "at": TS}), R("Effect")),
    "get_bill.json": (O({"period": STR}), R("Bill")),
    "explain_decision.json": (O({"decision_id": STR}), R("Decision")),
    "propose_importance_change.json": (O({"device_id": STR, "importance": IMPORTANCE, "limits": R("ImportanceLimits"),
                                          "summary": STR}), R("Proposal")),
    "propose_peak_cap_change.json": (O({"peak_mode": E("minimize", "cap"), "peak_cap_kw": Nl(NUM), "summary": STR}),
                                     R("Proposal")),
    "propose_escalation_choice.json": (O({"escalation_id": STR, "option_id": STR, "summary": STR}), R("Proposal")),
    "propose_undo.json": (O({"decision_id": STR, "summary": STR}), R("Proposal")),
    "propose_customer_event.json": (O({"customers": INT, "duration_min": INT, "start_sim_ts": TS, "summary": STR}),
                                    R("Proposal")),
    "get_context.json": (O({}), R("Context")),
    "get_escalation.json": (O({}), L(R("Escalation"))),
    "choose_escalation_option.json": (O({"option_id": STR, "rationale": STR}), R("Escalation")),
    "set_crowd_effect.json": (O({"value": E("none", "small", "medium", "large"), "reason": STR}), R("Ok")),
}


def check_wrapper(obj, keys, where):
    if not isinstance(obj, dict) or set(obj) != set(keys):
        fail(where, "wrapper keys %s != %s" % (sorted(obj) if isinstance(obj, dict) else obj, sorted(keys)))
        return False
    return True


def shapes_pass(store):
    for f in files_under("shapes"):
        name = os.path.basename(f)
        if name not in SHAPE_FILES:
            fail(f, "no shape mapping")
            continue
        obj = load(f)
        store[f] = obj
        validate(obj, SHAPE_FILES[name], f)
    for name in SHAPE_FILES:
        if not os.path.exists(os.path.join(HERE, "shapes", name)):
            fail("shapes/" + name, "missing")


def hub_pass(store):
    for f in files_under("hub_protocol"):
        obj = load(f)
        store[f] = obj
        msgs = obj if f.endswith(".jsonl") else [obj]
        for i, m in enumerate(msgs):
            t = m.get("type") if isinstance(m, dict) else None
            if t not in HUB:
                fail("%s[%d]" % (f, i), "unknown hub message type %r" % t)
                continue
            validate(m, HUB[t], "%s[%d]" % (f, i))
            if m["type"] != t:
                fail(f, "type mismatch")
    if not load("hub_protocol/sim_tick_replay.json")["replay"] or load("hub_protocol/sim_tick.json")["replay"]:
        fail("hub_protocol", "sim_tick_replay.json must have replay true, sim_tick.json false")
    for t in ("hub_hello", "hub_welcome_accepted", "hub_welcome_host_taken", "sim_build", "sim_tick", "sim_tick_replay",
              "hub_report", "sim_control"):
        if not os.path.exists(os.path.join(HERE, "hub_protocol", t + ".json")):
            fail("hub_protocol/%s.json" % t, "missing")
    hw = load("hub_protocol/hub_welcome_host_taken.json")
    if hw["accepted"] or hw["reason"] != "host_taken":
        fail("hub_welcome_host_taken", "must be accepted false + host_taken")


def rest_pass(store):
    seen = set()
    for f in files_under("rest"):
        name = os.path.basename(f)[:-5]
        obj = load(f)
        store[f] = obj
        if name not in REST_SPECS:
            fail(f, "no REST spec")
            continue
        seen.add(name)
        if not check_wrapper(obj, ("method", "path", "status", "request", "response"), f):
            continue
        method, path_re, req, resp = REST_SPECS[name]
        if obj["method"] != method or not re.match(path_re, obj["path"]):
            fail(f, "method/path %s %s" % (obj["method"], obj["path"]))
        exp_status = 422 if name.endswith("_422") else 404 if name.endswith("_404") else 200
        if obj["status"] != exp_status:
            fail(f, "status %s != %s" % (obj["status"], exp_status))
        if req is None:
            if obj["request"] is not None:
                fail(f, "request must be null")
        elif req == PARTIAL_CONTEXT:
            validate_partial_context(obj["request"], f + ".request")
        else:
            validate(obj["request"], req, f + ".request")
        validate(obj["response"], resp, f + ".response")
    for n in REST_SPECS:
        if n not in seen:
            fail("rest/%s.json" % n, "missing")


def ws_pass(store):
    for f in files_under("ws"):
        obj = load(f)
        store[f] = obj
        msgs = obj if f.endswith(".jsonl") else [obj]
        for i, m in enumerate(msgs):
            t = m.get("type")
            if t not in WS:
                fail("%s[%d]" % (f, i), "unknown ws type %r" % t)
                continue
            validate(m, WS[t], "%s[%d]" % (f, i))
    for t in WS:
        if not os.path.exists(os.path.join(HERE, "ws", t + ".json")):
            fail("ws/%s.json" % t, "missing")


def facade_pass(store):
    for name, (call, args, ret) in FACADE_SPECS.items():
        f = "facade/" + name
        obj = load(f)
        store[f] = obj
        keys = ("call", "args", "returns", "raises") if name.endswith("rule_error.json") else ("call", "args", "returns")
        if not check_wrapper(obj, keys, f):
            continue
        if obj["call"] != call:
            fail(f, "call %s" % obj["call"])
        validate(obj["args"], args, f + ".args")
        if ret is None:
            if obj["returns"] is not None:
                fail(f, "returns must be null")
        else:
            validate(obj["returns"], ret, f + ".returns")
        if "raises" in obj and (obj["raises"].get("error") != "RuleError"):
            fail(f, "raises must be RuleError")
    rows = load("facade/step_stream.jsonl")
    store["facade/step_stream.jsonl"] = rows
    for i, r in enumerate(rows):
        if check_wrapper(r, ("args", "returns"), "step_stream[%d]" % i):
            validate(r["args"], O({"minutes": INT, "hub_report": R("HubReport")}), "step_stream[%d].args" % i)
            validate(r["returns"], R("TickState"), "step_stream[%d].returns" % i)
    for f in files_under("facade"):
        if os.path.basename(f) not in FACADE_SPECS and not f.endswith("step_stream.jsonl"):
            fail(f, "unexpected facade file")


def ai_pass(store):
    for name, (inp, out) in AI_SPECS.items():
        f = "ai_tools/" + name
        obj = load(f)
        store[f] = obj
        keys = ("tool", "input", "output", "input_enum") if "input_enum" in obj else ("tool", "input", "output")
        if not check_wrapper(obj, keys, f):
            continue
        if obj["tool"] != name[:-5]:
            fail(f, "tool name")
        validate(obj["input"], inp, f + ".input")
        validate(obj["output"], out, f + ".output")
        if name.startswith("propose_"):
            p = obj["output"]
            if dict(p["payload"], summary=p["summary"]) != obj["input"] or p["status"] != "pending":
                fail(f, "Proposal payload must be the tool input without summary")
        for k, allowed in obj.get("input_enum", {}).items():
            if obj["input"][k] not in allowed:
                fail(f, "input %s=%r not in its enum" % (k, obj["input"][k]))


def spacetime_pass(store):
    for f in files_under("spacetime/tables"):
        t = os.path.basename(f)[:-5]
        obj = load(f)
        store[f] = obj
        if t not in ST:
            fail(f, "unknown table")
            continue
        validate(obj, L(ST[t]), f)
    for t in ST:
        if not os.path.exists(os.path.join(HERE, "spacetime/tables", t + ".json")):
            fail("spacetime/tables/%s.json" % t, "missing")
    reducers = {"publish_ticks": 1, "publish_feed": 1, "set_clock": 7, "publish_context": 1, "publish_escalation": 1,
                "log_agent": 1, "reset_all": 0, "request_surge": 2, "consume_surge": 1}
    for r, nargs in reducers.items():
        f = "spacetime/reducers/%s.json" % r
        obj = load(f)
        store[f] = obj
        if check_wrapper(obj, ("reducer", "args"), f):
            if obj["reducer"] != r or not isinstance(obj["args"], list) or len(obj["args"]) != nargs:
                fail(f, "reducer/args")
    pt = json.loads(store["spacetime/reducers/publish_ticks.json"]["args"][0])
    validate(pt, PAYLOAD, "publish_ticks.payload_json")
    validate(json.loads(store["spacetime/reducers/publish_feed.json"]["args"][0]), ST["live_feed"], "publish_feed arg")
    validate(json.loads(store["spacetime/reducers/publish_context.json"]["args"][0]), ST["live_context"], "publish_context")
    validate(json.loads(store["spacetime/reducers/publish_escalation.json"]["args"][0]), ST["live_escalation"],
             "publish_escalation")
    validate(json.loads(store["spacetime/reducers/log_agent.json"]["args"][0]), R("AgentLog"), "log_agent")
    validate(store["spacetime/reducers/set_clock.json"]["args"],
             ("list", ANY), "set_clock")
    c, d = store["spacetime/reducers/request_surge.json"]["args"]
    if not (1 <= c <= 80 and 15 <= d <= 120):
        fail("request_surge", "customers 1-80, duration 15-120")
    rows = load("spacetime/rows_stream.jsonl")
    store["spacetime/rows_stream.jsonl"] = rows
    for i, p in enumerate(rows):
        validate(p, PAYLOAD, "rows_stream[%d]" % i)


PAYLOAD = O({"live_tick": L(ST["live_tick"]), "tick_history": L(ST["tick_history"]), "live_device": L(ST["live_device"]),
             "live_comparison": ST["live_comparison"]})


def convex_pass(store):
    for t, spec in CONVEX.items():
        f = "convex/tables/%s.json" % t
        obj = load(f)
        store[f] = obj
        validate(obj, L(spec), f)
    fn = {"commands_forDevice": ("commands:forDevice", "query", O({"hub_id": STR}), L(R("Command"))),
          "commands_ack": ("commands:ack", "mutation", O({"command_id": STR, "ok": BOOL, "applied_value": Nl(NUM),
                                                          "reason": SHAPES["CommandAck"][1]["reason"]}), None),
          "commands_enqueue": ("commands:enqueue", "mutation", O({"command": R("Command"), "lane": LANE,
                                                                  "hub_id": Nl(STR)}), None),
          "decisions_record": ("decisions:record", "mutation", O({"decisions": L(CONVEX["decisions"])}), None),
          "proposals_upsert": ("proposals:upsert", "mutation", O({"proposal": R("Proposal")}), None),
          "bills_save": ("bills:save", "mutation", O({"bill": R("Bill"), "lane": LANE}), None),
          "backtest_save": ("backtest:save", "mutation", O({"run_id": STR, "results": L(R("BacktestResult"))}), None),
          "devices_report": ("devices:report", "mutation", O({"reading": R("Reading")}), None),
          "hubs_heartbeat": ("hubs:heartbeat", "mutation", O({"hub_id": STR}), None)}
    for name, (fname, typ, args, ret) in fn.items():
        f = "convex/functions/%s.json" % name
        obj = load(f)
        store[f] = obj
        if check_wrapper(obj, ("function", "type", "args", "returns"), f):
            if obj["function"] != fname or obj["type"] != typ:
                fail(f, "function/type")
            validate(obj["args"], args, f + ".args")
            if ret is None:
                if obj["returns"] is not None:
                    fail(f, "returns must be null")
            else:
                validate(obj["returns"], ret, f + ".returns")


def agents_pass(store):
    for name, spec in AGENT_MSG.items():
        f = "agents/%s.json" % name
        obj = load(f)
        store[f] = obj
        validate(obj, spec, f)
    logs = load("agents/agent_log.jsonl")
    store["agents/agent_log.jsonl"] = logs
    validate(logs, L(R("AgentLog")), "agents/agent_log.jsonl")
    cp = load("agents/context_post.json")
    store["agents/context_post.json"] = cp
    if check_wrapper(cp, ("method", "path", "headers", "body"), "agents/context_post.json"):
        if cp["method"] != "POST" or cp["path"] != "/api/context" or set(cp["headers"]) != {"X-Agent-Token"}:
            fail("agents/context_post.json", "method/path/headers")
        validate_partial_context(cp["body"], "agents/context_post.json.body")
    ctx = cp["body"]
    if store["agents/weather_response.json"]["hourly"] != ctx["weather"]["hourly"]:
        fail("agents", "weather numbers changed between WeatherResponse and Context")
    if store["agents/price_response.json"]["hourly"] != ctx["prices"]["hourly"] or \
            store["agents/price_response.json"]["stress"] != ctx["prices"]["stress"]:
        fail("agents", "price numbers changed between PriceResponse and Context")
    if store["agents/events_response.json"]["items"] != ctx["events"]["items"]:
        fail("agents", "events changed between EventsResponse and Context")


# ----------------------------------------------------------------------------- scenario invariants
def scenario_pass(store):
    sc = load("scenario/demo_cafe/scenario.json")
    idx = load("scenario/demo_cafe/index.json")
    for k, v in idx.items():
        if isinstance(v, str) and not os.path.exists(os.path.join(HERE, v)):
            fail("scenario/index.json", "missing %s" % v)
    cfg = sc["config"]
    validate(cfg, R("KitchenConfig"), "scenario.config")
    cap = cfg["peak_cap_kw"]
    auth = cfg["authority"]
    catalog = {c["type_id"]: c for c in store["shapes/equipment_catalog.json"]}
    devices = {}
    for eq in cfg["equipment"]:
        for i in range(1, eq["count"] + 1):
            devices["%s_%d" % (eq["type_id"], i)] = {"importance": eq["importance"], "limits": eq["limits"],
                                                     "type": catalog[eq["type_id"]]}
    if cfg != store["shapes/kitchen_config.json"]:
        fail("scenario", "config differs from shapes/kitchen_config.json")
    # catalog default limits pass the food-safety rule; limits keys match importance
    for c in catalog.values():
        if c["default_importance"] == "flexible" and c["category"] == "refrigeration" and \
                c["default_limits"]["min_power_pct"] < 50:
            fail("catalog", "%s default below food-safety floor" % c["type_id"])
        if set(c["default_limits"]) != set(LIMITS_BY_IMP[c["default_importance"]][1]):
            fail("catalog", "%s default_limits keys do not match its importance" % c["type_id"])
    for eq in cfg["equipment"]:
        if set(eq["limits"]) != set(LIMITS_BY_IMP[eq["importance"]][1]):
            fail("config", "%s limits keys do not match importance" % eq["type_id"])

    tariff = store["shapes/tariff.json"]
    if cfg["tariff_id"] != tariff["tariff_id"]:
        fail("scenario", "config tariff_id differs from shapes/tariff.json")
    latest_fc = {}
    # catalog params keys per power model
    for c in catalog.values():
        if set(c["params"]) != PARAMS_BY_MODEL[c["power_model"]]:
            fail("catalog", "%s params keys %s do not match power_model %s" % (c["type_id"], sorted(c["params"]),
                                                                                c["power_model"]))
    # tariff covers 24 h exactly once
    cover = []
    for e_ in tariff["energy"]:
        cover.append((hm_min(e_["start"]), hm_min(e_["end"])))
    cover.sort()
    if cover[0][0] != 0 or cover[-1][1] != 1440 or any(a[1] != b[0] for a, b in zip(cover, cover[1:])):
        fail("tariff", "energy periods must cover 00:00-24:00 without gaps or overlaps")
    s2h = store["hub_protocol/server_to_hub.jsonl"]
    h2s = store["hub_protocol/hub_to_server.jsonl"]
    steps = store["facade/step_stream.jsonl"]
    rows = store["spacetime/rows_stream.jsonl"]
    ws = store["ws/stream.jsonl"]
    n_ticks = sc["ticks"]
    start = parse_ts(sc["start_sim_ts"])
    if [m["type"] for m in s2h[:2]] != ["hub_welcome", "sim_build"] or len(s2h) != n_ticks + 2:
        fail("server_to_hub", "must be hub_welcome, sim_build, then %d sim_ticks" % n_ticks)
    if h2s[0]["type"] != "hub_hello" or len(h2s) != n_ticks + 1:
        fail("hub_to_server", "must be hub_hello then %d hub_reports" % n_ticks)
    if not s2h[0]["accepted"]:
        fail("server_to_hub", "first welcome must be accepted")
    build = s2h[1]
    if build["config"] != cfg or build["start_sim_ts"] != sc["start_sim_ts"] or build["seed"] != cfg["seed"]:
        fail("sim_build", "config/start/seed mismatch")
    if sorted(d["device_id"] for d in build["devices"]) != sorted(devices):
        fail("sim_build", "device roster mismatch")
    if build["catalog"] != store["shapes/equipment_catalog.json"]:
        fail("sim_build", "catalog mismatch")
    ticks = s2h[2:]
    reports = h2s[1:]
    if len(steps) != 2 * n_ticks or len(rows) != n_ticks:
        fail("streams", "step_stream must have 2 lines per tick, rows_stream 1 per tick")

    # context in force per tick (posted before tick 1, refreshed at tick 61) from the ws stream
    contexts = []   # (first tick, context)
    cur_tick = 0
    for m in ws:
        if m["type"] == "tick":
            cur_tick = m["data"]["hub"]["tick_id"]
        if m["type"] == "context":
            contexts.append((cur_tick + 1, m["data"]))

    def ctx_for(n):
        c = None
        for first, ctx in contexts:
            if first <= n:
                c = ctx
        return c

    def hourly(section, key, dt):
        h = dt.replace(minute=0, second=0)
        for row in section["hourly"]:
            if parse_ts(row["ts"]) == h:
                return row[key]
        return None

    for c in [x[1] for x in contexts]:
        for sec in ("weather", "prices", "events"):
            if c[sec]["label"] != "recorded":
                fail("context", "label must be recorded in the demo scenario")

    all_decisions, all_commands, issued = {}, {}, {}
    acks_by_cmd = {}
    meters_prev = {}
    block = {}
    state_by = {}
    surge_ids = set()
    without_over = False
    for i, t in enumerate(ticks):
        n = i + 1
        w = "tick %d" % n
        if t["type"] != "sim_tick" or t["tick_id"] != n or parse_ts(t["sim_ts"]) != start + timedelta(minutes=n - 1):
            fail(w, "sim_tick ordering / sim_ts")
        if t["minutes"] != 1:
            fail(w, "minutes must be 1")
        if t["replay"]:
            fail(w, "live stream ticks are not replays")
        for s in t["surges"]:
            surge_ids.add(s["surge_id"])
        ctx = ctx_for(n)
        sim_dt = parse_ts(t["sim_ts"])
        if ctx is None:
            fail(w, "no context in force")
        else:
            if not near(t["inputs"]["outdoor_temp_c"], hourly(ctx["weather"], "temp_c", sim_dt) or -999):
                fail(w, "outdoor_temp_c not the context value for this hour")
            mult = {"none": 1.0, "small": 1.10, "medium": 1.25, "large": 1.40}[ctx["crowd_effect"]["value"]]
            if t["inputs"]["crowd_multiplier"] != mult:
                fail(w, "crowd_multiplier does not match crowd_effect")
        hr = reports[i]
        if hr["type"] != "hub_report" or hr["tick_id"] != n:
            fail(w, "hub_report tick_id")
        # commands delivered this tick = new_commands of tick n-1, both lanes, in order
        expected = []
        if n > 1:
            expected = state_by[(n - 1, "without")]["new_commands"] + state_by[(n - 1, "with")]["new_commands"]
        if t["commands"] != expected:
            fail(w, "sim_tick commands != TickState new_commands of tick %d" % (n - 1))
        for lane in ("without", "with"):
            cmd_ids = [c["command_id"] for c in t["commands"] if c["lane"] == lane]
            lane_acks = hr["reports"][lane]["acks"]
            ack_ids = [a["command_id"] for a in lane_acks]
            if sorted(cmd_ids) != sorted(ack_ids) or len(set(ack_ids)) != len(ack_ids):
                fail(w, "each %s command needs exactly one ack in the %s HubReport of the same tick" % (lane, lane))
            for a in lane_acks:
                if a["lane"] != lane:
                    fail(w, "ack lane differs from its HubReport lane")
                acks_by_cmd[a["command_id"]] = (n, a)
        cph = {}
        for lane in ("without", "with"):
            rep = hr["reports"][lane]
            lw = "%s %s" % (w, lane)
            if rep["lane"] != lane or rep["tick_id"] != n or parse_ts(rep["ts"]) != sim_dt + timedelta(minutes=1):
                fail(lw, "HubReport lane/tick_id/ts (ts must be sim_ts + minutes)")
            if rep["hub_id"] != "sim_hub" or rep["source"] != "simulated":
                fail(lw, "hub_id/source")
            if not near(rep["total_kw"], sum(d["power_kw"] for d in rep["devices"])):
                fail(lw, "total_kw != sum of devices")
            if sorted(d["device_id"] for d in rep["devices"]) != sorted(devices):
                fail(lw, "device roster")
            for d in rep["devices"]:
                if not (0 <= d["power_kw"] <= d["rated_kw"] + 1e-9):
                    fail(lw, "%s power out of [0, rated]" % d["device_id"])
                if d["power_pct"] != half_up(100 * d["power_kw"] / d["rated_kw"]):
                    fail(lw, "%s power_pct" % d["device_id"])
                if d["source"] != "simulated":
                    fail(lw, "%s source must be simulated" % d["device_id"])
                if set(d.get("physical", {})) - PHYSICAL_KEYS:
                    fail(lw, "%s unknown physical keys" % d["device_id"])
                dv = devices[d["device_id"]]
                if d["importance"] != dv["importance"] or d["rated_kw"] != dv["type"]["rated_kw"]:
                    fail(lw, "%s importance/rated mismatch with config" % d["device_id"])
            cph[lane] = rep["customers_per_hour"]
            # step stream
            sl = steps[2 * i + (0 if lane == "without" else 1)]
            ts_ = sl["returns"]
            if sl["args"]["minutes"] != 1 or sl["args"]["hub_report"] != rep:
                fail(lw, "step_stream args must be (1, the tick's HubReport)")
            if ts_["lane"] != lane or ts_["hub"] != rep or ts_["ts"] != rep["ts"]:
                fail(lw, "TickState lane/hub/ts must echo the HubReport")
            if ts_["customers_per_hour"] != rep["customers_per_hour"]:
                fail(lw, "TickState customers_per_hour")
            hv = {d["physical"]["indoor_temp_c"] for d in rep["devices"] if "indoor_temp_c" in d.get("physical", {})}
            if len(hv) > 1:
                fail(lw, "every HVAC unit must report the one shared dining-room temperature")
            if hv and ts_["indoor_temp_c"] != next(iter(hv)):
                fail(lw, "indoor_temp_c must copy the dining-room temperature")
            fk = ts_["forecast_kw"]
            if n % 5 == 0:
                if not (isinstance(fk, list) and len(fk) == 8):
                    fail(lw, "forecast_kw must have 8 values on replan ticks")
            elif fk is not None:
                fail(lw, "forecast_kw must be null off replan ticks")
            if lane == "without" and (ts_["new_decisions"] or ts_["new_commands"] or ts_["new_escalations"]):
                fail(lw, "without lane never gets decisions/commands/escalations")
            if lane == "with" and (ts_["new_decisions"] or ts_["new_commands"]) and n % 5 and \
                    not all(d["reason_code"] == "escalation_choice" for d in ts_["new_decisions"]):
                fail(lw, "routine decisions only on replan ticks")
            for d in ts_["new_decisions"]:
                all_decisions.setdefault(d["decision_id"], d)
                if d["ts"] != ts_["ts"]:
                    fail(lw, "decision ts")
            for c in ts_["new_commands"]:
                if c["command_id"] in issued:
                    fail(lw, "command %s issued twice" % c["command_id"])
                issued[c["command_id"]] = (n, c)
                all_commands[c["command_id"]] = c
                if c["lane"] != lane or c["ts"] != ts_["ts"]:
                    fail(lw, "command lane/ts")
            state_by[(n, lane)] = ts_
            # meter
            m = ts_["meter"]
            if m["ts"] != rep["ts"] or not near(m["total_kw"], rep["total_kw"]) or m["peak_cap_kw"] != cap or \
                    m["peak_mode"] != cfg["peak_mode"]:
                fail(lw, "meter ts/total/peak_mode/cap")
            k = (n - 1) // 15
            bstart = start + timedelta(minutes=15 * k)
            if parse_ts(m["block_start"]) != bstart:
                fail(lw, "block_start")
            b = block.setdefault((lane, k), [])
            b.append(rep["total_kw"])
            if not near(m["block_avg_kw"], sum(b) / len(b)):
                fail(lw, "block_avg_kw != mean of the block's ticks so far")
            price = tariff_price(tariff, sim_dt)
            if price is None or m["price_usd_per_kwh_now"] != price:
                fail(lw, "price_usd_per_kwh_now not the recorded context price")
            prev = meters_prev.get(lane)
            if prev is not None:
                if not near(m["energy_kwh_today"] - prev["energy_kwh_today"], rep["total_kw"] / 60):
                    fail(lw, "energy increment")
                inc = rep["total_kw"] / 60 * m["price_usd_per_kwh_now"]
                if not near(m["cost_usd_today"] - prev["cost_usd_today"], inc, 0.0101) or \
                        not near(m["cost_usd_month"] - prev["cost_usd_month"], inc, 0.0101):
                    fail(lw, "cost increment")
                exp_peak = prev["month_peak_kw"]
                if n % 15 == 0:
                    exp_peak = max(exp_peak, m["block_avg_kw"])
                if not near(m["month_peak_kw"], exp_peak):
                    fail(lw, "month_peak_kw update rule")
                if n > 1 and len(b) == 1 and lane == "with" and prev["block_avg_kw"] > cap + 1e-9:
                    pass
            meters_prev[lane] = m
            if lane == "with" and n % 15 == 0:
                state_by.setdefault("closed_with", []).append((n, m["block_avg_kw"]))
            if lane == "without" and n % 15 == 0 and m["block_avg_kw"] > cap:
                without_over = True
        if cph["without"] != cph["with"]:
            fail(w, "both lanes must see the same customers_per_hour")
        # command effect visible in this tick's report
        for c in t["commands"]:
            a = next(x for x in hr["reports"][c["lane"]]["acks"] if x["command_id"] == c["command_id"])
            if a["lane"] != c["lane"]:
                fail(w, "ack lane")
            dev = next(d for d in hr["reports"][c["lane"]]["devices"] if d["device_id"] == c["device_id"])
            if a["ok"]:
                if c["action"] == "reduce" and (dev["state"] != "reduced" or dev["power_pct"] > c["value"] + 1):
                    fail(w, "%s reduce not reflected" % c["command_id"])
                if c["action"] == "restore" and dev["state"] != "on":
                    fail(w, "%s restore not reflected" % c["command_id"])
                if c["action"] == "delay" and dev["state"] != "waiting":
                    fail(w, "%s delay not reflected" % c["command_id"])
                if c["action"] in ("reduce", "delay") and a["applied_value"] != c["value"]:
                    fail(w, "%s ok ack must echo applied_value" % c["command_id"])
            elif a["reason"] is None:
                fail(w, "failed ack needs a reason")
        # spacetime payload = TickState values re-keyed
        p = rows[i]
        sw, sv = state_by[(n, "without")], state_by[(n, "with")]
        for j, s in enumerate((sw, sv)):
            mm = s["meter"]
            exp = {"lane": s["lane"], "ts": s["ts"], "tick_id": n, "total_kw": mm["total_kw"],
                   "block_avg_kw": mm["block_avg_kw"], "month_peak_kw": mm["month_peak_kw"], "peak_mode": mm["peak_mode"],
                   "peak_cap_kw": mm["peak_cap_kw"], "target_kw": mm["target_kw"],
                   "energy_kwh_today": mm["energy_kwh_today"], "price_usd_per_kwh_now": mm["price_usd_per_kwh_now"],
                   "cost_usd_today": mm["cost_usd_today"], "cost_usd_month": mm["cost_usd_month"],
                   "customers_per_hour": s["customers_per_hour"], "indoor_temp_c": s["indoor_temp_c"],
                   "forecast_kw_json": None, "forecast_ts": None}
            if s["forecast_kw"] is not None:
                latest_fc[s["lane"]] = (json.dumps(s["forecast_kw"], separators=(",", ":")), s["ts"])
            exp["forecast_kw_json"], exp["forecast_ts"] = latest_fc.get(s["lane"], (None, None))
            if p["live_tick"][j] != exp:
                fail(w, "live_tick row != TickState (%s)" % s["lane"])
            if p["tick_history"][j] != {"lane": s["lane"], "ts": s["ts"], "total_kw": mm["total_kw"],
                                        "block_avg_kw": mm["block_avg_kw"]}:
                fail(w, "tick_history row")
        exp_dev = []
        for s in (sw, sv):
            for d in s["hub"]["devices"]:
                exp_dev.append({"key": "%s:%s" % (s["lane"], d["device_id"]), "lane": s["lane"], "device_id": d["device_id"], "type_id": d["type_id"], "name": d["name"],
                                "importance": d["importance"], "state": d["state"], "power_kw": d["power_kw"],
                                "rated_kw": d["rated_kw"], "power_pct": d["power_pct"], "source": d["source"],
                                "physical_json": None if "physical" not in d else
                                json.dumps(d["physical"], separators=(",", ":"), ensure_ascii=False)})
        if p["live_device"] != exp_dev:
            fail(w, "live_device rows != HubReport devices")
        cmp_ = p["live_comparison"]
        if not (near(cmp_["saved_today_usd"], sw["meter"]["cost_usd_today"] - sv["meter"]["cost_usd_today"]) and
                near(cmp_["peak_avoided_kw"], sw["meter"]["month_peak_kw"] - sv["meter"]["month_peak_kw"]) and
                cmp_["month_peak_without_kw"] == sw["meter"]["month_peak_kw"] and
                cmp_["month_peak_with_kw"] == sv["meter"]["month_peak_kw"] and cmp_["ts"] == sv["ts"] and cmp_["id"] == 0):
            fail(w, "LaneComparison not derived from the two meters")
    last_cmds = state_by[(n_ticks, "without")]["new_commands"] + state_by[(n_ticks, "with")]["new_commands"]
    if last_cmds:
        fail("tick %d" % n_ticks, "commands issued on the last tick are never delivered")
    if not without_over:
        fail("scenario", "without lane must break the cap")

    # every issued command delivered exactly once in n + 1
    for cid, (n, c) in issued.items():
        if cid not in acks_by_cmd or acks_by_cmd[cid][0] != n + 1:
            fail("command %s" % cid, "not acked in tick n + 1")

    # escalation(s)
    escs = {}
    for (n, lane), s in [(k, v) for k, v in state_by.items() if isinstance(k, tuple)]:
        for e in s["new_escalations"]:
            escs[e["escalation_id"]] = (n, e)
    if len(escs) != 1:
        fail("scenario", "exactly one escalation expected")
    esc_variants = [store[f] for f in store if f.startswith("shapes/escalation_")] + \
        [m["data"] for m in ws if m["type"] == "escalation"]
    for e in esc_variants:
        check_escalation(e, devices, auth, cap)
    resolved = [m["data"] for m in ws if m["type"] == "escalation" and m["data"]["status"] == "resolved"]
    allowance = 0.0
    for e in resolved:
        if e["resolved_by"] != "claude":
            fail("ws escalation", "scenario escalation must be resolved by claude")
        opt = next(o for o in e["options"] if o["option_id"] == e["chosen_option_id"])
        if not opt["within_authority"]:
            fail("ws escalation", "claude resolved outside authority")
        for b in opt["rule_breaks"]:
            if b["kind"] == "cap_overrun":
                allowance = max(allowance, b["amount"])
        n_open, e_open = escs[e["escalation_id"]]
        if n_open % 5:
            fail("escalation", "opened off a replan tick")
        fk = state_by[(n_open, "with")]["forecast_kw"]
        if fk is None or not near(max(fk), e["problem"]["forecast_peak_kw"]):
            fail("escalation", "forecast_peak_kw must match the with-lane forecast at that tick")
        # chosen option's actions executed as escalation_choice decisions
        chs = [d for d in all_decisions.values() if d["reason_code"] == "escalation_choice"]
        if len(chs) != len(opt["actions"]):
            fail("escalation", "chosen option actions must become escalation_choice decisions")
        for a, d in zip(opt["actions"], chs):
            if (a["device_id"], a["action"], a["value"]) != (d["device_id"], d["action"], d["value"]):
                fail("escalation", "escalation_choice decision differs from the chosen option's command")
        past = {b["device_id"]: b["amount"] for b in opt["rule_breaks"] if b["kind"] == "past_deadline"}
    for n, avg in state_by.get("closed_with", []):
        if avg > cap + allowance + 1e-9:
            fail("tick %d" % n, "with lane block average %.2f kW over the cap" % avg)

    # decisions / commands hard rules
    for d in all_decisions.values():
        dv = devices[d["device_id"]]
        check_move(d["device_id"], d["action"], d["value"], dv, "decision %s" % d["decision_id"],
                   allow_break=d["reason_code"] == "escalation_choice")
        cmd = [c for c in all_commands.values() if c["decision_id"] == d["decision_id"]]
        if len(cmd) != 1:
            fail("decision %s" % d["decision_id"], "needs exactly one command")
        elif (cmd[0]["device_id"], cmd[0]["action"], cmd[0]["value"]) != (d["device_id"], d["action"], d["value"]):
            fail("decision %s" % d["decision_id"], "command differs from decision")
        if d["inside_rules"] == (d["reason_code"] == "escalation_choice"):
            fail("decision %s" % d["decision_id"], "inside_rules must be false only for escalation_choice")
    for c in all_commands.values():
        if c["issued_by"] == "engine" and c["decision_id"] not in all_decisions:
            fail("command %s" % c["command_id"], "engine command without its decision")
        if c["lane"] != "with":
            fail("command %s" % c["command_id"], "engine commands only in the with lane")

    # deferrable deadlines (with lane): every job run ends by must_finish_by (+ chosen past_deadline amount)
    for dev_id, dv in devices.items():
        if dv["importance"] != "deferrable":
            continue
        deadline = dv["limits"]["must_finish_by"]
        extra = 0
        for e in resolved:
            opt = next(o for o in e["options"] if o["option_id"] == e["chosen_option_id"])
            extra += sum(b["amount"] for b in opt["rule_breaks"] if b["kind"] == "past_deadline" and b["device_id"] == dev_id)
        hh, mm_ = deadline.split(":")
        prev_state = None
        for i, r in enumerate(reports):
            d = next(x for x in r["reports"]["with"]["devices"] if x["device_id"] == dev_id)
            if d["state"] == "running_job" and prev_state != "running_job":
                end = parse_ts(r["reports"]["with"]["ts"]) - timedelta(minutes=1) + \
                    timedelta(minutes=dv["type"]["params"]["cycle_min"])
                local = end - timedelta(hours=7)
                dl = local.replace(hour=int(hh), minute=int(mm_), second=0)
                # only jobs that were moved by the engine are bound by WattWise; uncontrolled starts are physics
                moved = any(x["device_id"] == dev_id for x in all_decisions.values())
                if moved and local > dl + timedelta(minutes=extra):
                    fail(dev_id, "job ends %s local, past %s (+%d min allowed)" % (local.strftime("%H:%M"), deadline, extra))
            prev_state = d["state"]

    cmd_index = {}
    for f, obj in store.items():
        for path, o in walk_objs(obj, f):
            if set(o) >= set(SHAPES["Command"][1]) and "command_id" in o and "issued_by" in o:
                cmd_index.setdefault(o["command_id"], o)
    # acks follow the clamping rule; bills follow the tariff; proposals carry the payload of their kind; single-row ids
    for f, obj in store.items():
        for path, o in walk_objs(obj, f):
            if set(o) == set(SHAPES["CommandAck"][1]) and o["command_id"] in cmd_index:
                c = cmd_index[o["command_id"]]
                if o["ok"]:
                    if (o["applied_value"] == c["value"]) != (o["reason"] is None) or \
                            (o["reason"] not in (None, "out_of_range")):
                        fail(path, "ok ack: reason null iff applied unchanged, else out_of_range")
                elif o["reason"] not in ("job_running", "already_off", "unknown_device") or o["applied_value"] is not None:
                    fail(path, "rejected ack needs job_running | already_off | unknown_device and no applied_value")
            if set(o) == set(SHAPES["Bill"][1]) or set(o) == set(SHAPES["Bill"][1]) | {"lane"}:
                rates = {c["name"]: c["usd_per_kw"] for c in tariff["demand"]}
                if o["tariff_id"] != tariff["tariff_id"] or sorted(d["name"] for d in o["demand_charges"]) != sorted(rates):
                    fail(path, "bill must use every demand charge of the tariff")
                for d in o["demand_charges"]:
                    if d["name"] in rates and not near(d["cost_usd"], d["peak_kw"] * rates[d["name"]]):
                        fail(path, "demand charge cost != peak x rate")
                if not near(o["total_usd"], o["energy_cost_usd"] + sum(d["cost_usd"] for d in o["demand_charges"])):
                    fail(path, "bill total")
            if set(o) == set(SHAPES["Proposal"][1]) and set(o["payload"]) != PROPOSAL_PAYLOAD[o["kind"]]:
                fail(path, "proposal payload keys for kind %s" % o["kind"])
            if set(o) == set(SHAPES["Snapshot"][1]) and any(e["status"] != "open" for e in o["open_escalations"]):
                fail(path, "snapshot open_escalations must be open")
    kinds = {store[f]["kind"] for f in store if f.startswith("shapes/proposal_")}
    if kinds != set(PROPOSAL_PAYLOAD):
        fail("shapes", "one Proposal example per kind expected, have %s" % sorted(kinds))
    for t_ in ("live_clock", "live_context", "live_comparison"):
        if any(r["id"] != 0 for r in store["spacetime/tables/%s.json" % t_]):
            fail("spacetime/tables/%s.json" % t_, "single-row table id must be 0")
    for r in store["spacetime/tables/live_device.json"]:
        if r["key"] != "%s:%s" % (r["lane"], r["device_id"]):
            fail("live_device", "key must be <lane>:<device_id>")
    wd = store["ws/warning.json"]
    if wd["code"] == "cap_unreachable" and set(wd["data"]) != {"unavoidable_kw", "peak_cap_kw"}:
        fail("ws/warning.json", "cap_unreachable data must be {unavoidable_kw, peak_cap_kw}")

    # peak_mode consistency everywhere a KitchenConfig or Meter appears
    for f, obj in store.items():
        for path, o in walk_objs(obj, f):
            if set(o) == set(SHAPES["KitchenConfig"][1]) or set(o) == set(SHAPES["Meter"][1]):
                if o["peak_mode"] == "cap" and o["peak_cap_kw"] is None and "_422" not in path:
                    fail(path, "peak_mode cap needs peak_cap_kw")
                if o["peak_mode"] == "minimize" and o["peak_cap_kw"] is not None:
                    fail(path, "peak_mode minimize needs peak_cap_kw null")
            if set(o) == set(SHAPES["Meter"][1]) and o["peak_mode"] == "cap" and o["target_kw"] != o["peak_cap_kw"]:
                fail(path, "target_kw must equal peak_cap_kw in cap mode")
    for f in ("rest/put_peak_cap_422.json", "facade/set_peak_cap_rule_error.json"):
        o = store[f]
        body = o.get("request") or o.get("args")
        if body["peak_mode"] != "cap" or body["peak_cap_kw"] is not None:
            fail(f, "must show cap mode with a null peak_cap_kw")
    if store["shapes/kitchen_config_minimize.json"]["peak_mode"] != "minimize" or cfg["peak_mode"] != "cap":
        fail("shapes", "kitchen_config_minimize must be minimize; Demo Café must be cap")
    # clock: slowed (never paused) exactly while the escalation is open
    open_e = set()
    for i, m in enumerate(ws):
        if m["type"] == "escalation":
            if m["data"]["status"] in ("open", "awaiting_owner"):
                open_e.add(m["data"]["escalation_id"])
            else:
                open_e.discard(m["data"]["escalation_id"])
        if m["type"] == "clock":
            if m["paused_reason"] is not None or not m["playing"]:
                fail("ws/stream.jsonl[%d]" % i, "scenario runs outside demo mode: no pause")
            if open_e and (m["slowed_reason"] != "escalation" or m["speed"] != 1):
                fail("ws/stream.jsonl[%d]" % i, "clock must be slowed to 1x while an escalation is open")
            if not open_e and (m["slowed_reason"] is not None or m["speed"] != 120):
                fail("ws/stream.jsonl[%d]" % i, "clock must run at 120x with slowed_reason null")
    if not any(m["type"] == "clock" and m["slowed_reason"] == "escalation" for m in ws):
        fail("ws/stream.jsonl", "no slowed clock during the escalation")

    # ids: formats and cross references
    ids = {"d": set(all_decisions), "c": set(all_commands), "e": set(escs), "s": surge_ids}
    for f, obj in store.items():
        for path, k, v in walk(obj, f):
            if k == "decision_id" and v is not None and v not in ids["d"] and not path.startswith("rest/post_decision_undo_404"):
                fail(path, "unknown decision_id %s" % v)
            if k == "escalation_id" and v not in ids["e"]:
                fail(path, "unknown escalation_id %s" % v)
            if k == "surge_id" and v not in ids["s"]:
                fail(path, "unknown surge_id %s" % v)
            if k == "device_id" and v not in devices and "_404" not in path and v is not None:
                fail(path, "unknown device_id %s" % v)
            for key, pat in (("decision_id", r"^d_\d{4}$"), ("command_id", r"^c_\d{4}$"), ("escalation_id", r"^e_\d{4}$"),
                             ("proposal_id", r"^p_\d{4}$"), ("surge_id", r"^s_\d{4}$"), ("kitchen_id", r"^k_\d{2}$")):
                if k == key and v is not None and not re.match(pat, v):
                    fail(path, "%s format %s" % (key, v))
    # every command_id that appears anywhere is defined once with one content
    cmd_defs = {}
    for f, obj in store.items():
        for path, o in walk_objs(obj, f):
            if set(o) == set(SHAPES["Command"][1]) or set(o) == set(SHAPES["Command"][1]) | {"hub_id", "delivery"}:
                base = {k: o[k] for k in SHAPES["Command"][1]}
                if o["command_id"] in cmd_defs and cmd_defs[o["command_id"]] != base:
                    fail(path, "command %s has two different contents" % o["command_id"])
                cmd_defs[o["command_id"]] = base
    for f, obj in store.items():
        for path, o in walk_objs(obj, f):
            if set(o) == set(SHAPES["CommandAck"][1]) and o["command_id"] not in cmd_defs:
                fail(path, "ack for unknown command %s" % o["command_id"])
            if set(o) == set(SHAPES["Command"][1]):
                dv = devices.get(o["device_id"])
                if dv and dv["importance"] == "always_on" and o["issued_by"] == "engine":
                    fail(path, "engine command to always_on device")
                if o["issued_by"] == "owner" and o["decision_id"] is not None:
                    fail(path, "owner command must have decision_id null")
            if set(o) == set(SHAPES["Decision"][1]):
                dv = devices.get(o["device_id"])
                if dv and dv["importance"] == "always_on":
                    fail(path, "decision on always_on device")
            if set(o) == set(SHAPES["Proposal"][1]):
                if (o["status"] == "pending") != (o["confirmed_via"] is None) and o["status"] in ("pending", "confirmed"):
                    fail(path, "confirmed_via must be null iff pending")
    # scenario index lists exactly the stream ids
    if sorted(idx["decision_ids"]) != sorted(ids["d"]) or sorted(idx["command_ids"]) != sorted(ids["c"]):
        fail("scenario/index.json", "id lists differ from the streams")
    # ws stream covers every tick for both lanes + comparison
    tick_msgs = [(m["data"]["hub"]["tick_id"], m["data"]["lane"]) for m in ws if m["type"] == "tick"]
    if tick_msgs != [(n, l) for n in range(1, n_ticks + 1) for l in ("without", "with")]:
        fail("ws/stream.jsonl", "tick messages must cover every tick, without then with")
    if sum(1 for m in ws if m["type"] == "comparison") != n_ticks:
        fail("ws/stream.jsonl", "one comparison per tick")
    feed_ids = [r["decision_id"] for r in store["spacetime/tables/live_feed.json"]]
    if sorted(feed_ids) != sorted(ids["d"]):
        fail("live_feed", "rows must be the scenario decisions")
    for r in store["spacetime/tables/live_feed.json"]:
        d = all_decisions[r["decision_id"]]
        if json.loads(r["effect_json"]) != d["effect"] or r["status"] != d["status"] or r["value"] != d["value"]:
            fail("live_feed", "row differs from decision %s" % d["decision_id"])
    dm = [m for m in ws if m["type"] == "decision"]
    if sorted(m["data"]["decision_id"] for m in dm) != sorted(ids["d"]):
        fail("ws/stream.jsonl", "one decision message per decision")


def check_move(dev_id, action, value, dv, where, allow_break=False, breaks=()):
    imp = dv["importance"]
    if imp == "always_on":
        fail(where, "always_on device moved")
    if action == "reduce":
        if imp != "flexible":
            fail(where, "reduce on a non-flexible device")
        if dv["type"]["category"] == "refrigeration" and value < 50:
            fail(where, "food-safety floor crossed")
        if value < dv["limits"].get("min_power_pct", 0) and not any(
                b["kind"] == "below_min_power" and b.get("device_id") == dev_id for b in breaks):
            fail(where, "below min_power_pct without a below_min_power rule break")
    if action in ("delay", "start") and imp != "deferrable":
        fail(where, "%s on a non-deferrable device" % action)
    if action == "delay" and not allow_break and value > dv["limits"]["max_delay_min"]:
        fail(where, "delay beyond max_delay_min")


def check_escalation(e, devices, auth, cap):
    w = "escalation %s (%s)" % (e["escalation_id"], e["status"])
    ids = [o["option_id"] for o in e["options"]]
    if not (3 <= len(ids) <= 4) or ids[-1] != "ask_owner" or ids.count("ask_owner") != 1:
        fail(w, "2-3 alternatives plus ask_owner")
    for o in e["options"][:-1]:
        if not re.match(r"^(accept_overrun|deep_reduce_[a-z_]+|extend_delay_[a-z_]+)$", o["option_id"]):
            fail(w, "option id %s" % o["option_id"])
        for a in o["actions"]:
            dv = devices[a["device_id"]]
            if a["lane"] != e["lane"] or a["issued_by"] != "engine":
                fail(w, "option action lane/issued_by")
            check_move(a["device_id"], a["action"], a["value"], dv, w + " " + o["option_id"], allow_break=True,
                       breaks=o["rule_breaks"])
        exp = auth["enabled"]
        for b in o["rule_breaks"]:
            if b["kind"] == "cap_overrun":
                exp = exp and b["amount"] <= auth["max_cap_overrun_kw"]
                if not near(b["amount"], o["projected"]["peak_kw"] - cap, 0.06):
                    fail(w, "cap_overrun amount != projected peak - cap")
            elif b["kind"] == "below_min_power":
                exp = exp and auth["may_go_below_min_power"]
                if devices[b["device_id"]]["type"]["category"] == "refrigeration":
                    fail(w, "food-safety option generated")
            elif b["kind"] in ("past_deadline", "over_max_delay"):
                exp = exp and b["amount"] <= auth["max_extra_delay_min"]
            elif b["kind"] == "over_max_reduce":
                exp = exp and b["amount"] <= auth["max_extra_reduce_min"]
            else:
                fail(w, "unknown rule_break kind %s" % b["kind"])
        if o["projected"] and o["projected"]["peak_kw"] > cap + 0.05 and not any(
                b["kind"] == "cap_overrun" for b in o["rule_breaks"]):
            fail(w, "%s projects over the cap without a cap_overrun break" % o["option_id"])
        if o["within_authority"] != exp:
            fail(w, "%s within_authority should be %s" % (o["option_id"], exp))
    if e["options"][-1]["projected"] is not None or e["options"][-1]["actions"]:
        fail(w, "ask_owner has no actions and no projection")
    if e["default_option_id"] not in ids:
        fail(w, "default not in options")
    acc = next((o for o in e["options"] if o["option_id"] == "accept_overrun"), None)
    exp_default = "accept_overrun" if acc and acc["within_authority"] else "ask_owner"
    if e["default_option_id"] != exp_default:
        fail(w, "default should be %s" % exp_default)
    p = e["problem"]
    if not near(p["excess_kw"], p["forecast_peak_kw"] - p["target_kw"], 0.06) or p["target_kw"] != cap:
        fail(w, "problem numbers")
    if parse_ts(e["deadline_sim_ts"]) != min(parse_ts(e["ts"]) + timedelta(minutes=15),
                                             parse_ts(e["block_start"]) - timedelta(minutes=5)):
        fail(w, "deadline must be ts + 15 min, capped at block_start - 5 min")
    st = e["status"]
    if st == "open" and (e["resolved_by"] or e["chosen_option_id"] or e["rationale"]):
        fail(w, "open escalation has a resolution")
    if st == "resolved":
        if e["chosen_option_id"] not in ids or e["resolved_by"] not in ("claude", "owner"):
            fail(w, "resolved needs a chosen option and claude/owner")
        if e["resolved_by"] == "claude":
            if not next(o for o in e["options"] if o["option_id"] == e["chosen_option_id"])["within_authority"]:
                fail(w, "claude resolved outside authority (must be awaiting_owner)")
    if st == "awaiting_owner":
        o = next((o for o in e["options"] if o["option_id"] == e["chosen_option_id"]), None)
        if o is None or o["within_authority"]:
            fail(w, "awaiting_owner must hold an outside-authority choice")
    if st == "expired_default" and (e["chosen_option_id"] != e["default_option_id"] or e["resolved_by"] != "default"):
        fail(w, "expired_default applies the default, resolved_by default")


def walk(obj, path):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                yield from walk(v, path + "." + k)
            else:
                yield path, k, v
            if isinstance(v, str) and v[:1] in "{[" and k.endswith("_json"):
                try:
                    yield from walk(json.loads(v), path + "." + k)
                except ValueError:
                    pass
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk(v, "%s[%d]" % (path, i))


def walk_objs(obj, path):
    if isinstance(obj, dict):
        yield path, obj
        for k, v in obj.items():
            yield from walk_objs(v, path + "." + k)
            if isinstance(v, str) and v[:1] in "{[" and (k.endswith("_json") or k == "args"):
                try:
                    yield from walk_objs(json.loads(v), path + "." + k)
                except ValueError:
                    pass
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            if isinstance(v, str) and v[:1] in "{[":
                try:
                    yield from walk_objs(json.loads(v), "%s[%d]" % (path, i))
                except ValueError:
                    pass
            else:
                yield from walk_objs(v, "%s[%d]" % (path, i))


def manifest_pass():
    man = load("MANIFEST.json")
    on_disk = set()
    for root, _, fs in os.walk(HERE):
        if "__pycache__" in root:
            continue
        for f in fs:
            on_disk.add(os.path.relpath(os.path.join(root, f), HERE))
    if set(man) != on_disk:
        fail("MANIFEST.json", "lists %s / missing %s" % (sorted(set(man) - on_disk), sorted(on_disk - set(man))))


def determinism_pass():
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([sys.executable, os.path.join(HERE, "generate.py"), tmp], capture_output=True, text=True)
        if r.returncode:
            return fail("generate.py", "failed: %s" % r.stderr[-500:])
        n = 0
        for root, _, fs in os.walk(tmp):
            for f in fs:
                rel = os.path.relpath(os.path.join(root, f), tmp)
                n += 1
                with open(os.path.join(root, f), "rb") as a, open(os.path.join(HERE, rel), "rb") as b:
                    if a.read() != b.read():
                        fail(rel, "regenerating gives different bytes (stale or non-deterministic)")
        return n


def main():
    store = {}
    for p in (shapes_pass, hub_pass, rest_pass, ws_pass, facade_pass, ai_pass, spacetime_pass, convex_pass, agents_pass):
        try:
            p(store)
        except Exception as ex:   # a crash is a failure, not a pass
            fail(p.__name__, "crashed: %r" % ex)
    try:
        scenario_pass(store)
    except Exception as ex:
        import traceback
        traceback.print_exc()
        fail("scenario_pass", "crashed: %r" % ex)
    manifest_pass()
    regen = determinism_pass()
    if FAIL:
        for f in FAIL[:200]:
            print("FAIL", f)
        print("%d failure(s)" % len(FAIL))
        sys.exit(1)
    print("OK: %d files, %d values validated; invariants, cross-references and determinism (%s files regenerated "
          "byte-identical) pass" % (COUNT["files"], COUNT["objects"], regen))


if __name__ == "__main__":
    main()
