"""The paid plan (upgrade.py): the upgrade card → RequestPayment → verified CommitPayment → CompletePayment → an
`authority` Proposal; every failure stays on the free tier. Stripe is a stub here; the API is a MockTransport recording
each POST."""

import json

import httpx
import pytest
from uagents_core.contrib.protocols.payment import (
    CancelPayment,
    CommitPayment,
    CompletePayment,
    Funds,
    RejectPayment,
    RequestPayment,
)

from cards import STAY_FREE, UPGRADE, Reply
from stripe_checkout import StripeConfig
from upgrade import NOT_AVAILABLE, PAID_AUTHORITY, PROPOSE_FAILED, STAYS_FREE, Upgrade, authority_summary, match_upgrade

TOKEN = "test-agent-token"
OWNER = "agent1qowner"
OTHER = "agent1qsomeoneelse"
ASK = "Let Claude handle tonight's decisions"
START = "upgrade"  # the [Upgrade] button, typed
CONFIG = StripeConfig(secret_key="sk_test_x", publishable_key="pk_test_x", amount_cents=100, currency="usd",
                      product_name="p", success_url="https://example.test/ok", expires_s=1800)


class FakeStripe:
    config = CONFIG

    def __init__(self, paid: bool = True, fail_create: bool = False):
        self.paid, self.fail_create = paid, fail_create
        self.created: list[dict] = []

    def create_session(self, *, user_address: str, chat_session_id: str, description: str) -> dict:
        if self.fail_create:
            raise RuntimeError("stripe down")
        self.created.append({"user": user_address, "chat_session": chat_session_id})
        sid = f"cs_test_{len(self.created)}"
        return {"client_secret": f"{sid}_secret", "id": sid, "checkout_session_id": sid,
                "publishable_key": CONFIG.publishable_key, "currency": "usd", "amount_cents": "100",
                "ui_mode": "embedded"}

    def is_paid(self, checkout_session_id: str) -> bool:
        return self.paid


class DictStorage(dict):
    def set(self, key, value):
        self[key] = value


class FakeApi:
    def __init__(self, status: int = 200):
        self.status = status
        self.posts: list[tuple[str, dict, dict]] = []
        self.http = httpx.AsyncClient(base_url="http://api.test", transport=httpx.MockTransport(self._handle))

    def _handle(self, request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.content)
        self.posts.append((request.url.path, body, dict(request.headers)))
        if self.status != 200:
            return httpx.Response(self.status, json={"detail": "nope"})
        return httpx.Response(200, json={**body, "proposal_id": "p_0042", "status": "pending"})


def make(stripe=None, api=None):
    api = api or FakeApi()
    logs = []

    async def agent_log(*hop):
        logs.append(hop)

    up = Upgrade(api.http, TOKEN, FakeStripe() if stripe is None else stripe, DictStorage(), agent_log)
    return up, api, logs


async def ask(up, sender=OWNER, text=START):
    return await up.on_chat(sender, text, agent_address="agent1qconcierge", chat_session="sess-1")


def commit(tx="cs_test_1", method="stripe"):
    return CommitPayment(funds=Funds(currency="USD", amount="1.00", payment_method=method), recipient="agent1qconcierge",
                         transaction_id=tx)


def test_match_upgrade():
    assert match_upgrade(ASK)
    assert match_upgrade("please  LET CLAUDE DECIDE for me")
    assert not match_upgrade("what will lunch cost me?")
    assert not match_upgrade("should I upgrade my HVAC")


async def test_the_ask_shows_the_upgrade_card_first():
    up, api, _ = make()
    assert up.handles(OWNER, ASK) and not up.handles(OWNER, START)  # "upgrade" alone only after the card
    [reply] = await ask(up, text=ASK)
    assert isinstance(reply, Reply) and reply.card.kind == "review"
    rows = {r["label"]: r["value"] for r in reply.card.payload["summary_rows"]}
    assert rows["Price"] == "1.00 USD (Stripe test mode)"
    assert rows["Paid plan"] == authority_summary(PAID_AUTHORITY) + "."
    assert reply.text == reply.card.fallback and 'Reply "upgrade"' in reply.text
    assert api.posts == [] and up.handles(OWNER, START) and up.handles(OWNER, "Stay free")


@pytest.mark.parametrize("press", [json.dumps({"action": UPGRADE}), START,
                                   "The user tapped wattwise_upgrade on the plan card."])
async def test_upgrade_button_or_text_starts_the_checkout(press):
    up, _, _ = make()
    await ask(up, text=ASK)
    assert up.handles(OWNER, press)
    request, prompt = await ask(up, text=press)
    assert isinstance(request, RequestPayment) and "1.00 USD" in prompt


@pytest.mark.parametrize("press", [json.dumps({"action": STAY_FREE}), "stay free", "cancel"])
async def test_stay_free_button_or_text_drops_the_offer(press):
    up, _, _ = make()
    await ask(up, text=ASK)
    assert up.handles(OWNER, press)
    assert await ask(up, text=press) == [STAYS_FREE]
    assert not up.handles(OWNER, "cancel")  # nothing open: back to the normal proposal path


async def test_paid_commit_completes_and_proposes_the_authority():
    up, api, logs = make()
    request, prompt = await ask(up)
    assert isinstance(request, RequestPayment)
    assert request.accepted_funds[0].payment_method == "stripe" and request.accepted_funds[0].amount == "1.00"
    assert request.metadata["stripe"]["checkout_session_id"] == "cs_test_1"
    assert "sk_test" not in str(request.metadata)
    assert "1.00 USD" in prompt

    done, reply = await up.on_commit(OWNER, commit())
    assert isinstance(done, CompletePayment) and done.transaction_id == "cs_test_1"
    path, body, headers = api.posts[0]
    assert path == "/api/proposals" and headers["x-agent-token"] == TOKEN
    assert body["kind"] == "authority" and body["payload"] == PAID_AUTHORITY
    assert "confirm" in reply.text and reply.text.startswith("Payment received")
    assert reply.card.payload["approve_cta"]["selection"] == {"action": "wattwise_proposal_confirm",
                                                              "proposal_id": "p_0042"}
    assert logs[-1][:3] == ("concierge", "engine", "post")
    # A repeated commit confirms again but never makes a second Proposal.
    assert await up.on_commit(OWNER, commit()) == [CancelPayment(transaction_id="cs_test_1",
                                                                 reason="No open WattWise checkout for this payment.")]
    assert len(api.posts) == 1


async def test_unpaid_commit_cancels_and_keeps_the_checkout_open():
    stripe = FakeStripe(paid=False)
    up, api, _ = make(stripe)
    await ask(up)
    [cancel] = await up.on_commit(OWNER, commit())
    assert isinstance(cancel, CancelPayment) and api.posts == []
    stripe.paid = True  # the owner finishes the checkout and commits again
    done, _ = await up.on_commit(OWNER, commit())
    assert isinstance(done, CompletePayment) and len(api.posts) == 1


@pytest.mark.parametrize("sender, msg", [(OTHER, commit()), (OWNER, commit(tx="cs_test_999")),
                                         (OWNER, commit(method="fet_direct"))])
async def test_commit_not_for_this_checkout_is_cancelled(sender, msg):
    up, api, _ = make()
    await ask(up)
    [cancel] = await up.on_commit(sender, msg)
    assert isinstance(cancel, CancelPayment) and api.posts == []


async def test_reject_and_cancel_stay_free():
    up, api, _ = make()
    await ask(up)
    assert await up.on_reject(OWNER, RejectPayment(reason="changed my mind")) == [STAYS_FREE]
    assert not up.handles(OWNER, "cancel")  # nothing open: "cancel" goes to the normal proposal path

    await ask(up)
    assert up.handles(OWNER, "cancel")
    assert await ask(up, text="cancel") == [STAYS_FREE]
    [cancel] = await up.on_commit(OWNER, commit(tx="cs_test_2"))
    assert isinstance(cancel, CancelPayment) and api.posts == []


async def test_asking_again_while_open_resends_the_same_checkout():
    stripe = FakeStripe()
    up, _, _ = make(stripe)
    await ask(up)
    request, _ = await ask(up)
    assert request.metadata["stripe"]["checkout_session_id"] == "cs_test_1" and len(stripe.created) == 1


async def test_paid_but_api_down_retries_without_a_new_charge():
    stripe = FakeStripe()
    api = FakeApi(status=503)
    up, _, logs = make(stripe, api)
    await ask(up)
    _, reply = await up.on_commit(OWNER, commit())
    assert reply == PROPOSE_FAILED and logs[-1][2] == "error"
    api.status = 200
    [reply] = await ask(up, text=ASK)
    assert "Payment received" in reply.text and len(stripe.created) == 1 and len(api.posts) == 2


async def test_without_stripe_or_when_stripe_fails_nothing_is_charged():
    up, _, _ = make(stripe=False)
    up._checkout = None
    assert await ask(up) == [NOT_AVAILABLE]
    up, api, _ = make(FakeStripe(fail_create=True))
    [reply] = await ask(up)
    assert "Nothing was charged" in reply and api.posts == []


def test_live_keys_are_refused(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_abc")
    monkeypatch.setenv("STRIPE_PUBLISHABLE_KEY", "pk_live_abc")
    assert StripeConfig.from_env() is None
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_abc")
    monkeypatch.setenv("STRIPE_PUBLISHABLE_KEY", "pk_test_abc")
    assert StripeConfig.from_env().amount == "1.00"
