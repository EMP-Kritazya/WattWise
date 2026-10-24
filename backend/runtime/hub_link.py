"""Server side of the hub protocol on `/ws/hub` (CONTRACTS.md §8).

Exactly one sim host: the first `hub_hello` with `role: "sim_host"` is accepted; any later one gets `host_taken` and stays a
viewer (its socket stays open, its frames are ignored). The host is whatever speaks the protocol: the browser hub,
`fakes/fake_hub_client.py` or a script. Nothing here assumes a browser.

The runtime drives it: `send_build` once per kitchen build, then `tick` once per sim minute. `tick` sends the `sim_tick` and
waits for the `hub_report` with the same `tick_id`. Tick n + 1 is never sent before report n. The clock state this implies
goes to `on_status(paused_reason)`:
- no report within `report_timeout_s` (2 real s) → "hub_waiting" (tick keeps waiting),
- host socket closed → "sim_host_offline", plus a `/ws` `warning` message `{ last_tick_id }` to `on_warning`,
- the report arrives, or a host is accepted → None.
On every accepted hello the link re-sends `sim_build`, then replays every past `sim_tick` with `"replay": true` at full
speed; the hub answers only the last one. If that tick is still pending, the answer completes it; otherwise it is a
duplicate and is dropped, so the engine is never stepped twice for one tick. Ticks issued during the burst wait for it.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from dataclasses import dataclass
from typing import Any, Callable

from fastapi import WebSocket, WebSocketDisconnect

PROTOCOL = 1
HUB_REPORT_TIMEOUT_S = 2.0

log = logging.getLogger("runtime.hub_link")


class TickAborted(Exception):
    """The pending tick was abandoned because the kitchen was rebuilt (`send_build`) before its report arrived."""


@dataclass
class _Host:
    websocket: WebSocket
    hub_id: str | None
    last_sent_tick_id: int = 0


@dataclass
class _Pending:
    tick_id: int
    message: dict
    report: asyncio.Future


def _roster_entry(device: dict) -> dict:
    """§8: `sim_build.devices` is the roster only (off, 0 kW, no `physical`); the simulation sets real state on tick 1."""
    entry = {k: v for k, v in device.items() if k != "physical"}
    entry.update(state="off", power_kw=0.0, power_pct=0)
    return entry


class HubLink:
    def __init__(
        self,
        *,
        report_timeout_s: float = HUB_REPORT_TIMEOUT_S,
        on_status: Callable[[str | None], Any] | None = None,
        on_warning: Callable[[dict], Any] | None = None,
        on_host: Callable[[bool], Any] | None = None,
    ):
        self.report_timeout_s = report_timeout_s
        self._on_status = on_status
        self._on_warning = on_warning
        self._on_host = on_host
        self._host: _Host | None = None
        self._build: dict | None = None
        self._history: list[dict] = []  # every sim_tick of this build, in order (replayed on reconnect)
        self._pending: _Pending | None = None
        self._replay_until: int | None = None  # tick_id whose answer ends the current host's replay burst
        self._lock = asyncio.Lock()  # one writer at a time: welcome + build + replay never interleave with a tick
        self.paused_reason: str | None = "sim_host_offline"
        self.last_report_tick_id = 0

    @property
    def connected(self) -> bool:
        return self._host is not None

    @property
    def tick_id(self) -> int:
        """The last tick sent (or due) in this build; 0 before the first."""
        return self._history[-1]["tick_id"] if self._history else 0

    # ------------------------------------------------------------ runtime side

    async def send_build(
        self, kitchen_id: str, config: dict, catalog: list[dict], devices: list[dict], seed: int, start_sim_ts: str
    ) -> bool:
        """Start a new build: forget past ticks, send `sim_build` now if a host is connected (else on connect)."""
        message = {
            "type": "sim_build", "kitchen_id": kitchen_id, "config": config, "catalog": catalog,
            "devices": [_roster_entry(d) for d in devices], "seed": seed, "start_sim_ts": start_sim_ts,
        }
        async with self._lock:
            if self._pending is not None and not self._pending.report.done():
                self._pending.report.set_exception(TickAborted(f"tick {self._pending.tick_id} aborted by sim_build"))
            self._pending = None
            self._build = message
            self._history = []
            self._replay_until = None
            self.last_report_tick_id = 0
            host = self._host
            if host is None:
                return False
            host.last_sent_tick_id = 0
            return await self._send(host, message)

    async def tick(
        self, tick_id: int, sim_ts: str, surges: list[dict], inputs: dict, commands: list[dict], *, minutes: int = 1
    ) -> dict:
        """Send one `sim_tick` and return the matching `hub_report` message. Waits through hub_waiting and offline.

        Cancelling the call abandons the tick: the hub may still have stepped it, so its late report is dropped.
        """
        async with self._lock:
            if self._build is None:
                raise RuntimeError("send_build before the first tick")
            if self._pending is not None:
                raise RuntimeError(f"tick {tick_id} sent before hub_report {self._pending.tick_id}")
            if tick_id <= self.tick_id:
                raise ValueError(f"tick {tick_id} is not after tick {self.tick_id}")
            message = {
                "type": "sim_tick", "tick_id": tick_id, "sim_ts": sim_ts, "minutes": minutes, "surges": list(surges),
                "inputs": inputs, "commands": list(commands), "replay": False,
            }
            self._history.append(message)
            pending = self._pending = _Pending(tick_id, message, asyncio.get_running_loop().create_future())
            host = self._host
            if host is not None and self._replay_until is None:
                await self._send_tick(host, message)
        try:
            while True:
                try:
                    return await asyncio.wait_for(asyncio.shield(pending.report), self.report_timeout_s)
                except asyncio.TimeoutError:
                    if self._host is not None:
                        await self._set_status("hub_waiting")
        finally:
            if self._pending is pending:
                self._pending = None

    async def send_control(self, action: str, speed: int, paused_reason: str | None = None) -> bool:
        """Tell the hub the clock state (`sim_control`). False when no host is connected."""
        message = {"type": "sim_control", "action": action, "speed": speed, "paused_reason": paused_reason}
        async with self._lock:
            return self._host is not None and await self._send(self._host, message)

    # ------------------------------------------------------------ socket side

    async def serve(self, websocket: WebSocket) -> None:
        """The `/ws/hub` endpoint: hello → welcome; the host's frames are read until it disconnects."""
        await websocket.accept()
        host = None
        try:
            hello = await self._receive(websocket)
            if (
                not hello or hello.get("type") != "hub_hello" or hello.get("role") != "sim_host"
                or hello.get("protocol") != PROTOCOL
            ):
                log.warning("refused /ws/hub client: first frame is not a protocol %s sim_host hub_hello", PROTOCOL)
                await websocket.close(code=1008)
                return
            host = await self._accept_host(websocket, hello)
            if host is None:
                await websocket.send_text(json.dumps(
                    {"type": "hub_welcome", "accepted": False, "reason": "host_taken", "tick_id": self.tick_id}
                ))
                while True:  # stays a viewer: nothing it sends is used
                    await self._receive(websocket)
            while True:
                message = await self._receive(websocket)
                if message is None:
                    continue
                if message.get("type") == "hub_report":
                    await self._on_report(host, message)
                else:
                    log.info("ignored %s from the sim host", message.get("type"))
        except WebSocketDisconnect:
            pass
        finally:
            if host is not None:
                await self._host_gone(host)

    async def _accept_host(self, websocket: WebSocket, hello: dict) -> _Host | None:
        async with self._lock:
            if self._host is not None:
                return None
            host = self._host = _Host(websocket, hello.get("hub_id"))
            await self._send(host, {"type": "hub_welcome", "accepted": True, "reason": None, "tick_id": self.tick_id})
            if self._build is not None:
                await self._send(host, self._build)
                for message in self._history:
                    await self._send_tick(host, {**message, "replay": True})
                self._replay_until = self.tick_id if self._history else None
        log.info("sim host %s connected", host.hub_id)
        await self._emit(self._on_host, True)
        await self._set_status(None)
        return host

    async def _on_report(self, host: _Host, message: dict) -> None:
        tick_id = message.get("tick_id")
        pending = self._pending
        if pending is not None and tick_id == pending.tick_id and not pending.report.done():
            self._pending = None
            self.last_report_tick_id = tick_id
            pending.report.set_result(message)
            await self._set_status(None)
        else:
            log.info("dropped hub_report %s: not the pending tick (a replay answer or late)", tick_id)
        if self._replay_until is not None and tick_id == self._replay_until:
            async with self._lock:
                self._replay_until = None
                pending = self._pending
                if pending is not None and self._host is host and pending.tick_id > host.last_sent_tick_id:
                    await self._send_tick(host, pending.message)  # issued during the replay burst

    async def _host_gone(self, host: _Host) -> None:
        async with self._lock:
            if self._host is not host:
                return
            self._host = None
            self._replay_until = None
        log.warning("sim host %s disconnected after tick %s", host.hub_id, self.last_report_tick_id)
        await self._emit(self._on_host, False)
        await self._set_status("sim_host_offline")
        await self._emit(self._on_warning, {
            "type": "warning", "code": "sim_host_offline",
            "message": "The simulation host disconnected. The clock is paused until it reconnects.",
            "data": {"last_tick_id": self.last_report_tick_id},
        })

    # ------------------------------------------------------------ helpers

    async def _send_tick(self, host: _Host, message: dict) -> None:
        if await self._send(host, message):
            host.last_sent_tick_id = message["tick_id"]

    @staticmethod
    async def _send(host: _Host, message: dict) -> bool:
        try:
            await host.websocket.send_text(json.dumps(message))
            return True
        except Exception as exc:  # closed under us; serve() notices the disconnect and reports it
            log.warning("send %s to sim host failed: %s", message.get("type"), exc)
            return False

    @staticmethod
    async def _receive(websocket: WebSocket) -> dict | None:
        """One JSON frame, None if it is not a JSON object. Raises WebSocketDisconnect when the socket closes."""
        frame = await websocket.receive()
        if frame["type"] == "websocket.disconnect":
            raise WebSocketDisconnect(frame.get("code", 1000))
        raw = frame.get("text") if frame.get("text") is not None else (frame.get("bytes") or b"").decode("utf-8", "replace")
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("ignored a non-JSON frame on /ws/hub")
            return None
        return message if isinstance(message, dict) else None

    async def _set_status(self, paused_reason: str | None) -> None:
        if paused_reason != self.paused_reason:
            self.paused_reason = paused_reason
            await self._emit(self._on_status, paused_reason)

    @staticmethod
    async def _emit(callback: Callable[[Any], Any] | None, value: Any) -> None:
        if callback is None:
            return
        try:
            result = callback(value)
            if inspect.isawaitable(result):
                await result
        except Exception:  # a listener never breaks the link
            log.exception("hub_link listener failed")
