"""Section 8 of docs/CONTRACTS.md: hub protocol on WebSocket `/ws/hub` (browser hub <-> FastAPI)."""
from __future__ import annotations

from typing import Annotated, Literal, Optional, Union

from pydantic import Field, RootModel, model_validator

from ._base import ContractModel, NonNegInt, UtcDatetime
from .api import PausedReason
from .shapes import Command, Device, EquipmentType, HubReport, KitchenConfig

# ---------------------------------------------------------------------------------------------------------------------
# Hub -> server
# ---------------------------------------------------------------------------------------------------------------------


class HubHello(ContractModel):
    type: Literal["hub_hello"]
    protocol: Literal[1]
    hub_id: str
    role: Literal["sim_host"]
    client: str


class LaneReports(ContractModel):
    without: HubReport
    with_: HubReport = Field(alias="with")

    @model_validator(mode="after")
    def _check(self) -> "LaneReports":
        if self.without.lane != "without" or self.with_.lane != "with":
            raise ValueError("reports.<lane> must carry a HubReport of that lane")
        return self


class HubReportMessage(ContractModel):
    type: Literal["hub_report"]
    tick_id: NonNegInt
    reports: LaneReports

    @model_validator(mode="after")
    def _check(self) -> "HubReportMessage":
        if self.reports.without.tick_id != self.tick_id or self.reports.with_.tick_id != self.tick_id:
            raise ValueError("each HubReport carries the message tick_id")
        return self


HubToServerUnion = Annotated[Union[HubHello, HubReportMessage], Field(discriminator="type")]


class HubToServerMessage(RootModel[HubToServerUnion]):
    """Any message the hub sends on `/ws/hub`."""


# ---------------------------------------------------------------------------------------------------------------------
# Server -> hub
# ---------------------------------------------------------------------------------------------------------------------


class HubWelcome(ContractModel):
    type: Literal["hub_welcome"]
    accepted: bool
    reason: Optional[Literal["host_taken"]]
    tick_id: NonNegInt  # the last tick the server completed (the reconnect cue)

    @model_validator(mode="after")
    def _check(self) -> "HubWelcome":
        if self.accepted != (self.reason is None):
            raise ValueError("accepted true <=> reason null; accepted false => reason host_taken")
        return self


class SimBuild(ContractModel):
    type: Literal["sim_build"]
    kitchen_id: str
    config: KitchenConfig
    catalog: list[EquipmentType]
    devices: list[Device]
    seed: int
    start_sim_ts: UtcDatetime


class Surge(ContractModel):
    surge_id: str
    customers: Annotated[int, Field(ge=1)]
    duration_min: Annotated[int, Field(ge=1)]


class SimInputs(ContractModel):
    outdoor_temp_c: Optional[float]  # null = no context yet -> the simulation's built-in summer-day curve
    crowd_multiplier: Annotated[float, Field(gt=0)]
    is_open: bool


class SimTick(ContractModel):
    type: Literal["sim_tick"]
    tick_id: NonNegInt
    sim_ts: UtcDatetime
    minutes: Annotated[int, Field(ge=1)]
    surges: list[Surge]
    inputs: SimInputs
    commands: list[Command]
    replay: bool
    fast_forward: bool


class SimControl(ContractModel):
    type: Literal["sim_control"]
    action: Literal["play", "pause", "reset"]
    speed: Annotated[int, Field(gt=0)]
    paused_reason: Optional[PausedReason]


ServerToHubUnion = Annotated[Union[HubWelcome, SimBuild, SimTick, SimControl], Field(discriminator="type")]


class ServerToHubMessage(RootModel[ServerToHubUnion]):
    """Any message the server sends on `/ws/hub`."""
