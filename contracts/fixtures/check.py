#!/usr/bin/env python3
"""Validates every WattWise fixture against docs/CONTRACTS.md. Python standard library only.

Usage: python3 contracts/fixtures/check.py        exits non-zero on any failure.
       CHECK_QUICK=1 python3 contracts/fixtures/check.py   (skips the Pydantic and regeneration passes; never for sign-off)

Checks: exact field sets + enums per shape; sums and averages (tol 0.01); tick ordering; the n -> n + 1 command rule; the
meter (energy, running block mean, two month peaks, demand added today, local-midnight reset) re-computed from the HubReports
and the history; hard rules (always_on, min power, food-safety floor, deadlines); escalation lifecycle (harm, rank, default,
fallback at open, deadline); clock phases (service -> overnight -> service ... -> closed); SpacetimeDB rows = TickState values
re-keyed; history (sorted, roster per block, ends <= end) and daily inputs = the stream inputs; the fake backtest re-billed;
cross-references; determinism (full regeneration and `--days` byte-identical). If backend/.venv has pydantic, every fixture is
also model_validate'd with backend/contracts (the multi-day streams included).
"""
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
TOL = 0.01
FAIL = []
COUNT = {"files": 0, "objects": 0}
UTC = timezone.utc
LOCAL = timedelta(hours=-7)          # America/Los_Angeles, PDT for every date in the fixtures


def fail(where, msg):
    FAIL.append("%s: %s" % (where, msg))


# ----------------------------------------------------------------------------- schema DSL
TS_RE = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d{3})?Z$")
HM_RE = re.compile(r"^(([01]\d|2[0-3]):[0-5]\d|24:00)$")
YM_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
DATE_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")
NUM, INT, STR, BOOL, TS, HM, ANY, DICT, YM, DATE = "num", "int", "str", "bool", "ts", "hm", "any", "dict", "ym", "date"


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
PEAK_MODE = E("minimize", "cap")
REASON = E("avoid_new_peak", "stay_under_cap", "release_into_valley", "catch_up", "owner_override", "escalation_fallback",
           "escalation_choice")
ESC_STATUS = E("open", "resolved", "expired_default", "obsolete")
PAUSED = Nl(E("manual", "hub_waiting", "sim_host_offline", "run_complete"))
PHASE = E("service", "overnight", "closed")
DAYS = E("all", "weekdays", "weekends")
PARAMS_BY_MODEL = {"fixed": set(), "cycling": {"duty_idle_pct", "duty_busy_pct"}, "thermal": {"setpoint_c"},
                   "demand_driven": {"idle_kw", "kw_per_order"}, "job": {"cycle_min"}}
PROPOSAL_PAYLOAD = {"importance": {"device_id", "importance", "limits"}, "peak_cap": {"peak_mode", "peak_cap_kw"},
                    "undo_decision": {"decision_id"}, "customer_event": {"customers", "duration_min", "start_sim_ts"},
                    "authority": {"enabled", "max_cap_overrun_kw", "max_extra_delay_min", "max_extra_reduce_min",
                                  "may_go_below_min_power"}}
PHYSICAL_KEYS = {"indoor_temp_c", "box_temp_c", "dirty_racks", "ice_level_pct", "job_remaining_min", "orders_in_progress"}
WARNING_DATA = {"cap_unreachable": O({"unavoidable_kw": NUM, "peak_cap_kw": Nl(NUM), "target_kw": NUM}),
                "sim_host_offline": O({"last_tick_id": INT}), "hub_offline": O({"device_id": STR, "hub_id": STR}),
                "live_transport_down": O({}), "store_down": O({})}
CLOCK_FIELDS = {"playing": BOOL, "speed": INT, "sim_ts": TS, "tick_id": INT, "paused_reason": PAUSED, "day_index": INT,
                "run_days": INT, "phase": PHASE}

SHAPES = {
    "EquipmentType": O({"type_id": STR, "name": STR,
                        "category": E("cooling", "refrigeration", "cooking", "water_heating", "lighting", "other"),
                        "default_importance": IMPORTANCE, "rated_kw": NUM,
                        "power_model": E("fixed", "cycling", "thermal", "demand_driven", "job"), "params": DICT,
                        "default_limits": R("ImportanceLimits"), "source_note": STR}),
    "Tariff": O({"tariff_id": STR, "name": STR, "label": E("illustrative", "urdb"), "currency": STR, "timezone": STR,
                 "energy": L(O({"name": STR, "start": HM, "end": HM, "usd_per_kwh": NUM, "months": Nl(L(INT)),
                                "days": DAYS})),
                 "demand": L(O({"name": STR, "windows": Nl(L(O({"start": HM, "end": HM}))), "months": Nl(L(INT)),
                                "days": DAYS, "usd_per_kw": NUM})),
                 "fixed_charges": L(O({"name": STR, "usd": NUM, "per": E("day", "month")}))}),
    "ClaudeAuthority": O({"enabled": BOOL, "max_cap_overrun_kw": NUM, "max_extra_delay_min": INT,
                          "max_extra_reduce_min": INT, "may_go_below_min_power": BOOL}),
    "KitchenConfig": O({"name": STR,
                        "equipment": L(O({"type_id": STR, "count": INT, "importance": IMPORTANCE,
                                          "limits": R("ImportanceLimits")})),
                        "peak_mode": PEAK_MODE, "peak_cap_kw": Nl(NUM), "operating_hours": O({"open": HM, "close": HM}),
                        "location": O({"lat": NUM, "lon": NUM, "label": STR}), "owner_preferences": STR,
                        "authority": R("ClaudeAuthority"), "tariff_id": STR, "run_days": INT, "seed": INT}),
    "WarmUpHistory": O({"source": E("nrel_comstock", "fixture_synthetic"), "label": E("calibrated_model", "simulated"),
                        "dataset_id": STR, "scale": NUM, "day_offset": INT, "start": TS, "end": TS,
                        "blocks": L(O({"block_start": TS, "device_id": STR, "avg_kw": NUM})),
                        "month_to_date": Nl(O({"month": YM, "month_peak_kw": NUM, "on_peak_month_peak_kw": Nl(NUM),
                                               "energy_kwh_month": NUM, "cost_usd_month": NUM,
                                               "demand_peaks": Nl(L(R("DemandPeak")))}, optional=("demand_peaks",)))}),
    "Warning": ("warning", None),
    "Device": O({"device_id": STR, "type_id": STR, "name": STR, "importance": IMPORTANCE,
                 "state": E("off", "on", "reduced", "waiting", "running_job"), "power_kw": NUM, "rated_kw": NUM,
                 "power_pct": INT, "source": E("simulated", "measured"), "physical": DICT}, optional=("physical",)),
    "HubReport": O({"hub_id": STR, "lane": LANE, "tick_id": INT, "ts": TS, "total_kw": NUM, "customers_per_hour": INT,
                    "devices": L(R("Device")), "acks": L(R("CommandAck")), "source": E("simulated", "mixed")}),
    "Reading": O({"hub_id": STR, "channel": INT, "device_id": STR, "ts": TS, "raw_w": NUM, "scale": NUM, "power_kw": NUM}),
    "Command": O({"command_id": STR, "lane": LANE, "ts": TS, "device_id": STR, "action": ACTION, "value": Nl(INT),
                  "decision_id": Nl(STR), "issued_by": E("engine", "owner")}),
    "CommandAck": O({"command_id": STR, "lane": LANE, "ok": BOOL, "applied_value": Nl(INT),
                     "reason": Nl(E("job_running", "already_off", "out_of_range", "unknown_device"))}),
    "Effect": O({"peak_before_kw": NUM, "peak_after_kw": NUM, "saving_usd": NUM}),
    "Decision": O({"decision_id": STR, "ts": TS, "device_id": STR, "action": ACTION, "value": Nl(INT), "reason_code": REASON,
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
    "RuleBreak": O({"kind": E("cap_overrun", "below_min_power", "past_deadline", "over_max_reduce", "over_max_delay"),
                    "device_id": STR, "amount": NUM, "unit": E("kW", "pct", "min")}, optional=("device_id",)),
    "EscalationOption": O({"option_id": STR, "summary": STR, "actions": L(R("Command")),
                           "projected": Nl(O({"peak_kw": NUM, "cost_delta_usd": NUM, "max_indoor_temp_change_c": Nl(NUM)})),
                           "rule_breaks": L(R("RuleBreak")), "within_authority": BOOL, "harm_score": Nl(NUM),
                           "rank": Nl(INT)}),
    "Escalation": O({"escalation_id": STR, "lane": LANE, "ts": TS, "updated_ts": TS, "block_start": TS,
                     "problem": O({"forecast_peak_kw": NUM, "target_kw": NUM, "excess_kw": NUM, "reason": STR}),
                     "options": L(R("EscalationOption")), "default_option_id": STR, "active_option_id": Nl(STR),
                     "deadline_sim_ts": TS, "status": ESC_STATUS,
                     "resolved_by": Nl(E("claude", "default")), "chosen_option_id": Nl(STR),
                     "rationale": Nl(STR), "claude_attempts": L(O({"ts": TS, "option_id": STR, "accepted": BOOL,
                         "reason": Nl(E("outside_authority", "after_deadline")), "rationale": Nl(STR)}))}),
    "Meter": O({"ts": TS, "total_kw": NUM, "block_avg_kw": NUM, "block_start": TS, "month_peak_kw": NUM,
                "on_peak_month_peak_kw": Nl(NUM), "peak_mode": PEAK_MODE, "peak_cap_kw": Nl(NUM), "target_kw": NUM,
                "energy_kwh_today": NUM, "energy_kwh_month": NUM, "price_usd_per_kwh_now": NUM, "cost_usd_today": NUM,
                "cost_usd_month": NUM, "demand_peaks": L(R("DemandPeak"))}),
    "DemandPeak": O({"name": STR, "peak_kw": NUM, "usd_per_kw": NUM, "cost_usd": NUM}),
    "TickState": O({"lane": LANE, "ts": TS, "hub": R("HubReport"), "meter": R("Meter"), "customers_per_hour": INT,
                    "new_decisions": L(R("Decision")), "new_commands": L(R("Command")),
                    "new_escalations": L(R("Escalation")), "warnings": L(R("Warning")), "indoor_temp_c": NUM,
                    "forecast_kw": Nl(L(NUM))}),
    "LaneComparison": O({"ts": TS, "saved_today_usd": NUM, "peak_avoided_kw": NUM, "month_peak_without_kw": NUM,
                         "month_peak_with_kw": NUM}),
    "Proposal": O({"proposal_id": STR, "ts": TS,
                   "kind": E("importance", "peak_cap", "authority", "undo_decision", "customer_event"),
                   "payload": DICT, "summary": STR, "status": E("pending", "confirmed", "cancelled", "expired"),
                   "created_by": E("ai"), "confirmed_via": Nl(E("ui", "asi_one")), "expires_at": TS}),
    "Bill": O({"period": YM, "energy_kwh": NUM, "energy_cost_usd": NUM,
               "demand_charges": L(O({"name": STR, "peak_kw": NUM, "cost_usd": NUM})), "fixed_usd": NUM, "total_usd": NUM,
               "tariff_id": STR}),
    "BacktestResult": O({"dataset": STR, "month": YM,
                         "policies": O({"without": R("Bill"), "timer": R("Bill"), "with": R("Bill")}),
                         "checks": O({"baseline_matches_raw": BOOL, "energy_conserved": BOOL, "rule_violations": INT}),
                         "assumptions_id": STR, "tariff_id": STR, "partial": BOOL, "saved_usd": NUM,
                         "saved_vs_timer_usd": NUM}),
    "PolicyCosts": O({"without": NUM, "timer": NUM, "with": NUM}),
    "BacktestPoint": O({"dataset": STR, "assumptions_id": STR, "tariff_id": STR, "month": YM, "day": DATE, "ts": TS,
                        "partial": BOOL, "cost_to_date_usd": R("PolicyCosts"), "saved_month_to_date_usd": NUM,
                        "saved_vs_timer_month_to_date_usd": NUM, "saved_year_to_date_usd": NUM}),
    "BacktestInputs": O({"config": R("KitchenConfig"), "tariff": R("Tariff"), "catalog": L(R("EquipmentType")), "seed": INT,
                         "series": R("WarmUpHistory"),
                         "assumptions": O({"assumptions_id": STR, "flex_scale": NUM, "draw_scale": NUM,
                                           "forecast_noise_pct": NUM})}),
    "AgentLog": O({"ts_real": TS, "from_agent": AGENT, "to_agent": AGENT, "kind": E("request", "response", "post", "error"),
                   "summary": STR}),
    "Snapshot": O({"tick_id": INT, "sim_ts": TS, "lane": LANE, "control": LANE, "peak_mode": PEAK_MODE,
                   "config": R("KitchenConfig"), "meter": R("Meter"), "forecast_kw": Nl(L(NUM)), "forecast_ts": Nl(TS),
                   "devices": L(R("Device")), "active_commands": L(R("Command")), "owed_kwh": DICT,
                   "open_escalations": L(R("Escalation")), "warnings": L(R("Warning")), "recent_decisions": L(R("Decision")),
                   "context": R("Context"), "id_counters": O({"d": INT, "c": INT, "e": INT})}),
    "Ok": O({"ok": BOOL}),
    "ClockState": O(dict(CLOCK_FIELDS)),
    "ErrorBody": O({"detail": STR}),
}
LIMITS_BY_IMP = {"always_on": O({}), "flexible": O({"min_power_pct": INT, "max_reduce_min": INT}),
                 "deferrable": O({"max_delay_min": INT, "must_finish_by": HM})}

WS = {
    "tick": O({"type": STR, "data": R("TickState")}),
    "decision": O({"type": STR, "data": R("Decision"), "explanation": STR, "explanation_source": E("ai", "template")}),
    "clock": O(dict({"type": STR}, **CLOCK_FIELDS)),
    "warning": ("ws_warning", None),
    "chat_delta": O({"type": STR, "chat_id": STR, "text": STR}),
    "chat_done": O({"type": STR, "chat_id": STR}),
    "backtest_progress": O({"type": STR, "run_id": STR, "month": YM, "pct": INT}),
    "backtest_point": O({"type": STR, "run_id": STR, "data": R("BacktestPoint")}),
    "backtest_month": O({"type": STR, "run_id": STR, "data": R("BacktestResult")}),
    "comparison": O({"type": STR, "data": R("LaneComparison")}),
    "proposal": O({"type": STR, "data": R("Proposal")}),
    "escalation": O({"type": STR, "data": R("Escalation"), "explanation": STR,
                     "explanation_source": E("ai", "template")}),
    "context": O({"type": STR, "data": R("Context")}),
    "agent_log": O({"type": STR, "data": R("AgentLog")}),
}
HUB = {
    "hub_hello": O({"type": STR, "protocol": INT, "hub_id": STR, "role": E("sim_host"), "client": STR}),
    "hub_report": O({"type": STR, "tick_id": INT, "reports": O({"without": R("HubReport"), "with": R("HubReport")})}),
    "hub_welcome": O({"type": STR, "accepted": BOOL, "reason": Nl(E("host_taken")), "tick_id": INT}),
    "sim_build": O({"type": STR, "kitchen_id": STR, "config": R("KitchenConfig"), "catalog": L(R("EquipmentType")),
                    "devices": L(R("Device")), "seed": INT, "start_sim_ts": TS}),
    "sim_tick": O({"type": STR, "tick_id": INT, "sim_ts": TS, "minutes": INT,
                   "surges": L(O({"surge_id": STR, "customers": INT, "duration_min": INT})),
                   "inputs": O({"outdoor_temp_c": Nl(NUM), "crowd_multiplier": NUM, "is_open": BOOL}),
                   "commands": L(R("Command")), "replay": BOOL, "fast_forward": BOOL}),
    "sim_control": O({"type": STR, "action": E("play", "pause", "reset"), "speed": INT, "paused_reason": PAUSED}),
}
ST = {
    "live_tick": O({"lane": LANE, "ts": TS, "tick_id": INT, "total_kw": NUM, "block_avg_kw": NUM, "month_peak_kw": NUM,
                    "on_peak_month_peak_kw": Nl(NUM), "peak_mode": PEAK_MODE, "peak_cap_kw": Nl(NUM), "target_kw": NUM,
                    "energy_kwh_today": NUM, "energy_kwh_month": NUM, "price_usd_per_kwh_now": NUM, "cost_usd_today": NUM,
                    "cost_usd_month": NUM, "demand_peaks_json": STR, "customers_per_hour": INT, "indoor_temp_c": NUM,
                    "forecast_kw_json": Nl(STR), "forecast_ts": Nl(TS)}),
    "tick_history": O({"lane": LANE, "ts": TS, "total_kw": NUM, "block_avg_kw": NUM}),
    "live_device": O({"key": STR, "lane": LANE, "device_id": STR, "type_id": STR, "name": STR, "importance": IMPORTANCE,
                      "state": E("off", "on", "reduced", "waiting", "running_job"), "power_kw": NUM, "rated_kw": NUM,
                      "power_pct": INT, "source": E("simulated", "measured"), "physical_json": Nl(STR)}),
    "live_comparison": O({"id": INT, "ts": TS, "saved_today_usd": NUM, "peak_avoided_kw": NUM,
                          "month_peak_without_kw": NUM, "month_peak_with_kw": NUM}),
    "live_feed": O({"decision_id": STR, "lane": LANE, "ts": TS, "device_id": STR, "action": ACTION, "value": Nl(INT),
                    "status": E("executed", "undone"), "reason_code": REASON, "effect_json": STR,
                    "explanation": STR, "explanation_source": E("ai", "template")}),
    "live_clock": O(dict({"id": INT, "sim_host": E("connected", "offline")}, **CLOCK_FIELDS)),
    "live_context": O({"id": INT, "weather_summary": STR, "weather_label": E("live_api", "recorded"), "prices_summary": STR,
                       "prices_label": E("live_api", "recorded"), "events_summary": STR,
                       "events_label": E("live_api", "recorded"), "crowd_effect": E("none", "small", "medium", "large")}),
    "live_escalation": O({"escalation_id": STR, "lane": LANE, "status": ESC_STATUS, "block_start": TS, "updated_ts": TS,
                          "problem_json": STR, "options_json": STR, "default_option_id": STR, "active_option_id": Nl(STR),
                          "deadline_sim_ts": TS, "chosen_option_id": Nl(STR),
                          "resolved_by": Nl(E("claude", "default")), "rationale": Nl(STR),
                          "claude_attempts_json": STR, "explanation": STR, "explanation_source": E("ai", "template")}),
    "live_agent_log": O({"id": INT, "ts_real": TS, "from_agent": AGENT, "to_agent": AGENT,
                         "kind": E("request", "response", "post", "error"), "summary": STR}),
    "surge_request": O({"id": INT, "customers": INT, "duration_min": INT, "requested_by": STR, "created_at": TS,
                        "consumed": BOOL}),
    "backtest_point": O({"key": STR, "run_id": STR, "day": DATE, "month": YM, "ts": TS, "partial": BOOL,
                         "cost_to_date_json": STR, "saved_month_to_date_usd": NUM, "saved_vs_timer_month_to_date_usd": NUM,
                         "saved_year_to_date_usd": NUM, "dataset": STR, "tariff_id": STR, "assumptions_id": STR}),
    "backtest_month": O({"key": STR, "run_id": STR, "month": YM, "partial": BOOL, "saved_usd": NUM, "saved_vs_timer_usd": NUM,
                         "policies_json": STR, "checks_json": STR, "dataset": STR, "tariff_id": STR, "assumptions_id": STR}),
}
PAYLOAD = O({"live_tick": L(ST["live_tick"]), "tick_history": L(ST["tick_history"]), "live_device": L(ST["live_device"]),
             "live_comparison": ST["live_comparison"]})


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
              "ym": lambda x: isinstance(x, str) and bool(YM_RE.match(x)),
              "date": lambda x: isinstance(x, str) and bool(DATE_RE.match(x)),
              "dict": lambda x: isinstance(x, dict), "any": lambda x: True}[spec](v)
        if not ok:
            fail(where, "expected %s, got %r" % (spec, v if not isinstance(v, (dict, list)) else type(v).__name__))
        return
    kind = spec[0]
    if kind in ("warning", "ws_warning"):
        base = {"code": STR, "message": STR, "data": DICT}
        if kind == "ws_warning":
            base["type"] = STR
        if not isinstance(v, dict) or v.get("code") not in WARNING_DATA:
            return fail(where, "unknown warning %r" % (v,))
        validate(v, O(base), where)
        return validate(v.get("data"), WARNING_DATA[v["code"]], where + ".data")
    if kind == "ref":
        name = spec[1]
        if name == "ImportanceLimits":
            if not isinstance(v, dict):
                return fail(where, "limits must be an object")
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


# ----------------------------------------------------------------------------- loading and time helpers
def load(rel):
    COUNT["files"] += 1
    with open(os.path.join(HERE, rel), encoding="utf-8") as f:
        if rel.endswith(".jsonl"):
            return [json.loads(line) for line in f if line.strip()]
        return json.load(f)


def files_under(folder):
    out = []
    for root, _, fs in os.walk(os.path.join(HERE, folder)):
        for f in fs:
            out.append(os.path.relpath(os.path.join(root, f), HERE))
    return sorted(out)


def pts(s):
    return datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)


def loc(dt):
    return (dt + LOCAL).replace(tzinfo=None)


def lmin(dt):
    x = loc(dt)
    return x.hour * 60 + x.minute


def near(a, b, tol=TOL):
    return abs(a - b) <= tol + 1e-9


def hm_min(hm):
    h, m = hm.split(":")
    return int(h) * 60 + int(m)


def half_up(x):
    return int(math.floor(x + 0.5))


def in_span(lm, a, b):
    """`[a, b)` local minutes; b < a wraps past midnight; a == b is empty (CONTRACTS.md section 1 Tariff)."""
    return a <= lm < b if a < b else (lm >= a or lm < b) if a > b else False


class Tariff:
    """Independent re-implementation of the tariff function (months, day types, windows, fixed charges)."""

    def __init__(self, t):
        self.t = t
        self.energy = [(hm_min(e["start"]), hm_min(e["end"]), e["usd_per_kwh"], e["months"], e["days"]) for e in t["energy"]]
        self.charges = [(c["name"], c["usd_per_kw"], None if c["windows"] is None else
                         [(hm_min(w["start"]), hm_min(w["end"])) for w in c["windows"]], c["months"], c["days"])
                        for c in t["demand"]]
        self.fixed_day = sum(f["usd"] for f in t["fixed_charges"] if f["per"] == "day")
        self.fixed_month = sum(f["usd"] for f in t["fixed_charges"] if f["per"] == "month")

    @staticmethod
    def _ok(months, days, d):
        dt_ = "weekends" if d.weekday() >= 5 else "weekdays"
        return (months is None or d.month in months) and days in ("all", dt_)

    def periods_at(self, d, lm):
        return [p for a, b, p, mo, dy in self.energy if self._ok(mo, dy, d) and in_span(lm, a, b)]

    def price(self, dt):
        x = loc(dt)
        hits = self.periods_at(x.date(), x.hour * 60 + x.minute)
        if len(hits) != 1:
            raise ValueError("%d energy periods at %s" % (len(hits), dt))
        return hits[0]

    def applicable(self, month):
        return [c for c in self.charges if c[3] is None or month in c[3]]

    def counts(self, c, bs):
        x = loc(bs)
        lm = x.hour * 60 + x.minute
        return self._ok(c[3], c[4], x.date()) and (c[2] is None or any(in_span(lm, a, b) for a, b in c[2]))

    def on_peak(self, month):
        win = [c for c in self.applicable(month) if c[2] is not None]
        return max(win, key=lambda c: c[1])[0] if win else None


def tariff_cover_pass(t, where):
    """Every local minute of the year: exactly one energy period (month x day type x minute)."""
    tc = Tariff(t)
    for month in range(1, 13):
        for d in (date(2026, month, 5), date(2026, month, 10)):       # one weekday and one weekend day of every month
            days = {d + timedelta(days=i) for i in range(7)}
            for day in sorted(days):
                if day.month != month:
                    continue
                for lm in range(0, 1440):
                    if len(tc.periods_at(day, lm)) != 1:
                        return fail(where, "month %d %s %02d:%02d: not exactly one energy period" % (
                            month, "weekend" if day.weekday() >= 5 else "weekday", lm // 60, lm % 60))
    for c in t["demand"]:
        for k in ("months",):
            if c[k] is not None and (not c[k] or any(not 1 <= m <= 12 for m in c[k])):
                fail(where, "demand %s months must be 1..12, non-empty" % c["name"])


def urdb_b19_pass(t):
    """shapes/tariff_pge_b19.json = the URDB record, hour by hour, when dataset/ is present (it is gitignored)."""
    src = os.path.join(REPO, "dataset", "tariffs", "pge_b19_secondary_voluntary_urdb_69de8cdb02f684104e01267d.json")
    if not os.path.exists(src):
        print("note: %s not found; B-19 URDB cross-check skipped" % os.path.relpath(src, REPO))
        return False
    with open(src, encoding="utf-8") as f:
        r = json.load(f)["items"][0]
    w = "shapes/tariff_pge_b19.json"
    if t["label"] != "urdb" or t["timezone"] != "America/Los_Angeles" or t["currency"] != "USD":
        fail(w, "label urdb, timezone America/Los_Angeles")
    tc = Tariff(t)
    e_rates = [p[0]["rate"] for p in r["energyratestructure"]]
    d_rates = [p[0]["rate"] for p in r["demandratestructure"]]
    for month in range(1, 13):
        for wkend, key_e, key_d in ((False, "energyweekdayschedule", "demandweekdayschedule"),
                                    (True, "energyweekendschedule", "demandweekendschedule")):
            day = next(date(2026, month, k) for k in range(1, 15) if (date(2026, month, k).weekday() >= 5) == wkend)
            for h in range(24):
                for mm in (0, 15, 30, 45):
                    lm = h * 60 + mm
                    if tc.periods_at(day, lm) != [e_rates[r[key_e][month - 1][h]]]:
                        fail(w, "energy price month %d %s %02d:%02d != URDB" % (month, "weekend" if wkend else "weekday",
                                                                               h, mm))
                    bs = datetime(day.year, day.month, day.day, h, mm, tzinfo=UTC) - LOCAL
                    tou = [c[1] for c in tc.applicable(month) if c[2] is not None and tc.counts(c, bs)]
                    want = d_rates[r[key_d][month - 1][h]]
                    if sorted(tou) != ([want] if want else []):
                        fail(w, "TOU demand month %d %02d:%02d: %s != URDB %s" % (month, h, mm, tou, want))
        flat = [c[1] for c in tc.applicable(month) if c[2] is None]
        if flat != [r["flatdemandstructure"][r["flatdemandmonths"][month - 1]][0]["rate"]]:
            fail(w, "flat demand month %d != URDB" % month)
    unit = {"$/day": "day", "$/month": "month"}.get(r["fixedchargeunits"])
    if t["fixed_charges"] != [{"name": "customer_charge", "usd": r["fixedchargefirstmeter"], "per": unit}]:
        fail(w, "fixed charge must be URDB fixedchargefirstmeter %s %s" % (r["fixedchargefirstmeter"], r["fixedchargeunits"]))
    return True


# ----------------------------------------------------------------------------- per-folder shape passes
SHAPE_FILES = {
    "equipment_catalog.json": L(R("EquipmentType")), "kitchen_config.json": R("KitchenConfig"),
    "kitchen_config_minimize.json": R("KitchenConfig"), "claude_authority.json": R("ClaudeAuthority"),
    "device.json": R("Device"), "device_measured.json": R("Device"),
    "hub_report_with.json": R("HubReport"), "hub_report_without.json": R("HubReport"), "reading.json": R("Reading"),
    "command.json": R("Command"), "command_ack_ok.json": R("CommandAck"), "command_ack_clamped.json": R("CommandAck"),
    "command_ack_rejected.json": R("CommandAck"), "command_owner.json": R("Command"), "tariff.json": R("Tariff"),
    "proposal_peak_cap.json": R("Proposal"), "proposal_authority.json": R("Proposal"),
    "proposal_undo_decision.json": R("Proposal"), "proposal_customer_event.json": R("Proposal"),
    "decision.json": R("Decision"), "decision_owner_override.json": R("Decision"), "context.json": R("Context"),
    "warning_cap_unreachable.json": R("Warning"),
    "escalation_open.json": R("Escalation"), "escalation_resolved_claude.json": R("Escalation"),
    "escalation_rejected_claude.json": R("Escalation"), "escalation_expired_default.json": R("Escalation"),
    "escalation_obsolete.json": R("Escalation"),
    "meter.json": R("Meter"), "tick_state_with.json": R("TickState"), "tick_state_without.json": R("TickState"),
    "lane_comparison.json": R("LaneComparison"), "proposal_pending.json": R("Proposal"),
    "proposal_confirmed.json": R("Proposal"), "bill.json": R("Bill"), "backtest_result.json": R("BacktestResult"),
    "backtest_point.json": R("BacktestPoint"), "backtest_inputs.json": R("BacktestInputs"),
    "tariff_pge_b19.json": R("Tariff"),
    "agent_log.json": R("AgentLog"), "warm_up_history.json": R("WarmUpHistory"),
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


SIM_CONTROL_REQ = O({"action": E("play", "pause", "reset", "next_day"), "speed": INT}, optional=("speed",))
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
    "put_peak_cap": ("PUT", r"^/api/kitchen/peak-cap$", O({"peak_mode": PEAK_MODE, "peak_cap_kw": Nl(NUM)}), R("Meter")),
    "put_peak_cap_422": ("PUT", r"^/api/kitchen/peak-cap$", O({"peak_mode": PEAK_MODE, "peak_cap_kw": Nl(NUM)}), R("ErrorBody")),
    "post_sim_control": ("POST", r"^/api/sim/control$", SIM_CONTROL_REQ, R("ClockState")),
    "post_sim_control_next_day": ("POST", r"^/api/sim/control$", SIM_CONTROL_REQ, R("ClockState")),
    "post_sim_control_422": ("POST", r"^/api/sim/control$", SIM_CONTROL_REQ, R("ErrorBody")),
    "post_device_command": ("POST", r"^/api/devices/[a-z_]+_\d+/command$", O({"action": ACTION, "value": INT},
                                                                              optional=("value",)), R("Command")),
    "post_device_command_404": ("POST", r"^/api/devices/[a-z_]+_\d+/command$", O({"action": ACTION, "value": INT},
                                                                                  optional=("value",)), R("ErrorBody")),
    "post_events_customers": ("POST", r"^/api/events/customers$", O({"customers": INT, "duration_min": INT}), R("Ok")),
    "post_decision_undo": ("POST", r"^/api/decisions/d_\d{4}/undo$", None, R("Decision")),
    "post_decision_undo_422": ("POST", r"^/api/decisions/d_\d{4}/undo$", None, R("ErrorBody")),
    "post_decision_undo_404": ("POST", r"^/api/decisions/d_\d{4}/undo$", None, R("ErrorBody")),
    "get_decisions": ("GET", r"^/api/decisions\?limit=\d+$", None, L(R("Decision"))),
    "post_backtest_run": ("POST", r"^/api/backtest/run$", O({"months": L(YM), "assumptions_id": STR}), O({"run_id": STR})),
    "get_backtest": ("GET", r"^/api/backtest/run_\d{4}$", None, L(R("BacktestResult"))),
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
    "post_agent_log": ("POST", r"^/api/agent-log$", R("AgentLog"), R("Ok")),
    "get_health": ("GET", r"^/api/health$", None,
                   O({"ok": BOOL, "kitchen_impl": E("fake", "real"), "live_transport": E("spacetime", "ws"),
                      "store": E("convex", "memory"), "hardware": E("off", "sim_bridge", "esp32"),
                      "sim_host": E("connected", "offline")})),
}

FACADE_SPECS = {   # file -> (call, args spec, returns spec)
    "kitchen.json": ("Kitchen", O({"config": R("KitchenConfig"), "tariff": R("Tariff"),
                                   "catalog": L(R("EquipmentType")), "control": LANE, "seed": INT,
                                   "ids": Nl(ANY)}), None),
    "warm_up.json": ("warm_up", O({"history": R("WarmUpHistory")}), None),
    "ingest_reading.json": ("ingest_reading", O({"reading": R("Reading")}), R("Device")),
    "owner_command.json": ("owner_command", O({"device_id": STR, "action": ACTION, "value": Nl(INT)}), R("Command")),
    "set_importance.json": ("set_importance", O({"device_id": STR, "importance": IMPORTANCE,
                                                 "limits": R("ImportanceLimits")}), R("Device")),
    "set_importance_rule_error.json": ("set_importance", O({"device_id": STR, "importance": IMPORTANCE,
                                                            "limits": R("ImportanceLimits")}), None),
    "set_peak_cap.json": ("set_peak_cap", O({"peak_mode": PEAK_MODE, "peak_cap_kw": Nl(NUM)}), R("Meter")),
    "set_peak_cap_rule_error.json": ("set_peak_cap", O({"peak_mode": PEAK_MODE, "peak_cap_kw": Nl(NUM)}), None),
    "undo.json": ("undo", O({"decision_id": STR}), R("Decision")),
    "set_context.json": ("set_context", O({"context": R("Context")}), None),
    "set_authority.json": ("set_authority", O({"authority": R("ClaudeAuthority")}), None),
    "set_preferences.json": ("set_preferences", O({"text": STR}), None),
    "open_escalations.json": ("open_escalations", O({}), L(R("Escalation"))),
    "resolve_escalation.json": ("resolve_escalation", O({"escalation_id": STR, "option_id": STR,
                                                         "resolved_by": E("claude"),
                                                         "rationale": Nl(STR)}), R("Escalation")),
    "forecast.json": ("forecast", O({"horizon_min": INT}), L(NUM)),
    "what_if.json": ("what_if", O({"device_id": STR, "action": ACTION, "value": Nl(INT), "at": TS}), R("Effect")),
    "snapshot.json": ("snapshot", O({}), R("Snapshot")),
    "run_backtest.json": ("run_backtest", O({"inputs": R("BacktestInputs"), "months": L(YM), "assumptions_id": STR,
                                             "on_progress": Nl(ANY)}), L(R("BacktestResult"))),
    "compare_lanes.json": ("compare_lanes", O({"without": R("TickState"), "with_": R("TickState")}), R("LaneComparison")),
}
AI_SPECS = {
    "get_kitchen_state.json": (O({}), R("Snapshot")),
    "get_forecast.json": (O({}), L(NUM)),
    "what_if.json": (O({"device_id": STR, "action": ACTION, "value": Nl(INT), "at": TS, "lane": LANE}, optional=("lane",)),
                     R("Effect")),
    "get_bill.json": (O({"period": YM}), R("Bill")),
    "explain_decision.json": (O({"decision_id": STR}), R("Decision")),
    "propose_importance_change.json": (O({"device_id": STR, "importance": IMPORTANCE, "limits": R("ImportanceLimits"),
                                          "summary": STR}), R("Proposal")),
    "propose_peak_cap_change.json": (O({"peak_mode": PEAK_MODE, "peak_cap_kw": Nl(NUM), "summary": STR}), R("Proposal")),
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
    for t in ("hub_hello", "hub_welcome_accepted", "hub_welcome_host_taken", "sim_build", "sim_tick", "sim_tick_replay",
              "sim_tick_overnight", "hub_report", "sim_control", "server_to_hub", "hub_to_server"):
        ext = ".jsonl" if t in ("server_to_hub", "hub_to_server") else ".json"
        if not os.path.exists(os.path.join(HERE, "hub_protocol", t + ext)):
            fail("hub_protocol/%s%s" % (t, ext), "missing")
    if not store["hub_protocol/sim_tick_replay.json"]["replay"] or store["hub_protocol/sim_tick.json"]["replay"]:
        fail("hub_protocol", "sim_tick_replay.json must have replay true, sim_tick.json false")
    ov = store["hub_protocol/sim_tick_overnight.json"]
    if not ov["fast_forward"] or ov["inputs"]["is_open"]:
        fail("sim_tick_overnight.json", "must be fast_forward true with is_open false")
    hw = store["hub_protocol/hub_welcome_host_taken.json"]
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


def ws_messages(msgs, where):
    for i, m in enumerate(msgs):
        t = m.get("type")
        if t not in WS:
            fail("%s[%d]" % (where, i), "unknown ws type %r" % t)
            continue
        validate(m, WS[t], "%s[%d]" % (where, i))


def ws_pass(store):
    for f in files_under("ws"):
        obj = load(f)
        store[f] = obj
        ws_messages(obj if f.endswith(".jsonl") else [obj], f)
    for t in WS:
        if not os.path.exists(os.path.join(HERE, "ws", t + ".json")):
            fail("ws/%s.json" % t, "missing")


def steps_shape(rows, where):
    for i, r in enumerate(rows):
        if check_wrapper(r, ("args", "returns"), "%s[%d]" % (where, i)):
            validate(r["args"], O({"minutes": INT, "hub_report": R("HubReport")}), "%s[%d].args" % (where, i))
            validate(r["returns"], R("TickState"), "%s[%d].returns" % (where, i))


def facade_pass(store):
    for name, (call, args, ret) in FACADE_SPECS.items():
        f = "facade/" + name
        obj = load(f)
        store[f] = obj
        keys = ("call", "args", "returns", "raises") if name.endswith("rule_error.json") else \
            ("call", "note", "args", "returns") if name == "run_backtest.json" else ("call", "args", "returns")
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
    steps_shape(rows, "facade/step_stream.jsonl")
    ev = load("facade/run_backtest_on_progress.jsonl")
    store["facade/run_backtest_on_progress.jsonl"] = ev
    for i, m in enumerate(ev):
        w = "facade/run_backtest_on_progress.jsonl[%d]" % i
        spec = {"backtest_point": O({"type": STR, "data": R("BacktestPoint")}),
                "backtest_month": O({"type": STR, "data": R("BacktestResult")}),
                "backtest_progress": O({"type": STR, "month": YM, "pct": INT})}.get(m.get("type"))
        if spec is None:
            fail(w, "unknown on_progress event %r" % m.get("type"))
        else:
            validate(m, spec, w)
    for f in files_under("facade"):
        if os.path.basename(f) not in FACADE_SPECS and not f.endswith(("step_stream.jsonl", "run_backtest_on_progress.jsonl")):
            fail(f, "unexpected facade file")
    if store["facade/forecast.json"]["args"]["horizon_min"] != 120 or len(store["facade/forecast.json"]["returns"]) != 8:
        fail("facade/forecast.json", "horizon_min 120 -> 8 values")


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


REDUCER_ARGS = {"publish_ticks": 1, "publish_feed": 1, "set_clock": 9, "publish_context": 1, "publish_escalation": 1,
                "log_agent": 1, "reset_all": 0, "request_surge": 2, "consume_surge": 1, "publish_backtest_point": 1,
                "publish_backtest_month": 1, "reset_backtest": 1}
SET_CLOCK_ARGS = ("playing", "speed", "sim_ts", "tick_id", "paused_reason", "day_index", "run_days", "phase", "sim_host")


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
    for r, nargs in REDUCER_ARGS.items():
        f = "spacetime/reducers/%s.json" % r
        obj = load(f)
        store[f] = obj
        if check_wrapper(obj, ("reducer", "args"), f):
            if obj["reducer"] != r or not isinstance(obj["args"], list) or len(obj["args"]) != nargs:
                fail(f, "reducer/args")
    validate(json.loads(store["spacetime/reducers/publish_ticks.json"]["args"][0]), PAYLOAD, "publish_ticks.payload_json")
    validate(json.loads(store["spacetime/reducers/publish_feed.json"]["args"][0]), ST["live_feed"], "publish_feed arg")
    validate(json.loads(store["spacetime/reducers/publish_context.json"]["args"][0]), ST["live_context"], "publish_context")
    validate(json.loads(store["spacetime/reducers/publish_escalation.json"]["args"][0]), ST["live_escalation"],
             "publish_escalation")
    validate(json.loads(store["spacetime/reducers/log_agent.json"]["args"][0]), R("AgentLog"), "log_agent")
    validate(json.loads(store["spacetime/reducers/publish_backtest_point.json"]["args"][0]), ST["backtest_point"],
             "publish_backtest_point")
    validate(json.loads(store["spacetime/reducers/publish_backtest_month.json"]["args"][0]), ST["backtest_month"],
             "publish_backtest_month")
    validate(store["spacetime/reducers/reset_backtest.json"]["args"][0], STR, "reset_backtest")
    for r in store["spacetime/tables/live_tick.json"]:
        validate(json.loads(r["demand_peaks_json"]), L(R("DemandPeak")), "live_tick.demand_peaks_json")
    for r in store["spacetime/tables/backtest_point.json"]:
        validate(json.loads(r["cost_to_date_json"]), R("PolicyCosts"), "backtest_point.cost_to_date_json")
        if r["key"] != "%s:%s" % (r["run_id"], r["day"]) or not r["day"].startswith(r["month"] + "-"):
            fail("backtest_point", "key <run_id>:<day>, day in month")
    for r in store["spacetime/tables/backtest_month.json"]:
        validate(json.loads(r["policies_json"]), O({"without": R("Bill"), "timer": R("Bill"), "with": R("Bill")}),
                 "backtest_month.policies_json")
        if r["key"] != "%s:%s" % (r["run_id"], r["month"]):
            fail("backtest_month", "key <run_id>:<month>")
    validate(dict(zip(SET_CLOCK_ARGS, store["spacetime/reducers/set_clock.json"]["args"]), id=0), ST["live_clock"], "set_clock")
    c, d = store["spacetime/reducers/request_surge.json"]["args"]
    if not (1 <= c <= 80 and 15 <= d <= 120):
        fail("request_surge", "customers 1-80, duration 15-120")
    rows = load("spacetime/rows_stream.jsonl")
    store["spacetime/rows_stream.jsonl"] = rows
    for i, p in enumerate(rows):
        validate(p, PAYLOAD, "rows_stream[%d]" % i)
    for t_ in ("live_clock", "live_context", "live_comparison"):
        if any(r["id"] != 0 for r in store["spacetime/tables/%s.json" % t_]):
            fail("spacetime/tables/%s.json" % t_, "single-row table id must be 0")
    for r in store["spacetime/tables/live_device.json"]:
        if r["key"] != "%s:%s" % (r["lane"], r["device_id"]):
            fail("live_device", "key must be <lane>:<device_id>")
    clock_row = store["spacetime/tables/live_clock.json"][0]
    if store["spacetime/reducers/set_clock.json"]["args"] != [clock_row[k] for k in SET_CLOCK_ARGS]:
        fail("set_clock.json", "args must be the live_clock row in contract order")


def convex_pass(store):
    for t, spec in CONVEX.items():
        f = "convex/tables/%s.json" % t
        obj = load(f)
        store[f] = obj
        validate(obj, L(spec), f)
    fn = {"commands_forDevice": ("commands:forDevice", "query", O({"hub_id": STR}), L(R("Command"))),
          "commands_ack": ("commands:ack", "mutation", O({"command_id": STR, "ok": BOOL, "applied_value": Nl(INT),
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


# ----------------------------------------------------------------------------- history + daily inputs + backtest
def history_pass(store, cfg, tariff, roster):
    hist = load("history/warmup_demo_cafe.json")
    store["history/warmup_demo_cafe.json"] = hist
    validate(hist, R("WarmUpHistory"), "history/warmup_demo_cafe.json")
    if (hist["source"], hist["label"]) != ("fixture_synthetic", "simulated") or hist["month_to_date"] is not None or \
            hist["day_offset"] != 0:
        fail("history", "fixture history: fixture_synthetic / simulated, day_offset 0, month_to_date null (this build)")
    start, end = pts(hist["start"]), pts(hist["end"])
    if loc(start) != datetime(2026, 5, 17, 0, 0) or loc(end) != datetime(2026, 7, 17, 17, 30):
        fail("history", "window must be 2026-05-17 00:00 -> 2026-07-17 17:30 local")
    prev, group, totals = None, [], []
    order = list(roster)

    def close(bs, grp):
        if [b["device_id"] for b in grp] != order:
            fail("history %s" % bs, "every roster device once per block, roster order")
        totals.append((pts(bs), sum(b["avg_kw"] for b in grp)))
    for b in hist["blocks"]:
        if b["avg_kw"] < 0 or round(b["avg_kw"], 3) != b["avg_kw"]:
            fail("history %s" % b["block_start"], "avg_kw >= 0 with 3 decimals")
        dt = pts(b["block_start"])
        if dt.minute % 15 or dt < start or dt + timedelta(minutes=15) > end:
            fail("history %s" % b["block_start"], "blocks aligned and ending at or before `end`")
        if b["block_start"] != prev:
            if prev is not None:
                if pts(b["block_start"]) != pts(prev) + timedelta(minutes=15):
                    fail("history %s" % b["block_start"], "blocks sorted and contiguous")
                close(prev, group)
            prev, group = b["block_start"], []
        group.append(b)
    close(prev, group)
    if totals[0][0] != start or totals[-1][0] + timedelta(minutes=15) != end:
        fail("history", "blocks must cover start..end")
    peaks = {}
    for bs, t in totals:
        d = loc(bs).date()
        peaks[d] = max(peaks.get(d, 0.0), t)
    month_peaks = {}
    for d, p in peaks.items():
        month_peaks[d.month] = max(month_peaks.get(d.month, 0.0), p)
    if not all(38.0 <= month_peaks[m] <= 46.0 for m in (5, 6, 7)):
        fail("history", "monthly peaks should be around 38-46 kW, got %s" % month_peaks)
    lights = [b for b in hist["blocks"] if b["device_id"] == "lights_1"]
    for b in lights:
        lm = lmin(pts(b["block_start"]))
        exp = 2.4 if hm_min(cfg["operating_hours"]["open"]) <= lm < hm_min(cfg["operating_hours"]["close"]) else 0.24
        if not near(b["avg_kw"], exp, 0.001):
            fail("history lights %s" % b["block_start"], "lights at rated while open, 10 %% while closed")
            break
    di = load("history/daily_inputs.json")
    store["history/daily_inputs.json"] = di
    days = {d["date"]: d for d in di["days"]}
    want = [(date(2026, 5, 17) + timedelta(days=i)).isoformat() for i in range(68)]
    if sorted(days) != want:
        fail("daily_inputs", "days must be 2026-05-17 .. 2026-07-23 (history + 7 live days)")
    for d in di["days"]:
        if len(d["hourly_outdoor_temp_c"]) != 24 or len(d["hourly_grid_usd_per_kwh"]) != 24 or \
                d["crowd_effect"] not in di["crowd_multiplier"]:
            fail("daily_inputs %s" % d["date"], "24 hourly values and a crowd_effect category")
        if d["weekday"] != ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][
                date.fromisoformat(d["date"]).weekday()]:
            fail("daily_inputs %s" % d["date"], "weekday")
        for s in d["surges"]:
            if d["in_live"] and not re.match(r"^s_\d{4}$", s["surge_id"] or ""):
                fail("daily_inputs %s" % d["date"], "live surges carry their surge_id")
    if sum(1 for d in di["days"] if d["events"] and d["in_history"] and not d["in_live"]) != 1:
        fail("daily_inputs", "exactly one event night in the history")
    # backtest = the history billed on the tariff (without), energy conserved by the other policies; daily points
    rows_by_month = {}
    for bs, t in totals:
        x = loc(bs)
        rows_by_month.setdefault("%04d-%02d" % (x.year, x.month), []).append((bs, t))
    bt = load("rest/get_backtest.json")["response"]
    for r in bt:
        rows = rows_by_month[r["month"]]
        mo = int(r["month"][5:])
        b = r["policies"]["without"]
        e = sum(t * 0.25 for _, t in rows)
        c = sum(t * 0.25 * tariff.price(bs) for bs, t in rows)
        if not near(b["energy_kwh"], e, 0.002) or not near(b["energy_cost_usd"], c, 0.01):
            fail("backtest %s" % r["month"], "without bill must be the history billed on the tariff")
        app = tariff.applicable(mo)
        if [dc["name"] for dc in b["demand_charges"]] != [ch[0] for ch in app]:
            fail("backtest %s" % r["month"], "demand_charges = the charges that apply in the month, tariff order")
        for dc, ch in zip(b["demand_charges"], app):
            pk = max([t for bs, t in rows if tariff.counts(ch, bs)] or [0.0])
            if not near(dc["peak_kw"], pk, 0.002):
                fail("backtest %s" % r["month"], "demand charge %s peak" % ch[0])
        ndays = len({loc(bs).date() for bs, _ in rows})
        for p in ("without", "timer", "with"):
            if not near(r["policies"][p]["energy_kwh"], b["energy_kwh"], 0.002):
                fail("backtest %s" % r["month"], "%s policy must conserve energy" % p)
            if not near(r["policies"][p]["fixed_usd"], tariff.fixed_day * ndays + tariff.fixed_month):
                fail("backtest %s" % r["month"], "%s fixed_usd = fixed charges of the metered days" % p)
        if not r["checks"]["baseline_matches_raw"] or not r["checks"]["energy_conserved"] or r["checks"]["rule_violations"]:
            fail("backtest %s" % r["month"], "checks must all pass")
        if "simulated" not in r["dataset"].lower():
            fail("backtest %s" % r["month"], "dataset label must say simulated fixture data")
        pol = r["policies"]
        if not near(r["saved_usd"], pol["without"]["total_usd"] - pol["with"]["total_usd"]) or \
                not near(r["saved_vs_timer_usd"], pol["timer"]["total_usd"] - pol["with"]["total_usd"]):
            fail("backtest %s" % r["month"], "saved_usd = without - with, saved_vs_timer_usd = timer - with")
        y_, m_ = int(r["month"][:4]), mo
        n_cal = (date(y_ + m_ // 12, m_ % 12 + 1, 1) - date(y_, m_, 1)).days
        if r["partial"] != (ndays < n_cal):
            fail("backtest %s" % r["month"], "partial iff fewer scored days than calendar days")
        if r["tariff_id"] != tariff.t["tariff_id"] or any(pol[p]["tariff_id"] != r["tariff_id"] for p in pol):
            fail("backtest %s" % r["month"], "tariff_id")
    if [r["month"] for r in bt] != ["2026-06", "2026-07"]:
        fail("backtest", "months 2026-06 and 2026-07")
    # points: one per local day, in order; the last of a month equals the month's saved_usd to the cent; year to date
    pts_ = [m["data"] for m in load("facade/run_backtest_on_progress.jsonl") if m["type"] == "backtest_point"]
    by_month = {r["month"]: r for r in bt}
    before, prev_month = 0.0, None
    for i, p in enumerate(pts_):
        w = "backtest point %s" % p["day"]
        r = by_month.get(p["month"])
        if r is None or not p["day"].startswith(p["month"] + "-") or p["partial"] != r["partial"] or \
                p["tariff_id"] != r["tariff_id"] or p["dataset"] != r["dataset"] or p["assumptions_id"] != r["assumptions_id"]:
            fail(w, "point fields must match its month's BacktestResult")
            continue
        if prev_month is not None and p["month"] != prev_month:
            before += by_month[prev_month]["saved_usd"]
        prev_month = p["month"]
        d = date.fromisoformat(p["day"])
        if i and date.fromisoformat(pts_[i - 1]["day"]) + timedelta(days=1) != d:
            fail(w, "one point per local day, consecutive")
        if pts(p["ts"]) != datetime(d.year, d.month, d.day, tzinfo=UTC) - LOCAL + timedelta(days=1):
            fail(w, "ts = end of the local day (UTC)")
        rows = [(bs, t) for bs, t in rows_by_month[p["month"]] if loc(bs).date() <= d]
        mo = d.month
        e_c = sum(t * 0.25 * tariff.price(bs) for bs, t in rows)
        dem = sum(round(max([t for bs, t in rows if tariff.counts(ch, bs)] or [0.0]), 3) * ch[1]
                  for ch in tariff.applicable(mo))
        fx = tariff.fixed_day * len({loc(bs).date() for bs, _ in rows}) + tariff.fixed_month
        if not near(p["cost_to_date_usd"]["without"], e_c + dem + fx, 0.03):
            fail(w, "cost_to_date_usd.without = month-to-date bill (energy + demand on the peaks so far + fixed)")
        c = p["cost_to_date_usd"]
        if not near(p["saved_month_to_date_usd"], c["without"] - c["with"]) or \
                not near(p["saved_vs_timer_month_to_date_usd"], c["timer"] - c["with"]) or \
                not near(p["saved_year_to_date_usd"], before + p["saved_month_to_date_usd"]):
            fail(w, "saved_* arithmetic")
        last = i + 1 == len(pts_) or pts_[i + 1]["month"] != p["month"]
        if last:
            for k in ("without", "timer", "with"):
                if c[k] != r["policies"][k]["total_usd"]:
                    fail(w, "last point of the month: cost_to_date_usd.%s must equal the bill total" % k)
            if p["saved_month_to_date_usd"] != r["saved_usd"]:
                fail(w, "last point of the month must equal saved_usd to the cent")
    if sorted({p["month"] for p in pts_}) != ["2026-06", "2026-07"]:
        fail("backtest points", "every replayed month")
    return hist, totals, di


def meter_from_history(totals, tariff, start):
    """The meter at the start of the run: the engine meters the current month's history blocks (month_to_date null)."""
    day = loc(start - timedelta(minutes=1)).date()
    peaks = {c[0]: 0.0 for c in tariff.charges}
    month_peak = 0.0
    mid = None
    e_t = c_t = e_m = c_m = 0.0
    for bs, t in totals:
        d = loc(bs).date()
        if (d.year, d.month) != (day.year, day.month):
            continue
        if d == day and mid is None:
            mid = dict(peaks)
        e = t * 0.25
        c = e * tariff.price(bs)
        e_m += e
        c_m += c
        if d == day:
            e_t += e
            c_t += c
        month_peak = max(month_peak, t)
        for ch in tariff.applicable(d.month):
            if tariff.counts(ch, bs):
                peaks[ch[0]] = max(peaks[ch[0]], t)
    return {"e_today": e_t, "c_today": c_t, "e_month": e_m, "c_month": c_m, "peaks": peaks, "mid": mid or dict(peaks),
            "month_peak": month_peak, "day": day}


def check_demand_peaks(m, tariff, month, lw):
    """Meter demand_peaks: the charges that apply this month, tariff order, cost = usd_per_kw x peak_kw; on_peak = the
    highest-rate windowed charge's peak."""
    app = tariff.applicable(month)
    dps = m["demand_peaks"]
    if [d["name"] for d in dps] != [c[0] for c in app] or any(d["usd_per_kw"] != c[1] for d, c in zip(dps, app)):
        fail(lw, "demand_peaks: one per charge that applies this month, tariff order, its rate")
    for d in dps:
        if not near(d["cost_usd"], d["usd_per_kw"] * d["peak_kw"]):
            fail(lw, "demand_peaks %s cost_usd = usd_per_kw x peak_kw" % d["name"])
    op = tariff.on_peak(month)
    want = None if op is None else next((d["peak_kw"] for d in dps if d["name"] == op), None)
    if m["on_peak_month_peak_kw"] != want:
        fail(lw, "on_peak_month_peak_kw = the highest-rate windowed charge's month peak")
    return {d["name"]: d["peak_kw"] for d in dps}


# ----------------------------------------------------------------------------- run streams (evening and multi-day)
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


def harm(breaks, devices, auth):
    h = 0.0
    for b in breaks:
        k = b["kind"]
        if k == "cap_overrun":
            tol = auth["max_cap_overrun_kw"] or 3.0
        elif k in ("past_deadline", "over_max_delay"):
            tol = auth["max_extra_delay_min"] or 20
        elif k == "over_max_reduce":
            tol = auth["max_extra_reduce_min"] or 15
        else:
            dv = devices[b["device_id"]]
            tol = dv["limits"]["min_power_pct"] - (50 if dv["type"]["category"] == "refrigeration" else 0)
        h += b["amount"] / tol
    return h


def check_escalation(e, devices, auth, cap):
    w = "escalation %s (%s)" % (e["escalation_id"], e["status"])
    ids = [o["option_id"] for o in e["options"]]
    alts = e["options"]
    if not (1 <= len(alts) <= 3) or "accept_overrun" not in ids or len(set(ids)) != len(ids):
        fail(w, "1-3 evaluated alternatives, accept_overrun always, unique ids")
    for o in alts:
        if not re.match(r"^(accept_overrun|deep_reduce_[a-z_]+|extend_delay_[a-z_]+)$", o["option_id"]):
            fail(w, "option id %s" % o["option_id"])
        for a in o["actions"]:
            if a["lane"] != e["lane"] or a["issued_by"] != "engine" or a["decision_id"] is not None:
                fail(w, "option action: same lane, issued_by engine, decision_id null (template)")
            if o["option_id"].startswith("deep_reduce_") and devices[a["device_id"]]["type"]["type_id"] != o["option_id"][12:]:
                fail(w, "deep_reduce_<type_id> acts on that type only")
            if o["option_id"].startswith("extend_delay_") and devices[a["device_id"]]["type"]["type_id"] != o["option_id"][13:]:
                fail(w, "extend_delay_<type_id> acts on that type only")
            check_move(a["device_id"], a["action"], a["value"], devices[a["device_id"]], w + " " + o["option_id"],
                       allow_break=True, breaks=o["rule_breaks"])
        exp = auth["enabled"]
        for b in o["rule_breaks"]:
            if b["kind"] == "cap_overrun":
                exp = exp and b["amount"] <= auth["max_cap_overrun_kw"]
                if not near(b["amount"], o["projected"]["peak_kw"] - cap, 0.06) or "device_id" in b or b["unit"] != "kW":
                    fail(w, "cap_overrun amount = projected peak - target, unit kW, no device")
            elif b["kind"] == "below_min_power":
                exp = exp and auth["may_go_below_min_power"]
                if b["unit"] != "pct":
                    fail(w, "food-safety option generated / unit pct")
            elif b["kind"] in ("past_deadline", "over_max_delay"):
                exp = exp and b["amount"] <= auth["max_extra_delay_min"]
                if b["unit"] != "min":
                    fail(w, "delay breaks in min")
            elif b["kind"] == "over_max_reduce":
                exp = exp and b["amount"] <= auth["max_extra_reduce_min"]
                if b["unit"] != "min":
                    fail(w, "over_max_reduce in min")
        if o["projected"]["peak_kw"] > cap + 0.05 and not any(b["kind"] == "cap_overrun" for b in o["rule_breaks"]):
            fail(w, "%s projects over the target without a cap_overrun break" % o["option_id"])
        if o["projected"]["max_indoor_temp_change_c"] is not None:
            fail(w, "max_indoor_temp_change_c must be null (not modelled in this build)")
        if o["within_authority"] != exp:
            fail(w, "%s within_authority should be %s" % (o["option_id"], exp))
        if o["harm_score"] is None or not near(o["harm_score"], harm(o["rule_breaks"], devices, auth), 0.002):
            fail(w, "%s harm_score must be sum(amount / tolerance)" % o["option_id"])
    order = sorted(alts, key=lambda o: (not o["within_authority"], o["harm_score"], o["projected"]["cost_delta_usd"],
                                        len({a["device_id"] for a in o["actions"]}), o["option_id"]))
    if [o["rank"] for o in order] != list(range(1, len(alts) + 1)):
        fail(w, "rank: within authority first, then harm, cost, fewer devices, option_id")
    top = order[0]
    if e["default_option_id"] != (top["option_id"] if top["within_authority"] else "accept_overrun"):
        fail(w, "default must be rank 1 if within authority, else accept_overrun")
    p = e["problem"]
    acc = next(o for o in alts if o["option_id"] == "accept_overrun")
    if not near(p["excess_kw"], p["forecast_peak_kw"] - p["target_kw"], 0.06) or p["target_kw"] != cap or \
            p["forecast_peak_kw"] <= p["target_kw"] or not near(acc["projected"]["peak_kw"], p["forecast_peak_kw"], 0.06):
        fail(w, "problem: forecast after in-rules moves (= accept_overrun peak) over the target, excess = it - target")
    ts, bs = pts(e["ts"]), pts(e["block_start"])
    if pts(e["deadline_sim_ts"]) != max(ts + timedelta(minutes=5), min(ts + timedelta(minutes=15), bs - timedelta(minutes=5))):
        fail(w, "deadline = max(ts + 5, min(ts + 15, block_start - 5))")
    if bs - ts >= timedelta(minutes=30) or bs + timedelta(minutes=15) <= ts or bs.minute % 15:
        fail(w, "opens for a block starting within 30 min (the block in progress included)")
    if pts(e["updated_ts"]) < ts:
        fail(w, "updated_ts before ts")
    st = e["status"]
    fallback = e["default_option_id"]
    if st in ("open", "expired_default", "obsolete") and e["active_option_id"] != fallback:
        fail(w, "active_option_id must stay the fallback until a resolve")
    if st == "open" and (e["resolved_by"] or e["chosen_option_id"] or e["rationale"]):
        fail(w, "open escalation has a resolution")
    if st == "resolved":
        if e["chosen_option_id"] not in ids or e["resolved_by"] != "claude" or e["active_option_id"] != e["chosen_option_id"]:
            fail(w, "resolved: chosen option by claude, now active")
        if e["resolved_by"] == "claude" and not next(o for o in e["options"] if o["option_id"] == e["chosen_option_id"])[
                "within_authority"]:
            fail(w, "claude resolved outside authority")
    if sum(pts(a["ts"]) < pts(e["deadline_sim_ts"]) for a in e["claude_attempts"]) > 2:
        fail(w, "Claude gets one retry")
    for attempt in e["claude_attempts"]:
        if attempt["option_id"] not in ids or attempt["accepted"] != (attempt["reason"] is None):
            fail(w, "attempt records a valid option and acceptance/rejection reason")
        if attempt["accepted"] and pts(attempt["ts"]) >= pts(e["deadline_sim_ts"]):
            fail(w, "accepted Claude attempt after deadline")
    if st == "expired_default" and (e["resolved_by"] != "default" or pts(e["updated_ts"]) < pts(e["deadline_sim_ts"])):
        fail(w, "expired_default: resolved_by default, at or after the deadline")
    if st == "obsolete" and (e["resolved_by"] is not None or e["chosen_option_id"] is not None):
        fail(w, "obsolete keeps resolved_by null")


def run_pass(name, store, s2h, h2s, steps, rows, ws, clocks, cfg, tariff, catalog, hist_totals, daily, sc, every_tick):
    """Invariants of one run's streams (the files may hold several contiguous segments)."""
    W = name
    cap, auth = cfg["peak_cap_kw"], cfg["authority"]
    open_m, close_m = hm_min(cfg["operating_hours"]["open"]), hm_min(cfg["operating_hours"]["close"])
    devices = {}
    for eq in cfg["equipment"]:
        for i in range(1, eq["count"] + 1):
            devices["%s_%d" % (eq["type_id"], i)] = {"importance": eq["importance"], "limits": eq["limits"],
                                                     "type": catalog[eq["type_id"]]}
    start = pts(sc["start_sim_ts"])
    last_tick = sc["ticks"]
    run_days = cfg["run_days"]
    days = {d["date"]: d for d in daily["days"]}
    crowd_mult = daily["crowd_multiplier"]
    if [m["type"] for m in s2h[:2]] != ["hub_welcome", "sim_build"] or not s2h[0]["accepted"]:
        fail(W, "server_to_hub must start with an accepted hub_welcome and sim_build")
    if h2s[0]["type"] != "hub_hello":
        fail(W, "hub_to_server must start with hub_hello")
    build = s2h[1]
    if build["config"] != cfg or build["start_sim_ts"] != sc["start_sim_ts"] or build["seed"] != cfg["seed"] or \
            build["catalog"] != list(catalog.values()):
        fail(W, "sim_build config/start/seed/catalog")
    if [d["device_id"] for d in build["devices"]] != list(devices) or any(
            d["state"] != "off" or d["power_kw"] != 0 or "physical" in d for d in build["devices"]):
        fail(W, "sim_build devices: the roster only (off, 0 kW, no physical)")
    ticks = s2h[2:]
    reports = h2s[1:]
    tick_ids = [t["tick_id"] for t in ticks]
    if [r["tick_id"] for r in reports] != tick_ids or len(steps) != 2 * len(ticks):
        fail(W, "hub_report per sim_tick and two step lines per tick")
    segs = []
    for n in tick_ids:
        if segs and n == segs[-1][1] + 1:
            segs[-1][1] = n
        else:
            segs.append([n, n])
    declared = [(s["from_tick"], s["to_tick"]) for s in sc.get("segments", []) if "phase" in s and "from_tick" in s]
    if declared:
        merged = []
        for a, b in declared:
            if merged and a == merged[-1][1] + 1:
                merged[-1][1] = b
            else:
                merged.append([a, b])
        if merged != segs:
            fail(W, "segments in scenario.json %s != streams %s" % (merged, segs))
    contiguous = set()
    for a, b in segs:
        contiguous.update(range(a + 1, b + 1))
    # context posts at the documented ticks; inputs from the context in force
    posts = sc["context_post_ticks"]
    ctx_msgs = [m["data"] for m in ws if m["type"] == "context"]
    for c in ctx_msgs:
        d0 = loc(pts(c["ts"])).date().isoformat()
        for row in c["weather"]["hourly"]:
            x = loc(pts(row["ts"]))
            if days[x.date().isoformat()]["hourly_outdoor_temp_c"][x.hour] != row["temp_c"]:
                fail(W, "context weather != daily_inputs at %s" % row["ts"])
        for row in c["prices"]["hourly"]:
            x = loc(pts(row["ts"]))
            if days[x.date().isoformat()]["hourly_grid_usd_per_kwh"][x.hour] != row["usd_per_kwh"]:
                fail(W, "context prices != daily_inputs at %s" % row["ts"])
        if c["crowd_effect"]["value"] != days[d0]["crowd_effect"] or c["events"]["items"] != days[d0]["events"]:
            fail(W, "context crowd/events != daily_inputs of %s" % d0)
        for sec in ("weather", "prices", "events"):
            if c[sec]["label"] != "recorded":
                fail(W, "context label must be recorded in the demo scenario")

    def post_of(n):
        return max(p for p in posts if p <= n)
    meter_init = meter_from_history(hist_totals, tariff, start)
    state_by, all_dec, all_cmd, issued, acks_by, dec_lane = {}, {}, {}, {}, {}, {}
    prev_meter = {}
    block_sum = {}
    closed_with, without_over = [], False
    fallback_seen = []
    for i, t in enumerate(ticks):
        n = t["tick_id"]
        w = "%s tick %d" % (W, n)
        sim_dt = start + timedelta(minutes=n - 1)
        if pts(t["sim_ts"]) != sim_dt or t["minutes"] != 1 or t["replay"]:
            fail(w, "sim_ts = start + (n - 1) min, minutes 1, replay false")
        lm = lmin(sim_dt)
        is_open = open_m <= lm < close_m
        if t["inputs"]["is_open"] != is_open or t["fast_forward"] != (not is_open):
            fail(w, "is_open = operating hours; fast_forward true iff overnight")
        x = loc(sim_dt)
        dayrow = days[x.date().isoformat()]
        if t["inputs"]["outdoor_temp_c"] != dayrow["hourly_outdoor_temp_c"][x.hour]:
            fail(w, "outdoor_temp_c != daily_inputs for this hour")
        pd = loc(start + timedelta(minutes=post_of(n) - 1)).date().isoformat()
        if t["inputs"]["crowd_multiplier"] != crowd_mult[days[pd]["crowd_effect"]]:
            fail(w, "crowd_multiplier != the crowd effect of the context in force")
        for s in t["surges"]:
            exp = [x_ for x_ in dayrow["surges"] if x_["surge_id"] == s["surge_id"]]
            if not exp or hm_min(exp[0]["start_local"]) != lm or exp[0]["customers"] != s["customers"] or \
                    exp[0]["duration_min"] != s["duration_min"] or not is_open:
                fail(w, "surge %s not in daily_inputs at this minute" % s["surge_id"])
        hr = reports[i]
        if n in contiguous:
            expected = state_by[(n - 1, "without")]["new_commands"] + state_by[(n - 1, "with")]["new_commands"]
            if t["commands"] != expected:
                fail(w, "sim_tick commands != TickState new_commands of tick %d" % (n - 1))
        for lane in ("without", "with"):
            cmd_ids = [c["command_id"] for c in t["commands"] if c["lane"] == lane]
            ack_ids = [a["command_id"] for a in hr["reports"][lane]["acks"]]
            if sorted(cmd_ids) != sorted(ack_ids) or len(set(ack_ids)) != len(ack_ids):
                fail(w, "each %s command needs exactly one ack in the %s HubReport" % (lane, lane))
            for a in hr["reports"][lane]["acks"]:
                acks_by[a["command_id"]] = (n, a)
        cph = {}
        for lane in ("without", "with"):
            rep = hr["reports"][lane]
            lw = "%s %s" % (w, lane)
            if rep["lane"] != lane or rep["tick_id"] != n or pts(rep["ts"]) != sim_dt + timedelta(minutes=1) or \
                    rep["hub_id"] != "sim_hub" or rep["source"] != "simulated":
                fail(lw, "HubReport lane/tick_id/ts (= sim_ts + minutes)/hub_id/source")
            if not near(rep["total_kw"], sum(d["power_kw"] for d in rep["devices"])):
                fail(lw, "total_kw != sum of devices")
            if [d["device_id"] for d in rep["devices"]] != list(devices):
                fail(lw, "device roster / order")
            if not is_open and rep["customers_per_hour"] != 0:
                fail(lw, "no customers while closed")
            for d in rep["devices"]:
                dv = devices[d["device_id"]]
                if not (0 <= d["power_kw"] <= d["rated_kw"] + 1e-9) or d["power_pct"] != half_up(100 * d["power_kw"] / d["rated_kw"]):
                    fail(lw, "%s power range / power_pct" % d["device_id"])
                if d["source"] != "simulated" or set(d.get("physical", {})) - PHYSICAL_KEYS:
                    fail(lw, "%s source/physical keys" % d["device_id"])
                if d["importance"] != dv["importance"] or d["rated_kw"] != dv["type"]["rated_kw"]:
                    fail(lw, "%s importance/rated" % d["device_id"])
                if d["type_id"] == "lights" and not near(d["power_kw"], dv["type"]["rated_kw"] * (1 if is_open else 0.1)):
                    fail(lw, "lights at rated while open, 10 % while closed")
            cph[lane] = rep["customers_per_hour"]
            sl = steps[2 * i + (0 if lane == "without" else 1)]
            ts_ = sl["returns"]
            if sl["args"]["minutes"] != 1 or sl["args"]["hub_report"] != rep:
                fail(lw, "step_stream args must be (1, the tick's HubReport)")
            if ts_["lane"] != lane or ts_["hub"] != rep or ts_["ts"] != rep["ts"] or \
                    ts_["customers_per_hour"] != rep["customers_per_hour"]:
                fail(lw, "TickState lane/hub/ts/customers must echo the HubReport")
            hv = {d["physical"]["indoor_temp_c"] for d in rep["devices"] if "indoor_temp_c" in d.get("physical", {})}
            if len(hv) != 1 or ts_["indoor_temp_c"] != next(iter(hv)):
                fail(lw, "one shared dining-room temperature, copied to indoor_temp_c")
            fk = ts_["forecast_kw"]
            if (n % 5 == 0) != (isinstance(fk, list) and len(fk) == 8) or (n % 5 and fk is not None):
                fail(lw, "forecast_kw: 8 values on decision ticks, null otherwise (both lanes)")
            for d in ts_["new_decisions"]:
                if d["decision_id"] in all_dec:
                    fail(lw, "decision %s twice" % d["decision_id"])
                all_dec[d["decision_id"]] = d
                dec_lane[d["decision_id"]] = lane
                if pts(d["ts"]) > pts(ts_["ts"]):
                    fail(lw, "decision ts after its step")
                if lane == "without" and d["reason_code"] != "owner_override":
                    fail(lw, "without lane gets only owner_override decisions")
                if d["reason_code"] not in ("owner_override", "escalation_choice") and n % 5:
                    fail(lw, "engine decisions only on decision ticks")
                if d["reason_code"] in ("stay_under_cap", "avoid_new_peak") and \
                        not (open_m <= lmin(pts(ts_["ts"])) < close_m):
                    fail(lw, "no reductions or holds start outside operating hours")
            if lane == "without" and ts_["new_escalations"]:
                fail(lw, "without lane never escalates")
            for c in ts_["new_commands"]:
                if c["command_id"] in issued:
                    fail(lw, "command %s issued twice" % c["command_id"])
                issued[c["command_id"]] = (n, c)
                all_cmd[c["command_id"]] = c
                if c["lane"] != lane or (c["issued_by"] == "engine" and c["ts"] != ts_["ts"]):
                    fail(lw, "command lane/ts")
                if lane == "without" and c["issued_by"] != "owner":
                    fail(lw, "without lane never receives engine commands")
            for wn in ts_["warnings"]:
                if wn["code"] != "cap_unreachable":
                    fail(lw, "the engine emits only cap_unreachable")
            state_by[(n, lane)] = ts_
            # meter, re-computed
            m = ts_["meter"]
            if m["ts"] != rep["ts"] or not near(m["total_kw"], rep["total_kw"]) or m["peak_cap_kw"] != cap or \
                    m["peak_mode"] != cfg["peak_mode"] or m["target_kw"] != cap:
                fail(lw, "meter ts/total/peak_mode/cap/target")
            k = (n - 1) // 15
            if pts(m["block_start"]) != start + timedelta(minutes=15 * k):
                fail(lw, "block_start")
            b = block_sum.setdefault((lane, k), [])
            b.append(rep["total_kw"])
            if n in contiguous or (n - 1) % 15 == 0:
                if len(b) == ((n - 1) % 15) + 1 and not near(m["block_avg_kw"], sum(b) / len(b)):
                    fail(lw, "block_avg_kw != mean of the block's ticks so far")
            if m["price_usd_per_kwh_now"] != tariff.price(pts(rep["ts"])):
                fail(lw, "price_usd_per_kwh_now = tariff price of the minute starting at ts")
            prev = prev_meter.get(lane)
            month = loc(sim_dt).month
            peaks_now = check_demand_peaks(m, tariff, month, lw)
            fixed_inc = tariff.fixed_day + (tariff.fixed_month if loc(sim_dt).day == 1 else 0.0)
            if prev is None:
                if n == 1:
                    mi = meter_init
                    inc = rep["total_kw"] / 60
                    exp_c_today = mi["c_today"] + inc * tariff.price(sim_dt) + sum(
                        c[1] * (round(mi["peaks"][c[0]], 2) - round(mi["mid"][c[0]], 2)) for c in tariff.applicable(month)) + \
                        fixed_inc
                    if not near(m["energy_kwh_today"], mi["e_today"] + inc, 0.002) or \
                            not near(m["energy_kwh_month"], mi["e_month"] + inc, 0.002) or \
                            not near(m["month_peak_kw"], mi["month_peak"]) or \
                            any(not near(peaks_now[k], mi["peaks"][k]) for k in peaks_now) or \
                            not near(m["cost_usd_today"], exp_c_today, 0.011):
                        fail(lw, "first meter must continue the month metered from the history blocks")
            elif n in contiguous:
                new_day = loc(sim_dt).date() != loc(sim_dt - timedelta(minutes=1)).date()
                new_month = new_day and loc(sim_dt).day == 1
                inc = rep["total_kw"] / 60
                if new_day:
                    if not near(m["energy_kwh_today"], inc, 0.002):
                        fail(lw, "energy_kwh_today resets at local midnight")
                elif not near(m["energy_kwh_today"] - prev["energy_kwh_today"], inc, 0.002):
                    fail(lw, "energy increment")
                if not new_month and not near(m["energy_kwh_month"] - prev["energy_kwh_month"], inc, 0.002):
                    fail(lw, "energy_kwh_month increment")
                prev_peaks = {} if new_month else {d["name"]: d["peak_kw"] for d in prev["demand_peaks"]}
                exp_peaks = {c[0]: prev_peaks.get(c[0], 0.0) for c in tariff.applicable(month)}
                exp_mp = 0.0 if new_month else prev["month_peak_kw"]
                if n % 15 == 0:
                    bs0 = start + timedelta(minutes=15 * k)
                    exp_mp = max(exp_mp, m["block_avg_kw"])
                    for c in tariff.applicable(month):
                        if tariff.counts(c, bs0):
                            exp_peaks[c[0]] = max(exp_peaks[c[0]], m["block_avg_kw"])
                if not near(m["month_peak_kw"], exp_mp) or any(not near(peaks_now[k], v) for k, v in exp_peaks.items()):
                    fail(lw, "month peaks: max(prev, closed block avg) per demand charge (months, days, windows)")
                dem = sum(c[1] * (exp_peaks[c[0]] - prev_peaks.get(c[0], 0.0)) for c in tariff.applicable(month))
                e_inc = inc * tariff.price(sim_dt)
                ctol = 0.0151 + (sum(c[1] for c in tariff.applicable(month)) * 0.0101 if dem else 0.0)
                if not new_day and not near(m["cost_usd_today"] - prev["cost_usd_today"], e_inc + dem, ctol):
                    fail(lw, "cost_usd_today increment (energy at the minute's price + demand added)")
                if new_day and not near(m["cost_usd_today"], e_inc + dem + fixed_inc, 0.011):
                    fail(lw, "cost_usd_today resets at local midnight (+ today's fixed charges)")
                if not new_month and not near(m["cost_usd_month"] - prev["cost_usd_month"],
                                              e_inc + dem + (fixed_inc if new_day else 0.0), ctol):
                    fail(lw, "cost_usd_month increment")
            prev_meter[lane] = m
            if n % 15 == 0 and len(b) == 15:
                if lane == "with":
                    closed_with.append((n, start + timedelta(minutes=15 * k), m["block_avg_kw"]))
                elif m["block_avg_kw"] > cap:
                    without_over = True
        if cph["without"] != cph["with"]:
            fail(w, "both lanes see the same customers_per_hour")
        for c in t["commands"]:
            a = next(x for x in hr["reports"][c["lane"]]["acks"] if x["command_id"] == c["command_id"])
            dev = next(d for d in hr["reports"][c["lane"]]["devices"] if d["device_id"] == c["device_id"])
            if a["ok"]:
                if c["action"] == "reduce" and (dev["state"] != "reduced" or dev["power_pct"] > a["applied_value"] + 1):
                    fail(w, "%s reduce not reflected (power <= value %% of rated)" % c["command_id"])
                if c["action"] == "restore" and dev["state"] == "reduced":
                    fail(w, "%s restore not reflected" % c["command_id"])
                if c["action"] == "delay" and c["value"] > 0 and dev["state"] != "waiting":
                    fail(w, "%s delay not reflected" % c["command_id"])
            elif a["reason"] is None:
                fail(w, "failed ack needs a reason")
        sw, sv = state_by[(n, "without")], state_by[(n, "with")]
        for e in sv["new_escalations"]:
            if e["status"] == "open" and e["ts"] == sv["ts"]:
                fallback_seen.append((n, e, sv))
    # publishing: rows_stream + ws ticks (every tick, or overnight once per closed block)
    pub = [n for n in tick_ids if every_tick or (open_m <= lmin(start + timedelta(minutes=n - 1)) < close_m) or n % 15 == 0]
    if len(rows) != len(pub):
        fail(W, "rows_stream: %d payloads for %d published ticks" % (len(rows), len(pub)))
    for p_i, n in enumerate(pub[:len(rows)]):
        p = rows[p_i]
        for j, lane in enumerate(("without", "with")):
            s = state_by[(n, lane)]
            mm = s["meter"]
            exp = {"lane": lane, "ts": s["ts"], "tick_id": n, "total_kw": mm["total_kw"], "block_avg_kw": mm["block_avg_kw"],
                   "month_peak_kw": mm["month_peak_kw"], "on_peak_month_peak_kw": mm["on_peak_month_peak_kw"],
                   "peak_mode": mm["peak_mode"], "peak_cap_kw": mm["peak_cap_kw"], "target_kw": mm["target_kw"],
                   "energy_kwh_today": mm["energy_kwh_today"], "energy_kwh_month": mm["energy_kwh_month"],
                   "price_usd_per_kwh_now": mm["price_usd_per_kwh_now"], "cost_usd_today": mm["cost_usd_today"],
                   "cost_usd_month": mm["cost_usd_month"], "customers_per_hour": s["customers_per_hour"],
                   "indoor_temp_c": s["indoor_temp_c"]}
            if json.loads(p["live_tick"][j]["demand_peaks_json"]) != mm["demand_peaks"]:
                fail("%s tick %d" % (W, n), "live_tick demand_peaks_json != Meter demand_peaks (%s)" % lane)
            got = {k_: v for k_, v in p["live_tick"][j].items()
                   if k_ not in ("forecast_kw_json", "forecast_ts", "demand_peaks_json")}
            if got != exp:
                fail("%s tick %d" % (W, n), "live_tick row != TickState (%s)" % lane)
            fkj = p["live_tick"][j]["forecast_kw_json"]
            if s["forecast_kw"] is not None and (json.loads(fkj) != s["forecast_kw"] or p["live_tick"][j]["forecast_ts"] != s["ts"]):
                fail("%s tick %d" % (W, n), "live_tick forecast_kw_json must be this decision tick's forecast")
            if fkj is not None and p["live_tick"][j]["forecast_ts"] is None:
                fail("%s tick %d" % (W, n), "forecast_ts with forecast_kw_json")
            if p["tick_history"][j] != {"lane": lane, "ts": s["ts"], "total_kw": mm["total_kw"],
                                        "block_avg_kw": mm["block_avg_kw"]}:
                fail("%s tick %d" % (W, n), "tick_history row")
        exp_dev = []
        for lane in ("without", "with"):
            for d in state_by[(n, lane)]["hub"]["devices"]:
                exp_dev.append({"key": "%s:%s" % (lane, d["device_id"]), "lane": lane, "device_id": d["device_id"],
                                "type_id": d["type_id"], "name": d["name"], "importance": d["importance"], "state": d["state"],
                                "power_kw": d["power_kw"], "rated_kw": d["rated_kw"], "power_pct": d["power_pct"],
                                "source": d["source"], "physical_json": None if "physical" not in d else
                                json.dumps(d["physical"], separators=(",", ":"), ensure_ascii=False)})
        if p["live_device"] != exp_dev:
            fail("%s tick %d" % (W, n), "live_device rows != HubReport devices")
        sw, sv = state_by[(n, "without")], state_by[(n, "with")]
        cmp_ = p["live_comparison"]
        if not (near(cmp_["saved_today_usd"], sw["meter"]["cost_usd_today"] - sv["meter"]["cost_usd_today"]) and
                near(cmp_["peak_avoided_kw"], sw["meter"]["month_peak_kw"] - sv["meter"]["month_peak_kw"]) and
                cmp_["month_peak_without_kw"] == sw["meter"]["month_peak_kw"] and
                cmp_["month_peak_with_kw"] == sv["meter"]["month_peak_kw"] and cmp_["ts"] == sv["ts"] and cmp_["id"] == 0):
            fail("%s tick %d" % (W, n), "LaneComparison not derived from the two meters")
    ws_ticks = [(m["data"]["hub"]["tick_id"], m["data"]["lane"]) for m in ws if m["type"] == "tick"]
    if ws_ticks != [(n, l) for n in pub for l in ("without", "with")]:
        fail(W, "ws tick messages: published ticks, without then with")
    if sum(1 for m in ws if m["type"] == "comparison") != len(pub):
        fail(W, "ws: one comparison per published tick")
    for m in ws:
        if m["type"] == "tick" and m["data"] != state_by[(m["data"]["hub"]["tick_id"], m["data"]["lane"])]:
            fail(W, "ws tick != TickState")
    ws_dec = [m["data"]["decision_id"] for m in ws if m["type"] == "decision"]
    if sorted(ws_dec) != sorted(all_dec):
        fail(W, "ws: one decision message per decision")
    # clock: phases, run_complete, day_index
    cks = [m for m in ws if m["type"] == "clock"]
    if [dict((k, v) for k, v in m.items() if k != "type") for m in cks] != clocks:
        fail(W, "clock_stream / clocks differ from the ws clock messages")
    order = {"service": 0, "overnight": 1, "closed": 2}
    prev_c = None
    for c in cks:
        cw = "%s clock tick %d" % (W, c["tick_id"])
        if (c["paused_reason"] == "run_complete") != (c["phase"] == "closed") or (c["phase"] == "closed") == c["playing"]:
            fail(cw, "run_complete only with phase closed (and not playing)")
        if c["run_days"] != run_days or not 1 <= c["day_index"] <= run_days or c["speed"] != sc["speed"]:
            fail(cw, "day_index 1..run_days, speed")
        if c["phase"] != "closed":
            nxt = start + timedelta(minutes=c["tick_id"])
            if (c["phase"] == "service") != (open_m <= lmin(nxt) < close_m):
                fail(cw, "phase must match the opening hours of the next tick")
        if prev_c is not None:
            if pts(c["sim_ts"]) < pts(prev_c["sim_ts"]) or prev_c["phase"] == "closed":
                fail(cw, "clock goes forward; nothing after closed")
            if c["day_index"] != prev_c["day_index"]:
                if not (c["day_index"] == prev_c["day_index"] + 1 and prev_c["phase"] == "overnight" and c["phase"] == "service"):
                    fail(cw, "day_index increments only at open (overnight -> service)")
            if prev_c["phase"] == "service" and c["phase"] == "overnight" and c["day_index"] >= run_days:
                fail(cw, "no overnight after the last day")
            if prev_c["phase"] == "service" and c["phase"] == "closed" and c["day_index"] != run_days:
                fail(cw, "closed only after the last day")
        prev_c = c
    if not every_tick:
        phases = [c["phase"] for c in cks]
        compact = [p for i, p in enumerate(phases) if i == 0 or p != phases[i - 1]]
        if compact != ["service", "overnight", "service", "closed"] or cks[-1]["tick_id"] != last_tick:
            fail(W, "multi-day phases must be service -> overnight -> service -> closed (got %s)" % compact)
        for c in cks:
            if c["phase"] == "overnight" and c["tick_id"] % 15 and c["tick_id"] not in (
                    x for x in tick_ids if not (open_m <= lmin(start + timedelta(minutes=x - 1)) < close_m)):
                fail(W, "overnight clock once per closed block")
    # the n -> n + 1 rule inside contiguous ticks
    for cid, (n, c) in issued.items():
        if n + 1 in contiguous and (cid not in acks_by or acks_by[cid][0] != n + 1):
            fail("%s command %s" % (W, cid), "not acked in tick n + 1")
    if tick_ids[-1] in contiguous and every_tick is False and state_by[(tick_ids[-1], "with")]["new_commands"]:
        fail(W, "commands issued on the final tick are never delivered")
    # escalations: shape, lifecycle, fallback at open
    escs = {}
    for (n, lane), s in state_by.items():
        for e in s["new_escalations"]:
            check_escalation(e, devices, auth, cap)
            escs.setdefault(e["escalation_id"], []).append((n, e))
    after = [m["data"] for m in ws if m["type"] == "escalation"]
    for e in after:
        check_escalation(e, devices, auth, cap)
    blocks_active = {}
    for eid, lst in escs.items():
        n0, e0 = lst[0]
        if e0["status"] != "open" or n0 % 5:
            fail("%s %s" % (W, eid), "opens on a decision tick with status open")
        if e0["block_start"] in blocks_active:
            fail("%s %s" % (W, eid), "one active escalation per lane per block_start")
        blocks_active[e0["block_start"]] = eid
        for n, e in lst[1:]:
            for k_ in ("escalation_id", "deadline_sim_ts", "default_option_id", "block_start", "ts"):
                if e[k_] != e0[k_]:
                    fail("%s %s" % (W, eid), "%s never changes in place" % k_)
    for n, e, sv in fallback_seen:
        opt = next(o for o in e["options"] if o["option_id"] == e["default_option_id"])
        fb = [d for d in sv["new_decisions"] if d["reason_code"] == "escalation_fallback"]
        if [(a["device_id"], a["action"], a["value"]) for a in opt["actions"]] != \
                [(d["device_id"], d["action"], d["value"]) for d in fb]:
            fail("%s %s" % (W, e["escalation_id"]), "fallback Commands must be issued in the step the escalation opens")
        if any(d["inside_rules"] != (not opt["rule_breaks"]) for d in fb):
            fail("%s %s" % (W, e["escalation_id"]), "fallback decisions: inside_rules false when the option breaks a rule")
        for d in fb:
            if not any(c["decision_id"] == d["decision_id"] for c in sv["new_commands"]):
                fail("%s %s" % (W, e["escalation_id"]), "fallback decision without its command in new_commands")
    final = {}
    for e in [e for lst in escs.values() for _, e in lst] + after:
        final[e["escalation_id"]] = e
    for n, bs, avg in closed_with:
        if avg > cap + 0.005:
            e = next((x for x in final.values() if pts(x["block_start"]) == bs), None)
            if e is None:
                fail("%s tick %d" % (W, n), "with lane block %.2f kW over the target without an escalation" % avg)
                continue
            opt = next((o for o in e["options"] if o["option_id"] == e["active_option_id"]), None)
            allow = 10 ** 9 if opt is None else max([b["amount"] for b in opt["rule_breaks"] if b["kind"] == "cap_overrun"] + [0])
            if avg > cap + allow + 0.5:
                fail("%s tick %d" % (W, n), "with lane block %.2f kW beyond the overrun its escalation allows" % avg)
    if every_tick and not without_over:
        fail(W, "the without lane must break the cap")
    # decisions / commands hard rules
    for d in all_dec.values():
        dv = devices[d["device_id"]]
        esc_dec = d["reason_code"] in ("escalation_fallback", "escalation_choice")
        if d["reason_code"] != "owner_override":
            brk = []
            if esc_dec:
                for e in final.values():
                    for o in e["options"]:
                        for a in o["actions"]:
                            if (a["device_id"], a["action"], a["value"]) == (d["device_id"], d["action"], d["value"]):
                                brk = o["rule_breaks"]
            check_move(d["device_id"], d["action"], d["value"], dv, "%s decision %s" % (W, d["decision_id"]),
                       allow_break=esc_dec, breaks=brk)
            if not esc_dec and not d["inside_rules"]:
                fail("%s decision %s" % (W, d["decision_id"]), "routine decisions are inside the rules")
        cmd = [c for c in all_cmd.values() if c["decision_id"] == d["decision_id"]]
        if len(cmd) != 1 or (cmd[0]["device_id"], cmd[0]["action"], cmd[0]["value"]) != (d["device_id"], d["action"], d["value"]):
            fail("%s decision %s" % (W, d["decision_id"]), "exactly one command equal to the decision")
        elif cmd[0]["issued_by"] != ("owner" if d["reason_code"] == "owner_override" else "engine"):
            fail("%s decision %s" % (W, d["decision_id"]), "owner_override -> issued_by owner; else engine")
    for c in all_cmd.values():
        if c["decision_id"] not in all_dec:
            fail("%s command %s" % (W, c["command_id"]), "every command carries its decision_id")
    # held jobs (with lane): total hold <= max_delay_min and the run ends by min(must_finish_by, close), unless the option
    # in force allows over_max_delay / past_deadline for that device
    def allowance(dev, kind):
        a = 0
        for e in final.values():
            for o in e["options"]:
                if o["option_id"] == e["active_option_id"]:
                    a = max([a] + [b["amount"] for b in o["rule_breaks"] if b["kind"] == kind and b.get("device_id") == dev])
        return a
    for dev, dv in devices.items():
        if dv["importance"] != "deferrable":
            continue
        cycle = dv["type"]["params"]["cycle_min"]
        dl = min(hm_min(dv["limits"]["must_finish_by"]), close_m)
        first_hold, prev_state = None, None
        for i, t in enumerate(ticks):
            n = t["tick_id"]
            if n not in contiguous:
                first_hold, prev_state = None, None
            d = next(x for x in reports[i]["reports"]["with"]["devices"] if x["device_id"] == dev)
            if d["state"] == "waiting" and prev_state != "waiting":
                first_hold = n
            if d["state"] == "running_job" and prev_state == "waiting" and first_hold is not None:
                started = start + timedelta(minutes=n - 1)
                if (n - first_hold) > dv["limits"]["max_delay_min"] + allowance(dev, "over_max_delay"):
                    fail("%s %s tick %d" % (W, dev, n), "held longer than max_delay_min")
                if lmin(started) + cycle > dl + allowance(dev, "past_deadline"):
                    fail("%s %s tick %d" % (W, dev, n), "held job ends after min(must_finish_by, close)")
                first_hold = None
            prev_state = d["state"]
    # reductions: <= max_reduce_min (restore by t + 5k), cooldown, no new reduce in the last max_reduce_min before close
    seq = sorted(((issued[c["command_id"]][0], c) for c in all_cmd.values() if c["lane"] == "with" and c["issued_by"] == "engine"),
                 key=lambda x: (x[0], x[1]["command_id"]))
    red = {}
    for n, c in seq:
        dv = devices[c["device_id"]]
        if c["action"] == "reduce":
            r = red.get(c["device_id"])
            if r is None or r.get("restored") is not None:
                if r is not None and n < r["restored"] + dv["limits"]["max_reduce_min"]:
                    fail("%s %s" % (W, c["command_id"]), "reduce inside the cooldown after a restore")
                if lmin(start + timedelta(minutes=n)) + dv["limits"]["max_reduce_min"] > close_m:
                    fail("%s %s" % (W, c["command_id"]), "new reduce in the last max_reduce_min before close")
                red[c["device_id"]] = {"first": n, "restored": None}
        elif c["action"] == "restore" and c["device_id"] in red and red[c["device_id"]]["restored"] is None:
            r = red[c["device_id"]]
            limit = r["first"] + 5 * (dv["limits"]["max_reduce_min"] // 5)
            allowed = 0
            dec = all_dec[c["decision_id"]]
            for e in final.values():
                for o in e["options"]:
                    if o["option_id"] == e["active_option_id"]:
                        allowed = max([allowed] + [b["amount"] for b in o["rule_breaks"]
                                                   if b["kind"] == "over_max_reduce" and b["device_id"] == c["device_id"]])
            if n > limit + allowed:
                fail("%s %s" % (W, c["command_id"]), "restore later than max_reduce_min")
            r["restored"] = n
    return {"decisions": all_dec, "commands": all_cmd, "escalations": final, "surges": {s["surge_id"] for t in ticks
                                                                                      for s in t["surges"]},
            "dec_lane": dec_lane, "state_by": state_by, "devices": devices}


# ----------------------------------------------------------------------------- cross-file invariants
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


def scenario_pass(store):
    sc = load("scenario/demo_cafe/scenario.json")
    idx = load("scenario/demo_cafe/index.json")
    msc = load("scenario/demo_cafe_multiday/scenario.json")
    midx = load("scenario/demo_cafe_multiday/index.json")
    for k, v in list(idx.items()) + list(midx.items()):
        if isinstance(v, str) and v.endswith((".json", ".jsonl")) and not os.path.exists(os.path.join(HERE, v)):
            fail("scenario index", "missing %s" % v)
    cfg = sc["config"]
    validate(cfg, R("KitchenConfig"), "scenario.config")
    validate(msc["config"], R("KitchenConfig"), "multiday scenario.config")
    if cfg != store["shapes/kitchen_config.json"] or cfg["run_days"] != 1 or msc["config"] != dict(cfg, run_days=2):
        fail("scenario", "config = shapes/kitchen_config.json (run_days 1); multi-day = same with run_days 2")
    catalog = {c["type_id"]: c for c in store["shapes/equipment_catalog.json"]}
    tariff_obj = store["shapes/tariff.json"]
    tariff = Tariff(tariff_obj)
    for c in catalog.values():
        if c["default_importance"] == "flexible" and c["category"] == "refrigeration" and c["default_limits"]["min_power_pct"] < 50:
            fail("catalog", "%s default below food-safety floor" % c["type_id"])
        if set(c["default_limits"]) != set(LIMITS_BY_IMP[c["default_importance"]][1]):
            fail("catalog", "%s default_limits keys do not match its importance" % c["type_id"])
        if set(c["params"]) != PARAMS_BY_MODEL[c["power_model"]]:
            fail("catalog", "%s params keys do not match power_model" % c["type_id"])
    tariff_cover_pass(tariff_obj, "shapes/tariff.json")
    tariff_cover_pass(store["shapes/tariff_pge_b19.json"], "shapes/tariff_pge_b19.json")
    urdb_b19_pass(store["shapes/tariff_pge_b19.json"])
    if tariff_obj["fixed_charges"] != [] or [(c["name"], c["usd_per_kw"], c["windows"]) for c in tariff_obj["demand"]] != \
            [("max_demand", 20.0, None), ("peak_demand", 8.0, [{"start": "16:00", "end": "21:00"}])]:
        fail("shapes/tariff.json", "demo_tariff_v1 keeps $20/kW max, $8/kW 16:00-21:00, no fixed charges")
    # The fixture catalog is the frozen 2026-10-24 toy catalog the scripted scenario is tuned to; the real catalog
    # (re-cited 2026-10-25) has other numbers and two more types. Every fixture type must still exist there with the same
    # shape, so the fakes and the real app speak the same contract.
    src_cat = os.path.join(REPO, "backend", "data", "equipment_catalog.json")
    if os.path.exists(src_cat):
        with open(src_cat, encoding="utf-8") as f:
            real = {c["type_id"]: c for c in json.load(f)}
        for c in store["shapes/equipment_catalog.json"]:
            r = real.get(c["type_id"])
            same = r is not None and all(r[k] == c[k] for k in ("category", "power_model", "default_importance")) \
                and set(r["params"]) == set(c["params"]) and set(r["default_limits"]) == set(c["default_limits"])
            if not same:
                fail("shapes/equipment_catalog.json",
                     f"{c['type_id']}: not in backend/data/equipment_catalog.json with the same category, power_model, "
                     "default_importance and params / default_limits keys")
    if catalog["hvac"]["rated_kw"] != 8.0:
        fail("catalog", "hvac rated_kw 8.0")
    roster = []
    for eq in cfg["equipment"]:
        roster += ["%s_%d" % (eq["type_id"], i) for i in range(1, eq["count"] + 1)]
    hist, totals, daily = history_pass(store, cfg, tariff, roster)
    rated = {}
    for eq in cfg["equipment"]:
        for i in range(1, eq["count"] + 1):
            rated["%s_%d" % (eq["type_id"], i)] = catalog[eq["type_id"]]["rated_kw"]
    for b in hist["blocks"]:
        if b["avg_kw"] > rated[b["device_id"]] + 1e-9:
            fail("history %s %s" % (b["block_start"], b["device_id"]), "avg_kw above rated_kw (HVAC <= 8.0 kW)")
            break
    bi = store["shapes/backtest_inputs.json"]
    if bi != store["facade/run_backtest.json"]["args"]["inputs"] or bi["config"] != cfg or bi["tariff"] != tariff_obj or \
            bi["catalog"] != store["shapes/equipment_catalog.json"] or bi["seed"] != cfg["seed"]:
        fail("shapes/backtest_inputs.json", "= facade run_backtest inputs: the Demo Cafe config, tariff, catalog, seed")
    ser = bi["series"]
    if (ser["source"], ser["label"]) != ("fixture_synthetic", "simulated") or \
            ser["blocks"] != [b for b in hist["blocks"] if pts(ser["start"]) <= pts(b["block_start"]) < pts(ser["end"])] or \
            not ser["blocks"]:
        fail("shapes/backtest_inputs.json", "series = an excerpt of the fixture history (simulated)")
    if bi["assumptions"] != {"assumptions_id": "base", "flex_scale": 1.0, "draw_scale": 1.0, "forecast_noise_pct": 0.0}:
        fail("shapes/backtest_inputs.json", "assumptions base = 1.0 / 1.0 / 0.0")
    if store["facade/warm_up.json"]["args"]["history"] != hist:
        fail("facade/warm_up.json", "args.history must be history/warmup_demo_cafe.json")
    ex = store["shapes/warm_up_history.json"]
    if ex["blocks"] != hist["blocks"][-len(roster):] or ex["end"] != hist["end"]:
        fail("shapes/warm_up_history.json", "excerpt = the last block of the history")
    # evening
    ev = run_pass("evening", store, store["hub_protocol/server_to_hub.jsonl"], store["hub_protocol/hub_to_server.jsonl"],
                  store["facade/step_stream.jsonl"], store["spacetime/rows_stream.jsonl"], store["ws/stream.jsonl"],
                  [dict((k, v) for k, v in m.items() if k != "type") for m in store["ws/stream.jsonl"] if m["type"] == "clock"],
                  cfg, tariff, catalog, totals, daily, sc, True)
    if len(store["hub_protocol/server_to_hub.jsonl"]) != sc["ticks"] + 2:
        fail("evening", "120 sim_ticks")
    escs = ev["escalations"]
    if len(escs) != 1:
        fail("evening", "exactly one escalation expected, got %d" % len(escs))
    for e in escs.values():
        if e["status"] != "resolved" or e["resolved_by"] != "claude":
            fail("evening", "the escalation is resolved by Claude within authority")
    # multi-day
    md = "scenario/demo_cafe_multiday/"
    ms = {k: load(md + k + ".jsonl") for k in ("server_to_hub", "hub_to_server", "step_stream", "rows_stream", "ws_stream",
                                                "clock_stream")}
    for k, v in ms.items():
        store[md + k + ".jsonl"] = v
    for i, m in enumerate(ms["server_to_hub"]):
        validate(m, HUB.get(m.get("type"), O({})), "%sserver_to_hub[%d]" % (md, i))
    for i, m in enumerate(ms["hub_to_server"]):
        validate(m, HUB.get(m.get("type"), O({})), "%shub_to_server[%d]" % (md, i))
    steps_shape(ms["step_stream"], md + "step_stream")
    for i, p in enumerate(ms["rows_stream"]):
        validate(p, PAYLOAD, "%srows_stream[%d]" % (md, i))
    ws_messages(ms["ws_stream"], md + "ws_stream")
    clocks = []
    for i, c in enumerate(ms["clock_stream"]):
        if check_wrapper(c, ("reducer", "args"), "%sclock_stream[%d]" % (md, i)):
            row = dict(zip(SET_CLOCK_ARGS, c["args"]), id=0)
            validate(row, ST["live_clock"], "%sclock_stream[%d]" % (md, i))
            clocks.append({k: row[k] for k in SET_CLOCK_ARGS if k != "sim_host"})
    mrun = run_pass("multiday", store, ms["server_to_hub"], ms["hub_to_server"], ms["step_stream"], ms["rows_stream"],
                    ms["ws_stream"], clocks, msc["config"], tariff, catalog, totals, daily, msc, False)
    mid_tick = midx["midnight_tick"]
    if mid_tick not in [t["tick_id"] for t in ms["server_to_hub"][2:]]:
        fail("multiday", "the files must cross local midnight")
    # same run: the evening ticks the multi-day files share are identical (tick 1..120 vs later ticks share ids)
    ev_ids = set(ev["decisions"])
    for d in mrun["decisions"]:
        if d in ev_ids and mrun["decisions"][d] != ev["decisions"][d]:
            fail("multiday", "decision %s differs from the evening run" % d)
    return ev, mrun, sc, idx, msc, midx, tariff, catalog


def crossref_pass(store, ev, mrun, idx, midx, tariff):
    devices = ev["devices"]
    ids = {"d": set(ev["decisions"]) | set(mrun["decisions"]), "c": set(ev["commands"]) | set(mrun["commands"]),
           "e": set(ev["escalations"]) | set(mrun["escalations"]), "s": ev["surges"] | mrun["surges"]}
    sa = idx["standalone_example_ids"]
    ids["d"].add(sa["decision"])
    ids["c"].add(sa["command"])
    for e in list(ev["escalations"].values()):
        for o in e["options"]:
            for a in o["actions"]:
                ids["c"].add(a["command_id"])
    cmd_defs = {}
    for f, obj in store.items():
        for path, o in walk_objs(obj, f):
            if set(o) == set(SHAPES["Command"][1]) or set(o) == set(SHAPES["Command"][1]) | {"hub_id", "delivery"}:
                base = {k: o[k] for k in SHAPES["Command"][1]}
                if o["command_id"] in cmd_defs and cmd_defs[o["command_id"]] != base:
                    fail(path, "command %s has two different contents" % o["command_id"])
                cmd_defs[o["command_id"]] = base
                dv = devices.get(o["device_id"])
                if dv and dv["importance"] == "always_on" and o["issued_by"] == "engine":
                    fail(path, "engine command to an always_on device")
                if o["issued_by"] == "owner" and o["decision_id"] is None:
                    fail(path, "owner command carries its owner_override decision_id")
            if set(o) == set(SHAPES["Decision"][1]):
                dv = devices.get(o["device_id"])
                if dv and dv["importance"] == "always_on" and o["reason_code"] != "owner_override":
                    fail(path, "engine decision on an always_on device")
            if set(o) == set(SHAPES["CommandAck"][1]):
                c = cmd_defs.get(o["command_id"])
                if o["ok"]:
                    if o["reason"] not in (None, "out_of_range") or (c is not None and c["action"] in ("reduce", "delay")
                                                                    and (o["applied_value"] == c["value"]) != (o["reason"] is None)):
                        fail(path, "ok ack: reason null iff applied unchanged, else out_of_range")
                elif o["reason"] not in ("job_running", "already_off", "unknown_device") or o["applied_value"] is not None:
                    fail(path, "rejected ack: job_running | already_off | unknown_device, no applied_value")
            if set(o) == set(SHAPES["Bill"][1]) or set(o) == set(SHAPES["Bill"][1]) | {"lane"}:
                rates = [(c[0], c[1]) for c in tariff.applicable(int(o["period"][5:]))]
                if o["tariff_id"] != store["shapes/tariff.json"]["tariff_id"] or [d["name"] for d in o["demand_charges"]] != \
                        [nm for nm, _ in rates]:
                    fail(path, "bill must list every demand charge that applies in the period")
                for d, (nm, r) in zip(o["demand_charges"], rates):
                    if not near(d["cost_usd"], d["peak_kw"] * r):
                        fail(path, "demand charge cost != peak x rate")
                if not near(o["total_usd"], o["energy_cost_usd"] + sum(d["cost_usd"] for d in o["demand_charges"]) +
                            o["fixed_usd"]):
                    fail(path, "bill total = energy + demand charges + fixed")
            if set(o) == set(SHAPES["Proposal"][1]):
                if set(o["payload"]) != PROPOSAL_PAYLOAD[o["kind"]]:
                    fail(path, "proposal payload keys for kind %s" % o["kind"])
                if (o["status"] == "pending") != (o["confirmed_via"] is None) and o["status"] in ("pending", "confirmed"):
                    fail(path, "confirmed_via must be null iff pending")
            if set(o) == set(SHAPES["Snapshot"][1]):
                if any(e["status"] != "open" for e in o["open_escalations"]) or \
                        len(o["recent_decisions"]) > 20:
                    fail(path, "snapshot: open_escalations open, recent_decisions <= 20")
            if set(o) == set(SHAPES["Meter"][1]) or set(o) == set(SHAPES["KitchenConfig"][1]):
                if o["peak_mode"] == "cap" and o["peak_cap_kw"] is None and "_422" not in path and "rule_error" not in path:
                    fail(path, "peak_mode cap needs peak_cap_kw")
                if o["peak_mode"] == "minimize" and o["peak_cap_kw"] is not None:
                    fail(path, "peak_mode minimize needs peak_cap_kw null")
            if set(o) == set(SHAPES["Meter"][1]) and o["peak_mode"] == "cap" and o["target_kw"] != o["peak_cap_kw"]:
                fail(path, "target_kw must equal peak_cap_kw in cap mode")
    cfg = store["shapes/kitchen_config.json"]
    seen_esc = 0
    for f, obj in store.items():                 # every Escalation anywhere (shapes, REST, facade, tools, Convex, rows)
        for path, o in walk_objs(obj, f):
            if set(o) == set(SHAPES["Escalation"][1]):
                check_escalation(o, devices, cfg["authority"], cfg["peak_cap_kw"])
                seen_esc += 1
                if o["escalation_id"] in ev["escalations"]:
                    e0 = ev["escalations"][o["escalation_id"]]
                    for k in ("ts", "block_start", "problem", "options", "default_option_id", "deadline_sim_ts"):
                        if o[k] != e0[k]:
                            fail(path, "%s variant must keep %s of the stream escalation" % (o["escalation_id"], k))
            if "problem_json" in o and "options_json" in o:
                e = ev["escalations"].get(o["escalation_id"])
                if e is None or json.loads(o["problem_json"]) != e["problem"] or json.loads(o["options_json"]) != e["options"] \
                        or json.loads(o["claude_attempts_json"]) != e["claude_attempts"] \
                        or any(o[k] != e[k] for k in o if not k.endswith("_json") and k not in ("explanation", "explanation_source")):
                    fail(path, "live_escalation row != the escalation re-keyed")
    if seen_esc < 10:
        fail("escalations", "expected escalation examples across shapes/rest/facade/ai_tools/convex")
    for f, obj in store.items():
        for path, k, v in walk(obj, f):
            if k == "decision_id" and v is not None and v not in ids["d"] and "_404" not in path:
                fail(path, "unknown decision_id %s" % v)
            if k == "command_id" and v not in ids["c"] and v not in cmd_defs:
                fail(path, "unknown command_id %s" % v)
            if k == "escalation_id" and v not in ids["e"]:
                fail(path, "unknown escalation_id %s" % v)
            if k == "surge_id" and v is not None and v not in ids["s"] and not f.startswith("history/"):
                fail(path, "unknown surge_id %s" % v)
            if k == "device_id" and v not in devices and "_404" not in path and v is not None:
                fail(path, "unknown device_id %s" % v)
            for key, pat in (("decision_id", r"^d_\d{4,}$"), ("command_id", r"^c_\d{4,}$"), ("escalation_id", r"^e_\d{4,}$"),
                             ("proposal_id", r"^p_\d{4}$"), ("surge_id", r"^s_\d{4}$"), ("kitchen_id", r"^k_\d{2}$")):
                if k == key and v is not None and not re.match(pat, v):
                    fail(path, "%s format %s" % (key, v))
    if sorted(idx["decision_ids"]) != sorted(ev["decisions"]) or sorted(idx["command_ids"]) != sorted(ev["commands"]):
        fail("scenario/demo_cafe/index.json", "id lists differ from the streams")
    if sorted(midx["decision_ids"]) != sorted(mrun["decisions"]):
        fail("scenario/demo_cafe_multiday/index.json", "decision ids differ from the streams")
    kinds = {store[f]["kind"] for f in store if f.startswith("shapes/proposal_")}
    if kinds != set(PROPOSAL_PAYLOAD):
        fail("shapes", "one Proposal example per kind expected, have %s" % sorted(kinds))
    feed = store["spacetime/tables/live_feed.json"]
    for r in feed:
        d = ev["decisions"].get(r["decision_id"])
        if d is None or json.loads(r["effect_json"]) != d["effect"] or r["status"] != d["status"] or \
                r["lane"] != ev["dec_lane"][r["decision_id"]]:
            fail("live_feed", "row differs from decision %s" % r["decision_id"])
    if len(feed) > 50:
        fail("live_feed", "last 50 only")
    # snapshot / facade / REST views agree with the stream
    st = ev["state_by"]
    n_last = max(n for n, _ in st)
    snap = store["facade/snapshot.json"]["returns"]
    if snap["meter"] != st[(n_last, "with")]["meter"] or snap["devices"] != st[(n_last, "with")]["hub"]["devices"] or \
            snap["tick_id"] != n_last or snap["sim_ts"] != st[(n_last, "with")]["ts"]:
        fail("facade/snapshot.json", "snapshot = the with lane after the last evening tick")
    if [d["decision_id"] for d in snap["recent_decisions"]] != sorted(
            [d for d in ev["decisions"] if ev["dec_lane"][d] == "with"], reverse=True)[:20]:
        fail("facade/snapshot.json", "recent_decisions: last 20 of the with lane, newest first")
    if store["ai_tools/get_kitchen_state.json"]["output"] != snap:
        fail("ai_tools/get_kitchen_state.json", "must equal the snapshot")
    undo = store["facade/undo.json"]
    if not any(c["decision_id"] == undo["args"]["decision_id"] for c in snap["active_commands"]) or \
            ev["decisions"][undo["args"]["decision_id"]]["action"] not in ("reduce", "delay"):
        fail("facade/undo.json", "undo only for an executed reduce/delay whose command is still in force")
    bad = store["rest/post_decision_undo_422.json"]["path"].split("/")[3]
    if ev["decisions"][bad]["action"] in ("reduce", "delay"):
        fail("rest/post_decision_undo_422.json", "422 example must be a decision that cannot be undone")
    cmp_ = store["facade/compare_lanes.json"]
    a, b = cmp_["args"]["without"]["meter"], cmp_["args"]["with_"]["meter"]
    r = cmp_["returns"]
    if not near(r["saved_today_usd"], a["cost_usd_today"] - b["cost_usd_today"]) or \
            not near(r["peak_avoided_kw"], a["month_peak_kw"] - b["month_peak_kw"]):
        fail("facade/compare_lanes.json", "compare_lanes arithmetic")
    nd = store["rest/post_sim_control_next_day.json"]["response"]
    if nd["run_days"] != 2 or nd["phase"] != "overnight" or nd["paused_reason"] is not None or not nd["playing"]:
        fail("rest/post_sim_control_next_day.json", "next_day: run_days + 1, overnight, playing")
    ce = store["ai_tools/choose_escalation_option.json"]
    e_ = store["shapes/escalation_open.json"]
    if ce["input_enum"]["option_id"] != [o["option_id"] for o in e_["options"]]:
        fail("ai_tools/choose_escalation_option.json", "Claude sees every evaluated option with its authority flag")
    w_ = store["shapes/warning_cap_unreachable.json"]
    if w_["data"]["unavoidable_kw"] <= w_["data"]["target_kw"]:
        fail("shapes/warning_cap_unreachable.json", "cap_unreachable: unavoidable_kw above the target")
    if dict({"type": "warning"}, **w_) != store["ws/warning.json"]:
        fail("ws/warning.json", "= the Warning shape with type")
    clamped = store["shapes/command_ack_clamped.json"]
    if not clamped["ok"] or clamped["reason"] != "out_of_range" or clamped["applied_value"] == store["shapes/command_owner.json"]["value"]:
        fail("shapes/command_ack_clamped.json", "clamped: ok true, out_of_range, applied_value differs")
    if store["shapes/command_ack_rejected.json"]["ok"]:
        fail("shapes/command_ack_rejected.json", "rejected: ok false")


# ----------------------------------------------------------------------------- manifest, determinism, pydantic
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
    gen = os.path.join(HERE, "generate.py")
    n = 0
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([sys.executable, gen, tmp], capture_output=True, text=True)
        if r.returncode:
            fail("generate.py", "failed: %s" % r.stderr[-800:])
            return 0
        for root, _, fs in os.walk(tmp):
            for f in fs:
                rel = os.path.relpath(os.path.join(root, f), tmp)
                n += 1
                with open(os.path.join(root, f), "rb") as a, open(os.path.join(HERE, rel), "rb") as b:
                    if a.read() != b.read():
                        fail(rel, "regenerating gives different bytes (stale or non-deterministic)")
    with tempfile.TemporaryDirectory() as t1, tempfile.TemporaryDirectory() as t2:
        for t in (t1, t2):
            r = subprocess.run([sys.executable, gen, "--days", "2", "--out", t], capture_output=True, text=True)
            if r.returncode:
                fail("generate.py --days 2", "failed: %s" % r.stderr[-800:])
                return n
        for f in ("server_to_hub.jsonl", "hub_to_server.jsonl", "step_stream.jsonl", "index.json"):
            with open(os.path.join(t1, f), "rb") as a, open(os.path.join(t2, f), "rb") as b:
                if a.read() != b.read():
                    fail("generate.py --days 2", "%s differs between two runs" % f)
        # the committed multi-day segments are lines of the same full run
        full = {}
        for f, key in (("server_to_hub.jsonl", "tick_id"), ("hub_to_server.jsonl", "tick_id")):
            with open(os.path.join(t1, f), encoding="utf-8") as fh:
                full[f] = {json.loads(line).get(key): line for line in fh if json.loads(line).get("type") in
                           ("sim_tick", "hub_report")}
            with open(os.path.join(HERE, "scenario/demo_cafe_multiday", f), encoding="utf-8") as fh:
                for line in fh:
                    m = json.loads(line)
                    if m.get("type") in ("sim_tick", "hub_report") and full[f].get(m[key]) != line:
                        fail("scenario/demo_cafe_multiday/" + f, "tick %d differs from `--days 2`" % m[key])
        with open(os.path.join(t1, "step_stream.jsonl"), encoding="utf-8") as fh:
            steps = {}
            for line in fh:
                m = json.loads(line)
                steps[(m["args"]["hub_report"]["tick_id"], m["args"]["hub_report"]["lane"])] = line
        with open(os.path.join(HERE, "scenario/demo_cafe_multiday/step_stream.jsonl"), encoding="utf-8") as fh:
            for line in fh:
                m = json.loads(line)
                if steps.get((m["args"]["hub_report"]["tick_id"], m["args"]["hub_report"]["lane"])) != line:
                    fail("scenario/demo_cafe_multiday/step_stream.jsonl", "a step differs from `--days 2`")
                    break
        with open(os.path.join(t1, "step_stream.jsonl"), encoding="utf-8") as a, \
                open(os.path.join(HERE, "facade/step_stream.jsonl"), encoding="utf-8") as b:
            ev = [json.loads(x) for x in b]
            for line_ev in ev:
                key = (line_ev["args"]["hub_report"]["tick_id"], line_ev["args"]["hub_report"]["lane"])
                if json.loads(steps[key]) != line_ev:
                    fail("facade/step_stream.jsonl", "the evening differs from the same ticks of `--days 2`")
                    break
    return n


PYDANTIC_SCRIPT = r'''
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[2])
from pydantic import TypeAdapter
from contracts import shapes, hub, ws, live
from contracts.check_fixtures import checker_for
root = Path(sys.argv[1])
extra = {
    "scenario/demo_cafe_multiday/server_to_hub.jsonl": hub.ServerToHubMessage,
    "scenario/demo_cafe_multiday/hub_to_server.jsonl": hub.HubToServerMessage,
    "scenario/demo_cafe_multiday/ws_stream.jsonl": ws.ViewerMessage,
    "scenario/demo_cafe_multiday/rows_stream.jsonl": live.PublishTicksPayload,
    "shapes/decision_owner_override.json": shapes.Decision,
    "shapes/tariff_pge_b19.json": shapes.Tariff,
}
fails, n = [], 0
for path in sorted(root.rglob("*")):
    if not path.is_file() or path.suffix not in (".json", ".jsonl"):
        continue
    rel = path.relative_to(root).as_posix()
    if rel in ("MANIFEST.json", "history/daily_inputs.json") or rel.startswith("scenario/") and rel.endswith("index.json"):
        continue
    lines = [json.loads(l) for l in path.read_text().splitlines()] if path.suffix == ".jsonl" else [json.loads(path.read_text())]
    try:
        if rel in extra:
            ta = TypeAdapter(extra[rel])
            for o in lines:
                ta.validate_python(o)
        elif rel == "scenario/demo_cafe_multiday/step_stream.jsonl":
            for o in lines:
                TypeAdapter(shapes.HubReport).validate_python(o["args"]["hub_report"])
                TypeAdapter(shapes.TickState).validate_python(o["returns"])
        elif rel == "facade/run_backtest_on_progress.jsonl":
            for o in lines:
                t = o["type"]
                if t == "backtest_point":
                    TypeAdapter(shapes.BacktestPoint).validate_python(o["data"])
                elif t == "backtest_month":
                    TypeAdapter(shapes.BacktestResult).validate_python(o["data"])
                elif t == "backtest_progress":
                    TypeAdapter(ws.BacktestProgressMessage).validate_python(dict(o, run_id="run_0001"))
                else:
                    raise ValueError("unknown on_progress event %r" % t)
        elif rel == "scenario/demo_cafe_multiday/clock_stream.jsonl":
            names = ["playing", "speed", "sim_ts", "tick_id", "paused_reason", "day_index", "run_days", "phase", "sim_host"]
            for o in lines:
                TypeAdapter(live.LiveClockRow).validate_python(dict(zip(names, o["args"]), id=0))
        else:
            chk = checker_for(rel)
            if chk is None:
                continue
            for o in lines:
                chk(o)
        n += 1
    except Exception as exc:
        fails.append("%s: %s" % (rel, str(exc).splitlines()[0][:300]))
print(json.dumps({"validated": n, "fails": fails}))
'''


def pydantic_pass():
    py = os.path.join(REPO, "backend", ".venv", "bin", "python")
    if not os.path.exists(py) or not os.path.isdir(os.path.join(REPO, "backend", "contracts")):
        print("note: backend/.venv not found; Pydantic validation skipped")
        return None
    r = subprocess.run([py, "-c", PYDANTIC_SCRIPT, HERE, os.path.join(REPO, "backend")], capture_output=True, text=True)
    if r.returncode:
        fail("pydantic", "validator crashed: %s" % r.stderr[-800:])
        return None
    out = json.loads(r.stdout.strip().splitlines()[-1])
    for f in out["fails"]:
        fail("pydantic", f)
    return out["validated"]


def main():
    store = {}
    for p in (shapes_pass, hub_pass, rest_pass, ws_pass, facade_pass, ai_pass, spacetime_pass, convex_pass, agents_pass):
        try:
            p(store)
        except Exception as ex:   # a crash is a failure, not a pass
            import traceback
            traceback.print_exc()
            fail(p.__name__, "crashed: %r" % ex)
    try:
        ev, mrun, sc, idx, msc, midx, tariff, catalog = scenario_pass(store)
        crossref_pass(store, ev, mrun, idx, midx, tariff)
    except Exception as ex:
        import traceback
        traceback.print_exc()
        fail("scenario_pass", "crashed: %r" % ex)
    manifest_pass()
    quick = os.environ.get("CHECK_QUICK") == "1"       # CHECK_QUICK=1: skip Pydantic + regeneration (local iteration only)
    pyd = None if quick else pydantic_pass()
    regen = "skipped" if quick else determinism_pass()
    if FAIL:
        for f in FAIL[:200]:
            print("FAIL", f)
        print("%d failure(s)" % len(FAIL))
        sys.exit(1)
    if quick:
        print("OK (quick mode: Pydantic and determinism passes skipped): %d files, %d values validated"
              % (COUNT["files"], COUNT["objects"]))
        return
    print("OK: %d files, %d values validated; invariants, cross-references, history, backtest, clock phases and determinism "
          "(%s files regenerated byte-identical, --days 2 twice identical and equal to the committed segments) pass%s"
          % (COUNT["files"], COUNT["objects"], regen,
             "" if pyd is None else "; Pydantic model_validate OK on %d files (backend/contracts)" % pyd))


if __name__ == "__main__":
    main()
