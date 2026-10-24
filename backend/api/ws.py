"""Viewer WebSocket `/ws` (server → client, CONTRACTS.md §2).

`Broadcaster` holds every connected viewer; the runtime (later) calls `broadcast` with one contract message at a time.
Client → server frames are read only to notice disconnects; the viewer socket carries no client commands.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import BaseModel


class Broadcaster:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()

    @property
    def client_count(self) -> int:
        return len(self._clients)

    async def serve(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._clients.add(websocket)
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
