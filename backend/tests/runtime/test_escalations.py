"""runtime/escalations.py with Claude mocked: the four `shapes/escalation_*.json` outcomes of e_0001 (open, resolved,
awaiting_owner → owner Proposal, expired_default), the 8 s timeout, the demo-mode pause, the owner's REST choice and the
one-call-in-flight queue. The whole Demo Café run (e_0001 at tick 60 → `extend_delay_dishwasher` → its Command in tick
62) is in test_scenario.py."""

import asyncio
import json

import httpx
import pytest

from agent import claude_agent
from agent.claude_agent import ClaudeAgent, Turn
from api.main import create_app
from api.settings import REPO_ROOT, Settings
from runtime import escalations as escalations_module
from runtime.live_port import LiveRows, RecordingLive

FIXTURES = REPO_ROOT / "contracts" / "fixtures"
OPENED_AT = "2026-07-18T01:30:00Z"  # tick 60
DEADLINE = "2026-07-18T01:40:00Z"  # tick 70


def load(rel):
    return json.loads((FIXTURES / rel).read_text(encoding="utf-8"))


def tick_of(sim_ts):
    """The tick_id whose clock reads `sim_ts` (1 sim min per tick from 00:30Z)."""
    return int(sim_ts[11:13]) * 60 + int(sim_ts[14:16]) - 30


class ScriptedLLM:
    def __init__(self, *turns):
        self.turns = list(turns)

    async def turn(self, **_):
        return self.turns.pop(0)


def choosing(option_id, rationale):
    use = ("t1", "choose_escalation_option", {"option_id": option_id, "rationale": rationale})
    return ScriptedLLM(Turn([{"type": "tool_use", "id": use[0], "name": use[1], "input": use[2]}], [use], "tool_use"),
                       Turn([{"type": "text", "text": "Done."}], [], "end_turn"))


class GatedAgent:
    """An enabled agent whose answer waits for `release` (records what it was asked)."""

    enabled = True

    def __init__(self):
        self.asked = []
        self.release = asyncio.Event()

    async def decide_escalation(self, escalation):
        self.asked.append(escalation["escalation_id"])
        await self.release.wait()
        return None


class Harness:
    def __init__(self, app):
        self.app = app
        self.runtime = app.state.runtime
        self.esc = self.runtime.escalations
        self.live = RecordingLive()
        self.runtime.live.use(self.live)
        self.ws = []
        self.esc._publish_ws = self.ws.append
        self.runtime.hub_status = None

    def at(self, sim_ts):
        self.runtime.tick_id = tick_of(sim_ts)
        assert self.runtime.sim_ts == sim_ts

    def use_claude(self, llm):
        self.esc.agent = ClaudeAgent(self.app.state.agent_tools, llm, publish=lambda m: None)

    async def published(self):
        await self.runtime.live.flush()
        return [json.loads(args[0]) for args in self.live.calls_to("publish_escalation")]

    def stored(self, escalation_id="e_0001"):
        return [e for e in self.app.state.store.escalations() if e["escalation_id"] == escalation_id]


def make_app(**settings):
    return create_app(Settings(kitchen_impl="fake", live_transport="ws", store="memory", hardware="off",
                               agent_token="t", fixtures_dir=FIXTURES, **settings))


@pytest.fixture
def h():
    return Harness(make_app())


@pytest.fixture
def opened():
    return load("shapes/escalation_open.json")


def rows(*escalations):
    return [LiveRows.escalation(e) for e in escalations]


# ---------------------------------------------------------------- the four outcomes


async def test_open_is_published_on_spacetime_and_ws(h, opened):
    h.at(OPENED_AT)
    h.esc.opened(opened)  # Claude off (no key): published, nothing else
    assert await h.published() == rows(opened)
    assert h.ws == [{"type": "escalation", "data": opened}]
    assert h.esc.tracked() == [opened] and h.esc.paused_reason is None


async def test_claude_inside_authority_resolves(h, opened):
    resolved = load("shapes/escalation_resolved_claude.json")
    h.use_claude(choosing(resolved["chosen_option_id"], resolved["rationale"]))
    h.at(OPENED_AT)
    h.esc.opened(opened)
    await h.esc.idle()

    assert await h.published() == rows(opened, resolved)
    assert h.ws[-1] == {"type": "escalation", "data": resolved}
    assert h.stored() == [resolved] and h.esc.tracked() == []
    assert h.app.state.store.proposals("pending") == [load("shapes/proposal_pending.json")]  # no new proposal


async def test_claude_outside_authority_awaits_the_owner_then_expires(h, opened):
    awaiting = load("shapes/escalation_awaiting_owner.json")
    store = h.app.state.store
    store.record_escalation(opened)  # forget the seeded final state: only final states are stored
    h.use_claude(choosing(awaiting["chosen_option_id"], awaiting["rationale"]))
    h.at(OPENED_AT)
    h.esc.opened(opened)
    await h.esc.idle()

    assert await h.published() == rows(opened, awaiting)
    assert h.esc.tracked() == [awaiting] and h.stored() == [opened]  # not final yet
    want = load("shapes/proposal_resolve_escalation.json")
    proposal = store.proposals("pending")[-1]
    assert {k: proposal[k] for k in ("ts", "kind", "payload", "status", "created_by", "confirmed_via", "expires_at")} \
        == {k: want[k] for k in ("ts", "kind", "payload", "status", "created_by", "confirmed_via", "expires_at")}

    # The owner never answers: at the deadline the engine's default stands.
    h.at("2026-07-18T01:39:00Z")
    h.esc.after_tick()
    assert h.esc.tracked() == [awaiting]
    h.at(DEADLINE)
    h.esc.after_tick()
    expired = load("shapes/escalation_expired_default.json")
    assert (await h.published())[-1] == LiveRows.escalation(expired)
    assert h.stored() == [expired] and h.esc.tracked() == []
    h.app.state.proposals.expire_due()
    assert store.proposal(proposal["proposal_id"])["status"] == "expired"  # the owner Proposal expires with it


async def test_claude_timeout_leaves_it_to_the_default(h, opened, monkeypatch):
    monkeypatch.setattr(claude_agent, "ESCALATION_TIMEOUT_S", 0.05)

    class Silent:
        async def turn(self, **_):
            await asyncio.sleep(10)

    h.use_claude(Silent())
    h.at(OPENED_AT)
    h.esc.opened(opened)
    await asyncio.wait_for(h.esc.idle(), 2)
    assert await h.published() == rows(opened) and h.esc.tracked() == [opened]

    h.at(DEADLINE)
    h.esc.after_tick()
    expired = load("shapes/escalation_expired_default.json")
    assert await h.published() == rows(opened, expired) and h.stored() == [expired]


async def test_no_question_to_claude_after_the_deadline(h, opened):
    agent = h.esc.agent = GatedAgent()
    h.at(DEADLINE)
    h.esc.opened(opened)
    await h.esc.idle()
    assert agent.asked == []


# ---------------------------------------------------------------- demo mode, queue, owner


async def test_demo_mode_pauses_the_clock_while_claude_decides():
    h = Harness(make_app(demo_mode=True))
    h.runtime.playing = True
    agent = h.esc.agent = GatedAgent()
    h.at(OPENED_AT)
    h.esc.opened(load("shapes/escalation_open.json"))
    await asyncio.sleep(0.01)
    assert agent.asked == ["e_0001"]
    assert h.runtime.paused_reason == "escalation" and h.runtime.clock_state()["paused_reason"] == "escalation"
    assert not h.runtime._runnable()

    agent.release.set()
    await h.esc.idle()
    assert h.runtime.paused_reason is None
    await h.runtime.live.flush()
    clocks = h.live.calls_to("set_clock")
    assert [c[4] for c in clocks[-2:]] == ["escalation", None]  # paused, then resumed (paused_reason argument)


async def test_outside_demo_mode_the_clock_runs_on(h, opened):
    agent = h.esc.agent = GatedAgent()
    h.at(OPENED_AT)
    h.esc.opened(opened)
    await asyncio.sleep(0.01)
    assert agent.asked == ["e_0001"] and h.runtime.paused_reason is None
    agent.release.set()
    await h.esc.idle()


async def test_one_call_in_flight_and_at_most_three_waiting(h, opened):
    agent = h.esc.agent = GatedAgent()
    h.at(OPENED_AT)
    ids = [f"e_000{n}" for n in range(1, 6)]
    for escalation_id in ids:
        h.esc.opened({**opened, "escalation_id": escalation_id})
        await asyncio.sleep(0)
    assert agent.asked == ["e_0001"]  # one call in flight; e_0002 dropped (queue of 3)
    agent.release.set()
    await h.esc.idle()
    assert agent.asked == ["e_0001", "e_0003", "e_0004", "e_0005"]
    assert escalations_module.MAX_WAITING == 3


async def test_owner_resolves_through_rest(h, opened):
    h.at(OPENED_AT)
    h.esc.opened(opened)
    transport = httpx.ASGITransport(app=h.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        resp = await http.post("/api/escalations/e_0001/resolve", json={"option_id": "deep_reduce_hvac"})
    assert resp.status_code == 200
    chosen = resp.json()
    assert (chosen["status"], chosen["resolved_by"], chosen["chosen_option_id"], chosen["rationale"]) == \
        ("resolved", "owner", "deep_reduce_hvac", None)
    await asyncio.sleep(0)
    [stored] = h.stored()
    assert {k: stored[k] for k in chosen} == chosen  # the response is the engine's escalation (through the model)
    assert await h.published() == rows(opened, stored)
    assert h.ws[-1] == {"type": "escalation", "data": stored} and h.esc.tracked() == []


async def test_owner_rest_unknown_escalation_is_404(h):
    transport = httpx.ASGITransport(app=h.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        resp = await http.post("/api/escalations/e_9999/resolve", json={"option_id": "accept_overrun"})
    assert resp.status_code == 404


async def test_confirmed_proposal_is_published(h, opened):
    """Claude's outside-authority pick, confirmed by the owner in the UI: resolved by the owner, published, stored."""
    awaiting = load("shapes/escalation_awaiting_owner.json")
    h.use_claude(choosing(awaiting["chosen_option_id"], awaiting["rationale"]))
    h.at(OPENED_AT)
    h.esc.opened(opened)
    await h.esc.idle()
    proposal = h.app.state.store.proposals("pending")[-1]
    confirmed = h.app.state.proposals.confirm(proposal["proposal_id"], True, via="ui")
    assert confirmed["status"] == "confirmed"
    final = (await h.published())[-1]
    assert (final["status"], final["resolved_by"], final["chosen_option_id"]) == ("resolved", "owner", "deep_reduce_hvac")
    assert h.esc.tracked() == []
