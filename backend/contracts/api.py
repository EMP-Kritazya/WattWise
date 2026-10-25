"""Section 2 of docs/CONTRACTS.md: REST bodies (requests and responses that are not a section 1 shape) + ClockState."""
from __future__ import annotations

from typing import Annotated, Literal, Optional

from pydantic import Field, model_validator

from ._base import ContractModel, Importance, NonNegInt, PeakMode, UtcDatetime, YearMonth
from .shapes import (
    CommandAction,
    CrowdEffectValue,
    Device,
    ImportanceLimits,
    KitchenConfig,
    Tariff,
    _check_limits,
    _check_peak_mode,
)

# ---------------------------------------------------------------------------------------------------------------------
# ClockState (= ws `clock` without `type`; also the POST /api/sim/control response and the live_clock row fields)
# ---------------------------------------------------------------------------------------------------------------------

PausedReason = Literal["manual", "hub_waiting", "sim_host_offline", "run_complete"]
Phase = Literal["service", "overnight", "closed"]


class ClockState(ContractModel):
    playing: bool
    speed: Annotated[int, Field(gt=0)]
    sim_ts: UtcDatetime
    tick_id: NonNegInt
    paused_reason: Optional[PausedReason]
    day_index: Annotated[int, Field(ge=1)]
    run_days: Annotated[int, Field(ge=1)]
    phase: Phase

    @model_validator(mode="after")
    def _check(self) -> "ClockState":
        if self.day_index > self.run_days:
            raise ValueError("day_index must be <= run_days")
        if (self.paused_reason == "run_complete") != (self.phase == "closed"):
            raise ValueError("paused_reason run_complete <=> phase closed")
        return self


# ---------------------------------------------------------------------------------------------------------------------
# Generic responses
# ---------------------------------------------------------------------------------------------------------------------


class Ok(ContractModel):
    """'-> ok' = { "ok": true }"""

    ok: Literal[True]


class ErrorDetail(ContractModel):
    """422 (RuleError, invalid body) or 404 (unknown id)."""

    detail: str


# ---------------------------------------------------------------------------------------------------------------------
# Requests and responses per endpoint (in CONTRACTS.md table order)
# ---------------------------------------------------------------------------------------------------------------------


class KitchenCreated(ContractModel):
    """POST /api/kitchen -> { kitchen_id }"""

    kitchen_id: str


class KitchenView(ContractModel):
    """GET /api/kitchen"""

    config: KitchenConfig
    devices: list[Device]
    tariff: Tariff


class ImportanceUpdate(ContractModel):
    """PUT /api/kitchen/devices/{device_id}/importance"""

    importance: Importance
    limits: ImportanceLimits

    @model_validator(mode="after")
    def _check(self) -> "ImportanceUpdate":
        _check_limits(self.importance, self.limits, "limits")
        return self


class PeakCapUpdate(ContractModel):
    """PUT /api/kitchen/peak-cap (`peak_cap_kw` required for cap, null for minimize) -> Meter"""

    peak_mode: PeakMode
    peak_cap_kw: Optional[Annotated[float, Field(gt=0)]]

    @model_validator(mode="after")
    def _check(self) -> "PeakCapUpdate":
        _check_peak_mode(self.peak_mode, self.peak_cap_kw)
        return self


class SimControlRequest(ContractModel):
    """POST /api/sim/control -> ClockState (`next_day` only while paused_reason is run_complete; else 422)"""

    action: Literal["play", "pause", "reset", "next_day"]
    speed: Optional[Annotated[int, Field(gt=0)]] = None


class DeviceCommandRequest(ContractModel):
    """POST /api/devices/{device_id}/command -> Command (issued_by owner)"""

    action: CommandAction
    value: Optional[int] = None


class CustomerEventRequest(ContractModel):
    """POST /api/events/customers -> ok"""

    customers: Annotated[int, Field(ge=1)]
    duration_min: Annotated[int, Field(ge=1)]


class BacktestRunRequest(ContractModel):
    """POST /api/backtest/run"""

    months: list[YearMonth]
    assumptions_id: str


class BacktestRunCreated(ContractModel):
    run_id: str


class ChatRequest(ContractModel):
    """POST /api/chat"""

    message: str


class ChatCreated(ContractModel):
    chat_id: str


class ProposalConfirmRequest(ContractModel):
    """POST /api/proposals/{proposal_id}/confirm -> Proposal"""

    confirm: bool


class PreferencesUpdate(ContractModel):
    """PUT /api/kitchen/preferences -> ok"""

    text: str


class CrowdEffectRequest(ContractModel):
    """POST /api/context/crowd-effect -> ok (Concierge, X-Agent-Token)"""

    value: CrowdEffectValue
    reason: str


class Health(ContractModel):
    """GET /api/health"""

    ok: bool
    kitchen_impl: Literal["fake", "real"]
    live_transport: Literal["spacetime", "ws"]
    store: Literal["convex", "memory"]
    hardware: Literal["off", "sim_bridge", "esp32"]
    sim_host: Literal["connected", "offline"]
