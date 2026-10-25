"""Escalations: Claude resolves the engine's escalations, inside the owner's authority (API.md "Escalations",
ARCHITECTURE.md flow 3 + "Claude at 120×").

1. The run loop hands every new open escalation to `opened()`: it is published (`publish_escalation`, plus an
   `escalation` message on `/ws` when the live transport is not `/ws` already) and queued for Claude.
2. The council (agents/council.py): the Concierge asks Weather, Grid and Events about the escalation's window and posts
   the replies to `POST /api/context`. Before calling Claude this task waits up to COUNCIL_WAIT_S real s for a context
   post that arrived after the escalation opened (counted by post, not by `ts`: in demo mode the paused clock stamps the
   same sim minute). Claude then gets the freshest context and the parts posted since (`council`). Only this task waits;
   the tick never does, and the 8 s Claude timeout and the engine's default at the deadline still hold.
3. One Claude call at a time (`ClaudeAgent.decide_escalation`: options with engine numbers, context, preferences and
   authority; `choose_escalation_option` enum-constrained to the offered ids; 8 real s timeout). The tool calls
   `resolve_escalation(..., "claude", rationale)`; outside the authority the engine answers `awaiting_owner` and the tool
   makes the owner Proposal. No choice (Claude off, timeout, error) → nothing is done: the engine applies its default at
   the deadline. More than MAX_WAITING queued → the oldest is left to that default.
4. Every resolve (Claude's tool, the owner's `POST /api/escalations/{id}/resolve`, a confirmed proposal) reaches
   `changed()` through the service, from any thread, and is published. The service stores final states.
5. `after_tick()`: an escalation still open or awaiting the owner at its deadline has expired to the engine's default;
   its final state is stored and published.
6. `DEMO_MODE=1`: the clock pauses (`paused_reason: "escalation"`) while the council and Claude decide, and resumes after.
The tick never waits on any of this. The clock slowdown (`ESCALATION_SPEED`) is not built: open question Q1.
"""

from __future__ import annotations

import asyncio
import copy
import logging
from collections import deque
from typing import Any, Callable

from agent.templates import explain_escalation
from runtime.live_port import LivePublisher, WsLive

MAX_WAITING = 3  # escalations queued for Claude; older ones keep the engine's default
WAITING_STATUSES = ("open", "awaiting_owner")
FINAL_STATUSES = ("resolved", "expired_default")
COUNCIL_PARTS = ("weather", "prices", "events")  # Context parts the council agents answer with
MAX_CONTEXT_POSTS = 50  # recent posts remembered to tell Claude which parts came after an escalation opened

log = logging.getLogger("runtime.escalations")


class Escalations:
    def __init__(self, *, service: Any, live: LivePublisher, clock: Callable[[], str],
                 on_pause: Callable[[], None], publish_ws: Callable[[dict], None] | None = None,
                 demo_mode: bool = False, council_wait_s: float = 0.0):
        self._service = service  # api.service.KitchenService
        self._live = live
        self._clock = clock  # current sim time (RunLoop.sim_ts)
        self._on_pause = on_pause  # the pause changed: publish the clock, wake the loop
        self._publish_ws = publish_ws  # one /ws message (Broadcaster.send_soon)
        self.demo_mode = demo_mode
        self.council_wait_s = council_wait_s  # real s to wait for the council's context before calling Claude
        self.agent: Any = None  # agent.claude_agent.ClaudeAgent; None or disabled = Claude off
        self._tracked: dict[str, dict] = {}  # escalation_id → latest state, while open / awaiting_owner
        self._waiting: deque[dict] = deque()
        self._deciding: str | None = None
        self._worker: asyncio.Task | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._context_seq = 0  # POST /api/context count
        self._context_posts: deque[tuple[int, list[str]]] = deque(maxlen=MAX_CONTEXT_POSTS)  # (seq, parts posted)
        self._context_changed: asyncio.Event | None = None
        self._opened_seq: dict[str, int] = {}  # escalation_id → context posts seen when it opened

    @property
    def paused_reason(self) -> str | None:
        return "escalation" if self.demo_mode and self._deciding is not None else None

    def tracked(self) -> list[dict]:
        return [copy.deepcopy(e) for e in self._tracked.values()]

    # ------------------------------------------------------------ engine → runtime

    def opened(self, escalation: dict) -> None:
        """A TickState's new escalation (event loop). Published at once; Claude decides in the background."""
        self._bind_loop()
        if escalation["status"] in WAITING_STATUSES:
            self._tracked[escalation["escalation_id"]] = copy.deepcopy(escalation)
        self._publish(escalation)
        if escalation["status"] != "open":
            return
        self._opened_seq[escalation["escalation_id"]] = self._context_seq
        if self.agent is None or not self.agent.enabled:
            log.info("Claude is off; %s waits for the owner or the engine's default at %s",
                     escalation["escalation_id"], escalation["deadline_sim_ts"])
            return
        self._waiting.append(copy.deepcopy(escalation))
        while len(self._waiting) > MAX_WAITING:
            dropped = self._waiting.popleft()
            log.warning("escalation queue full; %s is left to the engine's default", dropped["escalation_id"])
        if self._worker is None or self._worker.done():
            self._worker = asyncio.get_running_loop().create_task(self._work(), name="escalations")

    def changed(self, escalation: dict) -> None:
        """The service resolved an escalation (Claude, owner or a confirmed proposal). Any thread."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:  # a worker thread (REST threadpool, agent tool)
            if self._loop is None or self._loop.is_closed():
                log.warning("no event loop; %s is not published", escalation["escalation_id"])
                return
            self._loop.call_soon_threadsafe(self._changed, copy.deepcopy(escalation))
            return
        self._changed(copy.deepcopy(escalation))

    def context_posted(self, parts: list[str]) -> None:
        """`POST /api/context` was merged (event loop): wake an escalation waiting for its council."""
        self._context_seq += 1
        self._context_posts.append((self._context_seq, list(parts)))
        if self._context_changed is not None:
            self._context_changed.set()

    def after_tick(self) -> None:
        """Past its deadline the engine has applied its default: store and publish the final state."""
        now = self._clock()
        for escalation in [e for e in self._tracked.values() if e["deadline_sim_ts"] <= now]:
            try:
                final = self._service.expire_escalation(escalation)
            except Exception:
                log.exception("expiring %s failed", escalation["escalation_id"])
                continue
            self._changed(final)

    # ------------------------------------------------------------ owner

    async def resolve_by_owner(self, escalation_id: str, option_id: str) -> dict:
        """`POST /api/escalations/{id}/resolve`: the owner may pick any generated option."""
        self._bind_loop()
        return await asyncio.to_thread(self._service.resolve_escalation, escalation_id, {"option_id": option_id},
                                       "owner", None)

    # ------------------------------------------------------------ Claude

    async def _work(self) -> None:
        while self._waiting:
            escalation = self._waiting.popleft()
            if self._still_open(escalation["escalation_id"]):
                await self._decide(escalation)

    def _still_open(self, escalation_id: str) -> bool:
        current = self._tracked.get(escalation_id)
        return current is not None and current["status"] == "open" and self._clock() < current["deadline_sim_ts"]

    async def _await_council(self, escalation_id: str) -> list[str]:
        """Wait up to `council_wait_s` for a context post after the escalation opened; the council parts posted since."""
        since = self._opened_seq.pop(escalation_id, self._context_seq)
        loop = asyncio.get_running_loop()
        give_up = loop.time() + self.council_wait_s
        while self._context_seq <= since and (remaining := give_up - loop.time()) > 0:
            self._context_changed = asyncio.Event()
            try:
                await asyncio.wait_for(self._context_changed.wait(), remaining)
            except asyncio.TimeoutError:
                break
            finally:
                self._context_changed = None
        posted = {part for seq, parts in self._context_posts if seq > since for part in parts}
        if not posted:
            log.info("no council context for %s; Claude decides on the last known", escalation_id)
        return [part for part in COUNCIL_PARTS if part in posted]

    async def _decide(self, escalation: dict) -> None:
        escalation_id = escalation["escalation_id"]
        self._set_deciding(escalation_id)
        try:
            council = await self._await_council(escalation_id)
            if not self._still_open(escalation_id):  # the owner chose, or the deadline passed, while the council met
                return
            chosen = await self.agent.decide_escalation(escalation, council=council)
        except Exception:
            log.exception("Claude failed on %s", escalation["escalation_id"])
            chosen = None
        finally:
            self._set_deciding(None)
        if chosen is None:
            log.info("no choice for %s; the engine's default applies at %s", escalation["escalation_id"],
                     escalation["deadline_sim_ts"])

    def _set_deciding(self, escalation_id: str | None) -> None:
        before = self.paused_reason
        self._deciding = escalation_id
        if self.paused_reason != before:
            self._on_pause()

    async def idle(self) -> None:
        """Wait until Claude has answered every queued escalation (tests)."""
        while self._worker is not None and not self._worker.done():
            await asyncio.shield(self._worker)
        await asyncio.sleep(0)  # resolves reported from the tool's thread run next

    # ------------------------------------------------------------ state + publish

    def _changed(self, escalation: dict) -> None:
        escalation_id, status = escalation["escalation_id"], escalation["status"]
        if status in WAITING_STATUSES:
            self._tracked[escalation_id] = escalation
        else:
            self._tracked.pop(escalation_id, None)
        if status in FINAL_STATUSES or status == "awaiting_owner":
            option = next((o for o in escalation["options"] if o["option_id"] == escalation["chosen_option_id"]), None)
            log.info("%s %s: %s", escalation_id, status,
                     escalation.get("rationale") or explain_escalation(escalation, option))
        self._publish(escalation)

    def _publish(self, escalation: dict) -> None:
        self._live.send("publish_escalation", copy.deepcopy(escalation))
        # Escalations are also /ws messages whatever the live transport (CONTRACTS.md §2); WsLive has sent it already.
        if self._publish_ws is not None and not isinstance(self._live.port, WsLive):
            self._publish_ws({"type": "escalation", "data": copy.deepcopy(escalation)})

    def _bind_loop(self) -> None:
        self._loop = asyncio.get_running_loop()

    def reset(self) -> None:
        """New kitchen: forget every escalation; a Claude call in flight is cancelled."""
        if self._worker is not None:
            self._worker.cancel()
            self._worker = None
        self._waiting.clear()
        self._tracked = {}
        self._opened_seq = {}
        self._set_deciding(None)

    async def stop(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            try:
                await self._worker
            except (asyncio.CancelledError, Exception):
                pass
            self._worker = None
