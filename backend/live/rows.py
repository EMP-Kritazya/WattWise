"""SpacetimeDB row builders (CONTRACTS.md section 5): engine / runtime objects -> the rows the reducers take.

Pure functions, no I/O. They copy numbers unchanged (the engine is the truth of every number; the module and the browser
never compute) and serialise `*_json` columns compactly (`separators=(",", ":")`, UTF-8), byte-identical to
`contracts/fixtures/spacetime/`. The only text built here is the `live_context` summary line (one formatted reading per
section, numbers as the agents posted them).
"""
from __future__ import annotations

import json
from typing import Any, Mapping, Optional

LANES = ("without", "with")


def cj(obj: Any) -> Optional[str]:
    """Compact JSON string of a section 1 shape (None stays None)."""
    return None if obj is None else json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _plain(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=True)
    return value


# ---------------------------------------------------------------------------------------------------------------------
# publish_ticks
# ---------------------------------------------------------------------------------------------------------------------


def live_tick_row(state: Mapping, forecast_kw: Optional[list], forecast_ts: Optional[str]) -> dict:
    """`live_tick` from one lane's TickState. `forecast_kw` / `forecast_ts`: the lane's latest forecast and the ts of the
    decision tick that made it (kept between decision ticks; null before the first)."""
    m = state["meter"]
    return {
        "lane": state["lane"], "ts": state["ts"], "tick_id": state["hub"]["tick_id"], "total_kw": m["total_kw"],
        "block_avg_kw": m["block_avg_kw"], "month_peak_kw": m["month_peak_kw"],
        "on_peak_month_peak_kw": m["on_peak_month_peak_kw"], "peak_mode": m["peak_mode"], "peak_cap_kw": m["peak_cap_kw"],
        "target_kw": m["target_kw"], "energy_kwh_today": m["energy_kwh_today"], "energy_kwh_month": m["energy_kwh_month"],
        "price_usd_per_kwh_now": m["price_usd_per_kwh_now"], "cost_usd_today": m["cost_usd_today"],
        "cost_usd_month": m["cost_usd_month"], "demand_peaks_json": cj(m["demand_peaks"]),
        "customers_per_hour": state["customers_per_hour"], "indoor_temp_c": state["indoor_temp_c"],
        "forecast_kw_json": cj(forecast_kw), "forecast_ts": forecast_ts,
    }


def tick_history_row(state: Mapping) -> dict:
    return {"lane": state["lane"], "ts": state["ts"], "total_kw": state["meter"]["total_kw"],
            "block_avg_kw": state["meter"]["block_avg_kw"]}


def live_device_row(lane: str, device: Mapping) -> dict:
    """`live_device` from a HubReport device (what the kitchen floor draws, for every tab)."""
    return {
        "key": f"{lane}:{device['device_id']}", "lane": lane, "device_id": device["device_id"],
        "type_id": device["type_id"], "name": device["name"], "importance": device["importance"],
        "state": device["state"], "power_kw": device["power_kw"], "rated_kw": device["rated_kw"],
        "power_pct": device["power_pct"], "source": device["source"], "physical_json": cj(device.get("physical")),
    }


def live_comparison_row(comparison: Mapping) -> dict:
    return {"id": 0, **dict(_plain(comparison))}


def publish_ticks_payload(states: Mapping[str, Mapping], comparison: Mapping,
                          forecasts: Mapping[str, tuple[Optional[list], Optional[str]]]) -> dict:
    """The `publish_ticks` object for one tick pair: both lanes' live_tick and tick_history, every device of both lanes
    (from each TickState's echoed HubReport), and the LaneComparison. `forecasts[lane]` = (forecast_kw, forecast_ts)."""
    st = {lane: _plain(states[lane]) for lane in LANES}
    return {
        "live_tick": [live_tick_row(st[lane], *forecasts.get(lane, (None, None))) for lane in LANES],
        "tick_history": [tick_history_row(st[lane]) for lane in LANES],
        "live_device": [live_device_row(lane, d) for lane in LANES for d in st[lane]["hub"]["devices"]],
        "live_comparison": live_comparison_row(comparison),
    }


# ---------------------------------------------------------------------------------------------------------------------
# other reducers
# ---------------------------------------------------------------------------------------------------------------------


def feed_row(decision: Mapping, lane: str, explanation: str, explanation_source: str = "template") -> dict:
    d = _plain(decision)
    return {
        "decision_id": d["decision_id"], "lane": lane, "ts": d["ts"], "device_id": d["device_id"],
        "action": d["action"], "value": d["value"], "status": d["status"], "reason_code": d["reason_code"],
        "effect_json": cj(d["effect"]), "explanation": explanation, "explanation_source": explanation_source,
    }


def escalation_row(escalation: Mapping) -> dict:
    e = _plain(escalation)
    return {
        "escalation_id": e["escalation_id"], "lane": e["lane"], "status": e["status"], "block_start": e["block_start"],
        "updated_ts": e["updated_ts"], "problem_json": cj(e["problem"]), "options_json": cj(e["options"]),
        "default_option_id": e["default_option_id"], "active_option_id": e["active_option_id"],
        "deadline_sim_ts": e["deadline_sim_ts"], "chosen_option_id": e["chosen_option_id"],
        "resolved_by": e["resolved_by"], "rationale": e["rationale"],
    }


def context_row(context: Mapping) -> dict:
    """`live_context` summary of a Context (sections as posted; missing sections keep a plain 'unavailable' line)."""
    c = _plain(context)
    w, p, ev, crowd = c.get("weather"), c.get("prices"), c.get("events"), c.get("crowd_effect")
    weather = "%.1f °C now" % w["hourly"][0]["temp_c"] if w and w.get("hourly") else "Weather unavailable"
    prices = ("%.2f USD/kWh now, stress %s" % (p["hourly"][0]["usd_per_kwh"], p["stress"])
              if p and p.get("hourly") else "Prices unavailable")
    events = ("; ".join("%s at %s, %.1f km" % (i["name"], i["venue"], i["distance_km"]) for i in ev["items"])
              if ev else "") or "No events nearby"
    return {
        "id": 0, "weather_summary": weather, "weather_label": (w or {}).get("label", "recorded"),
        "prices_summary": prices, "prices_label": (p or {}).get("label", "recorded"),
        "events_summary": events, "events_label": (ev or {}).get("label", "recorded"),
        "crowd_effect": (crowd or {}).get("value", "none"),
    }


def agent_log_row(log: Mapping) -> dict:
    a = _plain(log)
    return {"ts_real": a["ts_real"], "from_agent": a["from_agent"], "to_agent": a["to_agent"], "kind": a["kind"],
            "summary": a["summary"]}


def backtest_point_row(run_id: str, point: Mapping) -> dict:
    p = _plain(point)
    return {
        "key": f"{run_id}:{p['day']}", "run_id": run_id, "day": p["day"], "month": p["month"], "ts": p["ts"],
        "partial": p["partial"], "cost_to_date_json": cj(p["cost_to_date_usd"]),
        "saved_month_to_date_usd": p["saved_month_to_date_usd"],
        "saved_vs_timer_month_to_date_usd": p["saved_vs_timer_month_to_date_usd"],
        "saved_year_to_date_usd": p["saved_year_to_date_usd"], "dataset": p["dataset"], "tariff_id": p["tariff_id"],
        "assumptions_id": p["assumptions_id"],
    }


def backtest_month_row(run_id: str, result: Mapping) -> dict:
    r = _plain(result)
    return {
        "key": f"{run_id}:{r['month']}", "run_id": run_id, "month": r["month"], "partial": r["partial"],
        "saved_usd": r["saved_usd"], "saved_vs_timer_usd": r["saved_vs_timer_usd"], "policies_json": cj(r["policies"]),
        "checks_json": cj(r["checks"]), "dataset": r["dataset"], "tariff_id": r["tariff_id"],
        "assumptions_id": r["assumptions_id"],
    }


SET_CLOCK_ARGS = ("playing", "speed", "sim_ts", "tick_id", "paused_reason", "day_index", "run_days", "phase", "sim_host")


def set_clock_args(clock: Mapping, sim_host: str) -> list:
    """Positional `set_clock` arguments from a ClockState (the ws `clock` message fields) and the sim host status."""
    c = dict(_plain(clock))
    c["sim_host"] = sim_host
    return [c[k] for k in SET_CLOCK_ARGS]
