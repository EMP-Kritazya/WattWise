"""Every owner flow of AGENTS.md through the Concierge's chat code (`agents/owner_chat.py`) against the real API.

The app runs on a local port (uvicorn in a thread) with Claude scripted; the Concierge side talks HTTP + `/ws` to it
exactly as in production. Confirm / cancel never reach the model: they are matched by code and confirm the newest
pending Proposal with `confirmed_via: "asi_one"`.
"""

import asyncio
import importlib.util
import json
import sys
import threading
import time

import httpx
import pytest
import uvicorn

from agent.claude_agent import ClaudeAgent
from api.settings import REPO_ROOT

from .conftest import ScriptedLLM, load, text_turn, tool_turn

if str(REPO_ROOT / "agents") not in sys.path:  # owner_chat imports its sibling cards.py by name, as agents/ scripts do
    sys.path.insert(0, str(REPO_ROOT / "agents"))
_spec = importlib.util.spec_from_file_location("owner_chat", REPO_ROOT / "agents" / "owner_chat.py")
owner_chat = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(owner_chat)

OWNER = "agent1qowner"
TOKEN = "t"  # the agent conftest's agent_token


def use_llm(app, llm):
    app.state.agent = ClaudeAgent(app.state.agent_tools, llm, publish=app.state.broadcaster.send_soon,
                                  timezone="America/Los_Angeles")
    return llm


@pytest.fixture
def api_url(app):
    """The app on a real local port, as the Concierge reaches it in production."""
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", ws="websockets-sansio"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < deadline, "the API did not start"
        time.sleep(0.02)
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(10)


@pytest.fixture
async def concierge(api_url):
    async with httpx.AsyncClient(base_url=api_url) as http:
        yield owner_chat.OwnerChat(http, owner_chat.ws_url(api_url), TOKEN, reply_timeout_s=10)


def tool_results(llm, request_index):
    """The tool results the model got back in request `request_index`, by tool_use_id."""
    return {r["tool_use_id"]: json.loads(r["content"]) for r in llm.requests[request_index]["messages"][-1]["content"]}


def owner_message(llm, request_index=0):
    return llm.requests[request_index]["messages"][0]["content"]


def hint(summary):
    return f"\n\nWaiting for your confirmation: {summary}. {owner_chat.CONFIRM_HINT}"


# ---------------------------------------------------------------- the seven flows


async def test_what_will_lunch_cost_me(app, concierge):
    forecast = load("ai_tools/get_forecast.json")["output"]
    meter = load("ai_tools/get_kitchen_state.json")["output"]["meter"]
    answer = (f"The next 2 hours reach {forecast[5]} kW; power costs ${meter['price_usd_per_kwh_now']}/kWh right now. "
              "I don't have a dollar forecast for lunch yet.")
    llm = use_llm(app, ScriptedLLM(tool_turn(("t1", "get_forecast", {}), ("t2", "get_kitchen_state", {})),
                                   text_turn(answer)))

    assert await concierge.answer(OWNER, "What will lunch cost me?") == answer
    assert owner_message(llm) == "What will lunch cost me?"
    results = tool_results(llm, 1)
    assert results["t1"] == forecast and results["t2"]["meter"] == meter


async def test_why_delay_then_undo_that_then_yes(app, set_clock, facade_calls, concierge):
    set_clock("2026-07-18T02:30:00Z")
    decision = load("ai_tools/explain_decision.json")["output"]
    undo = load("ai_tools/propose_undo.json")["input"]
    why = (f"I delayed the dishwasher {decision['value']} min ({decision['reason_code']}): the peak went from "
           f"{decision['effect']['peak_before_kw']} to {decision['effect']['peak_after_kw']} kW.")
    llm = use_llm(app, ScriptedLLM(
        tool_turn(("t1", "explain_decision", {"decision_id": "d_0001"})), text_turn(why),
        tool_turn(("t2", "propose_undo", undo)), text_turn("I've proposed undoing the dishwasher delay.")))

    assert await concierge.answer(OWNER, "Why did you delay the dishwasher?") == why
    assert tool_results(llm, 1)["t1"] == decision

    reply = await concierge.answer(OWNER, "Undo that")
    assert reply == "I've proposed undoing the dishwasher delay." + hint(undo["summary"])
    # "that" resolves through the earlier turn, which rides in the message (no chat session in the contract).
    sent = owner_message(llm, 2)
    assert "Owner: Why did you delay the dishwasher?" in sent and f"You: {why}" in sent
    assert sent.endswith("The owner's new message: Undo that")
    assert facade_calls == []  # proposed, not applied

    assert await concierge.answer(OWNER, "yes") == f"Done: {undo['summary']}."
    assert facade_calls == [("undo", ("d_0001",))]
    proposal = app.state.store.proposal("p_0002")
    assert proposal["kind"] == "undo_decision" and proposal["status"] == "confirmed"
    assert proposal["confirmed_via"] == "asi_one"
    assert next(d for d in app.state.store.decisions() if d["decision_id"] == "d_0001")["status"] == "undone"
    assert not llm.turns and len(llm.requests) == 4  # "yes" never reached the model


async def test_never_touch_the_walk_in_then_confirm(app, set_clock, facade_calls, concierge):
    set_clock("2026-07-18T02:30:00Z")
    fx = load("ai_tools/propose_importance_change.json")["input"]
    use_llm(app, ScriptedLLM(tool_turn(("t1", "propose_importance_change", fx)),
                             text_turn("I've proposed making the walk-in always on.")))

    reply = await concierge.answer(OWNER, "Never touch the walk-in after 9 PM")
    assert reply == "I've proposed making the walk-in always on." + hint(fx["summary"])

    assert await concierge.answer(OWNER, "Confirm.") == f"Done: {fx['summary']}."
    assert facade_calls == [("set_importance", ("walk_in_cooler_1", "always_on", {}))]
    # The newest pending proposal is confirmed; the older seeded one is untouched.
    assert app.state.store.proposal("p_0002")["status"] == "confirmed"
    assert app.state.store.proposal("p_0002")["confirmed_via"] == "asi_one"
    assert app.state.store.proposal("p_0001")["status"] == "pending"


async def test_how_much_did_we_save_this_month(app, concierge):
    bill = load("ai_tools/get_bill.json")
    answer = (f"July so far with WattWise: ${bill['output']['total_usd']} in total. "
              "I don't have a savings number for the month yet.")
    llm = use_llm(app, ScriptedLLM(tool_turn(("t1", "get_bill", bill["input"])), text_turn(answer)))

    assert await concierge.answer(OWNER, "How much did we save this month?") == answer
    assert tool_results(llm, 1)["t1"] == bill["output"]


async def test_what_did_you_decide_then_choose_option_2_then_confirm(app, set_clock, facade_calls, concierge):
    set_clock("2026-07-18T01:32:00Z")  # e_0001 is open until 01:40Z
    escalations = load("ai_tools/get_escalation.json")["output"]
    options = escalations[0]["options"]
    listing = "Tonight's dinner rush needs your call:\n" + "\n".join(
        f"{i}. {o['summary']}" for i, o in enumerate(options, 1))
    pick = {"escalation_id": "e_0001", "option_id": options[1]["option_id"], "summary": options[1]["summary"]}
    llm = use_llm(app, ScriptedLLM(
        tool_turn(("t1", "get_escalation", {})), text_turn(listing),
        tool_turn(("t2", "get_escalation", {})), tool_turn(("t3", "propose_escalation_choice", pick)),
        text_turn(f"Option 2 it is: {options[1]['summary']}.")))

    reply = await concierge.answer_reply(OWNER, "What did you decide about tonight?")
    card = reply.card  # the escalation card rides on Claude's answer; its fallback follows the answer in the text
    assert reply.text == f"{listing}\n\n{card.fallback}"
    assert json.loads(card.metadata()["card_payload"])["root"]["title"] == "Peak cap at risk"
    assert tool_results(llm, 1)["t1"] == escalations

    reply = await concierge.answer_reply(OWNER, "Choose option 2")  # typed: still Claude's propose → confirm flow
    assert reply.text == f"Option 2 it is: {options[1]['summary']}." + hint(pick["summary"])
    assert reply.card.kind == "review" and reply.card.payload["approve_cta"]["selection"]["proposal_id"] == "p_0002"
    assert f"2. {options[1]['summary']}" in owner_message(llm, 2)  # the numbered list it refers to

    assert await concierge.answer(OWNER, "YES") == f"Done: {pick['summary']}."
    assert facade_calls == [("resolve_escalation", ("e_0001", "deep_reduce_hvac", "owner", None))]
    resolved = next(e for e in app.state.store.escalations() if e["escalation_id"] == "e_0001")
    assert resolved["status"] == "resolved" and resolved["resolved_by"] == "owner"
    assert resolved["chosen_option_id"] == "deep_reduce_hvac"
    proposal = app.state.store.proposal("p_0002")
    assert proposal["kind"] == "resolve_escalation" and proposal["confirmed_via"] == "asi_one"


async def test_escalation_card_button_resolves_it_and_typed_confirm_still_works(app, set_clock, facade_calls,
                                                                               concierge):
    set_clock("2026-07-18T01:32:00Z")  # e_0001 is open until 01:40Z
    use_llm(app, ScriptedLLM(text_turn("Tonight's dinner rush needs your call.")))
    card = (await concierge.answer_reply(OWNER, "What did you decide about tonight?")).card
    root = json.loads(card.metadata()["card_payload"])["root"]
    option_1 = next(el for el in root["children"] if el.get("title") == "Option 1")
    selection = next(c for c in option_1["children"] if c["type"] == "button")["action"]["selection"]

    # The tap arrives as the selection JSON (direct @mention); code resolves it, the model is never asked.
    reply = await concierge.answer(OWNER, json.dumps(selection))
    assert reply == "Done: Let the peak reach 42.4 kW for one block."
    assert facade_calls == [("resolve_escalation", ("e_0001", "accept_overrun", "owner", None))]

    assert await concierge.answer(OWNER, json.dumps({"action": "wattwise_launch"})) == "Sorry, that option expired."
    set_clock("2026-07-18T02:30:00Z")
    assert await concierge.answer(OWNER, "confirm") == "Done: Never touch the walk-in after 21:00."


async def test_proposal_card_button_confirms_that_proposal(app, set_clock, facade_calls, concierge):
    set_clock("2026-07-18T02:30:00Z")
    fx = load("ai_tools/propose_importance_change.json")["input"]
    use_llm(app, ScriptedLLM(tool_turn(("t1", "propose_importance_change", fx)), text_turn("Proposed.")))
    card = (await concierge.answer_reply(OWNER, "Never touch the walk-in after 9 PM")).card
    assert await concierge.answer(OWNER, json.dumps(card.payload["approve_cta"]["selection"])) == f"Done: {fx['summary']}."
    assert app.state.store.proposal("p_0002")["confirmed_via"] == "asi_one"
    assert app.state.store.proposal("p_0001")["status"] == "pending"
    assert facade_calls == [("set_importance", ("walk_in_cooler_1", "always_on", {}))]


# ---------------------------------------------------------------- confirmation edge cases


async def test_cancel_drops_the_newest_proposal(app, set_clock, facade_calls, concierge):
    set_clock("2026-07-18T02:30:00Z")
    assert await concierge.answer(OWNER, "cancel") == "Cancelled: Never touch the walk-in after 21:00."
    assert app.state.store.proposal("p_0001")["status"] == "cancelled"
    assert facade_calls == []


async def test_confirm_with_nothing_pending(app, set_clock, concierge):
    set_clock("2026-07-18T03:10:00Z")  # the seeded p_0001 expired at 03:00Z
    assert await concierge.answer(OWNER, "yes") == owner_chat.NOTHING_PENDING


async def test_confirm_with_a_bad_token_is_refused_plainly(app, set_clock, api_url):
    set_clock("2026-07-18T02:30:00Z")
    async with httpx.AsyncClient(base_url=api_url) as http:
        chat = owner_chat.OwnerChat(http, owner_chat.ws_url(api_url), "wrong")
        assert await chat.answer(OWNER, "confirm") == "I couldn't apply that: Missing or invalid X-Agent-Token."
    assert app.state.store.proposal("p_0001")["status"] == "pending"


def test_only_whole_word_replies_confirm():
    match = owner_chat.match_confirmation
    assert [match(t) for t in ("confirm", " Yes! ", "YES.", "no", "Cancel")] == [True, True, True, False, False]
    assert [match(t) for t in ("yes please", "confirm the walk-in rule", "don't", "")] == [None] * 4


def test_ws_url_follows_api_url():
    assert owner_chat.ws_url("http://127.0.0.1:8000") == "ws://127.0.0.1:8000/ws"
    assert owner_chat.ws_url("https://api.example.org/") == "wss://api.example.org/ws"


# ---------------------------------------------------------------- failures: short plain reply, session alive


async def test_api_down_is_a_plain_reply():
    async with httpx.AsyncClient(base_url="http://127.0.0.1:9") as http:
        chat = owner_chat.OwnerChat(http, "ws://127.0.0.1:9/ws", TOKEN, reply_timeout_s=5)
        assert await chat.answer(OWNER, "What will lunch cost me?") == owner_chat.API_DOWN
        assert await chat.answer(OWNER, "confirm") == owner_chat.API_DOWN


class SlowFirstLLM(ScriptedLLM):
    """The first answer takes 2 s (past the Concierge's timeout); later ones are immediate."""

    slow = True

    async def turn(self, **kwargs):
        if self.slow:
            self.slow = False
            await asyncio.sleep(2)
            return text_turn("too late")
        return await super().turn(**kwargs)


async def test_timeout_is_a_plain_reply_and_the_next_question_works(app, api_url):
    use_llm(app, SlowFirstLLM(text_turn("Still here.")))
    async with httpx.AsyncClient(base_url=api_url) as http:
        chat = owner_chat.OwnerChat(http, owner_chat.ws_url(api_url), TOKEN, reply_timeout_s=1)
        assert await chat.answer(OWNER, "What will lunch cost me?") == owner_chat.TIMED_OUT
        assert await chat.answer(OWNER, "Are you there?") == "Still here."


async def test_failed_tool_call_is_reported_plainly(app, concierge):
    llm = use_llm(app, ScriptedLLM(
        tool_turn(("t1", "propose_undo", {"decision_id": "d_9999", "summary": "Undo it"})),
        text_turn("I couldn't find that decision, so nothing was proposed.")))

    assert await concierge.answer(OWNER, "Undo d_9999") == "I couldn't find that decision, so nothing was proposed."
    error = llm.requests[1]["messages"][-1]["content"][0]
    assert error["is_error"] is True and "Traceback" not in error["content"]


class BrokenLLM:
    async def turn(self, **_):
        raise RuntimeError("model unavailable")


async def test_claude_failure_is_a_plain_reply(app, concierge):
    use_llm(app, BrokenLLM())
    reply = await concierge.answer(OWNER, "What will lunch cost me?")
    assert reply and "Traceback" not in reply and "RuntimeError" not in reply


async def test_every_hop_is_in_the_agent_log(app, set_clock, concierge, monkeypatch):
    logged = []
    monkeypatch.setattr(app.state.runtime, "log_agent", lambda body: logged.append(body) or {"ok": True})
    set_clock("2026-07-18T02:30:00Z")
    use_llm(app, ScriptedLLM(text_turn("Hello.")))

    await concierge.answer(OWNER, "Hi")
    await concierge.answer(OWNER, "no")
    assert [(e["from_agent"], e["to_agent"], e["kind"]) for e in logged] == [
        ("concierge", "claude", "request"), ("claude", "concierge", "response"), ("concierge", "engine", "post")]
    assert logged[2]["summary"] == "Owner cancelled p_0001 in ASI:One"


def test_ui_confirm_stays_ui(app, client, set_clock):
    set_clock("2026-07-18T02:30:00Z")
    resp = client.post("/api/proposals/p_0001/confirm", json={"confirm": True}, headers={"X-Agent-Token": "nope"})
    assert resp.status_code == 401 and app.state.store.proposal("p_0001")["status"] == "pending"
    resp = client.post("/api/proposals/p_0001/confirm", json={"confirm": True})
    assert resp.status_code == 200 and resp.json()["confirmed_via"] == "ui"
