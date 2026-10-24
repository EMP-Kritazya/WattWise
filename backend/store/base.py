"""Store interface: durable records (Convex tables, CONTRACTS.md §6). Live state goes to SpacetimeDB, never here.

Rows are the Convex documents exactly (no `_id` / `_creationTime`). Every read returns copies.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class Store(ABC):
    # ------------------------------------------------------------ kitchens
    @abstractmethod
    def record_kitchen(self, config: dict, created_at: str) -> None: ...

    @abstractmethod
    def latest_kitchen(self) -> dict | None:
        """The last `kitchens` row ({config, created_at}), or None."""

    # ------------------------------------------------------------ decisions + commands
    @abstractmethod
    def record_decisions(self, decisions: list[dict]) -> None:
        """`decisions:record`: Decision + lane, explanation, explanation_source. Upsert by decision_id."""

    @abstractmethod
    def decisions(self, lane: str | None = None) -> list[dict]:
        """Recorded decisions in insertion order, optionally for one lane."""

    @abstractmethod
    def record_command(self, command: dict, lane: str, hub_id: str | None) -> None:
        """`commands:enqueue`: stored with `delivery: "queued"`."""

    # ------------------------------------------------------------ proposals
    @abstractmethod
    def upsert_proposal(self, proposal: dict) -> None:
        """`proposals:upsert`, by proposal_id."""

    @abstractmethod
    def proposals(self, status: str | None = None) -> list[dict]: ...

    @abstractmethod
    def proposal(self, proposal_id: str) -> dict | None: ...

    # ------------------------------------------------------------ bills + backtests
    @abstractmethod
    def save_bill(self, bill: dict, lane: str) -> None:
        """`bills:save`."""

    @abstractmethod
    def bills(self) -> list[dict]:
        """Saved engine Bills, each with its `lane`."""

    @abstractmethod
    def save_backtest(self, run_id: str, results: list[dict]) -> None:
        """`backtest:save`: one row per BacktestResult + run_id."""

    @abstractmethod
    def backtest(self, run_id: str) -> list[dict] | None:
        """The BacktestResults of one run (without run_id), or None for an unknown run."""

    @abstractmethod
    def backtest_run_ids(self) -> list[str]: ...

    # ------------------------------------------------------------ blocks, escalations, context
    @abstractmethod
    def record_device_blocks(self, blocks: list[dict]) -> None:
        """Closed 15-min blocks: {lane, device_id, block_start, avg_kw, source}."""

    @abstractmethod
    def record_escalation(self, escalation: dict) -> None:
        """Final state of an Escalation. Upsert by escalation_id."""

    @abstractmethod
    def escalations(self) -> list[dict]: ...

    @abstractmethod
    def record_context_snapshot(self, context: dict) -> None:
        """Context + ts (hourly, from the runtime)."""
