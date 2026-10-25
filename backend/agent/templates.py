"""Template text: what every decision gets at once, and the fallback when Claude is off or slow (API.md).

Formatting only: every number is an engine-computed field (the Decision's `value` / `effect`, the Meter), quoted
unchanged. Text from here is marked `explanation_source: "template"`.
"""

from __future__ import annotations

OFFLINE = "The assistant is offline right now (Claude is not configured), so I can't answer questions."
CHAT_FAILED = "Sorry, I couldn't finish that answer. Please try again in a moment."


def explain_decision(decision: dict, device_name: str) -> str:
    effect = decision["effect"]
    peaks = f"({effect['peak_before_kw']:.1f} → {effect['peak_after_kw']:.1f} kW)"
    if decision["reason_code"] == "escalation_fallback":
        action = decision["action"]
        if action == "delay":
            return f"The engine applied its escalation fallback: delayed {device_name} {decision['value']:.0f} min {peaks}."
        if action == "reduce":
            return f"The engine applied its escalation fallback: reduced {device_name} to {decision['value']:.0f} % {peaks}."
        return f"The engine applied its escalation fallback for {device_name} {peaks}."
    if decision["reason_code"] == "escalation_choice":
        return f"Delayed {device_name} {decision['value']:.0f} min (escalation option chosen) {peaks}."
    if decision["action"] == "delay":
        return f"Delayed {device_name} {decision['value']:.0f} min to avoid a new peak {peaks}."
    if decision["action"] == "reduce":
        return f"Reduced {device_name} to {decision['value']:.0f} % to stay under the cap {peaks}."
    return f"Restored {device_name} to normal power to repay its energy {peaks}."


def explain_escalation(escalation: dict, option: dict | None) -> str:
    """A factual escalation report when there is no generated explanation."""
    summary = option["summary"] if option else escalation["chosen_option_id"]
    if escalation["resolved_by"] == "claude":
        rationale = escalation.get("rationale")
        if rationale:
            return f"Claude chose {summary} because {rationale.rstrip('.')} .".replace(" .", ".")
        return f"Claude chose {summary}."
    if escalation["resolved_by"] == "owner":
        return f"The owner chose: {summary}."
    return f"The engine's escalation fallback is active: {summary}."


def chat_reply(meter: dict | None) -> str:
    """The chat answer with no Claude key (or a failed call): the live Meter, quoted unchanged."""
    if meter is None:
        return f"{OFFLINE} Build a kitchen to see live numbers on the dashboard."
    target = f"the {meter['target_kw']:.1f} kW target" if meter.get("target_kw") is not None else "no fixed cap"
    return (
        f"{OFFLINE} Live numbers from the engine: ${meter['cost_usd_today']:.2f} so far today, "
        f"${meter['cost_usd_month']:.2f} this month; the current 15-min average is {meter['block_avg_kw']:.1f} kW "
        f"against {target}."
    )
