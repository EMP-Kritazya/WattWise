"""In-memory Store (`STORE=memory`, and the fallback when Convex is down). Same interface as the Convex store.

Optionally seeded from `contracts/fixtures/convex/tables/*.json` (FAKE DATA: the Demo Café scenario's records).

Liveness mirrors `convex/liveness.ts` (same constants, same rules, real time from `clock`): a hub's command still queued /
sent 15 s after it was enqueued is failed, a hub not seen for 30 s is offline in `hub_status`. Convex sweeps every 10 s;
here the sweep runs on every read of the commands, so a failure shows up at 15 s instead of 15–25 s.
"""

from __future__ import annotations

import copy
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .base import Store

COMMAND_TIMEOUT_S = 15.0  # convex/liveness.ts COMMAND_TIMEOUT_MS
HUB_OFFLINE_S = 30.0  # convex/liveness.ts HUB_OFFLINE_MS


def _epoch_s(ts: str) -> float:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()


class MemoryStore(Store):
    def __init__(self, seed_dir: Path | None = None, *, clock: Callable[[], float] = time.time):
        self._lock = threading.RLock()
        self._clock = clock  # real epoch seconds (Convex's `_creationTime` / Date.now())
        self._tables: dict[str, list[dict]] = {}
        if seed_dir is not None:
            for file in sorted(Path(seed_dir).glob("*.json")):
                self._tables[file.stem] = json.loads(file.read_text(encoding="utf-8"))
        now = self._clock()
        self._enqueued_at: dict[int, float] = {id(row): now for row in self._tables.get("commands", [])}  # `_creationTime`

    def rows(self, table: str) -> list[dict]:
        """Every row of one table, as stored (for tests and debugging)."""
        with self._lock:
            if table == "commands":
                self._sweep()
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
        row = copy.deepcopy({**command, "lane": lane, "hub_id": hub_id, "delivery": "queued"})
        with self._lock:
            self._tables.setdefault("commands", []).append(row)
            self._enqueued_at[id(row)] = self._clock()

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

    def failed_commands(self, hub_id: str, since_ms: float) -> list[dict]:
        with self._lock:
            self._sweep()
            return [
                {k: v for k, v in copy.deepcopy(c).items() if k not in ("hub_id", "delivery")}
                for c in self._tables.get("commands", [])
                if c["hub_id"] == hub_id and c["delivery"] == "failed"
                and self._enqueued_at.get(id(c), 0.0) * 1000 >= since_ms
            ]

    def _sweep(self) -> None:
        """`liveness:sweep`: a hub's command still queued / sent `COMMAND_TIMEOUT_S` after enqueue → failed."""
        cutoff = self._clock() - COMMAND_TIMEOUT_S
        for row in self._tables.get("commands", []):
            if (row["hub_id"] is not None and row["delivery"] in ("queued", "sent")
                    and self._enqueued_at.get(id(row), cutoff) < cutoff):
                row["delivery"] = "failed"

    # ------------------------------------------------------------ hubs (liveness)

    def heartbeat(self, hub_id: str) -> None:
        """`hubs:heartbeat` (the ESP32 calls it; here for fakes and tests)."""
        last_seen = datetime.fromtimestamp(self._clock(), timezone.utc).isoformat(timespec="milliseconds")
        last_seen = last_seen.replace("+00:00", "Z")
        with self._lock:
            hubs = self._tables.setdefault("hubs", [])
            hub = next((h for h in hubs if h["hub_id"] == hub_id), None)
            if hub is None:
                hubs.append({"hub_id": hub_id, "last_seen": last_seen, "firmware": None})
            else:
                hub["last_seen"] = last_seen

    def hub_status(self) -> list[dict]:
        now = self._clock()
        return [
            {**h, "status": "offline" if now - _epoch_s(h["last_seen"]) > HUB_OFFLINE_S else "online"}
            for h in self.rows("hubs")
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
