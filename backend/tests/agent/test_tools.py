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

    # The offered schema carries the fixture's enums.
    schema = next(t["input_schema"] for t in tools.schemas(allowed, escalation) if t["name"] == fx["tool"])
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


def test_claude_pick_outside_authority_becomes_a_proposal(app, set_clock):
    tools = app.state.agent_tools
    escalation = tools.get_escalation()[0]
    set_clock(escalation["ts"])
    result = tools.call("choose_escalation_option", {"option_id": "deep_reduce_hvac", "rationale": "Coolest choice."},
                        allowed=ESCALATION_TOOLS, escalation=escalation)
    assert result["status"] == "awaiting_owner" and result["chosen_option_id"] == "deep_reduce_hvac"
    proposal = app.state.proposals.latest_pending()
    assert proposal["kind"] == "resolve_escalation"
    assert proposal["payload"] == {"escalation_id": "e_0001", "option_id": "deep_reduce_hvac"}
    assert proposal["expires_at"] == escalation["deadline_sim_ts"]
