# STUB: replace with backend/contracts once Kritazya publishes it
"""Pydantic v2 models mirroring docs/CONTRACTS.md §1 (shared shapes) and §2 (REST bodies + /ws messages).

Field names, enums and units follow the contract exactly. Timestamps stay ISO 8601 strings (UTC, `Z`) and local
clock times stay "HH:MM" strings, so values round-trip unchanged. Every model forbids unknown keys so drift from the
contract fails loudly.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


IsoTs = Annotated[str, Field(description="ISO 8601 timestamp, UTC with Z")]
LocalTime = Annotated[str, Field(description='Local clock time "HH:MM"')]

Importance = Literal["always_on", "flexible", "deferrable"]
Category = Literal["cooling", "refrigeration", "cooking", "water_heating", "lighting", "other"]
PowerModel = Literal["fixed", "cycling", "thermal", "demand_driven", "job"]
PeakMode = Literal["minimize", "cap"]
Lane = Literal["without", "with"]
DeviceState = Literal["off", "on", "reduced", "waiting", "running_job"]
DeviceSource = Literal["simulated", "measured"]
CommandAction = Literal["on", "off", "start", "delay", "reduce", "restore"]
IssuedBy = Literal["engine", "owner"]
AckReason = Literal["out_of_range", "job_running", "already_off", "unknown_device"]
ReasonCode = Literal[
    "avoid_new_peak", "stay_under_cap", "release_into_valley", "catch_up", "owner_override", "escalation_choice"
]
DecisionStatus = Literal["executed", "undone"]
ContextLabel = Literal["live_api", "recorded"]
PriceStress = Literal["low", "normal", "high"]
CrowdEffectValue = Literal["none", "small", "medium", "large"]
CrowdEffectSetBy = Literal["claude", "owner", "default"]
EscalationStatus = Literal["open", "resolved", "awaiting_owner", "expired_default"]
ResolvedBy = Literal["claude", "owner", "default"]
RuleBreakKind = Literal["cap_overrun", "below_min_power", "past_deadline", "over_max_reduce", "over_max_delay"]
ProposalKind = Literal["importance", "peak_cap", "authority", "undo_decision", "customer_event", "resolve_escalation"]
ProposalStatus = Literal["pending", "confirmed", "cancelled", "expired"]
ConfirmedVia = Literal["ui", "asi_one"]
AgentName = Literal["concierge", "weather", "grid", "events", "claude", "engine"]
AgentLogKind = Literal["request", "response", "post", "error"]
PausedReason = Literal["escalation", "approval", "hub_waiting", "sim_host_offline"]
SlowedReason = Literal["escalation"]
Speed = Literal[1, 30, 120, 600]


# ---------------------------------------------------------------- §1 shared shapes

class ImportanceLimits(ContractModel):
    """Owner limits; which keys apply depends on the importance (always_on: none)."""

    min_power_pct: int | None = None
    max_reduce_min: int | None = None
    max_delay_min: int | None = None
    must_finish_by: LocalTime | None = None


class EquipmentType(ContractModel):
    type_id: str
    name: str
    category: Category
    default_importance: Importance
    rated_kw: float
    power_model: PowerModel
    params: dict[str, float]
    default_limits: ImportanceLimits
    source_note: str


class EquipmentEntry(ContractModel):
    type_id: str
    count: int
    importance: Importance
    limits: ImportanceLimits


class OperatingHours(ContractModel):
    open: LocalTime
    close: LocalTime


class Location(ContractModel):
    lat: float
    lon: float
    label: str


class ClaudeAuthority(ContractModel):
    enabled: bool
    max_cap_overrun_kw: float
    max_extra_delay_min: int
    max_extra_reduce_min: int
    may_go_below_min_power: bool


class KitchenConfig(ContractModel):
    name: str
    equipment: list[EquipmentEntry]
    peak_mode: PeakMode
    peak_cap_kw: float | None
    operating_hours: OperatingHours
    location: Location
    owner_preferences: str
    authority: ClaudeAuthority
    tariff_id: str
    seed: int


class TimeWindow(ContractModel):
    start: LocalTime
    end: LocalTime


class EnergyRate(ContractModel):
    name: str
    start: LocalTime
    end: LocalTime
    usd_per_kwh: float


class DemandRate(ContractModel):
    name: str
    window: TimeWindow | None
    usd_per_kw: float


class Tariff(ContractModel):
    tariff_id: str
    name: str
    label: Literal["illustrative", "urdb"]
    currency: str
    timezone: str
    energy: list[EnergyRate]
    demand: list[DemandRate]


class Device(ContractModel):
    device_id: str
    type_id: str
    name: str
    importance: Importance
    state: DeviceState
    power_kw: float
    rated_kw: float
    power_pct: int
    source: DeviceSource
    physical: dict[str, float] | None = None


class CommandAck(ContractModel):
    command_id: str
    lane: Lane
    ok: bool
    applied_value: int | None
    reason: AckReason | None


class HubReport(ContractModel):
    hub_id: str
    lane: Lane
    tick_id: int
    ts: IsoTs
    total_kw: float
    customers_per_hour: int
    devices: list[Device]
    acks: list[CommandAck]
    source: Literal["simulated", "mixed"]


class Reading(ContractModel):
    hub_id: str
    channel: int
    device_id: str
    ts: IsoTs
    raw_w: float
    scale: float
    power_kw: float


class Command(ContractModel):
    command_id: str
    lane: Lane
    ts: IsoTs
    device_id: str
    action: CommandAction
    value: int | None
    decision_id: str | None
    issued_by: IssuedBy


class Effect(ContractModel):
    peak_before_kw: float
    peak_after_kw: float
    saving_usd: float


class Decision(ContractModel):
    decision_id: str
    ts: IsoTs
    device_id: str
    action: CommandAction
    value: int | None
    reason_code: ReasonCode
    inside_rules: bool
    status: DecisionStatus
    effect: Effect


class WeatherPoint(ContractModel):
    ts: IsoTs
    temp_c: float


class Weather(ContractModel):
    label: ContextLabel
    source: str
    hourly: list[WeatherPoint]


class PricePoint(ContractModel):
    ts: IsoTs
    usd_per_kwh: float


class Prices(ContractModel):
    label: ContextLabel
    source: str
    hourly: list[PricePoint]
    stress: PriceStress


class EventItem(ContractModel):
    name: str
    venue: str
    start: IsoTs
    distance_km: float
    expected_attendance: int


class Events(ContractModel):
    label: ContextLabel
    source: str
    items: list[EventItem]


class CrowdEffect(ContractModel):
    value: CrowdEffectValue
    set_by: CrowdEffectSetBy
    reason: str


class Context(ContractModel):
    """Every part is optional: agents post partial Context and posts merge (`ts` is stamped by the API)."""

    ts: IsoTs | None = None
    weather: Weather | None = None
    prices: Prices | None = None
    events: Events | None = None
    crowd_effect: CrowdEffect | None = None


class EscalationProblem(ContractModel):
    forecast_peak_kw: float
    target_kw: float
    excess_kw: float
    reason: str


class OptionProjection(ContractModel):
    peak_kw: float
    cost_delta_usd: float
    max_indoor_temp_change_c: float


class RuleBreak(ContractModel):
    kind: RuleBreakKind
    device_id: str | None = None
    amount: float
    unit: str


class EscalationOption(ContractModel):
    option_id: str
    summary: str
    actions: list[Command]
    projected: OptionProjection | None
    rule_breaks: list[RuleBreak]
    within_authority: bool


class Escalation(ContractModel):
    escalation_id: str
    lane: Lane
    ts: IsoTs
    block_start: IsoTs
    problem: EscalationProblem
    options: list[EscalationOption]
    default_option_id: str
    deadline_sim_ts: IsoTs
    status: EscalationStatus
    resolved_by: ResolvedBy | None
    chosen_option_id: str | None
    rationale: str | None


class Meter(ContractModel):
    ts: IsoTs
    total_kw: float
    block_avg_kw: float
    block_start: IsoTs
    month_peak_kw: float
    peak_mode: PeakMode
    peak_cap_kw: float | None
    target_kw: float
    energy_kwh_today: float
    price_usd_per_kwh_now: float
    cost_usd_today: float
    cost_usd_month: float


class TickState(ContractModel):
    """PROVISIONAL (engine TBD) in the contract; shape is fixed."""

    lane: Lane
    ts: IsoTs
    hub: HubReport
    meter: Meter
    customers_per_hour: int
    new_decisions: list[Decision]
    new_commands: list[Command]
    new_escalations: list[Escalation]
    indoor_temp_c: float
    forecast_kw: list[float] | None


class LaneComparison(ContractModel):
    ts: IsoTs
    saved_today_usd: float
    peak_avoided_kw: float
    month_peak_without_kw: float
    month_peak_with_kw: float


class ImportancePayload(ContractModel):
    device_id: str
    importance: Importance
    limits: ImportanceLimits


class PeakCapPayload(ContractModel):
    peak_mode: PeakMode
    peak_cap_kw: float | None


class UndoDecisionPayload(ContractModel):
    decision_id: str


class CustomerEventPayload(ContractModel):
    customers: int
    duration_min: int
    start_sim_ts: IsoTs


class ResolveEscalationPayload(ContractModel):
    escalation_id: str
    option_id: str


class Proposal(ContractModel):
    proposal_id: str
    ts: IsoTs
    kind: ProposalKind
    # payload per kind = the matching propose_* input without `summary`; `authority` payload = ClaudeAuthority
    payload: Union[
        ImportancePayload,
        PeakCapPayload,
        ClaudeAuthority,
        UndoDecisionPayload,
        CustomerEventPayload,
        ResolveEscalationPayload,
    ]
    summary: str
    status: ProposalStatus
    created_by: Literal["ai"]
    confirmed_via: ConfirmedVia | None
    expires_at: IsoTs


class DemandChargeLine(ContractModel):
    name: str
    peak_kw: float
    cost_usd: float


class Bill(ContractModel):
    period: str
    energy_kwh: float
    energy_cost_usd: float
    demand_charges: list[DemandChargeLine]
    total_usd: float
    tariff_id: str


class BacktestPolicies(ContractModel):
    without: Bill
    timer: Bill
    with_: Bill = Field(alias="with")


class BacktestChecks(ContractModel):
    baseline_matches_raw: bool
    energy_conserved: bool
    rule_violations: int


class BacktestResult(ContractModel):
    dataset: str
    month: str
    policies: BacktestPolicies
    checks: BacktestChecks
    assumptions_id: str


class AgentLog(ContractModel):
    ts_real: IsoTs
    from_agent: AgentName
    to_agent: AgentName
    kind: AgentLogKind
    summary: str


# ---------------------------------------------------------------- §2 REST bodies

class Ok(ContractModel):
    ok: bool = True


class ErrorDetail(ContractModel):
    detail: str


class KitchenCreated(ContractModel):
    kitchen_id: str


class KitchenView(ContractModel):
    config: KitchenConfig
    devices: list[Device]
    tariff: Tariff


class ImportanceUpdate(ContractModel):
    importance: Importance
    limits: ImportanceLimits


class PeakCapUpdate(ContractModel):
    """`peak_cap_kw` required for `cap`, null for `minimize` (checked by the engine: RuleError → 422)."""

    peak_mode: PeakMode
    peak_cap_kw: float | None = None


class SimControlRequest(ContractModel):
    action: Literal["play", "pause", "reset"]
    speed: Speed | None = None


class ClockState(ContractModel):
    playing: bool
    speed: int
    sim_ts: IsoTs
    tick_id: int
    paused_reason: PausedReason | None
    slowed_reason: SlowedReason | None


class DeviceCommandRequest(ContractModel):
    action: CommandAction
    value: int | None = None


class CustomerEventRequest(ContractModel):
    customers: int
    duration_min: int


class BacktestRunRequest(ContractModel):
    months: list[str]
    assumptions_id: str


class BacktestRunStarted(ContractModel):
    run_id: str


class ChatRequest(ContractModel):
    message: str


class ChatStarted(ContractModel):
    chat_id: str


class ProposalConfirmRequest(ContractModel):
    confirm: bool


class PreferencesUpdate(ContractModel):
    text: str


class CrowdEffectRequest(ContractModel):
    value: CrowdEffectValue
    reason: str


class EscalationResolveRequest(ContractModel):
    option_id: str


class Health(ContractModel):
    ok: bool
    kitchen_impl: Literal["fake", "real"]
    live_transport: Literal["spacetime", "ws"]
    store: Literal["convex", "memory"]
    hardware: Literal["off", "sim_bridge", "esp32"]
    sim_host: Literal["connected", "offline"]


# ---------------------------------------------------------------- §2 viewer /ws messages (server → client)

class TickMessage(ContractModel):
    type: Literal["tick"]
    data: TickState


class DecisionMessage(ContractModel):
    type: Literal["decision"]
    data: Decision
    explanation: str
    explanation_source: Literal["ai", "template"]


class ClockMessage(ContractModel):
    type: Literal["clock"]
    playing: bool
    speed: int
    sim_ts: IsoTs
    tick_id: int
    paused_reason: PausedReason | None
    slowed_reason: SlowedReason | None


class WarningMessage(ContractModel):
    type: Literal["warning"]
    code: Literal["cap_unreachable", "sim_host_offline", "hub_offline", "live_transport_down", "store_down"]
    message: str
    # per code: cap_unreachable {unavoidable_kw, peak_cap_kw} · sim_host_offline {last_tick_id} ·
    # hub_offline {device_id, hub_id} · live_transport_down {} · store_down {}
    data: dict[str, Any]


class ChatDeltaMessage(ContractModel):
    type: Literal["chat_delta"]
    chat_id: str
    text: str


class ChatDoneMessage(ContractModel):
    type: Literal["chat_done"]
    chat_id: str


class BacktestProgressMessage(ContractModel):
    type: Literal["backtest_progress"]
    run_id: str
    month: str
    pct: int


class ComparisonMessage(ContractModel):
    type: Literal["comparison"]
    data: LaneComparison


class ProposalMessage(ContractModel):
    type: Literal["proposal"]
    data: Proposal


class EscalationMessage(ContractModel):
    type: Literal["escalation"]
    data: Escalation


class ContextMessage(ContractModel):
    type: Literal["context"]
    data: Context


class AgentLogMessage(ContractModel):
    type: Literal["agent_log"]
    data: AgentLog


WsMessage = Annotated[
    Union[
        TickMessage,
        DecisionMessage,
        ClockMessage,
        WarningMessage,
        ChatDeltaMessage,
        ChatDoneMessage,
        BacktestProgressMessage,
        ComparisonMessage,
        ProposalMessage,
        EscalationMessage,
        ContextMessage,
        AgentLogMessage,
    ],
    Field(discriminator="type"),
]
