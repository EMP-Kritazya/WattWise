"""API names backed by the canonical shared contracts.

Only the facade snapshot remains a local DTO.
"""
from contracts import *
from contracts.shapes import EscalationStatus, ProposalStatus, CrowdEffectValue
from contracts.ws import ViewerMessageUnion as WsMessage, WarningMessage as WarningMessageUnion
from pydantic import TypeAdapter

class WarningMessage:
    """Compatibility validator returning the canonical typed warning."""
    model_validate = staticmethod(TypeAdapter(WarningMessageUnion).validate_python)
from contracts import BacktestRunCreated as BacktestRunStarted, ChatCreated as ChatStarted
IsoTs = UtcDatetime

class KitchenSnapshot(ContractModel):
    """Pure per-lane facade read used by the runtime and AI tools (CONTRACTS.md §3)."""

    tick_id: int
    sim_ts: IsoTs
    lane: Lane
    control: Lane
    peak_mode: PeakMode
    config: KitchenConfig
    meter: Meter
    forecast_kw: list[float] | None
    forecast_ts: IsoTs | None
    devices: list[Device]
    active_commands: list[Command]
    owed_kwh: dict[str, float]
    open_escalations: list[Escalation]
    warnings: list[WarningShape]
    recent_decisions: list[Decision]
    context: Context | None
    id_counters: dict[str, int]
