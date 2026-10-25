"""SpacetimeDB live publisher (CONTRACTS.md section 5, docs/design/SPACETIMEDB.md). Owner: Kritazya. Used by the runtime.

Calls reducers over HTTP (`POST {uri}/v1/database/{db}/call/{reducer}`, body = JSON array of the arguments, bearer token of
the runtime identity) and reads new surge requests through the SQL endpoint (`POST {uri}/v1/database/{db}/sql`).

Never blocks the run loop: every public method only enqueues and returns at once; one background worker thread sends.
- `publish` (ticks), `set_clock` and `publish_context` are *state*: at most one pending call each; a newer one replaces the
  pending one in place (latest tick wins, older ticks are dropped and counted).
- feed, escalations, agent log, backtest rows, resets and surge consumption are *events*: never dropped; on a transport error
  they are retried in order (the backlog is reported in `stats()` so the runtime can raise `live_transport_down`).
- `consume_surges()` returns the surge requests the worker has read since the last call (each id once) and queues their
  `consume_surge(id)`; it never waits for the network.

Payloads are built by `live.rows` and equal `contracts/fixtures/spacetime/reducers/*.json`; optionally validated against the
`backend/contracts` row models before they are queued.
"""
from __future__ import annotations

import collections
import json
import logging
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional, Protocol

from contracts import (
    BacktestMonthRow,
    BacktestPointRow,
    LiveAgentLogRow,
    LiveClockRow,
    LiveContextRow,
    LiveEscalationRow,
    LiveFeedRow,
    PublishTicksPayload,
    SurgeRequestRow,
)

from . import rows as R

log = logging.getLogger("wattwise.live")

STATE_KINDS = ("ticks", "clock", "context")
OPTION_ENCODINGS = ("sats", "null")


# ---------------------------------------------------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------------------------------------------------


class Transport(Protocol):
    def call(self, reducer: str, args: list) -> None: ...

    def sql(self, query: str) -> list[dict]: ...


class TransportError(RuntimeError):
    pass


def encode_option(value: Any, encoding: str) -> Any:
    """SATS-JSON Option on the wire: `{"some": v}` / `{"none": []}` (encoding "sats"), or plain value / null ("null")."""
    if encoding == "null":
        return value
    return {"none": []} if value is None else {"some": value}


def decode_value(value: Any) -> Any:
    """SQL result value -> plain: Option sums `{"some": v}` / `{"none": ...}` or `[0, v]` / `[1, []]` -> v / None."""
    if isinstance(value, dict) and len(value) == 1:
        (k, v), = value.items()
        if k == "some":
            return decode_value(v)
        if k == "none":
            return None
    return value


class HttpTransport:
    """Stdlib HTTP transport (no extra dependency). Timeouts keep a dead server from stalling the worker for long."""

    def __init__(self, uri: str, database: str, token: Optional[str], *, timeout_s: float = 2.0) -> None:
        self.base = f"{uri.rstrip('/')}/v1/database/{database}"
        self.token = token
        self.timeout_s = timeout_s

    def _post(self, path: str, body: bytes, content_type: str) -> bytes:
        req = urllib.request.Request(f"{self.base}{path}", data=body, method="POST")
        req.add_header("Content-Type", content_type)
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as res:
                return res.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            raise TransportError(f"{path}: HTTP {exc.code} {detail}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise TransportError(f"{path}: {exc}") from exc

    def call(self, reducer: str, args: list) -> None:
        self._post(f"/call/{reducer}", json.dumps(args, ensure_ascii=False, separators=(",", ":")).encode(), "application/json")

    def sql(self, query: str) -> list[dict]:
        raw = self._post("/sql", query.encode(), "text/plain")
        out: list[dict] = []
        for stmt in json.loads(raw or b"[]"):
            names = [_column_name(el, i) for i, el in enumerate(stmt.get("schema", {}).get("elements", []))]
            for row in stmt.get("rows", []):
                out.append({n: decode_value(v) for n, v in zip(names, row)})
        return out


def _column_name(element: Mapping, i: int) -> str:
    name = element.get("name")
    if isinstance(name, dict):  # SATS Option<String>: {"some": "col"}
        name = name.get("some")
    return name if isinstance(name, str) else f"col{i}"


# ---------------------------------------------------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------------------------------------------------


@dataclass
class _Item:
    reducer: str
    args: list
    kind: Optional[str] = None  # a STATE_KINDS entry for coalesced state, None for events
    attempts: int = 0


@dataclass
class LiveStats:
    sent: int = 0
    dropped_ticks: int = 0
    errors: int = 0
    backlog: int = 0
    last_error: Optional[str] = None
    healthy: bool = True
    by_reducer: dict = field(default_factory=dict)


class SpacetimeClient:
    """The runtime's live publisher. `start()` launches the worker; every call returns immediately."""

    def __init__(self, transport: Transport, *, validate: bool = True, option_encoding: str = "sats",
                 surge_poll_s: float = 0.5, retry_backoff_s: float = 0.5, autostart: bool = True,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        if option_encoding not in OPTION_ENCODINGS:
            raise ValueError(f"option_encoding must be one of {OPTION_ENCODINGS}")
        self.transport = transport
        self.validate = validate
        self.option_encoding = option_encoding
        self.surge_poll_s = surge_poll_s
        self.retry_backoff_s = retry_backoff_s
        self._sleep = sleep
        self._queue: collections.deque[_Item] = collections.deque()
        self._pending_state: dict[str, _Item] = {}
        self._cv = threading.Condition()
        self._stats = LiveStats()
        self._forecasts: dict[str, tuple[Optional[list], Optional[str]]] = {lane: (None, None) for lane in R.LANES}
        self._surges_new: list[dict] = []
        self._surges_seen: set[int] = set()
        self._last_poll = 0.0
        self._stop = False
        self._inflight = False
        self._thread: Optional[threading.Thread] = None
        if autostart:
            self.start()

    @classmethod
    def from_env(cls, env: Mapping[str, str], **kwargs: Any) -> "SpacetimeClient":
        """SPACETIME_URI, SPACETIME_DB, SPACETIME_TOKEN (runtime identity), SPACETIME_OPTION_ENCODING (sats | null)."""
        transport = HttpTransport(env.get("SPACETIME_URI", "http://localhost:3000"), env.get("SPACETIME_DB", "wattwise"),
                                  env.get("SPACETIME_TOKEN"))
        return cls(transport, option_encoding=env.get("SPACETIME_OPTION_ENCODING", "sats"), **kwargs)

    # lifecycle --------------------------------------------------------------------------------------------------------
    def start(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._stop = False
            self._thread = threading.Thread(target=self._run, name="spacetime-live", daemon=True)
            self._thread.start()

    def close(self, timeout_s: float = 2.0) -> None:
        self.flush(timeout_s)
        with self._cv:
            self._stop = True
            self._cv.notify_all()
        if self._thread is not None:
            self._thread.join(timeout_s)

    def flush(self, timeout_s: float = 2.0) -> bool:
        """Wait until the queue is empty (tests / shutdown only; the run loop never calls this)."""
        deadline = time.monotonic() + timeout_s
        with self._cv:
            while self._queue or self._inflight:
                left = deadline - time.monotonic()
                if left <= 0:
                    return False
                self._cv.wait(left)
        return True

    def stats(self) -> LiveStats:
        with self._cv:
            s = LiveStats(**{**self._stats.__dict__, "by_reducer": dict(self._stats.by_reducer)})
            s.backlog = len(self._queue)
            return s

    # public API (all non-blocking) ------------------------------------------------------------------------------------
    def publish(self, states: Mapping[str, Mapping], comparison: Mapping) -> dict:
        """One tick pair: both lanes' TickStates (`{"without": ..., "with": ...}`) and the engine's LaneComparison.
        Keeps each lane's latest forecast for `live_tick.forecast_kw_json`. Returns the payload object queued."""
        for lane in R.LANES:
            st = R._plain(states[lane])
            if st.get("forecast_kw") is not None:
                self._forecasts[lane] = (st["forecast_kw"], st["ts"])
        payload = R.publish_ticks_payload(states, comparison, self._forecasts)
        self.publish_ticks(payload)
        return payload

    def publish_ticks(self, payload: Mapping) -> None:
        if self.validate:
            PublishTicksPayload.model_validate(payload)
        self._put_state("ticks", "publish_ticks", [R.cj(payload)])

    def publish_feed(self, decision: Mapping, lane: str, explanation: str, explanation_source: str = "template") -> dict:
        row = R.feed_row(decision, lane, explanation, explanation_source)
        if self.validate:
            LiveFeedRow.model_validate(row)
        self._put_event("publish_feed", [R.cj(row)])
        return row

    def set_clock(self, clock: Mapping, sim_host: str = "connected") -> list:
        args = R.set_clock_args(clock, sim_host)
        if self.validate:
            LiveClockRow.model_validate({"id": 0, **dict(zip(R.SET_CLOCK_ARGS, args))})
        self._put_state("clock", "set_clock", args)
        return args

    def publish_context(self, context: Mapping) -> dict:
        row = R.context_row(context)
        if self.validate:
            LiveContextRow.model_validate(row)
        self._put_state("context", "publish_context", [R.cj(row)])
        return row

    def publish_escalation(self, escalation: Mapping) -> dict:
        row = R.escalation_row(escalation)
        if self.validate:
            LiveEscalationRow.model_validate(row)
        self._put_event("publish_escalation", [R.cj(row)])
        return row

    def log_agent(self, agent_log: Mapping) -> dict:
        row = R.agent_log_row(agent_log)
        if self.validate:
            LiveAgentLogRow.model_validate({"id": 0, **row})
        self._put_event("log_agent", [R.cj(row)])
        return row

    def publish_backtest_point(self, run_id: str, point: Mapping) -> dict:
        row = R.backtest_point_row(run_id, point)
        if self.validate:
            BacktestPointRow.model_validate(row)
        self._put_event("publish_backtest_point", [R.cj(row)])
        return row

    def publish_backtest_month(self, run_id: str, result: Mapping) -> dict:
        row = R.backtest_month_row(run_id, result)
        if self.validate:
            BacktestMonthRow.model_validate(row)
        self._put_event("publish_backtest_month", [R.cj(row)])
        return row

    def reset_backtest(self, run_id: str) -> None:
        self._put_event("reset_backtest", [run_id])

    def reset_all(self) -> None:
        """New kitchen: drop any pending state, clear the live tables, forget the lanes' forecasts."""
        with self._cv:
            for kind in list(self._pending_state):
                item = self._pending_state.pop(kind)
                try:
                    self._queue.remove(item)
                except ValueError:
                    pass
            self._forecasts = {lane: (None, None) for lane in R.LANES}
        self._put_event("reset_all", [])

    def consume_surges(self) -> list[dict]:
        """Surge requests read since the last call (unconsumed, each id once), oldest first; queues `consume_surge(id)`."""
        with self._cv:
            new, self._surges_new = self._surges_new, []
            self._cv.notify_all()
        for s in new:
            self._put_event("consume_surge", [s["id"]])
        return new

    def read_surges(self) -> list[dict]:
        """Synchronous SQL read of unconsumed surge requests (diagnostics only: blocks on the network)."""
        rows = self.transport.sql("SELECT * FROM surge_request WHERE consumed = false")
        return sorted((SurgeRequestRow.model_validate(r).model_dump(mode="json") for r in rows), key=lambda r: r["id"])

    # queue ------------------------------------------------------------------------------------------------------------
    def _put_state(self, kind: str, reducer: str, args: list) -> None:
        with self._cv:
            pending = self._pending_state.get(kind)
            if pending is not None:
                pending.args = args  # latest wins, keeps its place in the order
                if kind == "ticks":
                    self._stats.dropped_ticks += 1
            else:
                item = _Item(reducer, args, kind)
                self._pending_state[kind] = item
                self._queue.append(item)
            self._cv.notify_all()

    def _put_event(self, reducer: str, args: list) -> None:
        with self._cv:
            self._queue.append(_Item(reducer, args))
            self._cv.notify_all()

    def _wire_args(self, item: _Item) -> list:
        if item.reducer == "set_clock":
            args = list(item.args)
            args[4] = encode_option(args[4], self.option_encoding)  # paused_reason: Option<String>
            return args
        return item.args

    # worker -----------------------------------------------------------------------------------------------------------
    def _run(self) -> None:
        while True:
            with self._cv:
                while not self._queue and not self._stop and not self._poll_due():
                    self._cv.wait(self._poll_wait())
                if self._stop and not self._queue:
                    return
                item = self._queue[0] if self._queue else None
                if item is not None:
                    if item.kind is not None:
                        self._pending_state.pop(item.kind, None)  # from here a newer state queues a new call
                    self._inflight = True
            if item is not None:
                self._send(item)
            if self._poll_due():
                self._poll_surges()

    def _send(self, item: _Item) -> None:
        try:
            self.transport.call(item.reducer, self._wire_args(item))
        except Exception as exc:  # noqa: BLE001 - the loop must survive any transport failure
            with self._cv:
                self._stats.errors += 1
                self._stats.last_error = f"{item.reducer}: {exc}"
                self._stats.healthy = False
                item.attempts += 1
                if item.kind is not None and item.kind in self._pending_state:
                    self._queue.popleft()  # a newer state is already queued: drop this one
                    if item.kind == "ticks":
                        self._stats.dropped_ticks += 1
                elif item.kind is not None:
                    self._pending_state[item.kind] = item  # retry the state unless replaced meanwhile
                self._inflight = False
                self._cv.notify_all()
            log.warning("spacetime %s failed (attempt %d): %s", item.reducer, item.attempts, exc)
            self._sleep(min(self.retry_backoff_s * item.attempts, 5.0))
            return
        with self._cv:
            if self._queue and self._queue[0] is item:
                self._queue.popleft()
            self._stats.sent += 1
            self._stats.healthy = True
            self._stats.by_reducer[item.reducer] = self._stats.by_reducer.get(item.reducer, 0) + 1
            self._inflight = False
            self._cv.notify_all()

    def _poll_due(self) -> bool:
        return self.surge_poll_s > 0 and time.monotonic() - self._last_poll >= self.surge_poll_s

    def _poll_wait(self) -> float:
        if self.surge_poll_s <= 0:
            return 1.0
        return max(0.01, self.surge_poll_s - (time.monotonic() - self._last_poll))

    def _poll_surges(self) -> None:
        self._last_poll = time.monotonic()
        try:
            rows = self.transport.sql("SELECT * FROM surge_request WHERE consumed = false")
        except Exception as exc:  # noqa: BLE001
            with self._cv:
                self._stats.errors += 1
                self._stats.last_error = f"sql surge_request: {exc}"
            return
        fresh = []
        for r in rows:
            try:
                row = SurgeRequestRow.model_validate(r).model_dump(mode="json")
            except Exception as exc:  # noqa: BLE001 - a malformed row is logged, never crashes the loop
                log.warning("surge_request row rejected: %s", exc)
                continue
            if row["id"] not in self._surges_seen:
                fresh.append(row)
        with self._cv:
            for row in sorted(fresh, key=lambda r: r["id"]):
                self._surges_seen.add(row["id"])
                self._surges_new.append(row)
