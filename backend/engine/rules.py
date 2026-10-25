"""Rules check (ENGINE.md section 8; golden rule 4). Every hard limit is checked here before a Command is emitted.

Times are minutes after local midnight (`tariff.timezone`). A move that breaks an owner limit only happens through an
Escalation (`escalation=True`); the food-safety floor never, whatever the caller says.
"""
from __future__ import annotations

import re
from typing import Any, Mapping, Optional

from pydantic import ValidationError

from contracts import FOOD_SAFETY_MIN_POWER_PCT  # 50, refrigeration set to flexible
from contracts import AlwaysOnLimits, DeferrableLimits, FlexibleLimits

from .tariff import hhmm_to_min


class RuleError(Exception):
    """An unsafe limit or move. The API maps it to HTTP 422."""


IMPORTANCES = ("always_on", "flexible", "deferrable")
LIMIT_KEYS = {
    "always_on": frozenset(),
    "flexible": frozenset({"min_power_pct", "max_reduce_min"}),
    "deferrable": frozenset({"max_delay_min", "must_finish_by"}),
}
ENGINE_ACTIONS = {"flexible": frozenset({"reduce", "restore"}), "deferrable": frozenset({"delay", "start"})}
_LIMITS_MODELS = {"always_on": AlwaysOnLimits, "flexible": FlexibleLimits, "deferrable": DeferrableLimits}
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _as_dict(limits: Any) -> dict:
    if hasattr(limits, "model_dump"):
        return limits.model_dump(mode="json")
    if not isinstance(limits, Mapping):
        raise RuleError(f"limits must be an object, got {type(limits).__name__}")
    return dict(limits)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def power_floor_pct(category: str) -> int:
    """Absolute power floor in % of rated_kw: 50 for refrigeration (food safety), else 0."""
    return FOOD_SAFETY_MIN_POWER_PCT if category == "refrigeration" else 0


def validate_limits(importance: str, limits: Any, category: str, power_model: Optional[str] = None) -> None:
    """Owner limits for one device (set_importance, KitchenConfig, catalog default_limits). With `power_model`, cycling
    refrigeration can't be deferrable (a hold would be 0 %); the job-model ice machine can (ENGINE.md section 8)."""
    if importance not in IMPORTANCES:
        raise RuleError(f"unknown importance {importance!r}")
    lim = _as_dict(limits)
    if frozenset(lim) != LIMIT_KEYS[importance]:
        raise RuleError(f"{importance} needs limits {sorted(LIMIT_KEYS[importance])}, got {sorted(lim)}")
    if importance == "flexible":
        pct, minutes = lim["min_power_pct"], lim["max_reduce_min"]
        if not _is_int(pct) or not 0 < pct <= 100:
            raise RuleError(f"min_power_pct must be an integer with 0 < min_power_pct <= 100, got {pct!r}")
        if not _is_int(minutes) or minutes <= 0:
            raise RuleError(f"max_reduce_min must be an integer > 0, got {minutes!r}")
        if pct < power_floor_pct(category):
            raise RuleError(f"refrigeration set to flexible needs min_power_pct >= {FOOD_SAFETY_MIN_POWER_PCT}")
    elif importance == "deferrable":
        if category == "refrigeration" and power_model is not None and power_model != "job":
            raise RuleError(f"refrigeration with power model {power_model!r} can't be deferrable (only job, e.g. the ice machine)")
        delay, deadline = lim["max_delay_min"], lim["must_finish_by"]
        if not _is_int(delay) or delay < 0:
            raise RuleError(f"max_delay_min must be an integer >= 0, got {delay!r}")
        if not isinstance(deadline, str) or not _HHMM.match(deadline):
            raise RuleError(f"must_finish_by must be local \"HH:MM\", got {deadline!r}")


def normalize_limits(importance: str, limits: Any) -> dict:
    """Limits as the contract model reads them (lax mode: an integral float such as 40.0 is the integer 40); a shape the
    model rejects (40.5, wrong keys) -> RuleError. Bounds are then checked by `validate_limits`."""
    model = _LIMITS_MODELS.get(importance)
    if model is None:
        raise RuleError(f"unknown importance {importance!r}")
    try:
        return model.model_validate(_as_dict(limits)).model_dump(mode="json")
    except ValidationError as exc:
        raise RuleError(f"invalid {importance} limits: {exc.errors()[0]['msg']}") from None


def check_engine_command(importance: str, action: str) -> None:
    """An engine-issued Command: never on always_on; flexible -> reduce/restore; deferrable -> delay/start."""
    if importance == "always_on":
        raise RuleError("always_on devices are never commanded by the engine")
    allowed = ENGINE_ACTIONS.get(importance)
    if allowed is None:
        raise RuleError(f"unknown importance {importance!r}")
    if action not in allowed:
        raise RuleError(f"the engine does not send {action!r} to a {importance} device")


def check_reduce(importance: str, limits: Any, category: str, value_pct: int, *, escalation: bool = False) -> None:
    """`reduce` value = % of rated_kw. Below min_power_pct only through an escalation; below the floor never."""
    if importance != "flexible":
        raise RuleError(f"reduce is only for flexible devices, not {importance}")
    if not _is_int(value_pct) or not 0 <= value_pct <= 100:
        raise RuleError(f"reduce value must be an integer 0..100 % of rated_kw, got {value_pct!r}")
    floor = power_floor_pct(category)
    if value_pct < floor:
        raise RuleError(f"reduce {value_pct} % crosses the food-safety floor {floor} %")
    if not escalation and value_pct < _as_dict(limits)["min_power_pct"]:
        raise RuleError(f"reduce {value_pct} % is below min_power_pct {_as_dict(limits)['min_power_pct']} %")


def effective_deadline_min(must_finish_by: str, close: str) -> int:
    """min(must_finish_by, close) in minutes after local midnight."""
    return min(hhmm_to_min(must_finish_by), hhmm_to_min(close))


def check_hold(importance: str, limits: Any, *, close: str, cycle_min: int, first_applied_min: int,
               release_min: int, open: Optional[str] = None) -> None:
    """A hold: starts while open, total hold <= max_delay_min, release + cycle_min <= effective deadline."""
    if importance != "deferrable":
        raise RuleError(f"holds are only for deferrable devices, not {importance}")
    lim = _as_dict(limits)
    if open is not None and first_applied_min < hhmm_to_min(open):
        raise RuleError("holds start only during operating_hours")
    if release_min < first_applied_min:
        raise RuleError("release before the hold started")
    if release_min - first_applied_min > lim["max_delay_min"]:
        raise RuleError(f"hold of {release_min - first_applied_min} min exceeds max_delay_min {lim['max_delay_min']}")
    deadline = effective_deadline_min(lim["must_finish_by"], close)
    if release_min + cycle_min > deadline:
        raise RuleError(f"job would finish at minute {release_min + cycle_min}, after the deadline {deadline}")


def check_peak_cap(peak_mode: str, peak_cap_kw: Optional[float]) -> None:
    if peak_mode == "cap":
        if peak_cap_kw is None:
            raise RuleError("peak_mode cap needs a peak_cap_kw")
        if isinstance(peak_cap_kw, bool) or not isinstance(peak_cap_kw, (int, float)) or peak_cap_kw <= 0:
            raise RuleError(f"peak_cap_kw must be a number > 0, got {peak_cap_kw!r}")
    elif peak_mode == "minimize":
        if peak_cap_kw is not None:
            raise RuleError("peak_mode minimize needs peak_cap_kw null")
    else:
        raise RuleError(f"unknown peak_mode {peak_mode!r}")
