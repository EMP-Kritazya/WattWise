"""Convex store (`STORE=convex`): the Store interface over Convex (CONTRACTS.md §6, functions in `convex/`).

Every write lands at once in an in-memory mirror (a `MemoryStore`; reads come from it, since the API runs as exactly one
replica and so holds the truth of its own records) and is queued as the matching Convex mutation. One background thread
sends the queue once per real second (`flush_s`) as one `batch:apply` call (in order, one transaction; chunks of
`BATCH_MAX`), so no caller ever waits on Convex and a fast clock cannot outrun it. A rejected batch is resent one write at a
time, so only the bad write is lost.

Convex unreachable (a transport error, or a call stuck past `call_timeout_s`) → the store switches to memory for good:
the queue is dropped (the mirror already holds it), one `store_down` warning goes to `on_warning`, and every later call
is memory only (`kind` becomes "memory"). A write Convex rejects (validation, "Server Error") is logged and skipped;
Convex itself is fine. `latest_readings` and `device_map` read Convex directly (an ESP32 writes there, not here), with
the mirror as fallback.

Transport: the Convex HTTP API (`ConvexHttp`, httpx), not the Rust-backed `convex.ConvexClient`: that client holds the GIL
for the whole round trip (measured: ~300 ms main-thread stalls per call), which would stall the event loop and the clock.
Same functions, same args; any object with `mutation` / `query` (e.g. `convex.ConvexClient`) can be passed as `client`.

Not in CONTRACTS.md §6 yet (contract questions): batch:apply, kitchens:record, escalations:record, deviceBlocks:record,
contextSnapshots:record, devices:latest, devices:map, devices:mapChannel.
"""

from __future__ import annotations

import concurrent.futures
import logging
import threading
from pathlib import Path
from typing import Any, Callable, Protocol

import httpx

from .base import Store
from .memory import MemoryStore

log = logging.getLogger("store.convex")

FLUSH_S = 1.0
CALL_TIMEOUT_S = 10.0
BATCH_MAX = 100
STORE_DOWN_WARNING = {
    "type": "warning",
    "code": "store_down",
    "message": "Convex is unreachable. Records are kept in memory from now on.",
    "data": {},
}


class ConvexApi(Protocol):
    """What the store uses of `convex.ConvexClient` (tests pass a double)."""

    def mutation(self, name: str, args: dict | None = None) -> Any: ...

    def query(self, name: str, args: dict | None = None) -> Any: ...


class ConvexRejected(Exception):
    """Convex answered and refused the call (bad args, unknown function, the function threw)."""


class ConvexHttp:
    """`POST /api/mutation` and `/api/query` (JSON format: numbers are Float64, as the validators expect)."""

    def __init__(self, url: str, timeout_s: float = CALL_TIMEOUT_S):
        self._http = httpx.Client(base_url=url.rstrip("/"), timeout=timeout_s)

    def _call(self, kind: str, name: str, args: dict | None) -> Any:
        response = self._http.post(f"/api/{kind}", json={"path": name, "args": args or {}, "format": "json"})
        try:
            body = response.json()
        except ValueError:
            response.raise_for_status()  # a gateway error page: unreachable
            raise
        if body.get("status") == "success":
            return body.get("value")
        if "errorMessage" in body:
            raise ConvexRejected(body["errorMessage"])
        response.raise_for_status()
        raise RuntimeError(f"unexpected Convex answer: {body}")

    def mutation(self, name: str, args: dict | None = None) -> Any:
        return self._call("mutation", name, args)

    def query(self, name: str, args: dict | None = None) -> Any:
        return self._call("query", name, args)

    def close(self) -> None:
        self._http.close()


def _rejected(exc: Exception) -> bool:
    """Convex answered and refused the call rather than being unreachable (the Rust client says "Server Error")."""
    return isinstance(exc, ConvexRejected) or "Server Error" in str(exc) or type(exc).__name__ == "ConvexError"


def _reading(row: dict) -> dict:
    """Convex numbers come back as floats; a Reading's channel is an integer."""
    return {**row, "channel": int(row["channel"])}


class ConvexStore(Store):
    def __init__(
        self,
        url: str | None = None,
        *,
        client: ConvexApi | None = None,
        seed_dir: Path | None = None,
        on_warning: Callable[[dict], Any] | None = None,
        flush_s: float = FLUSH_S,
        call_timeout_s: float = CALL_TIMEOUT_S,
        autostart: bool = True,
    ):
        if client is None:
            if not url:
                raise ValueError("STORE=convex needs CONVEX_URL")
            client = ConvexHttp(url, call_timeout_s)
        self._client = client
        self._mirror = MemoryStore(seed_dir)  # seeded mirror only: the seed is never pushed to Convex
        self._on_warning = on_warning
        self._flush_s = flush_s
        self._call_timeout_s = call_timeout_s
        self._lock = threading.Lock()
        self._queue: list[tuple[str, dict]] = []
        self._down = False
        self._caller = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="convex-call")
        self._send_lock = threading.Lock()
        self._wake = threading.Event()
        self._closed = False
        self._thread: threading.Thread | None = None
        if autostart:
            self._thread = threading.Thread(target=self._run, name="convex-store", daemon=True)
            self._thread.start()

    # ------------------------------------------------------------ state

    @property
    def kind(self) -> str:
        return "memory" if self._down else "convex"

    @property
    def mirror(self) -> MemoryStore:
        return self._mirror

    def rows(self, table: str) -> list[dict]:
        return self._mirror.rows(table)

    # ------------------------------------------------------------ sending

    def _send(self, name: str, args: dict) -> None:
        with self._lock:
            if not self._down:
                self._queue.append((name, args))

    def _call(self, kind: str, name: str, args: dict) -> Any:
        """One Convex call, time-boxed. Raises on failure."""
        fn = self._client.query if kind == "query" else self._client.mutation
        future = self._caller.submit(fn, name, args)
        try:
            return future.result(timeout=self._call_timeout_s)
        except concurrent.futures.TimeoutError:
            raise TimeoutError(f"Convex {kind} {name} took longer than {self._call_timeout_s} s") from None

    def flush(self) -> None:
        """Send every queued mutation now, in order (the background thread does this every `flush_s`)."""
        with self._send_lock:
            with self._lock:
                queued, self._queue = self._queue, []
            for start in range(0, len(queued), BATCH_MAX):
                chunk = queued[start:start + BATCH_MAX]
                if self._down:
                    return
                try:
                    self._call("mutation", "batch:apply", {"writes": [{"name": n, "args": a} for n, a in chunk]})
                except Exception as exc:
                    if not _rejected(exc):
                        self._go_down(exc)
                        return
                    log.warning("Convex rejected a batch (%s); sending its writes one by one", exc)
                    if not self._send_each(chunk):
                        return

    def _send_each(self, writes: list[tuple[str, dict]]) -> bool:
        """One call per write; a rejected one is logged and skipped. False when Convex turned out unreachable."""
        for name, args in writes:
            try:
                self._call("mutation", name, args)
            except Exception as exc:
                if not _rejected(exc):
                    self._go_down(exc)
                    return False
                log.error("Convex rejected %s: %s", name, exc)
        return True

    def _go_down(self, exc: Exception) -> None:
        with self._lock:
            if self._down:
                return
            self._down = True
            self._queue = []
        log.warning("store_down: Convex unreachable (%s); switched to the in-memory store", exc)
        self._caller.shutdown(wait=False, cancel_futures=True)
        if self._on_warning is not None:
            try:
                self._on_warning(dict(STORE_DOWN_WARNING))
            except Exception:
                log.exception("store_down warning could not be delivered")

    def _run(self) -> None:
        while not self._closed:
            self._wake.wait(self._flush_s)
            self._wake.clear()
            try:
                self.flush()
            except Exception:
                log.exception("Convex flush failed")

    def close(self) -> None:
        """Send what is queued, then stop the background thread."""
        self._closed = True
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=self._call_timeout_s + 1)
        self.flush()
        self._caller.shutdown(wait=False)
        close = getattr(self._client, "close", None)
        if close is not None:
            close()

    def _read(self, name: str, args: dict, fallback: Callable[[], list[dict]]) -> list[dict]:
        if self._down:
            return fallback()
        try:
            return self._call("query", name, args)
        except Exception as exc:
            if _rejected(exc):
                log.error("Convex rejected %s: %s", name, exc)
            else:
                self._go_down(exc)
            return fallback()

    # ------------------------------------------------------------ kitchens

    def record_kitchen(self, config: dict, created_at: str) -> None:
        self._mirror.record_kitchen(config, created_at)
        self._send("kitchens:record", {"config": config, "created_at": created_at})

    def latest_kitchen(self) -> dict | None:
        return self._mirror.latest_kitchen()

    # ------------------------------------------------------------ decisions + commands

    def record_decisions(self, decisions: list[dict]) -> None:
        self._mirror.record_decisions(decisions)
        self._send("decisions:record", {"decisions": decisions})

    def decisions(self, lane: str | None = None) -> list[dict]:
        return self._mirror.decisions(lane)

    def record_command(self, command: dict, lane: str, hub_id: str | None) -> None:
        self._mirror.record_command(command, lane, hub_id)
        self._send("commands:enqueue", {"command": command, "lane": lane, "hub_id": hub_id})

    def ack_command(self, command_id: str, ok: bool, applied_value: float | None, reason: str | None) -> None:
        self._mirror.ack_command(command_id, ok, applied_value, reason)
        self._send("commands:ack", {"command_id": command_id, "ok": ok, "applied_value": applied_value,
                                    "reason": reason})

    def commands_for_hub(self, hub_id: str) -> list[dict]:
        return self._read("commands:forDevice", {"hub_id": hub_id}, lambda: self._mirror.commands_for_hub(hub_id))

    # ------------------------------------------------------------ device bridge

    def report_reading(self, reading: dict) -> None:
        self._mirror.report_reading(reading)
        self._send("devices:report", {"reading": reading})

    def latest_readings(self, hub_id: str) -> list[dict]:
        rows = self._read("devices:latest", {"hub_id": hub_id}, lambda: self._mirror.latest_readings(hub_id))
        return [_reading(r) for r in rows]

    def device_map(self) -> list[dict]:
        rows = self._read("devices:map", {}, self._mirror.device_map)
        return [{**r, "channel": int(r["channel"])} for r in rows]

    def map_channel(self, row: dict) -> None:
        self._mirror.map_channel(row)
        self._send("devices:mapChannel", {"row": row})

    # ------------------------------------------------------------ proposals

    def upsert_proposal(self, proposal: dict) -> None:
        self._mirror.upsert_proposal(proposal)
        self._send("proposals:upsert", {"proposal": proposal})

    def proposals(self, status: str | None = None) -> list[dict]:
        return self._mirror.proposals(status)

    def proposal(self, proposal_id: str) -> dict | None:
        return self._mirror.proposal(proposal_id)

    # ------------------------------------------------------------ bills + backtests

    def save_bill(self, bill: dict, lane: str) -> None:
        self._mirror.save_bill(bill, lane)
        self._send("bills:save", {"bill": bill, "lane": lane})

    def bills(self) -> list[dict]:
        return self._mirror.bills()

    def save_backtest(self, run_id: str, results: list[dict]) -> None:
        self._mirror.save_backtest(run_id, results)
        self._send("backtest:save", {"run_id": run_id, "results": results})

    def backtest(self, run_id: str) -> list[dict] | None:
        return self._mirror.backtest(run_id)

    def backtest_run_ids(self) -> list[str]:
        return self._mirror.backtest_run_ids()

    # ------------------------------------------------------------ blocks, escalations, context

    def record_device_blocks(self, blocks: list[dict]) -> None:
        self._mirror.record_device_blocks(blocks)
        self._send("deviceBlocks:record", {"blocks": blocks})

    def record_escalation(self, escalation: dict) -> None:
        self._mirror.record_escalation(escalation)
        self._send("escalations:record", {"escalation": escalation})

    def escalations(self) -> list[dict]:
        return self._mirror.escalations()

    def record_context_snapshot(self, context: dict) -> None:
        self._mirror.record_context_snapshot(context)
        self._send("contextSnapshots:record", {"context": context})
