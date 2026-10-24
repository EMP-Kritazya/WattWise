"""In-memory Store (`STORE=memory`, and the fallback when Convex is down). Same interface as the Convex store.

Optionally seeded from `contracts/fixtures/convex/tables/*.json` (FAKE DATA: the Demo Café scenario's records).
"""

from __future__ import annotations

import copy
import json
import threading
from pathlib import Path

from .base import Store


class MemoryStore(Store):
    def __init__(self, seed_dir: Path | None = None):
        self._lock = threading.RLock()
        self._tables: dict[str, list[dict]] = {}
        if seed_dir is not None:
            for file in sorted(Path(seed_dir).glob("*.json")):
                self._tables[file.stem] = json.loads(file.read_text(encoding="utf-8"))

    def rows(self, table: str) -> list[dict]:
        """Every row of one table, as stored (for tests and debugging)."""
        with self._lock:
            return copy.deepcopy(self._tables.get(table, []))

    def _append(self, table: str, *rows: dict) -> None:
        with self._lock:
            self._tables.setdefault(table, []).extend(copy.deepcopy(list(rows)))

    def _upsert(self, table: str, key: str, row: dict) -> None:
        with self._lock:
            rows = self._tables.setdefault(table, [])
            for i, existing in enumerate(rows):
                if existing[key] == row[key]:
                    rows[i] = copy.deepcopy(row)
                    return
            rows.append(copy.deepcopy(row))

    # ------------------------------------------------------------ kitchens

    def record_kitchen(self, config: dict, created_at: str) -> None:
        self._append("kitchens", {"config": config, "created_at": created_at})

    def latest_kitchen(self) -> dict | None:
        kitchens = self.rows("kitchens")
        return kitchens[-1] if kitchens else None

    # ------------------------------------------------------------ decisions + commands

    def record_decisions(self, decisions: list[dict]) -> None:
        for decision in decisions:
            self._upsert("decisions", "decision_id", decision)

    def decisions(self, lane: str | None = None) -> list[dict]:
        return [d for d in self.rows("decisions") if lane is None or d["lane"] == lane]

    def record_command(self, command: dict, lane: str, hub_id: str | None) -> None:
        self._append("commands", {**command, "lane": lane, "hub_id": hub_id, "delivery": "queued"})

    def ack_command(self, command_id: str, ok: bool, applied_value: float | None, reason: str | None) -> None:
        with self._lock:
            for row in reversed(self._tables.get("commands", [])):  # ids restart per kitchen build: newest wins
                if row["command_id"] == command_id:
                    row["delivery"] = "acked" if ok else "failed"
                    return

    def commands_for_hub(self, hub_id: str) -> list[dict]:
        return [
            {k: v for k, v in c.items() if k not in ("hub_id", "delivery")}
            for c in self.rows("commands")
            if c["hub_id"] == hub_id and c["delivery"] in ("queued", "sent")
        ]

    # ------------------------------------------------------------ device bridge

    def report_reading(self, reading: dict) -> None:
        self._append("readings", reading)

    def latest_readings(self, hub_id: str) -> list[dict]:
        readings = self.rows("readings")
        latest = []
        for row in self.device_map():
            if row["hub_id"] != hub_id:
                continue
            mine = [r for r in readings if r["hub_id"] == hub_id and r["channel"] == row["channel"]]
            if mine:
                latest.append(mine[-1])
        return latest

    def device_map(self) -> list[dict]:
        return self.rows("device_map")

    def map_channel(self, row: dict) -> None:
        with self._lock:
            rows = self._tables.setdefault("device_map", [])
            rows[:] = [r for r in rows if (r["hub_id"], r["channel"]) != (row["hub_id"], row["channel"])]
            rows.append(copy.deepcopy(row))

    # ------------------------------------------------------------ proposals

    def upsert_proposal(self, proposal: dict) -> None:
        self._upsert("proposals", "proposal_id", proposal)

    def proposals(self, status: str | None = None) -> list[dict]:
        return [p for p in self.rows("proposals") if status is None or p["status"] == status]

    def proposal(self, proposal_id: str) -> dict | None:
        return next((p for p in self.rows("proposals") if p["proposal_id"] == proposal_id), None)

    # ------------------------------------------------------------ bills + backtests

    def save_bill(self, bill: dict, lane: str) -> None:
        self._append("bills", {**bill, "lane": lane})

    def bills(self) -> list[dict]:
        return self.rows("bills")

    def save_backtest(self, run_id: str, results: list[dict]) -> None:
        self._append("backtest_results", *({**r, "run_id": run_id} for r in results))

    def backtest(self, run_id: str) -> list[dict] | None:
        rows = [r for r in self.rows("backtest_results") if r["run_id"] == run_id]
        if not rows:
            return None
        return [{k: v for k, v in r.items() if k != "run_id"} for r in rows]

    def backtest_run_ids(self) -> list[str]:
        return list(dict.fromkeys(r["run_id"] for r in self.rows("backtest_results")))

    # ------------------------------------------------------------ blocks, escalations, context

    def record_device_blocks(self, blocks: list[dict]) -> None:
        self._append("device_blocks", *blocks)

    def record_escalation(self, escalation: dict) -> None:
        self._upsert("escalations", "escalation_id", escalation)

    def escalations(self) -> list[dict]:
        return self.rows("escalations")

    def record_context_snapshot(self, context: dict) -> None:
        self._append("context_snapshots", context)
