"""The runtime's door to live state (CONTRACTS.md §5 reducers, or the §2 `/ws` messages when `LIVE_TRANSPORT=ws`).

`LivePort` has one method per runtime reducer, plus `read_surges()`. Methods take the contract shapes (TickState,
LaneComparison, Decision, Escalation, Context, AgentLog, ClockState) so every transport can say them its own way:
- `RecordingLive`: records each call as `{reducer, args}`, args exactly as the HTTP reducer call sends them (tests;
  compared with `contracts/fixtures/spacetime/reducers/` and `rows_stream.jsonl`). Optionally forwards to another port.
- `WsLive`: the same calls as `/ws` messages to every viewer (offline fallback; also the dev default for now).
- `SpacetimeLive` adapts the canonical `backend/live/spacetime_client.py` without blocking ticks.
`LiveRows` delegates to the canonical shape → §5 row projections used by the SpacetimeDB client.

`LivePublisher` is what the run loop holds: calls are queued and sent by one background task, in order, so the loop never
waits on a transport. A failing port is dropped for the fallback (`/ws`) with a `live_transport_down` warning.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable, Protocol

log = logging.getLogger("runtime.live_port")

LANES = ("without", "with")
# ClockState in the order of the `set_clock` reducer args (CONTRACTS.md §5); `sim_host` follows them.
CLOCK_FIELDS = ("playing", "speed", "sim_ts", "tick_id", "paused_reason", "day_index", "run_days", "phase")

Broadcast = Callable[[dict], Awaitable[None]]


def compact_json(obj: Any) -> str | None:
    """The JSON-string form of every `*_json` column and reducer payload."""
    return None if obj is None else json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


class LivePort(Protocol):
    async def publish_ticks(self, tick_id: int, states: dict[str, dict], comparison: dict) -> None:
        """Both lanes' TickStates of one tick + their LaneComparison."""

    async def publish_feed(self, lane: str, decision: dict, explanation: str, explanation_source: str) -> None: ...

    async def publish_escalation(self, escalation: dict) -> None: ...

    async def publish_context(self, context: dict) -> None: ...

    async def log_agent(self, entry: dict) -> None: ...

    async def set_clock(self, clock: dict, sim_host: str) -> None:
        """`clock` = ClockState; `sim_host` connected | offline."""

    async def reset_all(self) -> None: ...

    async def consume_surge(self, request_id: int) -> None: ...

    async def read_surges(self) -> list[dict]:
        """Unconsumed `surge_request` rows."""


# ---------------------------------------------------------------- §5 rows


class LiveRows:
    """Use the canonical live projections for every runtime transport."""
    def __init__(self):
        self._forecast = {}

    def reset(self):
        self._forecast.clear()

    def ticks_payload(self, tick_id, states, comparison):
        from live.rows import publish_ticks_payload
        for lane in LANES:
            if states[lane].get("forecast_kw") is not None:
                self._forecast[lane] = (states[lane]["forecast_kw"], states[lane]["ts"])
        return publish_ticks_payload(states, comparison, self._forecast)

    @staticmethod
    def feed(lane, decision, explanation, explanation_source):
        from live.rows import feed_row
        return feed_row(decision, lane, explanation, explanation_source)

    @staticmethod
    def escalation(escalation):
        from live.rows import escalation_row
        return escalation_row(escalation)

    @staticmethod
    def context(context):
        from live.rows import context_row
        return context_row(context)


# ---------------------------------------------------------------- ports


class RecordingLive:
    """Records every reducer call as `{reducer, args}` (the HTTP JSON args array). For tests; `inner` also receives it."""

    def __init__(self, inner: LivePort | None = None) -> None:
        self.calls: list[dict] = []
        self.surge_requests: list[dict] = []  # what `read_surges` sees; tests insert rows (the `request_surge` reducer)
        self._rows = LiveRows()
        self._inner = inner

    def calls_to(self, reducer: str) -> list[list]:
        return [c["args"] for c in self.calls if c["reducer"] == reducer]

    def _record(self, reducer: str, *args: Any) -> None:
        self.calls.append({"reducer": reducer, "args": list(args)})

    async def _forward(self, method: str, *args: Any) -> Any:
        return await getattr(self._inner, method)(*args) if self._inner is not None else None

    async def publish_ticks(self, tick_id: int, states: dict[str, dict], comparison: dict) -> None:
        self._record("publish_ticks", compact_json(self._rows.ticks_payload(tick_id, states, comparison)))
        await self._forward("publish_ticks", tick_id, states, comparison)

    async def publish_feed(self, lane: str, decision: dict, explanation: str, explanation_source: str) -> None:
        self._record("publish_feed", compact_json(self._rows.feed(lane, decision, explanation, explanation_source)))
        await self._forward("publish_feed", lane, decision, explanation, explanation_source)

    async def publish_escalation(self, escalation: dict) -> None:
        self._record("publish_escalation", compact_json(self._rows.escalation(escalation)))
        await self._forward("publish_escalation", escalation)

    async def publish_context(self, context: dict) -> None:
        self._record("publish_context", compact_json(self._rows.context(context)))
        await self._forward("publish_context", context)

    async def log_agent(self, entry: dict) -> None:
        self._record("log_agent", compact_json(entry))
        await self._forward("log_agent", entry)

    async def set_clock(self, clock: dict, sim_host: str) -> None:
        self._record("set_clock", *(clock[k] for k in CLOCK_FIELDS), sim_host)
        await self._forward("set_clock", clock, sim_host)

    async def reset_all(self) -> None:
        self._rows.reset()
        self._record("reset_all")
        await self._forward("reset_all")

    async def consume_surge(self, request_id: int) -> None:
        self._record("consume_surge", request_id)
        for row in self.surge_requests:
            if row["id"] == request_id:
                row["consumed"] = True
        await self._forward("consume_surge", request_id)

    async def read_surges(self) -> list[dict]:
        return [dict(r) for r in self.surge_requests if not r.get("consumed")]


class WsLive:
    """`LIVE_TRANSPORT=ws`: every live update as a §2 `/ws` message. No surge requests exist without SpacetimeDB."""

    def __init__(self, broadcast: Broadcast) -> None:
        self._broadcast = broadcast
        self._last_clock: dict | None = None

    async def publish_ticks(self, tick_id: int, states: dict[str, dict], comparison: dict) -> None:
        for lane in LANES:
            await self._broadcast({"type": "tick", "data": states[lane]})
        await self._broadcast({"type": "comparison", "data": comparison})

    async def publish_feed(self, lane: str, decision: dict, explanation: str, explanation_source: str) -> None:
        await self._broadcast(
            {"type": "decision", "data": decision, "explanation": explanation, "explanation_source": explanation_source}
        )

    async def publish_escalation(self, escalation: dict) -> None:
        row = LiveRows.escalation(escalation)
        await self._broadcast({"type": "escalation", "data": escalation,
                               "explanation": row["explanation"], "explanation_source": row["explanation_source"]})

    async def publish_context(self, context: dict) -> None:
        await self._broadcast({"type": "context", "data": context})

    async def log_agent(self, entry: dict) -> None:
        await self._broadcast({"type": "agent_log", "data": entry})

    async def set_clock(self, clock: dict, sim_host: str) -> None:
        # Viewers get `clock` only when the clock state changes; every tick message already carries the sim time.
        state = {k: v for k, v in clock.items() if k not in ("sim_ts", "tick_id")}
        if state == self._last_clock:
            return
        self._last_clock = state
        await self._broadcast({"type": "clock", **{k: clock[k] for k in CLOCK_FIELDS}})

    async def reset_all(self) -> None:
        self._last_clock = None

    async def consume_surge(self, request_id: int) -> None:
        return None

    async def read_surges(self) -> list[dict]:
        return []


class SpacetimeLive:
    """Async runtime port over the existing nonblocking SpacetimeDB client."""
    def __init__(self, client):
        self.client = client

    def start(self):
        self.client.start()

    async def close(self):
        await asyncio.to_thread(self.client.close)

    def _check(self):
        if not self.client.stats().healthy:
            raise ConnectionError("SpacetimeDB publishing failed")

    async def publish_ticks(self, tick_id, states, comparison):
        self._check()
        self.client.publish(states, comparison)

    async def publish_feed(self, lane, decision, explanation, explanation_source):
        self._check()
        self.client.publish_feed(decision, lane, explanation, explanation_source)

    async def publish_escalation(self, escalation):
        self._check()
        self.client.publish_escalation(escalation)

    async def publish_context(self, context):
        self._check()
        self.client.publish_context(context)

    async def log_agent(self, entry):
        self._check()
        self.client.log_agent(entry)

    async def set_clock(self, clock, sim_host):
        self._check()
        self.client.set_clock(clock, sim_host)

    async def reset_all(self):
        self._check()
        self.client.reset_all()

    async def consume_surge(self, request_id):
        # consume_surges queues its own acknowledgement exactly once.
        pass

    async def read_surges(self):
        self._check()
        return self.client.consume_surges()


def create_live(live_transport: str, broadcast: Broadcast) -> tuple[LivePort, str]:
    """Construct the requested transport; start its worker in app lifespan."""
    if live_transport == "spacetime":
        import os
        from live.spacetime_client import SpacetimeClient
        env = dict(os.environ)
        for canonical, alias in (("SPACETIME_URI", "SPACETIMEDB_URL"),
                                 ("SPACETIME_DB", "SPACETIMEDB_DB"),
                                 ("SPACETIME_TOKEN", "SPACETIMEDB_TOKEN")):
            if canonical not in env and alias in env:
                env[canonical] = env[alias]
        return SpacetimeLive(SpacetimeClient.from_env(env, autostart=False)), "spacetime"
    return WsLive(broadcast), "ws"


# ---------------------------------------------------------------- publisher


class LivePublisher:
    """Queues live calls and sends them in order from one background task, so the run loop never waits on a transport."""

    def __init__(self, port: LivePort, *, fallback: LivePort | None = None,
                 on_warning: Callable[[dict], Awaitable[None]] | None = None, read_timeout_s: float = 0.2) -> None:
        self.port = port
        self._fallback = fallback
        self._on_warning = on_warning
        self._read_timeout_s = read_timeout_s
        self._early: list[tuple[str, tuple]] = []  # calls made before an event loop was running
        self._queue: asyncio.Queue | None = None
        self._task: asyncio.Task | None = None

    def use(self, port: LivePort) -> None:
        self.port = port

    def send(self, method: str, *args: Any) -> None:
        queue = self._ensure_drainer()
        if queue is None:
            self._early.append((method, args))
        else:
            queue.put_nowait((method, args))

    async def read_surges(self) -> list[dict]:
        """Bounded: a slow or failing read gives no surges this tick (they are read again next tick)."""
        try:
            return await asyncio.wait_for(self.port.read_surges(), self._read_timeout_s)
        except Exception as exc:  # incl. TimeoutError
            log.warning("read_surges failed: %r", exc)
            return []

    async def flush(self) -> None:
        """Wait until every queued call has been sent (tests, shutdown)."""
        queue = self._ensure_drainer()
        if queue is not None:
            await queue.join()

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
            self._queue = None

    def _ensure_drainer(self) -> asyncio.Queue | None:
        if self._task is not None and not self._task.done():
            return self._queue
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return None
        self._queue = asyncio.Queue()
        for item in self._early:
            self._queue.put_nowait(item)
        self._early = []
        self._task = asyncio.create_task(self._drain(self._queue), name="live-publisher")
        return self._queue

    async def _drain(self, queue: asyncio.Queue) -> None:
        while True:
            method, args = await queue.get()
            try:
                await getattr(self.port, method)(*args)
            except Exception:
                log.exception("live %s failed", method)
                await self._switch_to_fallback(method, args)
            finally:
                queue.task_done()

    async def _switch_to_fallback(self, method: str, args: tuple) -> None:
        if self._fallback is None or self.port is self._fallback:
            return
        self.port = self._fallback
        if self._on_warning is not None:
            try:
                await self._on_warning({
                    "type": "warning", "code": "live_transport_down",
                    "message": "SpacetimeDB is unreachable. Live updates now go over /ws.", "data": {},
                })
            except Exception:
                log.exception("live_transport_down warning failed")
        try:
            await getattr(self.port, method)(*args)
        except Exception:
            log.exception("live %s failed on the fallback too", method)
