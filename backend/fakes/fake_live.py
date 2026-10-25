"""FakeLive: the SpacetimeDB live publisher with no network (owner: Kritazya).

`FakeLive()` is a real `SpacetimeClient` over `InMemoryTransport`, which applies every reducer call to in-memory tables
with the module's semantics (upserts by key, bounds, runtime-only writes) and answers the one SQL query the client makes.
Surge requests come from `contracts/fixtures/spacetime/tables/surge_request.json` (`seed_fixture_surges()`, re-armed as
unconsumed) or from `request_surge()` (a viewer pressing the button). FIXTURE DATA: not measured, not live.
"""
from __future__ import annotations

import copy
import json
import threading
from pathlib import Path
from typing import Any, Optional

from live.spacetime_client import SpacetimeClient

FIXTURES = Path(__file__).resolve().parents[2] / "contracts" / "fixtures" / "spacetime"

TICK_HISTORY_SIM_MIN = 180
BOUNDS = {"live_feed": 50, "live_escalation": 20, "live_agent_log": 300}


def _id_number(value: str) -> int:
    tail = value.rsplit("_", 1)[-1]
    return int(tail) if tail.isdigit() else 0


def _opt(value: Any) -> Any:
    if isinstance(value, dict) and len(value) == 1 and next(iter(value)) in ("some", "none"):
        return value.get("some")
    return value


class InMemoryTransport:
    """In-memory SpacetimeDB: `call(reducer, args)` writes the tables, `sql(query)` reads unconsumed surges."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.calls: list[tuple[str, list]] = []  # every reducer call, wire args, in order
        self.tables: dict[str, dict] = {name: {} for name in (
            "live_tick", "tick_history", "live_device", "live_comparison", "live_feed", "live_clock", "live_context",
            "live_escalation", "live_agent_log", "backtest_point", "backtest_month", "surge_request")}
        self._next_id = {"live_agent_log": 1, "surge_request": 1}
        self.fail_next = 0  # tests: make the next N calls raise

    # reads ------------------------------------------------------------------------------------------------------------
    def rows(self, table: str) -> list[dict]:
        with self.lock:
            return [copy.deepcopy(r) for _, r in sorted(self.tables[table].items(), key=lambda kv: str(kv[0]))]

    def sql(self, query: str) -> list[dict]:
        if "surge_request" not in query:
            raise ValueError(f"InMemoryTransport answers only the surge query, got {query!r}")
        with self.lock:
            return [copy.deepcopy(r) for _, r in sorted(self.tables["surge_request"].items()) if not r["consumed"]]

    # viewer -----------------------------------------------------------------------------------------------------------
    def request_surge(self, customers: int, duration_min: int, requested_by: str = "viewer",
                      created_at: str = "2026-01-01T00:00:00.000Z") -> int:
        if not (1 <= customers <= 80) or not (15 <= duration_min <= 120):
            raise ValueError("request_surge: customers 1-80, duration_min 15-120")
        with self.lock:
            sid = self._next_id["surge_request"]
            self._next_id["surge_request"] += 1
            self.tables["surge_request"][sid] = {"id": sid, "customers": customers, "duration_min": duration_min,
                                                 "requested_by": requested_by, "created_at": created_at,
                                                 "consumed": False}
            return sid

    # reducers ---------------------------------------------------------------------------------------------------------
    def call(self, reducer: str, args: list) -> None:
        with self.lock:
            if self.fail_next > 0:
                self.fail_next -= 1
                raise ConnectionError("fake transport down")
            self.calls.append((reducer, copy.deepcopy(args)))
            getattr(self, f"_r_{reducer}")(*args)

    def _upsert(self, table: str, key: Any, row: dict) -> None:
        self.tables[table][key] = row

    def _bound(self, table: str) -> None:
        rows = self.tables[table]
        limit = BOUNDS[table]
        if len(rows) > limit:
            order = sorted(rows, key=lambda k: k if isinstance(k, int) else _id_number(k))
            for k in order[: len(rows) - limit]:
                del rows[k]

    def _r_publish_ticks(self, payload_json: str) -> None:
        from datetime import datetime, timedelta

        p = json.loads(payload_json)
        for r in p["live_tick"]:
            self._upsert("live_tick", r["lane"], r)
        for r in p["tick_history"]:
            self._upsert("tick_history", f"{r['lane']}:{r['ts']}", r)
            parse = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))  # noqa: E731
            lane_rows = {k: v for k, v in self.tables["tick_history"].items() if v["lane"] == r["lane"]}
            latest = max(parse(v["ts"]) for v in lane_rows.values())
            for k, v in lane_rows.items():
                if parse(v["ts"]) <= latest - timedelta(minutes=TICK_HISTORY_SIM_MIN):
                    del self.tables["tick_history"][k]
        for r in p["live_device"]:
            self._upsert("live_device", r["key"], r)
        self._upsert("live_comparison", 0, p["live_comparison"])

    def _r_publish_feed(self, decision_json: str) -> None:
        r = json.loads(decision_json)
        self._upsert("live_feed", r["decision_id"], r)
        self._bound("live_feed")

    def _r_set_clock(self, playing, speed, sim_ts, tick_id, paused_reason, day_index, run_days, phase, sim_host) -> None:
        self._upsert("live_clock", 0, {"id": 0, "playing": playing, "speed": speed, "sim_ts": sim_ts, "tick_id": tick_id,
                                        "paused_reason": _opt(paused_reason), "day_index": day_index,
                                        "run_days": run_days, "phase": phase, "sim_host": sim_host})

    def _r_publish_context(self, context_json: str) -> None:
        self._upsert("live_context", 0, json.loads(context_json))

    def _r_publish_escalation(self, escalation_json: str) -> None:
        r = json.loads(escalation_json)
        self._upsert("live_escalation", r["escalation_id"], r)
        self._bound("live_escalation")

    def _r_log_agent(self, agent_log_json: str) -> None:
        aid = self._next_id["live_agent_log"]
        self._next_id["live_agent_log"] += 1
        self._upsert("live_agent_log", aid, {"id": aid, **json.loads(agent_log_json)})
        self._bound("live_agent_log")

    def _keep_run(self, run_id: str) -> None:
        for table in ("backtest_point", "backtest_month"):
            for k in [k for k, v in self.tables[table].items() if v["run_id"] != run_id]:
                del self.tables[table][k]

    def _r_publish_backtest_point(self, point_json: str) -> None:
        r = json.loads(point_json)
        self._keep_run(r["run_id"])
        self._upsert("backtest_point", r["key"], r)

    def _r_publish_backtest_month(self, month_json: str) -> None:
        r = json.loads(month_json)
        self._keep_run(r["run_id"])
        self._upsert("backtest_month", r["key"], r)

    def _r_reset_backtest(self, run_id: str) -> None:
        self.tables["backtest_point"].clear()
        self.tables["backtest_month"].clear()

    def _r_reset_all(self) -> None:
        for table in ("live_tick", "tick_history", "live_device", "live_comparison", "live_feed", "live_clock",
                      "live_context", "live_escalation", "live_agent_log"):
            self.tables[table].clear()

    def _r_consume_surge(self, sid: int) -> None:
        row = self.tables["surge_request"].get(sid)
        if row is None:
            raise KeyError(f"consume_surge: no surge_request {sid}")
        row["consumed"] = True


class FakeLive(SpacetimeClient):
    """Drop-in for `SpacetimeClient` with no network. `transport` holds the in-memory tables and the call log."""

    def __init__(self, transport: Optional[InMemoryTransport] = None, **kwargs: Any) -> None:
        kwargs.setdefault("surge_poll_s", 0.05)
        kwargs.setdefault("retry_backoff_s", 0.01)
        super().__init__(transport or InMemoryTransport(), **kwargs)

    def seed_fixture_surges(self) -> list[int]:
        """Queue the fixture surge requests as new (unconsumed) viewer requests; returns their ids."""
        rows = json.loads((FIXTURES / "tables" / "surge_request.json").read_text())
        return [self.transport.request_surge(r["customers"], r["duration_min"], r["requested_by"], r["created_at"])
                for r in rows]

    def request_surge(self, customers: int, duration_min: int) -> int:
        return self.transport.request_surge(customers, duration_min)
