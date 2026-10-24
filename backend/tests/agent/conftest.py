import json

import pytest
from fastapi.testclient import TestClient

from agent.claude_agent import Turn
from api.main import create_app
from api.settings import REPO_ROOT, Settings

FIXTURES = REPO_ROOT / "contracts" / "fixtures"
SIM_START_TS = "2026-07-18T00:30:00Z"  # tick 0 of the Demo Café scenario


def load(rel):
    return json.loads((FIXTURES / rel).read_text(encoding="utf-8"))


def ticks_until(sim_ts):
    """The tick_id whose clock reads `sim_ts` (1 sim min per tick from 00:30Z)."""
    hours, minutes = int(sim_ts[11:13]), int(sim_ts[14:16])
    return (hours * 60 + minutes) - 30


@pytest.fixture
def app():
    # No ANTHROPIC_API_KEY: Claude is off, as in CI.
    settings = Settings(kitchen_impl="fake", live_transport="ws", store="memory", hardware="off",
                        agent_token="t", fixtures_dir=FIXTURES)
    app = create_app(settings)
    app.state.runtime.hub_status = None
    return app


@pytest.fixture
def set_clock(app):
    def _set(sim_ts):
        app.state.runtime.tick_id = ticks_until(sim_ts)
        assert app.state.runtime.sim_ts == sim_ts
    return _set


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


FACADE_WRITES = ("set_importance", "set_peak_cap", "set_authority", "undo", "resolve_escalation")


@pytest.fixture
def facade_calls(app, monkeypatch):
    """Record every write call on the `with` lane's kitchen and answer it with the real FakeKitchen result."""
    kitchen = app.state.service.lanes["with"]
    calls = []
    for name in FACADE_WRITES:
        real = getattr(kitchen, name)

        def recorder(*args, _name=name, _real=real):
            calls.append((_name, args))
            try:
                return _real(*args)
            except LookupError:  # NotRecordedError: no canned answer for these args; the call itself is what matters
                return {"proposal_test": True}

        monkeypatch.setattr(kitchen, name, recorder)
    return calls


class ScriptedLLM:
    """Stands in for AnthropicLLM: plays back Turns in order and records every request."""

    def __init__(self, *turns):
        self.turns = list(turns)
        self.requests = []

    async def turn(self, *, system, messages, tools, effort, on_text=None):
        self.requests.append({"system": system, "messages": [dict(m) for m in messages], "tools": tools,
                              "effort": effort})
        turn = self.turns.pop(0)
        if on_text is not None and turn.text:
            await on_text(turn.text)
        return turn


def text_turn(text):
    return Turn([{"type": "text", "text": text}], [], "end_turn")


def tool_turn(*uses):
    content = [{"type": "tool_use", "id": i, "name": n, "input": inp} for i, n, inp in uses]
    return Turn(content, list(uses), "tool_use")
