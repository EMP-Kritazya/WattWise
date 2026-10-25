"""One test per `contracts/fixtures/ai_tools/*.json`: the tool's input gives exactly the fixture output."""

import pytest

from agent.tools import CHAT_TOOLS, ESCALATION_TOOLS, AgentTools, ToolInputError

from .conftest import FIXTURES, load

AI_TOOL_FILES = sorted((FIXTURES / "ai_tools").glob("*.json"))
# The proposals the scenario made before each one (shapes/proposal_<kind>.json are p_0001 … p_0006).
PROPOSAL_SHAPES = ["proposal_pending", "proposal_peak_cap", "proposal_authority", "proposal_undo_decision",
                   "proposal_customer_event", "proposal_resolve_escalation"]


def _start_after_earlier_proposals(app, proposal_id):
    """The store holds the proposals made before `proposal_id` (all of them pending), so ids continue from there."""
    earlier = [load(f"shapes/{name}.json") for name in PROPOSAL_SHAPES]
    app.state.store._tables["proposals"] = [p for p in earlier if p["proposal_id"] < proposal_id]


@pytest.mark.parametrize("fixture_file", AI_TOOL_FILES, ids=[f.stem for f in AI_TOOL_FILES])
def test_ai_tool_fixture(app, set_clock, fixture_file):
    fx = load(f"ai_tools/{fixture_file.name}")
    tools: AgentTools = app.state.agent_tools
    allowed, escalation = CHAT_TOOLS, None
    if fx["tool"] == "choose_escalation_option":
        allowed, escalation = ESCALATION_TOOLS, tools.get_escalation()[0]
    if isinstance(fx["output"], dict) and "proposal_id" in fx["output"]:
        _start_after_earlier_proposals(app, fx["output"]["proposal_id"])
        set_clock(fx["output"]["ts"])

    # The stale fixture still lists every engine option. Claude is now offered only authority-eligible ids and never
    # ask_owner; the actual valid fixture call remains useful as a facade recording check.
    schema = next(t["input_schema"] for t in tools.schemas(allowed, escalation) if t["name"] == fx["tool"])
    if fx["tool"] == "choose_escalation_option":
        assert schema["properties"]["option_id"]["enum"] == ["accept_overrun", "extend_delay_dishwasher"]
    else:
        for key, values in fx.get("input_enum", {}).items():
            assert schema["properties"][key]["enum"] == values

    assert tools.call(fx["tool"], fx["input"], allowed=allowed, escalation=escalation) == fx["output"]


def test_propose_tools_store_a_pending_proposal(app, set_clock):
    fx = load("ai_tools/propose_peak_cap_change.json")
    _start_after_earlier_proposals(app, "p_0002")
    set_clock(fx["output"]["ts"])
    app.state.agent_tools.call(fx["tool"], fx["input"])
    assert app.state.store.proposal("p_0002") == fx["output"]


def test_bounded_tools_reject_values_outside_their_enum(app):
    tools = app.state.agent_tools
    escalation = tools.get_escalation()[0]
    with pytest.raises(ToolInputError):
        tools.call("set_crowd_effect", {"value": "1.25", "reason": "x"})
    with pytest.raises(ToolInputError):
        tools.call("choose_escalation_option", {"option_id": "turn_off_fryer", "rationale": "x"},
                   allowed=ESCALATION_TOOLS, escalation=escalation)


def test_chat_cannot_choose_escalation_options(app):
    tools = app.state.agent_tools
    assert "choose_escalation_option" not in {t["name"] for t in tools.schemas(CHAT_TOOLS)}
    with pytest.raises(ToolInputError):
        tools.call("choose_escalation_option", {"option_id": "accept_overrun", "rationale": "x"})


def test_claude_enum_excludes_ask_owner_and_outside_authority(app):
    tools = app.state.agent_tools
    escalation = tools.get_escalation()[0]
    tool = next(item for item in tools.schemas(ESCALATION_TOOLS, escalation) if item["name"] == "choose_escalation_option")
    assert tool["input_schema"]["properties"]["option_id"]["enum"] == [
        "accept_overrun", "extend_delay_dishwasher"
    ]
    assert "ask_owner" not in tool["input_schema"]["properties"]["option_id"]["enum"]
    assert "deep_reduce_hvac" not in tool["input_schema"]["properties"]["option_id"]["enum"]


def test_disabled_authority_does_not_offer_claude_a_choice(app):
    tools = app.state.agent_tools
    escalation = tools.get_escalation()[0]
    offered = {item["name"] for item in tools.schemas(ESCALATION_TOOLS, escalation, {"enabled": False})}
    assert "choose_escalation_option" not in offered


def test_outside_authority_claude_pick_is_rejected_without_a_proposal(app):
    tools = app.state.agent_tools
    escalation = tools.get_escalation()[0]
    before = list(app.state.store.proposals())
    with pytest.raises(ToolInputError):
        tools.call("choose_escalation_option", {"option_id": "deep_reduce_hvac", "rationale": "No."},
                   allowed=ESCALATION_TOOLS, escalation=escalation)
    assert app.state.store.proposals() == before


def test_what_if_accepts_an_optional_lane_and_defaults_to_with(app, monkeypatch):
    tools = app.state.agent_tools
    calls = []
    monkeypatch.setattr(app.state.service.lanes["without"], "what_if",
                        lambda *args: calls.append(args) or {"lane": "without"})
    result = tools.call("what_if", {"device_id": "walk_in_cooler_1", "action": "reduce", "value": 50,
                                     "at": "2026-07-18T01:50:00Z", "lane": "without"})
    assert result == {"lane": "without"}
    assert calls == [("walk_in_cooler_1", "reduce", 50, "2026-07-18T01:50:00Z")]
    schema = next(item["input_schema"] for item in tools.schemas() if item["name"] == "what_if")
    assert schema["required"] == ["device_id", "action", "value", "at"]


def test_forecast_tool_always_uses_the_contract_horizon(app, monkeypatch):
    calls = []
    monkeypatch.setattr(app.state.service.lanes["with"], "forecast", lambda horizon_min: calls.append(horizon_min) or [])
    assert app.state.agent_tools.get_forecast() == []
    assert calls == [120]
