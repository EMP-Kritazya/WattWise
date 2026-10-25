"""Interactive-card reports and direct owner escalation overrides.

The recorded escalation fixtures predate ranked options and the always-active fallback. These tests copy their engine
fields into an in-memory contract-shaped report; the fixture files themselves remain read-only.
"""

import copy
import json
from pathlib import Path

import httpx

from cards import (CHOOSE_OPTION, EXPIRED, PROPOSAL_CONFIRM, Card, Selection, escalation_card, forecast_card,
                   parse_selection, proposal_card, upgrade_card)
from owner_chat import CONFIRM_HINT, OwnerChat, match_option_number
from upgrade import PAID_AUTHORITY, authority_summary

FIXTURES = Path(__file__).resolve().parents[2] / "contracts" / "fixtures"
TOKEN = "test-agent-token"
OWNER = "agent1qowner"


def load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def report(*, claude: bool = False) -> dict:
    """An engine-shaped report made from the old fixture without changing the fixture."""
    escalation = copy.deepcopy(load("shapes/escalation_open.json"))
    escalation["updated_ts"] = escalation["ts"]
    escalation["active_option_id"] = "accept_overrun"
    for rank, option in enumerate(escalation["options"], 1):
        if option["option_id"] != "ask_owner":
            option["rank"] = rank
            option["harm_score"] = [0.6, 1.4, 0.3][rank - 1]
        else:
            option["rank"] = None
            option["harm_score"] = None
    if claude:
        escalation.update(status="resolved", resolved_by="claude", chosen_option_id="extend_delay_dishwasher",
                          rationale="its rank and harm score fit dinner service")
        escalation["active_option_id"] = "extend_delay_dishwasher"
    return escalation


OPEN = report()
CLAUDE_RESOLVED = report(claude=True)
PENDING = load("shapes/proposal_pending.json")
FORECAST = load("facade/forecast.json")["returns"]
TICK = load("ws/tick.json")["data"]


def walk(node):
    if isinstance(node, dict):
        yield node
        for child in node.get("children") or []:
            yield from walk(child)
        for item in node.get("items") or []:
            for child in item.get("children") or []:
                yield from walk(child)


def buttons(card: Card) -> list[dict]:
    return [node for node in walk(card.payload["root"]) if node.get("type") == "button"]


def section(card: Card, title: str) -> dict:
    return next(node for node in walk(card.payload["root"])
                if node.get("type") == "section" and node.get("title") == title)


def assert_wire(card: Card) -> None:
    metadata = card.metadata()
    assert metadata["card_protocol_version"] == "1"
    assert metadata["requires_card_interaction"] == "true"
    assert json.loads(metadata["card_payload"]) == card.payload
    assert card.fits() and card.fallback.strip()


def press(card: Card, label: str) -> str:
    return json.dumps(next(button for button in buttons(card) if button["label"] == label)["action"]["selection"])


# ---------------------------------------------------------------- escalation report


def test_escalation_card_is_a_ranked_report_with_an_active_option():
    card = escalation_card(OPEN)
    assert_wire(card)
    assert card.payload["root"]["title"] == "Escalation report"
    active = section(card, "Active option: option 1")
    assert active["subtitle"] == OPEN["options"][0]["summary"]
    assert [child["value"] for child in active["children"]] == ["Rank: 1", "Harm score: 0.6"]

    option_2 = section(card, "Option 2")
    values = [child["value"] for child in option_2["children"] if child["type"] == "text"]
    assert "Rank: 2" in values and "Harm score: 1.4" in values
    labels = {button["label"] for button in buttons(card)}
    assert labels == {"Override: option 2", "Override: option 3"}
    assert "Ask me later" not in card.fallback and "Approve" not in card.fallback
    assert "Owner override only" in card.fallback


def test_claude_escalation_report_quotes_the_choice_and_rationale():
    card = escalation_card(CLAUDE_RESOLVED)
    assert_wire(card)
    resolution = section(card, "Claude's resolution")
    expected = (f"Claude chose {CLAUDE_RESOLVED['options'][2]['summary']} because "
                f"{CLAUDE_RESOLVED['rationale']}")
    assert resolution["subtitle"] == expected
    assert expected in card.fallback
    assert f"Active option: {CLAUDE_RESOLVED['options'][2]['summary']}." in card.fallback
    assert {button["label"] for button in buttons(card)} == {"Override: option 1", "Override: option 2"}


def test_escalation_report_can_be_rendered_without_owner_override_controls():
    card = escalation_card(OPEN, allow_owner_override=False)
    assert buttons(card) == []
    assert "Owner override only" not in card.fallback


# ---------------------------------------------------------------- other cards and selection wire compatibility


def test_proposal_and_forecast_cards_stay_well_formed():
    proposal = proposal_card(PENDING)
    assert_wire(proposal)
    assert proposal.fallback == f"Waiting for your confirmation: {PENDING['summary']}. {CONFIRM_HINT}"

    forecast = forecast_card(FORECAST, TICK["meter"], [], device_names={})
    assert_wire(forecast)
    assert forecast.terminal is True
    assert all(f"{kw} kW" in forecast.fallback for kw in FORECAST)


def test_upgrade_card_describes_fallback_instead_of_owner_escalation_approval():
    card = upgrade_card(paid_summary=authority_summary(PAID_AUTHORITY), amount="1.00", currency="USD")
    assert_wire(card)
    values = [row["value"] for row in card.payload["summary_rows"]]
    assert "The engine fallback remains active for every escalation." in values
    assert all("Every escalation comes to you" not in value for value in values)


def test_only_direct_override_selection_is_recognized_for_escalations():
    selection = parse_selection(json.dumps({"action": CHOOSE_OPTION, "escalation_id": "e_0001",
                                             "option_id": "accept_overrun"}))
    assert selection == Selection(CHOOSE_OPTION, {"action": CHOOSE_OPTION, "escalation_id": "e_0001",
                                                    "option_id": "accept_overrun"})
    assert parse_selection(json.dumps({"action": "wattwise_approve_pick", "escalation_id": "e_0001",
                                       "option_id": "accept_overrun"})).action is None
    assert parse_selection(json.dumps({"action": "wattwise_ask_later", "escalation_id": "e_0001"})).action is None
    assert match_option_number("choose option 2") == 2
    assert match_option_number("choose option 2 now") is None


# ---------------------------------------------------------------- report actions → direct API owner overrides


class FakeApi:
    """Small API double for cards: resolve is direct and Proposal confirmation stays independent."""

    def __init__(self, *, open_=(OPEN,), awaiting_owner=(), resolved=(), expired_default=(), obsolete=(),
                 pending=(PENDING,)):
        self.escalations = {
            "open": list(open_), "awaiting_owner": list(awaiting_owner), "resolved": list(resolved),
            "expired_default": list(expired_default), "obsolete": list(obsolete),
        }
        self.pending = list(pending)
        self.calls: list[tuple[str, str, dict | None, str | None]] = []
        self.http = httpx.AsyncClient(base_url="http://api.test", transport=httpx.MockTransport(self._handle))

    def _handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "GET" and path == "/api/escalations":
            return httpx.Response(200, json=self.escalations.get(request.url.params["status"], []))
        if request.method == "GET" and path == "/api/proposals":
            return httpx.Response(200, json=self.pending)
        body = json.loads(request.content) if request.content else None
        if path != "/api/agent-log":
            self.calls.append((request.method, path, body, request.headers.get("x-agent-token")))
        if path == "/api/agent-log":
            return httpx.Response(200, json={"ok": True})
        if path == "/api/escalations/e_0001/resolve":
            escalation = next(rows[0] for rows in self.escalations.values() if rows)
            return httpx.Response(200, json={**escalation, "status": "resolved", "resolved_by": "owner",
                                             "chosen_option_id": body["option_id"]})
        if path == "/api/proposals/p_0001/confirm":
            return httpx.Response(200, json={**PENDING, "status": "confirmed" if body["confirm"] else "cancelled",
                                             "confirmed_via": "asi_one" if body["confirm"] else None})
        return httpx.Response(404, json={"detail": "not found"})


def chat(api: FakeApi) -> OwnerChat:
    return OwnerChat(api.http, "ws://api.test/ws", TOKEN)


async def test_override_button_posts_directly_without_touching_proposals():
    api = FakeApi()
    reply = await chat(api).answer(OWNER, press(escalation_card(OPEN), "Override: option 2"))
    assert reply == "Done: HVAC 1 and 2 to 30 % until their planned restore."
    assert api.calls == [("POST", "/api/escalations/e_0001/resolve", {"option_id": "deep_reduce_hvac"}, None)]


async def test_choose_option_n_is_a_direct_owner_override_without_a_model():
    api = FakeApi()
    reply = await chat(api).answer(OWNER, "choose option 3")
    assert reply == "Done: Delay the dishwasher 20 min past its deadline."
    assert api.calls == [("POST", "/api/escalations/e_0001/resolve",
                          {"option_id": "extend_delay_dishwasher"}, None)]


async def test_owner_can_override_a_claude_resolved_report_until_the_block_ends():
    api = FakeApi(open_=(), resolved=(CLAUDE_RESOLVED,))
    reply = await chat(api).answer(OWNER, press(escalation_card(CLAUDE_RESOLVED), "Override: option 1"))
    assert reply == "Done: Let the peak reach 42.4 kW for one block."
    assert api.calls == [("POST", "/api/escalations/e_0001/resolve", {"option_id": "accept_overrun"}, None)]


async def test_owner_can_override_an_expired_default_until_the_block_ends():
    expired = {**OPEN, "status": "expired_default", "resolved_by": "default",
               "chosen_option_id": OPEN["default_option_id"]}
    api = FakeApi(open_=(), expired_default=(expired,))
    reply = await chat(api).answer(OWNER, "choose option 2")

    assert reply == "Done: HVAC 1 and 2 to 30 % until their planned restore."
    assert api.calls == [("POST", "/api/escalations/e_0001/resolve", {"option_id": "deep_reduce_hvac"}, None)]


async def test_unrecognized_legacy_escalation_buttons_expire_without_api_calls():
    api = FakeApi()
    reply = await chat(api).answer(OWNER, json.dumps({"action": "wattwise_ask_later", "escalation_id": "e_0001"}))
    assert reply == EXPIRED
    assert api.calls == []


async def test_normal_proposal_confirmation_remains_available():
    api = FakeApi()
    reply = await chat(api).answer(OWNER, json.dumps({"action": PROPOSAL_CONFIRM, "proposal_id": "p_0001"}))
    assert reply == f"Done: {PENDING['summary']}."
    assert api.calls == [("POST", "/api/proposals/p_0001/confirm", {"confirm": True}, TOKEN)]
