"""Contract behavior for the non-blocking escalation runtime.

The fixture escalation predates the current ``updated_ts`` / ``active_option_id``
fields, so these tests add those engine-owned fields in memory rather than
editing the shared fixture.
"""

import asyncio
import copy
import json
from types import SimpleNamespace

import pytest

from api.settings import REPO_ROOT
from live.rows import escalation_row
from runtime.escalations import Escalations
from runtime.live_port import LivePublisher, RecordingLive

def ws_escalation(state):
    row = escalation_row(state)
    return {"type": "escalation", "data": state, "explanation": row["explanation"],
            "explanation_source": row["explanation_source"]}


FIXTURES = REPO_ROOT / "contracts" / "fixtures"
AUTHORITY = {
    "enabled": True,
    "max_cap_overrun_kw": 3.0,
    "max_extra_delay_min": 20,
    "max_extra_reduce_min": 15,
    "may_go_below_min_power": False,
}


def fixture_escalation(**changes):
    """Current-contract state based on the immutable recorded escalation."""
    state = json.loads((FIXTURES / "shapes" / "escalation_open.json").read_text(encoding="utf-8"))
    state.update({"updated_ts": state["ts"], "active_option_id": state["default_option_id"]})
    state.update(changes)
    return state


class MemoryStore:
    def __init__(self):
        self.rows = []

    def record_escalation(self, escalation):
        for index, existing in enumerate(self.rows):
            if existing["escalation_id"] == escalation["escalation_id"]:
                self.rows[index] = copy.deepcopy(escalation)
                return
        self.rows.append(copy.deepcopy(escalation))


class Service:
    """The narrow facade used by runtime/escalations.py, with no Proposal API."""

    def __init__(self, authority=AUTHORITY):
        self.lanes = SimpleNamespace(config={"authority": copy.deepcopy(authority)})
        self.store = MemoryStore()
        self.current = {}
        self.resolve_calls = []
        self.on_escalation = None

    def resolve_escalation(self, escalation_id, body, resolved_by, rationale):
        self.resolve_calls.append((escalation_id, copy.deepcopy(body), resolved_by, rationale))
        current = self.current[escalation_id]
        resolved = {
            **copy.deepcopy(current),
            "status": "resolved",
            "resolved_by": resolved_by,
            "chosen_option_id": body["option_id"],
            "rationale": rationale,
        }
        self.current[escalation_id] = resolved
        if self.on_escalation is not None:
            self.on_escalation(resolved)
        return resolved


class CaptureAgent:
    enabled = True

    def __init__(self):
        self.asked = []

    async def decide_escalation(self, escalation, council=None):
        self.asked.append((copy.deepcopy(escalation), list(council or [])))
        return None


class BlockingAgent(CaptureAgent):
    def __init__(self):
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def decide_escalation(self, escalation, council=None):
        self.asked.append((copy.deepcopy(escalation), list(council or [])))
        self.started.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        return None


class Harness:
    def __init__(self, *, authority=AUTHORITY, council_wait_s=0.0):
        self.service = Service(authority)
        self.port = RecordingLive()
        self.live = LivePublisher(self.port)
        self.ws = []

        def clock_must_not_be_read():
            raise AssertionError("escalation runtime must not read the simulation clock")

        self.escalations = Escalations(
            service=self.service,
            live=self.live,
            clock=clock_must_not_be_read,
            publish_ws=self.ws.append,
            council_wait_s=council_wait_s,
        )
        self.service.on_escalation = self.escalations.changed

    def open(self, escalation):
        self.service.current[escalation["escalation_id"]] = copy.deepcopy(escalation)
        self.escalations.opened(escalation)

    async def close(self):
        await self.escalations.stop()
        await self.live.stop()


async def wait_until(predicate):
    for _ in range(50):
        if predicate():
            return
        await asyncio.sleep(0)
    assert predicate()


async def test_fallback_is_already_active_before_claude_runs_and_runtime_never_applies_it():
    h = Harness()
    try:
        agent = h.escalations.agent = CaptureAgent()
        opened = fixture_escalation(default_option_id="extend_delay_dishwasher",
                                    active_option_id="extend_delay_dishwasher")
        h.open(opened)
        await h.escalations.idle()

        [(asked, council)] = agent.asked
        assert asked["active_option_id"] == "extend_delay_dishwasher"
        assert asked["default_option_id"] == "extend_delay_dishwasher"
        assert council == []
        assert h.service.resolve_calls == []
        assert h.escalations.tracked() == [opened]
    finally:
        await h.close()


async def test_updated_engine_state_is_republished_and_claude_is_asked_once_per_id():
    h = Harness()
    try:
        agent = h.escalations.agent = BlockingAgent()
        opened = fixture_escalation()
        h.open(opened)
        await asyncio.wait_for(agent.started.wait(), 1)

        updated = fixture_escalation(
            updated_ts="2026-07-18T01:35:00Z",
            problem={**opened["problem"], "reason": "later engine forecast"},
        )
        h.open(updated)
        await asyncio.sleep(0)

        assert len(agent.asked) == 1
        assert h.escalations.tracked() == [updated]
        assert h.ws == [
            ws_escalation(opened),
            ws_escalation(updated),
        ]
        await h.live.flush()
        assert len(h.port.calls_to("publish_escalation")) == 2

        agent.release.set()
        await h.escalations.idle()
        assert len(agent.asked) == 1
    finally:
        await h.close()


@pytest.mark.parametrize(
    ("authority", "options"),
    [
        ({**AUTHORITY, "enabled": False}, None),
        (AUTHORITY, [{"option_id": "ask_owner", "within_authority": True},
                     {"option_id": "deep_reduce_hvac", "within_authority": False}]),
    ],
    ids=("authority_disabled", "no_eligible_option"),
)
async def test_claude_is_not_called_without_an_authorized_choice(authority, options):
    h = Harness(authority=authority)
    try:
        agent = h.escalations.agent = CaptureAgent()
        changes = {} if options is None else {"options": options}
        opened = fixture_escalation(**changes)
        h.open(opened)
        await asyncio.sleep(0)

        assert agent.asked == []
        assert h.escalations.tracked() == [opened]
        assert h.service.resolve_calls == []
        assert h.ws == [ws_escalation(opened)]
    finally:
        await h.close()


async def test_obsolete_from_the_engine_cancels_pending_claude_without_reversing_commands():
    h = Harness(council_wait_s=10)
    try:
        agent = h.escalations.agent = BlockingAgent()
        opened = fixture_escalation()
        h.open(opened)
        # This task is waiting for council; it has not called Claude yet.
        await asyncio.sleep(0)
        assert agent.asked == []

        obsolete = fixture_escalation(
            status="obsolete",
            updated_ts="2026-07-18T01:35:00Z",
            resolved_by=None,
            chosen_option_id=None,
            rationale=None,
        )
        h.open(obsolete)
        await h.escalations.idle()

        assert h.escalations.tracked() == []
        assert h.service.resolve_calls == []
        assert h.service.store.rows == [obsolete]
        assert h.ws[-1] == ws_escalation(obsolete)
        assert agent.asked == []
    finally:
        await h.close()


@pytest.mark.parametrize("status", ("resolved", "expired_default", "obsolete"))
async def test_every_terminal_engine_state_cancels_an_in_flight_claude_call(status):
    h = Harness()
    try:
        agent = h.escalations.agent = BlockingAgent()
        opened = fixture_escalation()
        h.open(opened)
        await asyncio.wait_for(agent.started.wait(), 1)

        terminal = fixture_escalation(status=status, updated_ts="2026-07-18T01:35:00Z")
        h.open(terminal)
        await asyncio.wait_for(agent.cancelled.wait(), 1)
        await h.escalations.idle()

        assert h.service.resolve_calls == []
        assert h.escalations.tracked() == []
    finally:
        await h.close()


async def test_awaiting_owner_is_logged_and_never_creates_a_proposal(caplog):
    h = Harness()
    try:
        agent = h.escalations.agent = CaptureAgent()
        awaiting = fixture_escalation(
            status="awaiting_owner",
            chosen_option_id="deep_reduce_hvac",
            resolved_by="claude",
            rationale="legacy engine state",
        )
        h.open(awaiting)
        await asyncio.sleep(0)

        assert h.escalations.tracked() == [awaiting]
        assert agent.asked == []
        assert h.service.resolve_calls == []
        assert "creating no Proposal" in caplog.text
    finally:
        await h.close()


async def test_runtime_has_no_owner_escalation_resolution_hook():
    h = Harness()
    try:
        assert not hasattr(h.escalations, "resolve_by_owner")
        assert h.service.resolve_calls == []
    finally:
        await h.close()


async def test_after_tick_does_not_synthesize_an_engine_expiry():
    h = Harness()
    try:
        opened = fixture_escalation()
        h.open(opened)
        h.escalations.after_tick()

        assert h.escalations.tracked() == [opened]
        assert h.service.store.rows == []
        assert h.service.resolve_calls == []
    finally:
        await h.close()
