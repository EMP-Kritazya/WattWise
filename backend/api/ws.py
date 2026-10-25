"""Viewer WebSocket `/ws` (server → client, CONTRACTS.md §2).

`Broadcaster` holds every connected viewer; the runtime (later) calls `broadcast` with one contract message at a time.
Client → server frames are read only to notice disconnects; the viewer socket carries no client commands.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import BaseModel

log = logging.getLogger("api.ws")


class Broadcaster:
    def __init__(self) -> None:
        self._live_warning: dict | None = None
        self._clients: set[WebSocket] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue | None = None
        self._sender: asyncio.Task | None = None

    @property
    def client_count(self) -> int:
        return len(self._clients)

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def send_soon(self, message: BaseModel | dict[str, Any]) -> None:
        """`broadcast` from sync code on any thread (REST threadpool, agent tools), in call order: one queue, one sender."""
        try:
            asyncio.get_running_loop()
            on_loop = True
        except RuntimeError:  # a worker thread
            on_loop = False
        if on_loop:
            self._enqueue(message)
        elif self._loop is not None and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._enqueue, message)
        else:
            log.debug("no event loop yet, so no viewer is connected; dropped one message")

    def _enqueue(self, message: BaseModel | dict[str, Any]) -> None:
        if self._queue is None or self._sender is None or self._sender.done():
            self._queue = asyncio.Queue()
            self._sender = asyncio.get_running_loop().create_task(self._send_queued(self._queue), name="ws-sender")
        self._queue.put_nowait(message)

    async def _send_queued(self, queue: asyncio.Queue) -> None:
        while True:
            message = await queue.get()
            try:
                await self.broadcast(message)
            finally:
                queue.task_done()

    async def flush(self) -> None:
        """Wait until every `send_soon` message has been sent (tests, shutdown)."""
        if self._queue is not None:
            await self._queue.join()

    async def stop(self) -> None:
        await self.flush()
        if self._sender is not None:
            self._sender.cancel()
            self._sender = None

    async def serve(self, websocket: WebSocket) -> None:
        self._loop = asyncio.get_running_loop()
        await websocket.accept()
        self._clients.add(websocket)
        if self._live_warning is not None:
            await websocket.send_json(self._live_warning)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            self._clients.discard(websocket)

    async def broadcast(self, message: BaseModel | dict[str, Any]) -> None:
        """Send one `/ws` message to every viewer; a viewer that fails to receive is dropped."""
        if isinstance(message, BaseModel):
            message = message.model_dump(mode="json", by_alias=True, exclude_unset=True)
        if message.get("type") == "warning" and message.get("code") == "live_transport_down":
            self._live_warning = message
        for client in list(self._clients):
            try:
                await client.send_json(message)
            except Exception:
                self._clients.discard(client)


async def replay_fixture_stream(broadcaster: Broadcaster, stream_path: Path) -> int:
    """Test helper only: broadcast every line of `contracts/fixtures/ws/stream.jsonl` in order. Returns the count."""
    sent = 0
    for line in stream_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            await broadcaster.broadcast(json.loads(line))
            sent += 1
    return sent
