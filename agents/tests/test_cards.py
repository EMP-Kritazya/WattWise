"""ASI:One Interactive Cards (cards.py) built from the shared fixtures: every number on a card equals the fixture value
as received, no other number appears, every card has a text fallback, and every button maps to the right API call
(owner_chat.py against a MockTransport API)."""

import json
import re
from pathlib import Path

import httpx
import pytest

import cards
from cards import (APPROVE_PICK, ASK_LATER, CHOOSE_OPTION, EXPIRED, PROPOSAL_CANCEL, PROPOSAL_CONFIRM, STAY_FREE,
                   UPGRADE, Card, Reply, Selection, escalation_card, forecast_card, parse_selection, proposal_card,
                   upgrade_card)
from owner_chat import CONFIRM_HINT, OwnerChat
from upgrade import PAID_AUTHORITY, authority_summary

FIXTURES = Path(__file__).resolve().parents[2] / "contracts" / "fixtures"
TOKEN = "test-agent-token"
OWNER = "agent1qowner"
NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?![\w.])")


def load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


OPEN = load("shapes/escalation_open.json")
AWAITING = load("shapes/escalation_awaiting_owner.json")
CLAUDE_PROPOSAL = load("shapes/proposal_resolve_escalation.json")  # p_0006: Claude's deep_reduce_hvac pick
PENDING = load("shapes/proposal_pending.json")  # p_0001
FORECAST = load("facade/forecast.json")["returns"]
TICK = load("ws/tick.json")["data"]
DECISION = load("shapes/decision.json")


# ---------------------------------------------------------------- helpers

def walk(node):
    if isinstance(node, dict):
        yield node
        for child in node.get("children") or []:
            yield from walk(child)
        for item in node.get("items") or []:
            for child in item.get("children") or []:
                yield from walk(child)


def strings(card: Card) -> list[str]:
    """Every human-visible string on the card (texts, titles, labels, row values) and its fallback."""
    out = [card.fallback]
    if card.kind == "custom":
        for el in walk(card.payload["root"]):
            out += [el[k] for k in ("value", "title", "subtitle", "label") if isinstance(el.get(k), str)]
    else:
        out.append(card.payload["title"])
        out += [v for row in card.payload["summary_rows"] for v in row.values()]
        out += [card.payload[k]["label"] for k in ("approve_cta", "reject_cta")]
    return out


def numbers_in(card: Card) -> set[str]:
    return {n for s in strings(card) for n in NUMBER.findall(s)}


def fixture_numbers(obj) -> set[str]:
    """Every number in a fixture, as JSON wrote it (str(float) is Python's shortest round-trip form), and those inside
    its strings (an engine summary such as "Let the peak reach 42.4 kW")."""
    if isinstance(obj, bool):
        return set()
    if isinstance(obj, str):
        return set(NUMBER.findall(obj))
    if isinstance(obj, (int, float)):
        return {str(obj)}
    if isinstance(obj, dict):
        return set().union(*(fixture_numbers(v) for v in obj.values())) if obj else set()
    if isinstance(obj, list):
        return set().union(*(fixture_numbers(v) for v in obj)) if obj else set()
    return set()


def section(card: Card, title: str) -> dict:
    return next(el for el in walk(card.payload["root"]) if el.get("type") == "section" and el.get("title") == title)


def texts(el: dict) -> list[str]:
    return [c["value"] for c in walk(el) if c.get("type") == "text"]


def buttons(card: Card) -> list[dict]:
    return [el for el in walk(card.payload["root"]) if el.get("type") == "button"]


def assert_wire(card: Card) -> None:
    meta = card.metadata()
    assert meta["card_protocol_version"] == "1" and meta["requires_card_interaction"] == "true"
    assert meta["card_kind"] == card.kind and all(isinstance(v, str) for v in meta.values())
    assert json.loads(meta["card_payload"]) == card.payload  # top level, no envelope
    assert card.fits() and card.fallback.strip()
    if card.kind == "custom":
        assert set(card.payload) == {"root"} and cards.depth(card.payload["root"]) <= cards.MAX_DEPTH


# ---------------------------------------------------------------- 1. escalation card

@pytest.mark.parametrize("escalation", [OPEN, AWAITING], ids=["open", "awaiting_owner"])
def test_escalation_card_numbers_are_the_engine_numbers(escalation):
    card = escalation_card(escalation)
    assert_wire(card)
    problem = escalation["problem"]
    assert (f"Forecast {problem['forecast_peak_kw']} kW against a {problem['target_kw']} kW target "
            f"({problem['excess_kw']} kW over): {problem['reason']}.") in strings(card)
    for n, option in enumerate(escalation["options"], 1):
        if option["option_id"] == "ask_owner":
            continue
        el = section(card, f"Option {n}")
        assert el["subtitle"] == option["summary"]
        lines = texts(el)
        p = option["projected"]
        assert f"Peak after: {p['peak_kw']} kW" in lines
        assert f"Extra cost: ${p['cost_delta_usd']}" in lines
        assert f"Indoor temp change: {p['max_indoor_temp_change_c']} °C" in lines
        breaks = next(line for line in lines if line.startswith("Breaks"))
        for rb in option["rule_breaks"]:
            assert f"{rb['amount']} {'%' if rb['unit'] == 'pct' else rb['unit']}" in breaks
            assert rb.get("device_id", "") in breaks
        # The parsed values equal the fixture floats exactly.
        assert float(re.search(r"Peak after: (\S+) kW", " ".join(lines)).group(1)) == p["peak_kw"]
    # No number on the card that the engine did not produce (option numbers N excepted).
    labels = {str(n) for n in range(1, len(escalation["options"]) + 1)}
    assert numbers_in(card) <= fixture_numbers(escalation) | labels


def test_escalation_buttons_carry_ids_and_skip_ask_owner():
    card = escalation_card(OPEN)
    by_label = {b["label"]: b["action"]["selection"] for b in buttons(card)}
    assert by_label == {
        "Option 1": {"action": CHOOSE_OPTION, "escalation_id": "e_0001", "option_id": "accept_overrun"},
        "Option 2": {"action": CHOOSE_OPTION, "escalation_id": "e_0001", "option_id": "deep_reduce_hvac"},
        "Option 3": {"action": CHOOSE_OPTION, "escalation_id": "e_0001", "option_id": "extend_delay_dishwasher"},
        "Ask me later": {"action": ASK_LATER, "escalation_id": "e_0001"},
    }  # open: Claude has no pick yet, so no approve button


def test_claudes_pick_is_highlighted_with_its_rationale():
    card = escalation_card(AWAITING, confirm_approves_pick=True)
    pick = section(card, "Claude's pick: option 2")
    assert pick["subtitle"] == "HVAC 1 and 2 to 30 % until their planned restore"
    assert texts(pick) == [AWAITING["rationale"]]
    approve = next(b for b in buttons(card) if b["label"] == "Approve Claude's pick")
    assert approve["primary"] and approve["action"]["selection"] == {
        "action": APPROVE_PICK, "escalation_id": "e_0001", "option_id": AWAITING["chosen_option_id"]}
    badged = [n for n in (1, 2, 3) if any(c.get("label") == "Claude's pick" for c in walk(section(card, f"Option {n}")))]
    assert badged == [2]
    assert "Claude's pick: option 2" in card.fallback and AWAITING["rationale"] in card.fallback
    assert '"confirm" to approve' in card.fallback
    assert '"confirm"' not in escalation_card(AWAITING).fallback  # only when confirm would hit Claude's pick


def test_escalation_fallback_lists_every_option_with_its_numbers():
    fallback = escalation_card(OPEN).fallback
    for n, option in enumerate(OPEN["options"][:3], 1):
        line = next(l for l in fallback.splitlines() if l.startswith(f"{n}. {option['summary']}"))
        assert f"Peak after: {option['projected']['peak_kw']} kW" in line
        assert f"Extra cost: ${option['projected']['cost_delta_usd']}" in line
    assert "ask_owner" not in fallback and 'Reply "choose option N"' in fallback


# ---------------------------------------------------------------- 2. proposal card

def test_proposal_card():
    card = proposal_card(PENDING)
    assert_wire(card)
    assert card.kind == "review"
    assert card.payload["summary_rows"][0] == {"label": "Change", "value": PENDING["summary"]}
    assert card.payload["approve_cta"]["selection"] == {"action": PROPOSAL_CONFIRM, "proposal_id": "p_0001"}
    assert card.payload["reject_cta"]["selection"] == {"action": PROPOSAL_CANCEL, "proposal_id": "p_0001"}
    assert card.fallback == f"Waiting for your confirmation: {PENDING['summary']}. {CONFIRM_HINT}"
    assert numbers_in(card) <= fixture_numbers(PENDING)


# ---------------------------------------------------------------- 3. forecast card

def test_forecast_card_numbers_are_the_forecast_tool_numbers():
    names = {d["device_id"]: d["name"] for d in TICK["hub"]["devices"]}
    card = forecast_card(FORECAST, TICK["meter"], [DECISION], device_names=names, as_of=TICK["ts"])
    assert_wire(card)
    assert card.metadata()["is_terminal"] == "true"  # informational: no input expected
    rows = [el for el in walk(card.payload["root"]) if el.get("type") == "group"]
    kw = [next(t["value"] for t in row["children"] if t["value"].endswith(" kW")) for row in rows]
    assert kw == [f"{v} kW" for v in FORECAST]
    assert [float(k.split()[0]) for k in kw] == FORECAST  # exactly the tool's floats, in order
    assert f"Cap: {TICK['meter']['peak_cap_kw']} kW" in strings(card)
    over = [i for i, row in enumerate(rows) if any(c.get("type") == "badge" for c in row["children"])]
    assert over == [i for i, v in enumerate(FORECAST) if v > TICK["meter"]["peak_cap_kw"]]
    moves = texts(section(card, "Next planned moves"))
    effect = DECISION["effect"]
    assert moves == [f"{names['dishwasher_1']}: delay {DECISION['value']} min "
                     f"(peak {effect['peak_before_kw']} → {effect['peak_after_kw']} kW)"]
    steps = {str(15 * i) for i in range(1, len(FORECAST) + 1)}  # the +15 … +120 min labels
    allowed = (fixture_numbers(FORECAST) | fixture_numbers(TICK["meter"]) | fixture_numbers(DECISION)
               | fixture_numbers(names) | fixture_numbers(TICK["ts"]) | steps | {"2"})  # names: "Dishwasher 1"
    assert numbers_in(card) <= allowed
    assert all(f"{v} kW" in card.fallback for v in FORECAST)


def test_forecast_card_in_minimize_mode_uses_the_engine_target():
    meter = {**TICK["meter"], "peak_mode": "minimize", "peak_cap_kw": None}
    card = forecast_card(FORECAST, meter, [], device_names={})
    assert f"Target: {meter['target_kw']} kW" in strings(card)
    assert texts(section(card, "Next planned moves")) == ["No new moves planned."]


# ---------------------------------------------------------------- 4. upgrade card

def test_upgrade_card():
    card = upgrade_card(paid_summary=authority_summary(PAID_AUTHORITY), amount="1.00", currency="USD")
    assert_wire(card)
    rows = {r["label"]: r["value"] for r in card.payload["summary_rows"]}
    assert rows["Price"] == "1.00 USD (Stripe test mode)"
    assert rows["Paid plan"] == authority_summary(PAID_AUTHORITY) + "."
    assert rows["Free plan"] == "Every escalation comes to you."
    assert card.payload["approve_cta"]["selection"] == {"action": UPGRADE}
    assert card.payload["reject_cta"]["selection"] == {"action": STAY_FREE}
    assert 'Reply "upgrade"' in card.fallback


# ---------------------------------------------------------------- selections

def test_every_button_round_trips_as_json_and_as_prose():
    card = escalation_card(AWAITING)
    for button in buttons(card):
        sel = button["action"]["selection"]
        assert parse_selection(json.dumps(sel)) == Selection(sel["action"], sel)
        prose = "The user picked " + " with ".join(str(v) for v in sel.values()) + "."
        parsed = parse_selection(prose)
        assert parsed.action == sel["action"] and all(parsed.get(k) == v for k, v in sel.items() if k != "action")


@pytest.mark.parametrize("text", ["confirm", "What will lunch cost me?", "42", '"hi"', "choose option 2"])
def test_ordinary_messages_are_not_selections(text):
    assert parse_selection(text) is None


@pytest.mark.parametrize("text", ['{"action": "book_offer", "offer_id": "off_123"}', '{"cabin": "economy"}',
                                  '{"action": "wattwise_escalation_option"}', "The user tapped wattwise_launch_rocket."])
def test_unknown_or_incomplete_selections_are_unknown(text):
    assert parse_selection(text).action is None


def test_a_card_too_big_goes_as_text():
    big = Card("custom", {"root": {"type": "text", "value": "x" * (cards.MAX_PAYLOAD_BYTES + 1)}}, "fallback")
    assert Reply.with_card("hi", big) == Reply("hi\n\nfallback")


# ---------------------------------------------------------------- buttons → API calls (owner_chat)

class FakeApi:
    """GET escalations / proposals from fixtures; records every other request."""

    def __init__(self, awaiting=(AWAITING,), open_=(), pending=(CLAUDE_PROPOSAL,)):
        self.escalations = {"awaiting_owner": list(awaiting), "open": list(open_)}
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
        if m := re.fullmatch(r"/api/proposals/(p_\d+)/confirm", path):
            proposal = next(p for p in self.pending if p["proposal_id"] == m.group(1))
            return httpx.Response(200, json={**proposal, "status": "confirmed" if body["confirm"] else "cancelled",
                                             "confirmed_via": "asi_one" if body["confirm"] else None})
        if m := re.fullmatch(r"/api/escalations/(e_\d+)/resolve", path):
            return httpx.Response(200, json={**AWAITING, "status": "resolved", "resolved_by": "owner",
                                             "chosen_option_id": body["option_id"]})
        if path == "/api/agent-log":
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404, json={"detail": "not found"})


def chat(api: FakeApi) -> OwnerChat:
    return OwnerChat(api.http, "ws://api.test/ws", TOKEN)


def press(card: Card, label: str) -> str:
    """The text ASI:One sends on a direct @mention when the owner taps `label`."""
    if card.kind == "custom":
        return json.dumps(next(b for b in buttons(card) if b["label"] == label)["action"]["selection"])
    cta = next(c for c in (card.payload["approve_cta"], card.payload["reject_cta"]) if c["label"] == label)
    return json.dumps(cta["selection"])


async def test_approve_claudes_pick_confirms_its_proposal():
    api = FakeApi()
    reply = await chat(api).answer(OWNER, press(escalation_card(AWAITING), "Approve Claude's pick"))
    assert api.calls == [("POST", "/api/proposals/p_0006/confirm", {"confirm": True}, TOKEN)]
    assert reply == f"Done: {CLAUDE_PROPOSAL['summary']}."


async def test_option_n_resolves_as_the_owner_and_drops_claudes_stale_proposal():
    api = FakeApi()
    reply = await chat(api).answer(OWNER, press(escalation_card(AWAITING), "Option 3"))
    assert api.calls == [("POST", "/api/escalations/e_0001/resolve", {"option_id": "extend_delay_dishwasher"}, None),
                         ("POST", "/api/proposals/p_0006/confirm", {"confirm": False}, TOKEN)]
    assert reply == "Done: Delay the dishwasher 20 min past its deadline."


async def test_option_n_on_claudes_own_pick_is_the_same_as_approve():
    api = FakeApi()
    await chat(api).answer(OWNER, press(escalation_card(AWAITING), "Option 2"))
    assert api.calls == [("POST", "/api/proposals/p_0006/confirm", {"confirm": True}, TOKEN)]


async def test_option_n_on_an_open_escalation():
    api = FakeApi(awaiting=(), open_=(OPEN,), pending=())
    await chat(api).answer(OWNER, press(escalation_card(OPEN), "Option 1"))
    assert api.calls == [("POST", "/api/escalations/e_0001/resolve", {"option_id": "accept_overrun"}, None)]


async def test_ask_me_later_changes_nothing():
    api = FakeApi()
    reply = await chat(api).answer(OWNER, press(escalation_card(AWAITING), "Ask me later"))
    assert api.calls == []
    assert reply.endswith("the engine's default applies: Let the peak reach 42.4 kW for one block.")


@pytest.mark.parametrize("label, confirm", [("Confirm", True), ("Cancel", False)])
async def test_proposal_buttons(label, confirm):
    api = FakeApi(pending=(PENDING,))
    await chat(api).answer(OWNER, press(proposal_card(PENDING), label))
    assert api.calls == [("POST", "/api/proposals/p_0001/confirm", {"confirm": confirm}, TOKEN)]


async def test_planner_prose_is_the_same_press():
    api = FakeApi()
    await chat(api).answer(OWNER, "The user chose wattwise_escalation_option on escalation e_0001, option "
                                  "extend_delay_dishwasher.")
    assert api.calls[0] == ("POST", "/api/escalations/e_0001/resolve", {"option_id": "extend_delay_dishwasher"}, None)


@pytest.mark.parametrize("text", [
    '{"action": "book_offer", "offer_id": "off_123"}',  # not ours
    json.dumps({"action": CHOOSE_OPTION, "escalation_id": "e_0099", "option_id": "accept_overrun"}),  # gone
    json.dumps({"action": CHOOSE_OPTION, "escalation_id": "e_0001", "option_id": "ask_owner"}),  # no such button
    json.dumps({"action": CHOOSE_OPTION, "escalation_id": "e_0001", "option_id": "deep_reduce_oven"}),  # not offered
    json.dumps({"action": PROPOSAL_CONFIRM, "proposal_id": "p_0099"}),  # no longer pending
    json.dumps({"action": UPGRADE}),  # the upgrade flow handles its own; none here
])
async def test_unknown_or_stale_button_is_expired_and_calls_nothing(text):
    api = FakeApi()
    assert await chat(api).answer(OWNER, text) == EXPIRED
    assert api.calls == []


async def test_typed_confirm_still_confirms_the_newest_pending():
    api = FakeApi(pending=(PENDING, CLAUDE_PROPOSAL))
    assert await chat(api).answer(OWNER, "confirm") == f"Done: {CLAUDE_PROPOSAL['summary']}."
    assert api.calls == [("POST", "/api/proposals/p_0006/confirm", {"confirm": True}, TOKEN)]
