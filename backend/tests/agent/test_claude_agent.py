"""The Claude agent with no key (templates) and with a scripted model (the tool loop, enums, timeouts)."""

import asyncio
import json

from agent import templates
from agent.claude_agent import ClaudeAgent, create_llm

from .conftest import ScriptedLLM, load, text_turn, tool_turn


def _agent(app, llm):
    sent = []
    agent = ClaudeAgent(app.state.agent_tools, llm, publish=sent.append, timezone="America/Los_Angeles")
    return agent, sent


# ---------------------------------------------------------------- no key


def test_no_key_means_claude_is_off():
    assert create_llm("anthropic", None, None) is None
    assert create_llm("foundry", "key", None) is None  # STUB provider


def test_chat_with_no_key_streams_template_text(app, client):
    meter = load("facade/snapshot.json")["returns"]["meter"]
    with client.websocket_connect("/ws") as ws:
        resp = client.post("/api/chat", json={"message": "What will lunch cost me?"})
        assert resp.json() == {"chat_id": "chat_0001"}
        assert ws.receive_json() == {"type": "chat_delta", "chat_id": "chat_0001",
                                     "text": templates.chat_reply(meter)}
        assert ws.receive_json() == {"type": "chat_done", "chat_id": "chat_0001"}
    text = templates.chat_reply(meter)
    assert f"${meter['cost_usd_today']:.2f}" in text and text.startswith(templates.OFFLINE)


async def test_explanation_with_no_key_is_the_template(app):
    agent, _ = _agent(app, None)
    decision = load("ai_tools/explain_decision.json")["output"]
    assert await agent.explain_decision(decision, "Dishwasher 1") == (
        templates.explain_decision(decision, "Dishwasher 1"), "template")
    assert await agent.decide_escalation(load("shapes/escalation_open.json")) is None


# ---------------------------------------------------------------- with a (scripted) model


async def test_chat_answers_from_tool_results(app):
    forecast = load("ai_tools/get_forecast.json")["output"]
    llm = ScriptedLLM(tool_turn(("t1", "get_forecast", {})), text_turn(f"Peak ahead: {forecast[5]} kW."))
    agent, _ = _agent(app, llm)
    deltas = []

    async def on_text(t):
        deltas.append(t)

    assert await agent.reply("What's coming?", on_text) == ("Peak ahead: 43.9 kW.", "ai")
    assert deltas == ["Peak ahead: 43.9 kW."]
    tool_result = llm.requests[1]["messages"][-1]["content"][0]
    assert tool_result == {"type": "tool_result", "tool_use_id": "t1", "content": json.dumps(forecast)}
    offered = {t["name"] for t in llm.requests[0]["tools"]}
    assert "choose_escalation_option" not in offered and "propose_undo" in offered


async def test_chat_change_is_only_a_pending_proposal(app, set_clock):
    set_clock("2026-07-18T02:30:00Z")
    fx = load("ai_tools/propose_peak_cap_change.json")
    llm = ScriptedLLM(tool_turn(("t1", fx["tool"], fx["input"])), text_turn("Waiting for your confirmation."))
    agent, _ = _agent(app, llm)

    async def ignore(_):
        pass

    await agent.reply("Lower my cap to 38", ignore)
    proposal = app.state.proposals.latest_pending()
    assert proposal["kind"] == "peak_cap" and proposal["payload"] == {"peak_mode": "cap", "peak_cap_kw": 38.0}


async def test_bad_tool_input_is_an_error_result_not_a_crash(app):
    llm = ScriptedLLM(tool_turn(("t1", "set_crowd_effect", {"value": "huge", "reason": "x"})), text_turn("Sorry."))
    agent, _ = _agent(app, llm)

    async def ignore(_):
        pass

    await agent.reply("Big crowd tonight", ignore)
    result = llm.requests[1]["messages"][-1]["content"][0]
    assert result["is_error"] is True and "not one of" in result["content"]


async def test_streamed_chat_messages(app):
    llm = ScriptedLLM(text_turn("Hello."))
    agent, sent = _agent(app, llm)
    assert agent.start_chat("hi") == {"chat_id": "chat_0001"}
    await agent.wait_chats()
    assert sent == [{"type": "chat_delta", "chat_id": "chat_0001", "text": "Hello."},
                    {"type": "chat_done", "chat_id": "chat_0001"}]


async def test_failed_model_call_falls_back_to_template(app):
    class Broken:
        async def turn(self, **_):
            raise RuntimeError("api down")

    agent, _ = _agent(app, Broken())
    out = []

    async def on_text(t):
        out.append(t)

    text, source = await agent.reply("hi", on_text)
    assert source == "template" and out == [text] and text.startswith(templates.OFFLINE)


async def test_escalation_choice_goes_through_the_enum_tool(app):
    fx = load("ai_tools/choose_escalation_option.json")
    escalation = app.state.agent_tools.get_escalation()[0]
    llm = ScriptedLLM(tool_turn(("t1", "choose_escalation_option", fx["input"])), text_turn("Done."))
    agent, _ = _agent(app, llm)

    assert await agent.decide_escalation(escalation) == fx["output"]
    tool = next(t for t in llm.requests[0]["tools"] if t["name"] == "choose_escalation_option")
    assert tool["input_schema"]["properties"]["option_id"]["enum"] == fx["input_enum"]["option_id"]
    facts = json.loads(llm.requests[0]["messages"][0]["content"])
    assert facts["escalation"] == escalation and facts["authority"]["max_cap_overrun_kw"] == 3.0


async def test_escalation_with_an_unoffered_option_makes_no_choice(app):
    escalation = app.state.agent_tools.get_escalation()[0]
    llm = ScriptedLLM(tool_turn(("t1", "choose_escalation_option", {"option_id": "turn_off_fryer", "rationale": "x"})),
                      text_turn("Could not."))
    agent, _ = _agent(app, llm)
    assert await agent.decide_escalation(escalation) is None


async def test_slow_explanation_keeps_the_template(app, monkeypatch):
    monkeypatch.setattr("agent.claude_agent.EXPLAIN_TIMEOUT_S", 0.05)

    class Slow:
        async def turn(self, **_):
            await asyncio.sleep(1)

    agent, _ = _agent(app, Slow())
    decision = load("ai_tools/explain_decision.json")["output"]
    text, source = await agent.explain_decision(decision, "Dishwasher 1")
    assert (text, source) == (templates.explain_decision(decision, "Dishwasher 1"), "template")
