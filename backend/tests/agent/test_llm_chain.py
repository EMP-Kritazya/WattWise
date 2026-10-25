"""The provider chain Claude → ASI:One → templates (agent/llm.py), with ASI:One behind a mocked HTTP transport."""

import asyncio
import json

import httpx
import pytest

from agent import templates
from agent.claude_agent import ClaudeAgent
from agent.llm import ASI1_BASE_URL, create_asi1_llm

from .conftest import ScriptedLLM, load, text_turn


class ASI1Server:
    """Answers /chat/completions with canned OpenAI-shaped messages, in order, and records every request."""

    def __init__(self, *messages, status=200):
        self.messages = list(messages)
        self.status = status
        self.requests = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status != 200:
            return httpx.Response(self.status, json={"error": "down"})
        message = self.messages.pop(0)
        finish = "tool_calls" if message.get("tool_calls") else "stop"
        return httpx.Response(200, json={"choices": [{"index": 0, "message": message, "finish_reason": finish}]})

    def body(self, i):
        return json.loads(self.requests[i].content)

    def llm(self):
        return create_asi1_llm("test-key", None, transport=httpx.MockTransport(self))


def asi_text(text):
    return {"role": "assistant", "content": text}


def asi_tool(call_id, name, arguments):
    return {"role": "assistant", "content": None, "tool_calls": [
        {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}]}


class Slow:
    name, model = "claude", "slow"

    async def turn(self, **_):
        await asyncio.sleep(1)


class Broken:
    name, model = "claude", "broken"

    async def turn(self, **_):
        raise RuntimeError("api down")


def _agent(app, llm, fallback):
    sent = []
    agent = ClaudeAgent(app.state.agent_tools, llm, publish=sent.append, timezone="America/Los_Angeles",
                        fallback=fallback)
    return agent, sent


async def _collect(agent, message):
    out = []

    async def on_text(t):
        out.append(t)

    text, source = await agent.reply(message, on_text)
    return text, source, out


async def test_claude_timeout_then_asi1_answers_from_tool_results(app, monkeypatch, caplog):
    monkeypatch.setattr("agent.claude_agent.CHAT_TIMEOUT_S", 0.05)
    forecast = load("ai_tools/get_forecast.json")["output"]
    server = ASI1Server(asi_tool("call_1", "get_forecast", {}), asi_text(f"Peak ahead: {forecast[5]} kW."))
    agent, _ = _agent(app, Slow(), server.llm())

    with caplog.at_level("INFO", logger="agent.claude"):
        text, source, out = await _collect(agent, "What's coming?")
    assert (text, source, out) == ("Peak ahead: 36.8 kW.", "ai", ["Peak ahead: 36.8 kW."])
    assert "chat answered by asi1 (asi1)" in caplog.text

    first = server.body(0)
    assert server.requests[0].url == httpx.URL(f"{ASI1_BASE_URL}/chat/completions")
    assert server.requests[0].headers["authorization"] == "Bearer test-key"
    assert first["model"] == "asi1"
    assert first["messages"][0]["role"] == "system" and "Only state numbers that appear in tool results" in \
        first["messages"][0]["content"]
    offered = {t["function"]["name"] for t in first["tools"]}
    assert "choose_escalation_option" not in offered and "get_forecast" in offered
    # The tool result goes back unchanged, as a role "tool" message with the model's call id.
    assert server.body(1)["messages"][-2:] == [
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "call_1", "type": "function", "function": {"name": "get_forecast", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "call_1", "content": json.dumps(forecast)},
    ]


async def test_claude_error_then_asi1(app):
    server = ASI1Server(asi_text("Hello."))
    agent, _ = _agent(app, Broken(), server.llm())
    assert (await _collect(agent, "hi"))[:2] == ("Hello.", "ai")


async def test_both_down_means_template(app, monkeypatch):
    monkeypatch.setattr("agent.claude_agent.CHAT_TIMEOUT_S", 0.05)
    server = ASI1Server(status=503)
    agent, _ = _agent(app, Slow(), server.llm())
    meter = load("facade/snapshot.json")["returns"]["meter"]
    text, source, out = await _collect(agent, "hi")
    assert (text, source, out) == (templates.chat_reply(meter), "template", [templates.chat_reply(meter)])
    assert len(server.requests) == 1


async def test_partly_streamed_claude_answer_is_not_continued_by_asi1(app):
    class Cut:
        name, model = "claude", "cut"

        async def turn(self, *, on_text=None, **_):
            await on_text("Peak ahead")
            raise RuntimeError("stream dropped")

    server = ASI1Server(asi_text("never used"))
    agent, _ = _agent(app, Cut(), server.llm())
    text, source, out = await _collect(agent, "hi")
    assert (text, source) == (templates.CHAT_FAILED, "template") and out == ["Peak ahead", " " + templates.CHAT_FAILED]
    assert server.requests == []


async def test_claude_answers_first_when_it_works(app):
    server = ASI1Server(asi_text("never used"))
    agent, _ = _agent(app, ScriptedLLM(text_turn("From Claude.")), server.llm())
    assert (await _collect(agent, "hi"))[:2] == ("From Claude.", "ai")
    assert server.requests == []


async def test_tool_errors_reach_asi1_as_error_payloads(app):
    server = ASI1Server(asi_tool("c1", "set_crowd_effect", {"value": "huge", "reason": "x"}), asi_text("Sorry."))
    agent, _ = _agent(app, None, server.llm())
    await _collect(agent, "Big crowd tonight")
    tool_message = server.body(1)["messages"][-1]
    assert tool_message["role"] == "tool" and tool_message["tool_call_id"] == "c1"
    assert "not one of" in json.loads(tool_message["content"])["error"]


async def test_explanation_via_asi1_when_claude_is_off(app):
    decision = load("ai_tools/explain_decision.json")["output"]
    server = ASI1Server(asi_text(" Delayed the dishwasher to keep the peak down. "))
    agent, _ = _agent(app, None, server.llm())
    assert await agent.explain_decision(decision, "Dishwasher 1") == (
        "Delayed the dishwasher to keep the peak down.", "ai")


async def test_explanation_falls_to_template_when_both_fail(app):
    decision = load("ai_tools/explain_decision.json")["output"]
    agent, _ = _agent(app, Broken(), ASI1Server(status=500).llm())
    assert await agent.explain_decision(decision, "Dishwasher 1") == (
        templates.explain_decision(decision, "Dishwasher 1"), "template")


async def test_escalations_never_go_to_asi1(app):
    server = ASI1Server(asi_tool("c1", "choose_escalation_option",
                                 load("ai_tools/choose_escalation_option.json")["input"]))
    agent, _ = _agent(app, None, server.llm())
    assert agent.enabled is False  # runtime/escalations.py: no Claude → the engine's default
    assert await agent.decide_escalation(app.state.agent_tools.get_escalation()[0]) is None
    assert server.requests == []


def test_no_asi1_key_means_no_fallback():
    assert create_asi1_llm(None, None) is None


@pytest.fixture
def asi1_app(monkeypatch):
    """The real app with ANTHROPIC_API_KEY unset and ASI1_API_KEY set; ASI:One behind the mock transport."""
    from api import main
    from api.main import create_app
    from api.settings import Settings

    from .conftest import FIXTURES

    forecast = load("ai_tools/get_forecast.json")["output"]
    server = ASI1Server(asi_tool("call_1", "get_forecast", {}), asi_text(f"Peak ahead: {forecast[5]} kW."))
    monkeypatch.setattr(main, "create_asi1_llm", lambda key, model: create_asi1_llm(
        key, model, transport=httpx.MockTransport(server)))
    settings = Settings(kitchen_impl="fake", live_transport="ws", store="memory", hardware="off", agent_token="t",
                        fixtures_dir=FIXTURES, asi1_api_key="test-key")
    app = create_app(settings)
    app.state.runtime.hub_status = None
    return app, server


def test_chat_endpoint_answers_via_asi1_without_an_anthropic_key(asi1_app):
    from fastapi.testclient import TestClient

    app, server = asi1_app
    assert app.state.agent.enabled is False
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        assert client.post("/api/chat", json={"message": "What's coming?"}).json() == {"chat_id": "chat_0001"}
        assert ws.receive_json() == {"type": "chat_delta", "chat_id": "chat_0001", "text": "Peak ahead: 36.8 kW."}
        assert ws.receive_json() == {"type": "chat_done", "chat_id": "chat_0001"}
    assert len(server.requests) == 2
