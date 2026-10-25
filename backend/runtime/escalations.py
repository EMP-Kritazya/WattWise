"""Asynchronous handling for engine-owned escalations.

The engine applies an escalation fallback in the same ``step`` that opens it and
emits the full escalation again whenever it changes. This module only mirrors
that state to the live transport and, once per escalation id, asks Claude to
choose one already-evaluated option. It never changes the clock, applies a
fallback, or manufactures an expiry transition.

Council context may wait for ``COUNCIL_WAIT_S`` real seconds, but that wait is
contained in the escalation task. A simulation tick only calls :meth:`opened`
and continues immediately.
"""

from __future__ import annotations

import asyncio
import copy
import logging
from collections import deque
from typing import Any, Callable

from runtime.live_port import LivePublisher, WsLive

ACTIVE_STATUSES = ("open", "awaiting_owner")
TERMINAL_STATUSES = ("resolved", "expired_default", "obsolete")
COUNCIL_PARTS = ("weather", "prices", "events")
MAX_CONTEXT_POSTS = 50

log = logging.getLogger("runtime.escalations")


class Escalations:
    """Mirror engine escalations and run at most one Claude task per id."""

    def __init__(self, *, service: Any, live: LivePublisher, clock: Callable[[], str],
                 publish_ws: Callable[[dict], None] | None = None, council_wait_s: float = 0.0):
        self._service = service
        self._live = live
        # Kept in the constructor for the RunLoop seam. Escalation handling does
        # not read sim time: the engine owns deadlines and terminal transitions.
        del clock
        self._publish_ws = publish_ws
        self.council_wait_s = council_wait_s
        self.agent: Any = None

        self._tracked: dict[str, dict] = {}
        self._seen_active: set[str] = set()
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

        self._context_seq = 0
        self._context_posts: deque[tuple[int, list[str]]] = deque(maxlen=MAX_CONTEXT_POSTS)
        self._context_event: asyncio.Event | None = None
        self._opened_seq: dict[str, int] = {}

    def tracked(self) -> list[dict]:
        return [copy.deepcopy(escalation) for escalation in self._tracked.values()]

    # ------------------------------------------------------------ engine -> runtime

    def opened(self, escalation: dict) -> None:
        """Accept one ``TickState.new_escalations`` item.

        ``new_escalations`` contains an open state *and* later updates to that
        same id. Every item is therefore an upsert/publish event; only its
        first active appearance is eligible to start Claude work.
        """
        self._bind_loop()
        self._observe(copy.deepcopy(escalation), ask_if_first_active=True)

    def changed(self, escalation: dict) -> None:
        """Accept an owner/Claude resolution from the service, from any thread."""
        state = copy.deepcopy(escalation)
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            if self._loop is None or self._loop.is_closed():
                log.warning("no event loop; %s was not published", state.get("escalation_id"))
                return
            self._loop.call_soon_threadsafe(self._observe, state, False)
            return
        self._observe(state, False)

    def after_tick(self) -> None:
        """Compatibility hook for ``RunLoop``.

        The engine emits ``expired_default`` and ``obsolete`` in
        ``new_escalations``. The runtime must not synthesize either state or
        invoke a facade method to do so.
        """

    def context_posted(self, parts: list[str]) -> None:
        """Wake council waits after ``POST /api/context`` merges a fresh part."""
        self._context_seq += 1
        self._context_posts.append((self._context_seq, list(parts)))
        if self._context_event is not None:
            self._context_event.set()

    # ------------------------------------------------------------ Claude

    def _observe(self, escalation: dict, ask_if_first_active: bool) -> None:
        escalation_id = escalation["escalation_id"]
        status = escalation["status"]

        if status in ACTIVE_STATUSES:
            self._tracked[escalation_id] = escalation
        else:
            self._tracked.pop(escalation_id, None)

        if status in TERMINAL_STATUSES:
            self._cancel_task(escalation_id)
            self._record_terminal(escalation)
        elif status == "awaiting_owner":
            # This should be impossible under the authority-filtered tool enum.
            # Preserve the engine's active fallback and leave an explicit owner
            # override route available, but never create an escalation Proposal.
            log.warning("%s returned awaiting_owner; keeping the engine fallback and creating no Proposal", escalation_id)
        elif status not in ACTIVE_STATUSES:
            log.warning("%s has unknown escalation status %r", escalation_id, status)

        self._publish(escalation)

        if not ask_if_first_active or status not in ACTIVE_STATUSES:
            return
        if escalation_id in self._seen_active:
            return
        self._seen_active.add(escalation_id)

        if status != "open":
            # An unexpected legacy state is not a new request to Claude.
            return
        if not self._can_ask_claude(escalation):
            return
        self._opened_seq[escalation_id] = self._context_seq
        self._start_task(escalation_id)

    def _can_ask_claude(self, escalation: dict) -> bool:
        authority = self._authority()
        if not authority or not authority.get("enabled", False):
            log.info("Claude is not authorized for %s; the engine fallback remains active", escalation["escalation_id"])
            return False
        if not self._eligible_option_ids(escalation):
            log.info("%s has no authority-eligible option for Claude; the engine fallback remains active",
                     escalation["escalation_id"])
            return False
        if self.agent is None or not getattr(self.agent, "enabled", False):
            log.info("Claude is off for %s; the engine fallback remains active", escalation["escalation_id"])
            return False
        return True

    def _authority(self) -> dict | None:
        """Read the owner authority from the current engine snapshot.

        ``set_authority`` changes only the with-lane facade state.  The
        build-time ``Lanes.config`` is intentionally retained for clock
        configuration, but is not authoritative for a later escalation.
        """
        try:
            get_kitchen = getattr(self._service, "get_kitchen", None)
            if callable(get_kitchen):
                config = get_kitchen()["config"]
            else:  # Narrow test doubles expose only the lanes' initial config.
                config = getattr(getattr(self._service, "lanes", None), "config", None)
        except Exception:
            log.exception("could not read Claude authority; leaving the engine fallback active")
            return None
        authority = config.get("authority") if isinstance(config, dict) else None
        return authority if isinstance(authority, dict) else None

    @staticmethod
    def _eligible_option_ids(escalation: dict) -> tuple[str, ...]:
        return tuple(
            option["option_id"]
            for option in escalation.get("options", ())
            if option.get("option_id") != "ask_owner" and option.get("within_authority") is True
        )

    def _start_task(self, escalation_id: str) -> None:
        task = asyncio.get_running_loop().create_task(self._decide(escalation_id), name=f"escalation:{escalation_id}")
        self._tasks[escalation_id] = task

        def forget(done: asyncio.Task[None], *, key: str = escalation_id) -> None:
            if self._tasks.get(key) is done:
                self._tasks.pop(key, None)
            self._opened_seq.pop(key, None)

        task.add_done_callback(forget)

    def _cancel_task(self, escalation_id: str) -> None:
        task = self._tasks.pop(escalation_id, None)
        self._opened_seq.pop(escalation_id, None)
        if task is not None and not task.done():
            task.cancel()

    async def _decide(self, escalation_id: str) -> None:
        try:
            council = await self._await_council(escalation_id)
            current = self._tracked.get(escalation_id)
            if current is None or current.get("status") != "open":
                return
            # A later engine update can change authority markings/options while
            # the council waits. Do not let a stale invitation reach Claude.
            if not self._can_ask_claude(current):
                return
            await self.agent.decide_escalation(copy.deepcopy(current), council=council)
        except asyncio.CancelledError:
            log.info("Claude task for %s cancelled after the engine closed it", escalation_id)
            raise
        except Exception:
            log.exception("Claude failed on %s; the engine fallback remains active", escalation_id)

    async def _await_council(self, escalation_id: str) -> list[str]:
        """Wait only inside this background task for fresh council context."""
        since = self._opened_seq.get(escalation_id, self._context_seq)
        if self.council_wait_s > 0:
            loop = asyncio.get_running_loop()
            deadline = loop.time() + self.council_wait_s
            while self._context_seq <= since:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    break
                event = self._context_event
                if event is None:  # ``opened`` creates it; retain this for defensive callers.
                    event = self._context_event = asyncio.Event()
                event.clear()
                if self._context_seq > since:
                    break
                try:
                    await asyncio.wait_for(event.wait(), remaining)
                except asyncio.TimeoutError:
                    break
        posted = {part for seq, parts in self._context_posts if seq > since for part in parts}
        if not posted:
            log.info("no fresh council context for %s; Claude uses the latest known context", escalation_id)
        return [part for part in COUNCIL_PARTS if part in posted]

    async def idle(self) -> None:
        """Wait for currently scheduled Claude work (tests and controlled shutdown)."""
        while self._tasks:
            tasks = list(self._tasks.values())
            await asyncio.gather(*(asyncio.shield(task) for task in tasks), return_exceptions=True)
            await asyncio.sleep(0)

    # ------------------------------------------------------------ state + publish

    def _record_terminal(self, escalation: dict) -> None:
        """Persist engine-emitted final states; the store upserts by escalation id."""
        try:
            self._service.store.record_escalation(copy.deepcopy(escalation))
        except Exception:
            log.exception("could not persist terminal escalation %s", escalation["escalation_id"])

    def _publish(self, escalation: dict) -> None:
        self._live.send("publish_escalation", copy.deepcopy(escalation))
        # WsLive already broadcasts this call. A second broadcaster is needed
        # only when the live transport is SpacetimeDB.
        if self._publish_ws is not None and not isinstance(self._live.port, WsLive):
            from live.rows import escalation_row
            row = escalation_row(escalation)
            self._publish_ws({"type": "escalation", "data": copy.deepcopy(escalation),
                              "explanation": row["explanation"], "explanation_source": row["explanation_source"]})

    def _bind_loop(self) -> None:
        self._loop = asyncio.get_running_loop()
        if self._context_event is None:
            self._context_event = asyncio.Event()

    def reset(self) -> None:
        """Forget a previous kitchen and cancel all of its background work."""
        for task in list(self._tasks.values()):
            task.cancel()
        self._tasks.clear()
        self._tracked.clear()
        self._seen_active.clear()
        self._opened_seq.clear()
        self._context_posts.clear()
        self._context_seq = 0

    async def stop(self) -> None:
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
