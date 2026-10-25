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

    @abstractmethod
    def ack_command(self, command_id: str, ok: bool, applied_value: float | None, reason: str | None) -> None:
        """`commands:ack` (CommandAck meaning): delivery → acked (ok) or failed. Unknown ids are ignored."""

    @abstractmethod
    def commands_for_hub(self, hub_id: str) -> list[dict]:
        """`commands:forDevice`: the hub's queued / sent Commands, oldest first, as Command shapes."""

    @abstractmethod
    def failed_commands(self, hub_id: str, since_ms: float) -> list[dict]:
        """`commands:failed`: the hub's failed Commands (nacked, or still queued / sent 15 s after enqueue) enqueued at
        or after `since_ms` (real epoch ms), oldest first, one per failed row."""

    # ------------------------------------------------------------ hubs (liveness)
    @abstractmethod
    def hub_status(self) -> list[dict]:
        """`hubs:status`: {hub_id, last_seen, firmware, status: online | offline (last_seen older than 30 s)}."""

    # ------------------------------------------------------------ device bridge (readings, device map)
    @abstractmethod
    def report_reading(self, reading: dict) -> None:
        """`devices:report`."""

    @abstractmethod
    def latest_readings(self, hub_id: str) -> list[dict]:
        """`devices:latest`: the newest Reading of every mapped channel of one hub."""

    @abstractmethod
    def device_map(self) -> list[dict]:
        """`devices:map`: {hub_id, channel, device_id, scale} rows."""

    @abstractmethod
    def map_channel(self, row: dict) -> None:
        """`devices:mapChannel`: set up once per demo kitchen; replaces the row of the same hub_id + channel."""

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
