"""Section 2 of docs/CONTRACTS.md: WebSocket `/ws` (viewer socket, server -> client)."""
from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import Field, RootModel

from ._base import ContractModel, Pct, YearMonth
from .api import ClockState
from .shapes import (
    AgentLog,
    BacktestPoint,
    BacktestResult,
    CapUnreachableWarning,
    Context,
    Decision,
    Escalation,
    HubOfflineWarning,
    LaneComparison,
    LiveTransportDownWarning,
    Proposal,
    SimHostOfflineWarning,
    StoreDownWarning,
    TickState,
)


class TickMessage(ContractModel):
    type: Literal["tick"]
    data: TickState


class DecisionMessage(ContractModel):
    type: Literal["decision"]
    data: Decision
    explanation: str
    explanation_source: Literal["ai", "template"]


class ClockMessage(ClockState):
    type: Literal["clock"]


class CapUnreachableWarningMessage(CapUnreachableWarning):
    type: Literal["warning"]


class SimHostOfflineWarningMessage(SimHostOfflineWarning):
    type: Literal["warning"]


class HubOfflineWarningMessage(HubOfflineWarning):
    type: Literal["warning"]


class LiveTransportDownWarningMessage(LiveTransportDownWarning):
    type: Literal["warning"]


class StoreDownWarningMessage(StoreDownWarning):
    type: Literal["warning"]


WarningMessage = Annotated[
    Union[
        CapUnreachableWarningMessage,
        SimHostOfflineWarningMessage,
        HubOfflineWarningMessage,
        LiveTransportDownWarningMessage,
        StoreDownWarningMessage,
    ],
    Field(discriminator="code"),
]


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
    month: YearMonth
    pct: Pct


class BacktestPointMessage(ContractModel):
    type: Literal["backtest_point"]
    run_id: str
    data: BacktestPoint


class BacktestMonthMessage(ContractModel):
    type: Literal["backtest_month"]
    run_id: str
    data: BacktestResult


class ComparisonMessage(ContractModel):
    type: Literal["comparison"]
    data: LaneComparison


class ProposalMessage(ContractModel):
    type: Literal["proposal"]
    data: Proposal


class EscalationMessage(ContractModel):
    type: Literal["escalation"]
    data: Escalation
    explanation: str
    explanation_source: Literal["ai", "template"]


class ContextMessage(ContractModel):
    type: Literal["context"]
    data: Context


class AgentLogMessage(ContractModel):
    type: Literal["agent_log"]
    data: AgentLog


ViewerMessageUnion = Annotated[
    Union[
        TickMessage,
        DecisionMessage,
        ClockMessage,
        WarningMessage,
        ChatDeltaMessage,
        ChatDoneMessage,
        BacktestProgressMessage,
        BacktestPointMessage,
        BacktestMonthMessage,
        ComparisonMessage,
        ProposalMessage,
        EscalationMessage,
        ContextMessage,
        AgentLogMessage,
    ],
    Field(discriminator="type"),
]


class ViewerMessage(RootModel[ViewerMessageUnion]):
    """Any message on `/ws` (server -> viewer). `ViewerMessage.model_validate_json(frame).root`."""
