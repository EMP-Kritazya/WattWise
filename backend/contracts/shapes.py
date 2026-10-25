"""Section 1 of docs/CONTRACTS.md: every shared shape.

Code copy of the prose contract. If this file and docs/CONTRACTS.md disagree, CONTRACTS.md wins: fix this file
(through the `contract-sync` subagent), never the prose.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Optional, Union

from pydantic import ConfigDict, Field, model_validator

from ._base import (
    ContractModel,
    Importance,
    Lane,
    LocalTime,
    NonNegFloat,
    NonNegInt,
    Pct,
    PeakMode,
    UtcDatetime,
    YearMonth,
)

# ---------------------------------------------------------------------------------------------------------------------
# Importance limits
# ---------------------------------------------------------------------------------------------------------------------

FOOD_SAFETY_MIN_POWER_PCT = 50
"""Refrigeration set to flexible must keep `min_power_pct` >= 50 (never crossable)."""


class AlwaysOnLimits(ContractModel):
    """`always_on`: no limits (`{}`)."""


class FlexibleLimits(ContractModel):
    min_power_pct: Pct
    max_reduce_min: NonNegInt


class DeferrableLimits(ContractModel):
    max_delay_min: NonNegInt
    must_finish_by: LocalTime


ImportanceLimits = Union[FlexibleLimits, DeferrableLimits, AlwaysOnLimits]

_LIMITS_FOR: dict[str, type[ContractModel]] = {
    "always_on": AlwaysOnLimits,
    "flexible": FlexibleLimits,
    "deferrable": DeferrableLimits,
}


def _check_limits(importance: str, limits: ContractModel, where: str) -> None:
    expected = _LIMITS_FOR[importance]
    if not isinstance(limits, expected):
        raise ValueError(f"{where}: importance {importance!r} needs limits {expected.__name__}")


# ---------------------------------------------------------------------------------------------------------------------
# EquipmentType (catalog)
# ---------------------------------------------------------------------------------------------------------------------

Category = Literal["cooling", "refrigeration", "cooking", "water_heating", "lighting", "other"]
PowerModel = Literal["fixed", "cycling", "thermal", "demand_driven", "job"]

PARAMS_KEYS: dict[str, frozenset[str]] = {
    "fixed": frozenset(),
    "cycling": frozenset({"duty_idle_pct", "duty_busy_pct"}),
    "thermal": frozenset({"setpoint_c"}),
    "demand_driven": frozenset({"idle_kw", "kw_per_order"}),
    "job": frozenset({"cycle_min"}),
}


class EquipmentType(ContractModel):
    type_id: str
    name: str
    category: Category
    default_importance: Importance
    rated_kw: Annotated[float, Field(gt=0)]
    power_model: PowerModel
    params: dict[str, float]
    default_limits: ImportanceLimits
    source_note: str

    @model_validator(mode="after")
    def _check(self) -> "EquipmentType":
        keys = frozenset(self.params)
        if keys != PARAMS_KEYS[self.power_model]:
            raise ValueError(
                f"{self.type_id}: params for power_model {self.power_model!r} must be "
                f"{sorted(PARAMS_KEYS[self.power_model])}, got {sorted(keys)}"
            )
        _check_limits(self.default_importance, self.default_limits, self.type_id)
        if (
            self.category == "refrigeration"
            and isinstance(self.default_limits, FlexibleLimits)
            and self.default_limits.min_power_pct < FOOD_SAFETY_MIN_POWER_PCT
        ):
            raise ValueError(f"{self.type_id}: refrigeration set to flexible needs min_power_pct >= 50")
        return self


# ---------------------------------------------------------------------------------------------------------------------
# ClaudeAuthority, KitchenConfig
# ---------------------------------------------------------------------------------------------------------------------


class ClaudeAuthority(ContractModel):
    enabled: bool
    max_cap_overrun_kw: NonNegFloat
    max_extra_delay_min: NonNegInt
    max_extra_reduce_min: NonNegInt
    may_go_below_min_power: bool


class EquipmentEntry(ContractModel):
    type_id: str
    count: NonNegInt
    importance: Importance
    limits: ImportanceLimits

    @model_validator(mode="after")
    def _check(self) -> "EquipmentEntry":
        _check_limits(self.importance, self.limits, self.type_id)
        return self


class OperatingHours(ContractModel):
    open: LocalTime
    close: LocalTime


class Location(ContractModel):
    lat: Annotated[float, Field(ge=-90, le=90)]
    lon: Annotated[float, Field(ge=-180, le=180)]
    label: str


def _check_peak_mode(peak_mode: str, peak_cap_kw: Optional[float]) -> None:
    if peak_mode == "cap" and peak_cap_kw is None:
        raise ValueError("peak_mode cap needs a peak_cap_kw")
    if peak_mode == "minimize" and peak_cap_kw is not None:
        raise ValueError("peak_mode minimize needs peak_cap_kw null")


class KitchenConfig(ContractModel):
    name: str
    equipment: list[EquipmentEntry]
    peak_mode: PeakMode
    peak_cap_kw: Optional[Annotated[float, Field(gt=0)]]
    operating_hours: OperatingHours
    location: Location
    owner_preferences: str
    authority: ClaudeAuthority
    tariff_id: str
    run_days: Annotated[int, Field(ge=1)] = 1
    seed: int

    @model_validator(mode="after")
    def _check(self) -> "KitchenConfig":
        _check_peak_mode(self.peak_mode, self.peak_cap_kw)
        return self


# ---------------------------------------------------------------------------------------------------------------------
# Tariff
# ---------------------------------------------------------------------------------------------------------------------


class EnergyPeriod(ContractModel):
    name: str
    start: LocalTime
    end: LocalTime
    usd_per_kwh: NonNegFloat


class DemandWindow(ContractModel):
    start: LocalTime
    end: LocalTime


class DemandCharge(ContractModel):
    name: str
    window: Optional[DemandWindow]
    usd_per_kw: NonNegFloat


class Tariff(ContractModel):
    tariff_id: str
    name: str
    label: Literal["illustrative", "urdb"]
    currency: str
    timezone: str
    energy: list[EnergyPeriod]
    demand: list[DemandCharge]


# ---------------------------------------------------------------------------------------------------------------------
# WarmUpHistory
# ---------------------------------------------------------------------------------------------------------------------


class HistoryBlock(ContractModel):
    block_start: UtcDatetime
    device_id: str
    avg_kw: NonNegFloat


class MonthToDate(ContractModel):
    month: YearMonth
    month_peak_kw: NonNegFloat
    on_peak_month_peak_kw: Optional[NonNegFloat]
    energy_kwh_month: NonNegFloat
    cost_usd_month: NonNegFloat


_HISTORY_LABEL = {"nrel_comstock": "calibrated_model", "fixture_synthetic": "simulated"}


class WarmUpHistory(ContractModel):
    source: Literal["nrel_comstock", "fixture_synthetic"]
    label: Literal["calibrated_model", "simulated"]
    dataset_id: str
    scale: Annotated[float, Field(gt=0)]
    day_offset: int
    start: UtcDatetime
    end: UtcDatetime
    blocks: list[HistoryBlock]
    month_to_date: Optional[MonthToDate]

    @model_validator(mode="after")
    def _check(self) -> "WarmUpHistory":
        if _HISTORY_LABEL[self.source] != self.label:
            raise ValueError(f"source {self.source!r} needs label {_HISTORY_LABEL[self.source]!r}")
        # "Every block ends at or before `end`" is enforced by Kitchen.warm_up (ValueError), not here.
        return self


# ---------------------------------------------------------------------------------------------------------------------
# Warning (TickState.warnings and ws `warning` without `type`)
# ---------------------------------------------------------------------------------------------------------------------


class CapUnreachableData(ContractModel):
    unavoidable_kw: NonNegFloat
    peak_cap_kw: Optional[float]  # null in minimize mode
    target_kw: float


class SimHostOfflineData(ContractModel):
    last_tick_id: NonNegInt


class HubOfflineData(ContractModel):
    device_id: str
    hub_id: str


class EmptyData(ContractModel):
    """`{}`"""


class CapUnreachableWarning(ContractModel):
    code: Literal["cap_unreachable"]
    message: str
    data: CapUnreachableData


class SimHostOfflineWarning(ContractModel):
    code: Literal["sim_host_offline"]
    message: str
    data: SimHostOfflineData


class HubOfflineWarning(ContractModel):
    code: Literal["hub_offline"]
    message: str
    data: HubOfflineData


class LiveTransportDownWarning(ContractModel):
    code: Literal["live_transport_down"]
    message: str
    data: EmptyData


class StoreDownWarning(ContractModel):
    code: Literal["store_down"]
    message: str
    data: EmptyData


WarningShape = Annotated[
    Union[
        CapUnreachableWarning,
        SimHostOfflineWarning,
        HubOfflineWarning,
        LiveTransportDownWarning,
        StoreDownWarning,
    ],
    Field(discriminator="code"),
]
"""`Warning` in CONTRACTS.md (named WarningShape to avoid shadowing Python's builtin `Warning`)."""

WarningCode = Literal["cap_unreachable", "sim_host_offline", "hub_offline", "live_transport_down", "store_down"]


# ---------------------------------------------------------------------------------------------------------------------
# Device, Command, CommandAck, HubReport, Reading
# ---------------------------------------------------------------------------------------------------------------------

DeviceState = Literal["off", "on", "reduced", "waiting", "running_job"]
DeviceSource = Literal["simulated", "measured"]


class DevicePhysical(ContractModel):
    """Optional physical readings from the simulation. CONTRACTS.md: "Unknown keys are ignored" -> extra="ignore"."""

    model_config = ConfigDict(extra="ignore")

    indoor_temp_c: Optional[float] = None
    box_temp_c: Optional[float] = None
    dirty_racks: Optional[NonNegInt] = None
    ice_level_pct: Optional[Annotated[float, Field(ge=0, le=100)]] = None
    job_remaining_min: Optional[NonNegFloat] = None
    orders_in_progress: Optional[NonNegInt] = None


class Device(ContractModel):
    device_id: str
    type_id: str
    name: str
    importance: Importance
    state: DeviceState
    power_kw: NonNegFloat
    rated_kw: Annotated[float, Field(gt=0)]
    power_pct: NonNegInt
    source: DeviceSource
    physical: Optional[DevicePhysical] = None  # optional; absent on the sim_build roster


CommandAction = Literal["on", "off", "start", "delay", "reduce", "restore"]


class Command(ContractModel):
    command_id: str
    lane: Lane
    ts: UtcDatetime
    device_id: str
    action: CommandAction
    value: Optional[int]
    decision_id: Optional[str]
    issued_by: Literal["engine", "owner"]

    @model_validator(mode="after")
    def _check(self) -> "Command":
        if self.action == "reduce" and (self.value is None or not 0 <= self.value <= 100):
            raise ValueError("reduce needs value = % of rated_kw (0..100)")
        if self.action == "delay" and (self.value is None or self.value < 0):
            raise ValueError("delay needs value = minutes >= 0")
        return self


AckReason = Literal["out_of_range", "job_running", "already_off", "unknown_device"]


class CommandAck(ContractModel):
    command_id: str
    lane: Lane
    ok: bool
    applied_value: Optional[int]
    reason: Optional[AckReason]

    @model_validator(mode="after")
    def _check(self) -> "CommandAck":
        if self.ok and self.reason not in (None, "out_of_range"):
            raise ValueError("ok: true allows reason null or out_of_range only")
        if not self.ok and self.reason in (None, "out_of_range"):
            raise ValueError("ok: false needs reason job_running | already_off | unknown_device")
        return self


class HubReport(ContractModel):
    hub_id: str
    lane: Lane
    tick_id: NonNegInt
    ts: UtcDatetime
    total_kw: NonNegFloat
    customers_per_hour: NonNegInt
    devices: list[Device]
    acks: list[CommandAck]
    source: Literal["simulated", "mixed"]


class Reading(ContractModel):
    hub_id: str
    channel: NonNegInt
    device_id: str
    ts: UtcDatetime
    raw_w: float
    scale: Annotated[float, Field(gt=0)]
    power_kw: float


# ---------------------------------------------------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------------------------------------------------

ReasonCode = Literal[
    "avoid_new_peak",
    "stay_under_cap",
    "release_into_valley",
    "catch_up",
    "owner_override",
    "escalation_fallback",
    "escalation_choice",
]


class Effect(ContractModel):
    """Decision.effect and the `what_if` return."""

    peak_before_kw: float
    peak_after_kw: float
    saving_usd: float


class Decision(ContractModel):
    decision_id: str
    ts: UtcDatetime
    device_id: str
    action: CommandAction
    value: Optional[int]
    reason_code: ReasonCode
    inside_rules: bool
    status: Literal["executed", "undone"]
    effect: Effect


# ---------------------------------------------------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------------------------------------------------

ContextLabel = Literal["live_api", "recorded"]
CrowdEffectValue = Literal["none", "small", "medium", "large"]


class HourlyTemp(ContractModel):
    ts: UtcDatetime
    temp_c: float


class HourlyPrice(ContractModel):
    ts: UtcDatetime
    usd_per_kwh: float


class WeatherContext(ContractModel):
    label: ContextLabel
    source: str
    hourly: list[HourlyTemp]


class PricesContext(ContractModel):
    label: ContextLabel
    source: str
    hourly: list[HourlyPrice]
    stress: Literal["low", "normal", "high"]


class EventItem(ContractModel):
    name: str
    venue: str
    start: UtcDatetime
    distance_km: NonNegFloat
    expected_attendance: NonNegInt


class EventsContext(ContractModel):
    label: ContextLabel
    source: str
    items: list[EventItem]


class CrowdEffect(ContractModel):
    value: CrowdEffectValue
    set_by: Literal["claude", "owner", "default"]
    reason: str


class Context(ContractModel):
    """Merged context. Sections are null until some agent has posted them ("Partial posts merge")."""

    ts: UtcDatetime
    weather: Optional[WeatherContext] = None
    prices: Optional[PricesContext] = None
    events: Optional[EventsContext] = None
    crowd_effect: Optional[CrowdEffect] = None


class PartialContext(ContractModel):
    """Body of `POST /api/context` (agents): any subset of Context. `ts` is (re)stamped by the API in sim time."""

    ts: Optional[UtcDatetime] = None
    weather: Optional[WeatherContext] = None
    prices: Optional[PricesContext] = None
    events: Optional[EventsContext] = None
    crowd_effect: Optional[CrowdEffect] = None


# ---------------------------------------------------------------------------------------------------------------------
# Escalation
# ---------------------------------------------------------------------------------------------------------------------

RuleBreakKind = Literal["cap_overrun", "below_min_power", "past_deadline", "over_max_reduce", "over_max_delay"]
EscalationStatus = Literal["open", "resolved", "awaiting_owner", "expired_default", "obsolete"]
ResolvedBy = Literal["claude", "owner", "default"]

_OPTION_ID = re.compile(r"^(accept_overrun|ask_owner|deep_reduce_[a-z0-9_]+|extend_delay_[a-z0-9_]+)$")


class EscalationProblem(ContractModel):
    forecast_peak_kw: float
    target_kw: float
    excess_kw: float
    reason: str


class OptionProjection(ContractModel):
    peak_kw: float
    cost_delta_usd: float
    max_indoor_temp_change_c: Optional[float]  # null = not modelled


class RuleBreak(ContractModel):
    kind: RuleBreakKind
    device_id: Optional[str] = None  # absent for cap_overrun
    amount: float
    unit: Literal["kW", "pct", "min"]


class EscalationOption(ContractModel):
    option_id: Annotated[str, Field(pattern=_OPTION_ID.pattern)]
    summary: str
    actions: list[Command]
    projected: Optional[OptionProjection]
    rule_breaks: list[RuleBreak]
    within_authority: bool
    harm_score: Optional[NonNegFloat]
    rank: Optional[Annotated[int, Field(ge=1)]]

    @model_validator(mode="after")
    def _check(self) -> "EscalationOption":
        if any(a.decision_id is not None for a in self.actions):
            raise ValueError(f"{self.option_id}: option actions are templates (decision_id null)")
        if self.option_id == "ask_owner":
            if self.projected is not None or self.harm_score is not None or self.rank is not None:
                raise ValueError("ask_owner: projected, harm_score and rank are null")
            if self.actions or self.rule_breaks or not self.within_authority:
                raise ValueError("ask_owner: no actions, no rule_breaks, within_authority true")
        elif self.projected is None or self.harm_score is None or self.rank is None:
            raise ValueError(f"{self.option_id}: projected, harm_score and rank are required")
        return self


class Escalation(ContractModel):
    escalation_id: str
    lane: Lane
    ts: UtcDatetime
    updated_ts: UtcDatetime
    block_start: UtcDatetime
    problem: EscalationProblem
    options: Annotated[list[EscalationOption], Field(min_length=2, max_length=4)]
    default_option_id: str
    active_option_id: Optional[str]
    deadline_sim_ts: UtcDatetime
    status: EscalationStatus
    resolved_by: Optional[ResolvedBy]
    chosen_option_id: Optional[str]
    rationale: Optional[str]

    @model_validator(mode="after")
    def _check(self) -> "Escalation":
        ids = [o.option_id for o in self.options]
        if len(set(ids)) != len(ids):
            raise ValueError("option ids must be unique")
        if "accept_overrun" not in ids or "ask_owner" not in ids:
            raise ValueError("options always include accept_overrun and ask_owner")
        for ref in (self.default_option_id, self.active_option_id, self.chosen_option_id):
            if ref is not None and ref not in ids:
                raise ValueError(f"option id {ref!r} is not in options")
        ranks = sorted(o.rank for o in self.options if o.rank is not None)
        if ranks != list(range(1, len(ranks) + 1)):
            raise ValueError("ranks must be 1..n over the evaluated options")
        return self


# ---------------------------------------------------------------------------------------------------------------------
# Meter, TickState, LaneComparison
# ---------------------------------------------------------------------------------------------------------------------


class Meter(ContractModel):
    ts: UtcDatetime
    total_kw: NonNegFloat
    block_avg_kw: NonNegFloat
    block_start: UtcDatetime
    month_peak_kw: NonNegFloat
    on_peak_month_peak_kw: Optional[NonNegFloat]  # null if the tariff has no windowed demand charge
    peak_mode: PeakMode
    peak_cap_kw: Optional[float]  # null in minimize mode
    target_kw: float
    energy_kwh_today: NonNegFloat
    energy_kwh_month: NonNegFloat
    price_usd_per_kwh_now: float
    cost_usd_today: float
    cost_usd_month: float

    @model_validator(mode="after")
    def _check(self) -> "Meter":
        _check_peak_mode(self.peak_mode, self.peak_cap_kw)
        return self


class TickState(ContractModel):
    lane: Lane
    ts: UtcDatetime
    hub: HubReport
    meter: Meter
    customers_per_hour: NonNegInt
    new_decisions: list[Decision]
    new_commands: list[Command]
    new_escalations: list[Escalation]
    warnings: list[WarningShape]
    indoor_temp_c: float
    forecast_kw: Optional[Annotated[list[float], Field(min_length=8, max_length=8)]]


class LaneComparison(ContractModel):
    ts: UtcDatetime
    saved_today_usd: float
    peak_avoided_kw: float
    month_peak_without_kw: NonNegFloat
    month_peak_with_kw: NonNegFloat


# ---------------------------------------------------------------------------------------------------------------------
# Proposal (payload per kind = the matching propose_* input without `summary`)
# ---------------------------------------------------------------------------------------------------------------------

ProposalStatus = Literal["pending", "confirmed", "cancelled", "expired"]


class ImportancePayload(ContractModel):
    device_id: str
    importance: Importance
    limits: ImportanceLimits

    @model_validator(mode="after")
    def _check(self) -> "ImportancePayload":
        _check_limits(self.importance, self.limits, self.device_id)
        return self


class PeakCapPayload(ContractModel):
    peak_mode: PeakMode
    peak_cap_kw: Optional[float]

    @model_validator(mode="after")
    def _check(self) -> "PeakCapPayload":
        _check_peak_mode(self.peak_mode, self.peak_cap_kw)
        return self


class UndoDecisionPayload(ContractModel):
    decision_id: str


class CustomerEventPayload(ContractModel):
    customers: Annotated[int, Field(ge=1)]
    duration_min: Annotated[int, Field(ge=1)]
    start_sim_ts: UtcDatetime


class ResolveEscalationPayload(ContractModel):
    escalation_id: str
    option_id: str


class _ProposalBase(ContractModel):
    proposal_id: str
    ts: UtcDatetime
    summary: str
    status: ProposalStatus
    created_by: Literal["ai"]
    confirmed_via: Optional[Literal["ui", "asi_one"]]
    expires_at: UtcDatetime


class ImportanceProposal(_ProposalBase):
    kind: Literal["importance"]
    payload: ImportancePayload


class PeakCapProposal(_ProposalBase):
    kind: Literal["peak_cap"]
    payload: PeakCapPayload


class AuthorityProposal(_ProposalBase):
    kind: Literal["authority"]
    payload: ClaudeAuthority


class UndoDecisionProposal(_ProposalBase):
    kind: Literal["undo_decision"]
    payload: UndoDecisionPayload


class CustomerEventProposal(_ProposalBase):
    kind: Literal["customer_event"]
    payload: CustomerEventPayload


class ResolveEscalationProposal(_ProposalBase):
    kind: Literal["resolve_escalation"]
    payload: ResolveEscalationPayload


Proposal = Annotated[
    Union[
        ImportanceProposal,
        PeakCapProposal,
        AuthorityProposal,
        UndoDecisionProposal,
        CustomerEventProposal,
        ResolveEscalationProposal,
    ],
    Field(discriminator="kind"),
]


# ---------------------------------------------------------------------------------------------------------------------
# Bill, BacktestResult
# ---------------------------------------------------------------------------------------------------------------------


class BillDemandCharge(ContractModel):
    name: str
    peak_kw: NonNegFloat
    cost_usd: float


class Bill(ContractModel):
    period: YearMonth
    energy_kwh: NonNegFloat
    energy_cost_usd: float
    demand_charges: list[BillDemandCharge]
    total_usd: float
    tariff_id: str


class BacktestPolicies(ContractModel):
    without: Bill
    timer: Bill
    with_: Bill = Field(alias="with")


class BacktestChecks(ContractModel):
    baseline_matches_raw: bool
    energy_conserved: bool
    rule_violations: NonNegInt


class BacktestResult(ContractModel):
    dataset: str
    month: YearMonth
    policies: BacktestPolicies
    checks: BacktestChecks
    assumptions_id: str


# ---------------------------------------------------------------------------------------------------------------------
# AgentLog (section 7; also the body of POST /api/agent-log and the ws `agent_log` message)
# ---------------------------------------------------------------------------------------------------------------------

AgentName = Literal["concierge", "weather", "grid", "events", "claude", "engine"]


class AgentLog(ContractModel):
    ts_real: UtcDatetime
    from_agent: AgentName
    to_agent: AgentName
    kind: Literal["request", "response", "post", "error"]
    summary: str
