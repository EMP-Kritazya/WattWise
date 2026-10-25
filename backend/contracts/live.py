"""Section 5 of docs/CONTRACTS.md: SpacetimeDB rows as the runtime publishes them (via backend/live/spacetime_client.py).

The SpacetimeDB module in `spacetime/` is generated-binding truth for the browser; these models are the Python copy used
to build reducer payloads. `*_json` columns hold a JSON string of the section 1 shape; it is parsed and checked here.
"""
from __future__ import annotations

import json
from typing import Annotated, Any, Literal, Optional

from pydantic import Field, TypeAdapter, field_validator

from ._base import ContractModel, Importance, Lane, NonNegFloat, NonNegInt, PeakMode, UtcDatetime
from .api import ClockState
from .shapes import (
    AgentLog,
    CommandAction,
    ContextLabel,
    CrowdEffectValue,
    DevicePhysical,
    DeviceSource,
    DeviceState,
    EscalationOption,
    EscalationProblem,
    EscalationStatus,
    Effect,
    LaneComparison,
    ReasonCode,
    ResolvedBy,
)


def _json_of(adapter: TypeAdapter, raw: Optional[str], column: str) -> Optional[str]:
    if raw is None:
        return raw
    try:
        parsed: Any = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{column} is not valid JSON: {exc}") from exc
    adapter.validate_python(parsed)
    return raw


_FORECAST = TypeAdapter(Optional[Annotated[list[float], Field(min_length=8, max_length=8)]])
_PHYSICAL = TypeAdapter(DevicePhysical)
_EFFECT = TypeAdapter(Effect)
_PROBLEM = TypeAdapter(EscalationProblem)
_OPTIONS = TypeAdapter(list[EscalationOption])


class LiveTickRow(ContractModel):
    lane: Lane
    ts: UtcDatetime
    tick_id: NonNegInt
    total_kw: NonNegFloat
    block_avg_kw: NonNegFloat
    month_peak_kw: NonNegFloat
    on_peak_month_peak_kw: Optional[NonNegFloat]
    peak_mode: PeakMode
    peak_cap_kw: Optional[float]
    target_kw: float
    energy_kwh_today: NonNegFloat
    energy_kwh_month: NonNegFloat
    price_usd_per_kwh_now: float
    cost_usd_today: float
    cost_usd_month: float
    customers_per_hour: NonNegInt
    indoor_temp_c: float
    forecast_kw_json: Optional[str]  # the latest forecast (kept between decision ticks); null before the first one
    forecast_ts: Optional[UtcDatetime]

    @field_validator("forecast_kw_json")
    @classmethod
    def _forecast(cls, v: Optional[str]) -> Optional[str]:
        return _json_of(_FORECAST, v, "forecast_kw_json")


class TickHistoryRow(ContractModel):
    lane: Lane
    ts: UtcDatetime
    total_kw: NonNegFloat
    block_avg_kw: NonNegFloat


class LiveDeviceRow(ContractModel):
    key: Annotated[str, Field(pattern=r"^(without|with):.+$")]  # "<lane>:<device_id>"
    lane: Lane
    device_id: str
    type_id: str
    name: str
    importance: Importance
    state: DeviceState
    power_kw: NonNegFloat
    rated_kw: Annotated[float, Field(gt=0)]
    power_pct: NonNegInt
    source: DeviceSource
    physical_json: Optional[str]

    @field_validator("physical_json")
    @classmethod
    def _physical(cls, v: Optional[str]) -> Optional[str]:
        return _json_of(_PHYSICAL, v, "physical_json")


class LiveComparisonRow(LaneComparison):
    id: Literal[0]


class LiveFeedRow(ContractModel):
    decision_id: str
    lane: Lane
    ts: UtcDatetime
    device_id: str
    action: CommandAction
    value: Optional[int]
    status: Literal["executed", "undone"]
    reason_code: ReasonCode
    effect_json: str
    explanation: str
    explanation_source: Literal["ai", "template"]

    @field_validator("effect_json")
    @classmethod
    def _effect(cls, v: str) -> str:
        return _json_of(_EFFECT, v, "effect_json")


class LiveClockRow(ClockState):
    id: Literal[0]
    sim_host: Literal["connected", "offline"]


class LiveContextRow(ContractModel):
    id: Literal[0]
    weather_summary: str
    weather_label: ContextLabel
    prices_summary: str
    prices_label: ContextLabel
    events_summary: str
    events_label: ContextLabel
    crowd_effect: CrowdEffectValue


class LiveEscalationRow(ContractModel):
    escalation_id: str
    lane: Lane
    status: EscalationStatus
    block_start: UtcDatetime
    updated_ts: UtcDatetime
    problem_json: str
    options_json: str  # options with harm_score and rank
    default_option_id: str
    active_option_id: Optional[str]
    deadline_sim_ts: UtcDatetime
    chosen_option_id: Optional[str]
    resolved_by: Optional[ResolvedBy]
    rationale: Optional[str]

    @field_validator("problem_json")
    @classmethod
    def _problem(cls, v: str) -> str:
        return _json_of(_PROBLEM, v, "problem_json")

    @field_validator("options_json")
    @classmethod
    def _options(cls, v: str) -> str:
        return _json_of(_OPTIONS, v, "options_json")


class LiveAgentLogRow(AgentLog):
    id: NonNegInt


class SurgeRequestRow(ContractModel):
    id: NonNegInt
    customers: Annotated[int, Field(ge=1, le=80)]
    duration_min: Annotated[int, Field(ge=15, le=120)]
    requested_by: str
    created_at: UtcDatetime
    consumed: bool


class PublishTicksPayload(ContractModel):
    """`publish_ticks(payload_json)`: the object whose JSON string is the reducer argument."""

    live_tick: Annotated[list[LiveTickRow], Field(min_length=2, max_length=2)]
    tick_history: Annotated[list[TickHistoryRow], Field(min_length=2, max_length=2)]
    live_device: list[LiveDeviceRow]
    live_comparison: LiveComparisonRow
