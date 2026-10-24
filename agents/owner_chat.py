"""The Concierge's owner chat (AGENTS.md "Concierge loops" → Chat): one ASI:One message in, one plain-text reply out.

- `confirm` / `yes` and `no` / `cancel` (the whole message, any case) are matched here, by code, before any model call:
  they confirm or cancel the newest pending Proposal (`GET /api/proposals?status=pending` →
  `POST /api/proposals/{id}/confirm` with `X-Agent-Token`, so the API records `confirmed_via: "asi_one"`). The model
  never confirms.
- Anything else goes to the same Claude agent as the dashboard: open `/ws`, `POST /api/chat`, join that chat_id's
  `chat_delta` frames until its `chat_done`. A Proposal that turns up pending meanwhile gets a code-written
  "reply confirm" line.
- `POST /api/chat` carries only `{message}`, so the last HISTORY_TURNS exchanges with this sender ride in the message
  text (STUB until the contract has a chat session id), letting "Undo that" or "Choose option 2" refer back.
- Every hop is logged with `POST /api/agent-log`. Never raises: the API down, a timeout or an error status gives a short
  plain reply and the session stays alive.

No uagents import: the backend tests run it against the real API (`backend/tests/agent/test_owner_flows.py`).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from datetime import datetime, timezone
from typing import Any

import httpx
import websockets

log = logging.getLogger("agents.owner_chat")

CONFIRM_WORDS = ("confirm", "yes")
CANCEL_WORDS = ("no", "cancel")
REPLY_TIMEOUT_S = 30.0
API_TIMEOUT_S = 5.0
HISTORY_TURNS = 3
HISTORY_REPLY_CHARS = 600
LOG_SUMMARY_CHARS = 80

API_DOWN = "I can't reach the kitchen right now. Please try again in a moment."
TIMED_OUT = "Sorry, that took too long. Please ask again in a moment."
NO_ANSWER = "Sorry, I couldn't get an answer just now. Please try again."
NOTHING_PENDING = "Nothing is waiting for your confirmation right now."
CONFIRM_HINT = 'Reply "confirm" to apply it or "cancel" to drop it.'


def match_confirmation(text: str) -> bool | None:
    """True for confirm / yes, False for no / cancel, None for anything else (sent to Claude)."""
    word = text.strip().rstrip(".!").strip().lower()
    if word in CONFIRM_WORDS:
        return True
    if word in CANCEL_WORDS:
        return False
    return None


def ws_url(api_url: str) -> str:
    """The viewer socket next to API_URL: http → ws, https → wss."""
    scheme, rest = api_url.split("://", 1)
    return f"{'wss' if scheme == 'https' else 'ws'}://{rest.rstrip('/')}/ws"


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _sentence(text: str) -> str:
    return text.strip().rstrip(".") + "."


def _detail(r: httpx.Response) -> str:
    try:
        return str(r.json()["detail"])
    except (ValueError, KeyError, TypeError):
        return f"HTTP {r.status_code}"


def _ts_real() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


class OwnerChat:
    def __init__(self, http: httpx.AsyncClient, ws_url: str, token: str | None, *,
                 reply_timeout_s: float = REPLY_TIMEOUT_S, history_turns: int = HISTORY_TURNS):
        self._http = http  # base_url = API_URL
        self._ws_url = ws_url
        self._headers = {"X-Agent-Token": token or ""}
        self._timeout = reply_timeout_s
        self._history_turns = history_turns
        self._history: dict[str, deque[tuple[str, str]]] = {}  # sender → (owner text, reply)

    async def answer(self, sender: str, text: str) -> str:
        confirm = match_confirmation(text)
        try:
            reply = await (self._confirm(confirm) if confirm is not None else self._ask(sender, text))
        except Exception:
            log.exception("owner chat failed")
            reply = NO_ANSWER
        self._history.setdefault(sender, deque(maxlen=self._history_turns)).append((text, reply))
        return reply

    # ------------------------------------------------------------ confirm / cancel (code, never the model)

    async def _confirm(self, confirm: bool) -> str:
        try:
            r = await self._http.get("/api/proposals", params={"status": "pending"}, timeout=API_TIMEOUT_S)
            if r.status_code != 200:
                return API_DOWN
            pending = r.json()
            if not pending:
                return NOTHING_PENDING
            proposal = pending[-1]  # the newest, as ProposalBook.latest_pending
            r = await self._http.post(f"/api/proposals/{proposal['proposal_id']}/confirm", json={"confirm": confirm},
                                      headers=self._headers, timeout=API_TIMEOUT_S)
        except httpx.HTTPError:
            return API_DOWN
        verb = "confirmed" if confirm else "cancelled"
        if r.status_code != 200:
            await self.log("concierge", "engine", "error", f"Owner {verb} {proposal['proposal_id']}: {_detail(r)}")
            return f"I couldn't {'apply' if confirm else 'cancel'} that: {_sentence(_detail(r))}"
        done = r.json()
        await self.log("concierge", "engine", "post", f"Owner {verb} {done['proposal_id']} in ASI:One")
        return f"{'Done' if confirm else 'Cancelled'}: {_sentence(done['summary'])}"

    # ------------------------------------------------------------ questions (the Claude agent through the API)

    async def _ask(self, sender: str, text: str) -> str:
        await self.log("concierge", "claude", "request", f"Owner asks: {_clip(text, LOG_SUMMARY_CHARS)}")
        try:
            async with asyncio.timeout(self._timeout):
                # Open /ws first: the reply starts streaming as soon as the chat is posted.
                async with websockets.connect(self._ws_url, open_timeout=API_TIMEOUT_S) as ws:
                    r = await self._http.post("/api/chat", json={"message": self._with_history(sender, text)},
                                              timeout=API_TIMEOUT_S)
                    if r.status_code != 200:
                        await self.log("concierge", "claude", "error", f"Chat refused: {_detail(r)}")
                        return NO_ANSWER
                    chat_id = r.json()["chat_id"]
                    reply, proposal = await self._collect(ws, chat_id)
        except TimeoutError:
            await self.log("concierge", "claude", "error", "No answer in time")
            return TIMED_OUT
        except (OSError, httpx.HTTPError, websockets.WebSocketException) as e:
            log.warning("chat hop failed: %s", type(e).__name__)
            return API_DOWN
        await self.log("claude", "concierge", "response", f"Answered {chat_id}")
        reply = reply.strip() or NO_ANSWER
        if proposal is not None:
            reply += f"\n\nWaiting for your confirmation: {_sentence(proposal['summary'])} {CONFIRM_HINT}"
        return reply

    async def _collect(self, ws: Any, chat_id: str) -> tuple[str, dict | None]:
        """This chat's text until its `chat_done`, and the newest Proposal still pending at that point."""
        parts: list[str] = []
        pending: dict[str, dict] = {}
        async for raw in ws:
            msg = json.loads(raw)
            kind = msg.get("type")
            if kind == "chat_delta" and msg.get("chat_id") == chat_id:
                parts.append(msg["text"])
            elif kind == "chat_done" and msg.get("chat_id") == chat_id:
                return "".join(parts), list(pending.values())[-1] if pending else None
            elif kind == "proposal":
                proposal = msg["data"]
                pending.pop(proposal["proposal_id"], None)
                if proposal["status"] == "pending":
                    pending[proposal["proposal_id"]] = proposal
        raise ConnectionError("the viewer socket closed before chat_done")

    def _with_history(self, sender: str, text: str) -> str:
        turns = self._history.get(sender)
        if not turns:
            return text
        lines = ["Earlier in this chat, for reference only (take every number from tools):"]
        for asked, replied in turns:
            lines += [f"Owner: {asked}", f"You: {_clip(replied, HISTORY_REPLY_CHARS)}"]
        return "\n".join(lines) + f"\n\nThe owner's new message: {text}"

    # ------------------------------------------------------------ agent log

    async def log(self, from_agent: str, to_agent: str, kind: str, summary: str) -> None:
        body = {"ts_real": _ts_real(), "from_agent": from_agent, "to_agent": to_agent, "kind": kind,
                "summary": summary}
        try:
            r = await self._http.post("/api/agent-log", json=body, headers=self._headers, timeout=API_TIMEOUT_S)
            if r.status_code != 200:
                log.debug("agent log refused: HTTP %s", r.status_code)
        except httpx.HTTPError:
            log.debug("agent log not posted (API down)")
