"""The Concierge's owner chat (AGENTS.md "Concierge loops" → Chat): one ASI:One message in, one reply out (text, plus an
Interactive Card for the moments that matter; `cards.py`).

- `confirm` / `yes` and `no` / `cancel` (the whole message, any case) are matched here, by code, before any model call:
  they confirm or cancel the newest pending Proposal (`GET /api/proposals?status=pending` →
  `POST /api/proposals/{id}/confirm` with `X-Agent-Token`, so the API records `confirmed_via: "asi_one"`). The model
  never confirms.
- Anything else goes to the same Claude agent as the dashboard: open `/ws`, `POST /api/chat`, join that chat_id's
  `chat_delta` frames until its `chat_done`. A Proposal that turns up pending meanwhile gets a code-written
  "reply confirm" line and a proposal card.
- Cards on a Claude reply (the text always carries the card's fallback): a Proposal pending from this chat → proposal
  card; else a question about decisions / options while an escalation needs the owner → escalation card; else a forecast
  question → forecast card from the newest `with` tick's `forecast_kw` on `/ws` (no REST route to the forecast tool).
- A card button press (selection JSON, or the planner's prose naming its ids) is matched here by code: an option →
  `POST /api/escalations/{id}/resolve` (or, for the option Claude picked, confirming Claude's pending Proposal); a
  proposal button → `POST /api/proposals/{id}/confirm`, as a typed "confirm" does. Unknown or stale → EXPIRED.
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

from cards import (APPROVE_PICK, ASK_LATER, CHOOSE_OPTION, CONFIRM_HINT, EXPIRED, PROPOSAL_CANCEL, PROPOSAL_CONFIRM,
                   Card, Reply, Selection, escalation_card, forecast_card, numbered_options, parse_selection,
                   proposal_card)

log = logging.getLogger("agents.owner_chat")

CONFIRM_WORDS = ("confirm", "yes")
CANCEL_WORDS = ("no", "cancel")
REPLY_TIMEOUT_S = 30.0
API_TIMEOUT_S = 5.0
HISTORY_TURNS = 3
HISTORY_REPLY_CHARS = 600
LOG_SUMMARY_CHARS = 80
FORECAST_WAIT_S = 3.0  # after chat_done, how long to wait for a re-plan tick that carries forecast_kw
ESCALATION_WORDS = ("decide", "decision", "escalat", "option", "choice")
FORECAST_WORDS = ("forecast", "next 2 h", "next two hours", "next few hours", "coming hours")

API_DOWN = "I can't reach the kitchen right now. Please try again in a moment."
TIMED_OUT = "Sorry, that took too long. Please ask again in a moment."
NO_ANSWER = "Sorry, I couldn't get an answer just now. Please try again."
NOTHING_PENDING = "Nothing is waiting for your confirmation right now."


def match_confirmation(text: str) -> bool | None:
    """True for confirm / yes, False for no / cancel, None for anything else (sent to Claude)."""
    word = text.strip().rstrip(".!").strip().lower()
    if word in CONFIRM_WORDS:
        return True
    if word in CANCEL_WORDS:
        return False
    return None


def _mentions(text: str, words: tuple[str, ...]) -> bool:
    text = " ".join(text.lower().split())
    return any(word in text for word in words)


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


def _forecast_tick(msg: dict) -> bool:
    data = msg.get("data") or {}
    return msg.get("type") == "tick" and data.get("lane") == "with" and data.get("forecast_kw") is not None


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
        """The reply's text: what ASI:One shows when it drops the card."""
        return (await self.answer_reply(sender, text)).text

    async def answer_reply(self, sender: str, text: str) -> Reply:
        selection = parse_selection(text)
        confirm = match_confirmation(text) if selection is None else None
        try:
            if selection is not None:
                reply = Reply(await self.on_selection(selection))
            elif confirm is not None:
                reply = Reply(await self._confirm(confirm))
            else:
                reply = await self._ask(sender, text)
        except Exception:
            log.exception("owner chat failed")
            reply = Reply(NO_ANSWER)
        self._history.setdefault(sender, deque(maxlen=self._history_turns)).append((text, reply.text))
        return reply

    # ------------------------------------------------------------ confirm / cancel (code, never the model)

    async def _confirm(self, confirm: bool) -> str:
        pending = await self._pending()
        if pending is None:
            return API_DOWN
        if not pending:
            return NOTHING_PENDING
        return await self._apply_proposal(pending[-1]["proposal_id"], confirm)  # the newest, as ProposalBook.latest_pending

    async def _apply_proposal(self, proposal_id: str, confirm: bool) -> str:
        try:
            r = await self._http.post(f"/api/proposals/{proposal_id}/confirm", json={"confirm": confirm},
                                      headers=self._headers, timeout=API_TIMEOUT_S)
        except httpx.HTTPError:
            return API_DOWN
        verb = "confirmed" if confirm else "cancelled"
        if r.status_code != 200:
            await self.log("concierge", "engine", "error", f"Owner {verb} {proposal_id}: {_detail(r)}")
            return f"I couldn't {'apply' if confirm else 'cancel'} that: {_sentence(_detail(r))}"
        done = r.json()
        await self.log("concierge", "engine", "post", f"Owner {verb} {done['proposal_id']} in ASI:One")
        return f"{'Done' if confirm else 'Cancelled'}: {_sentence(done['summary'])}"

    async def _pending(self) -> list[dict] | None:
        """Pending Proposals, oldest first; None when the API is down."""
        try:
            r = await self._http.get("/api/proposals", params={"status": "pending"}, timeout=API_TIMEOUT_S)
        except httpx.HTTPError:
            return None
        return r.json() if r.status_code == 200 else None

    # ------------------------------------------------------------ card buttons (code, never the model)

    async def on_selection(self, selection: Selection) -> str:
        action = selection.action
        if action in (CHOOSE_OPTION, APPROVE_PICK):
            return await self._choose(selection.get("escalation_id"), selection.get("option_id"))
        if action == ASK_LATER:
            return await self._later(selection.get("escalation_id"))
        if action in (PROPOSAL_CONFIRM, PROPOSAL_CANCEL):
            pending = await self._pending()
            if pending is None:
                return API_DOWN
            if selection.get("proposal_id") not in {p["proposal_id"] for p in pending}:
                return EXPIRED
            return await self._apply_proposal(selection.get("proposal_id"), action == PROPOSAL_CONFIRM)
        return EXPIRED  # unknown button (or an upgrade button with no checkout flow behind it)

    async def _needing_owner(self) -> list[dict] | None:
        """Escalations the owner can still decide (awaiting_owner first, then open); None when the API is down."""
        found: list[dict] = []
        try:
            for status in ("awaiting_owner", "open"):
                r = await self._http.get("/api/escalations", params={"status": status}, timeout=API_TIMEOUT_S)
                if r.status_code != 200:
                    return None
                found += r.json()
        except httpx.HTTPError:
            return None
        return found

    async def _choose(self, escalation_id: str, option_id: str) -> str:
        """The owner picks an option on the escalation card. The option Claude proposed is confirmed through its pending
        Proposal (the existing flow); any other is the owner's choice (`POST /api/escalations/{id}/resolve`). Either
        way the escalation's other pending Proposals are cancelled, so a later "confirm" can't land on them."""
        needing, pending = await self._needing_owner(), await self._pending()
        if needing is None or pending is None:
            return API_DOWN
        escalation = next((e for e in needing if e["escalation_id"] == escalation_id), None)
        option = escalation and next((o for _, o in numbered_options(escalation) if o["option_id"] == option_id), None)
        if option is None:
            return EXPIRED
        stale = [p for p in pending if p["kind"] == "resolve_escalation" and p["payload"]["escalation_id"] == escalation_id]
        same = [p for p in stale if p["payload"]["option_id"] == option_id]
        if same:
            reply = await self._apply_proposal(same[-1]["proposal_id"], True)
            stale.remove(same[-1])
        else:
            reply = await self._resolve(escalation_id, option)
        for proposal in stale:
            await self._apply_proposal(proposal["proposal_id"], False)
        return reply

    async def _resolve(self, escalation_id: str, option: dict) -> str:
        try:
            r = await self._http.post(f"/api/escalations/{escalation_id}/resolve",
                                      json={"option_id": option["option_id"]}, timeout=API_TIMEOUT_S)
        except httpx.HTTPError:
            return API_DOWN
        if r.status_code == 404:
            return EXPIRED
        if r.status_code != 200:
            await self.log("concierge", "engine", "error", f"Owner chose {option['option_id']}: {_detail(r)}")
            return f"I couldn't apply that: {_sentence(_detail(r))}"
        await self.log("concierge", "engine", "post", f"Owner chose {option['option_id']} for {escalation_id} in ASI:One")
        return f"Done: {_sentence(option['summary'])}"

    async def _later(self, escalation_id: str) -> str:
        needing = await self._needing_owner()
        if needing is None:
            return API_DOWN
        escalation = next((e for e in needing if e["escalation_id"] == escalation_id), None)
        if escalation is None:
            return EXPIRED
        default = next(o for o in escalation["options"] if o["option_id"] == escalation["default_option_id"])
        await self.log("concierge", "engine", "post", f"Owner left {escalation_id} for later in ASI:One")
        return ("OK, it stays with you. If nobody decides in time, the engine's default applies: "
                f"{_sentence(default['summary'])}")

    async def _escalation_card(self) -> Card | None:
        needing, pending = await self._needing_owner(), await self._pending()
        if not needing:
            return None
        escalation = needing[0]  # awaiting_owner first: Claude's pick is waiting for the owner
        newest = pending[-1] if pending else None
        approves = (newest is not None and newest["kind"] == "resolve_escalation"
                    and newest["payload"] == {"escalation_id": escalation["escalation_id"],
                                              "option_id": escalation.get("chosen_option_id")})
        return escalation_card(escalation, confirm_approves_pick=approves)

    # ------------------------------------------------------------ questions (the Claude agent through the API)

    async def _ask(self, sender: str, text: str) -> Reply:
        want_forecast = _mentions(text, FORECAST_WORDS)
        await self.log("concierge", "claude", "request", f"Owner asks: {_clip(text, LOG_SUMMARY_CHARS)}")
        try:
            async with asyncio.timeout(self._timeout):
                # Open /ws first: the reply starts streaming as soon as the chat is posted.
                async with websockets.connect(self._ws_url, open_timeout=API_TIMEOUT_S) as ws:
                    r = await self._http.post("/api/chat", json={"message": self._with_history(sender, text)},
                                              timeout=API_TIMEOUT_S)
                    if r.status_code != 200:
                        await self.log("concierge", "claude", "error", f"Chat refused: {_detail(r)}")
                        return Reply(NO_ANSWER)
                    chat_id = r.json()["chat_id"]
                    reply, proposal, tick = await self._collect(ws, chat_id)
                    if want_forecast and tick is None:
                        tick = await self._next_forecast_tick(ws)
        except TimeoutError:
            await self.log("concierge", "claude", "error", "No answer in time")
            return Reply(TIMED_OUT)
        except (OSError, httpx.HTTPError, websockets.WebSocketException) as e:
            log.warning("chat hop failed: %s", type(e).__name__)
            return Reply(API_DOWN)
        await self.log("claude", "concierge", "response", f"Answered {chat_id}")
        reply = reply.strip() or NO_ANSWER
        card = None
        if proposal is not None:
            card = proposal_card(proposal)
        elif _mentions(text, ESCALATION_WORDS):
            card = await self._escalation_card()
        elif want_forecast and tick is not None:
            # STUB: the forecast tool (`forecast(120)`) has no REST route; the engine's re-plan tick carries the same
            # 2 h forecast_kw, and its new_decisions stand in for "next planned moves" (contract question).
            names = {d["device_id"]: d["name"] for d in tick["hub"]["devices"]}
            card = forecast_card(tick["forecast_kw"], tick["meter"], tick["new_decisions"], device_names=names,
                                 as_of=tick["ts"])
        return Reply.with_card(reply, card)

    async def _collect(self, ws: Any, chat_id: str) -> tuple[str, dict | None, dict | None]:
        """This chat's text until its `chat_done`, the newest Proposal still pending at that point, and the newest
        `with` re-plan tick (the one carrying `forecast_kw`) seen meanwhile."""
        parts: list[str] = []
        pending: dict[str, dict] = {}
        tick = None
        async for raw in ws:
            msg = json.loads(raw)
            kind = msg.get("type")
            if kind == "chat_delta" and msg.get("chat_id") == chat_id:
                parts.append(msg["text"])
            elif kind == "chat_done" and msg.get("chat_id") == chat_id:
                return "".join(parts), list(pending.values())[-1] if pending else None, tick
            elif kind == "proposal":
                proposal = msg["data"]
                pending.pop(proposal["proposal_id"], None)
                if proposal["status"] == "pending":
                    pending[proposal["proposal_id"]] = proposal
            elif _forecast_tick(msg):
                tick = msg["data"]
        raise ConnectionError("the viewer socket closed before chat_done")

    async def _next_forecast_tick(self, ws: Any) -> dict | None:
        """The next `with` re-plan tick, or None (clock paused or slow): the reply then goes without a forecast card."""
        try:
            async with asyncio.timeout(FORECAST_WAIT_S):
                async for raw in ws:
                    msg = json.loads(raw)
                    if _forecast_tick(msg):
                        return msg["data"]
        except TimeoutError:
            pass
        return None

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
