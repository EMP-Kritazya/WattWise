"""Template explanations: the text every decision gets at once, and the fallback when Claude is off or slow (API.md).

Formatting only: every number is the Decision's engine-computed `value` / `effect`, quoted unchanged.
"""

from __future__ import annotations


def explain_decision(decision: dict, device_name: str) -> str:
    effect = decision["effect"]
    peaks = f"({effect['peak_before_kw']:.1f} → {effect['peak_after_kw']:.1f} kW)"
    if decision["reason_code"] == "escalation_choice":
        return f"Delayed {device_name} {decision['value']:.0f} min (escalation option chosen) {peaks}."
    if decision["action"] == "delay":
        return f"Delayed {device_name} {decision['value']:.0f} min to avoid a new peak {peaks}."
    if decision["action"] == "reduce":
        return f"Reduced {device_name} to {decision['value']:.0f} % to stay under the cap {peaks}."
    return f"Restored {device_name} to normal power to repay its energy {peaks}."
