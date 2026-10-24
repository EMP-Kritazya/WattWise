"""The paid plan in ASI:One (AgentPaymentProtocol, seller role; Stripe TEST mode), API.md "Payment".

Free tier = `ClaudeAuthority.enabled: false`: every escalation goes to the owner. Paid tier = the owner grants Claude
the PAID_AUTHORITY bounds through the normal `authority` Proposal. The flow, all matched and run by code (no model call):

  "let Claude handle tonight's decisions" → the upgrade card (Free vs Paid, [Upgrade] [Stay free]; text fallback:
  "upgrade" / "stay free") → [Upgrade] → RequestPayment (embedded Stripe Checkout in `metadata["stripe"]`)
  → CommitPayment(transaction_id = Checkout Session id) → Stripe says `paid` → CompletePayment
  → POST /api/proposals (kind `authority`) + its proposal card → the owner confirms (owner_chat) → set_authority.

A commit that is not for this sender's open checkout, or not paid yet → CancelPayment (the owner may finish and commit
again). RejectPayment, [Stay free], or "cancel" while the card or a checkout is open → dropped. Every failure stays free.
Paid but the API was down → the payment is kept: asking again retries the Proposal without a new charge.
Per-sender state (only the Checkout Session id and whether it is paid; never card data) lives in the agent's storage.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Awaitable, Callable, Protocol

import httpx
from uagents_core.contrib.protocols.payment import (
    CancelPayment,
    CommitPayment,
    CompletePayment,
    Funds,
    RejectPayment,
    RequestPayment,
)

from cards import STAY_FREE, UPGRADE, Reply, parse_selection, proposal_card, upgrade_card
from owner_chat import API_TIMEOUT_S, _detail, match_confirmation
from stripe_checkout import StripeCheckout

log = logging.getLogger("agents.upgrade")

UPGRADE_PHRASES = ("let claude handle", "let claude decide", "paid plan", "upgrade to paid")
START_WORD = "upgrade"  # the [Upgrade] button typed (whole message)
STAY_FREE_WORDS = ("stay free",)
PAYMENT_DEADLINE_S = 300
STATE_PREFIX = "payment_state:"
SERVICE = "wattwise_authority"

# The paid plan's authority (CONTRACTS.md §1 ClaudeAuthority example); each bound overridable in agents/.env.
PAID_AUTHORITY = {
    "enabled": True,
    "max_cap_overrun_kw": float(os.environ.get("PAID_MAX_CAP_OVERRUN_KW", "3.0")),
    "max_extra_delay_min": int(os.environ.get("PAID_MAX_EXTRA_DELAY_MIN", "20")),
    "max_extra_reduce_min": int(os.environ.get("PAID_MAX_EXTRA_REDUCE_MIN", "15")),
    "may_go_below_min_power": False,
}

NOT_AVAILABLE = ("The paid plan isn't set up on this Concierge right now. Everything still works on the free plan, "
                 "where every escalation comes to you.")
CHECKOUT_FAILED = "I couldn't start the payment just now. Nothing was charged; please try again in a moment."
PAY_PROMPT = ("To let Claude handle tonight's decisions, pay {amount} {currency} (Stripe test mode) in the checkout "
              "above. Once it's paid you'll still confirm exactly what Claude may do. Say \"cancel\" to stay free.")
STILL_PENDING = "Your checkout above is still open. Finish it, or say \"cancel\" to stay on the free plan."
STAYS_FREE = "No payment taken. You stay on the free plan: every escalation comes to you."
PROPOSE_FAILED = ("Payment received, but I can't reach the kitchen to set this up. Ask me again in a moment and I'll "
                  "retry. You won't be charged again.")


class Storage(Protocol):
    def get(self, key: str) -> Any: ...
    def set(self, key: str, value: Any) -> None: ...


def match_upgrade(text: str) -> bool:
    """The owner asks for the paid plan ("let Claude handle tonight's decisions"); matched by code."""
    text = " ".join(text.lower().split())
    return any(phrase in text for phrase in UPGRADE_PHRASES)


def _word(text: str) -> str:
    return " ".join(text.lower().split()).rstrip(".!")


def authority_summary(authority: dict) -> str:
    return (f"Let Claude resolve escalations without asking, within {authority['max_cap_overrun_kw']:g} kW over the cap, "
            f"{authority['max_extra_delay_min']} min extra delay and {authority['max_extra_reduce_min']} min extra "
            "reduction, never below a device's minimum power")


class Upgrade:
    def __init__(self, http: httpx.AsyncClient, token: str | None, checkout: StripeCheckout | None,
                 storage: Storage, agent_log: Callable[[str, str, str, str], Awaitable[None]]):
        self._http = http  # base_url = API_URL
        self._headers = {"X-Agent-Token": token or ""}
        self._checkout = checkout  # None: Stripe not set up (or not test keys) → the plan is unavailable
        self._storage = storage
        self._log = agent_log

    # ------------------------------------------------------------ chat side

    def handles(self, sender: str, text: str) -> bool:
        """This chat message belongs to the payment flow: an upgrade ask, an upgrade card button, or, while the card or
        a checkout is open, "upgrade" / "stay free" / "cancel" typed."""
        selection = parse_selection(text)
        if selection is not None:
            return selection.action in (UPGRADE, STAY_FREE)
        if match_upgrade(text):
            return True
        status = self._state(sender).get("status")
        if status == "offered" and _word(text) in (START_WORD, *STAY_FREE_WORDS):
            return True
        return match_confirmation(text) is False and status in ("offered", "awaiting_payment")

    async def on_chat(self, sender: str, text: str, *, agent_address: str, chat_session: str) -> list[Any]:
        """The messages to send back (payment protocol models, Replies and/or plain reply strings)."""
        state = self._state(sender)
        selection = parse_selection(text)
        action = selection.action if selection is not None else None
        if action == STAY_FREE or _word(text) in STAY_FREE_WORDS or match_confirmation(text) is False:
            self._clear(sender)
            return [STAYS_FREE]
        if self._checkout is None:
            return [NOT_AVAILABLE]
        if state.get("status") == "paid":  # paid earlier, the Proposal did not go through: retry, no new charge
            return [await self._propose(sender)]
        if state.get("status") == "awaiting_payment":
            return [self._request(state["stripe"], agent_address, chat_session), STILL_PENDING]
        if action != UPGRADE and _word(text) != START_WORD:  # an upgrade ask: what Free vs Paid means, first
            self._save(sender, {"status": "offered"})
            cfg = self._checkout.config
            return [Reply.with_card("", upgrade_card(paid_summary=authority_summary(PAID_AUTHORITY),
                                                     amount=cfg.amount, currency=cfg.currency.upper()))]
        try:
            stripe = await asyncio.to_thread(
                self._checkout.create_session, user_address=sender, chat_session_id=chat_session,
                description="Claude resolves your kitchen's escalations within the bounds you confirm.")
        except Exception as e:  # Stripe down, bad key: a short reply, the session stays alive
            log.warning("checkout not created: %s", type(e).__name__)
            return [CHECKOUT_FAILED]
        self._save(sender, {"status": "awaiting_payment", "checkout_session_id": stripe["checkout_session_id"],
                            "stripe": stripe})
        cfg = self._checkout.config
        return [self._request(stripe, agent_address, chat_session),
                PAY_PROMPT.format(amount=cfg.amount, currency=cfg.currency.upper())]

    def _request(self, stripe: dict, agent_address: str, chat_session: str) -> RequestPayment:
        cfg = self._checkout.config
        return RequestPayment(
            accepted_funds=[Funds(currency=cfg.currency.upper(), amount=cfg.amount, payment_method="stripe")],
            recipient=agent_address,
            deadline_seconds=PAYMENT_DEADLINE_S,
            reference=chat_session,
            description="Let Claude handle tonight's decisions (WattWise paid plan, Stripe test mode).",
            metadata={"stripe": stripe, "service": SERVICE},
        )

    # ------------------------------------------------------------ payment protocol side (seller)

    async def on_commit(self, sender: str, msg: CommitPayment) -> list[Any]:
        state = self._state(sender)
        tx = msg.transaction_id
        if msg.funds.payment_method != "stripe" or not tx or tx != state.get("checkout_session_id"):
            return [CancelPayment(transaction_id=tx or None, reason="No open WattWise checkout for this payment.")]
        if state.get("status") == "paid":  # a repeated commit: confirm again, the Proposal is not duplicated
            return [CompletePayment(transaction_id=tx)]
        try:
            paid = await asyncio.to_thread(self._checkout.is_paid, tx)
        except Exception as e:
            log.warning("checkout not verified: %s", type(e).__name__)
            paid = False
        if not paid:  # the commit may arrive before Stripe marks it paid; the checkout stays open
            return [CancelPayment(transaction_id=tx, reason="Stripe payment not completed yet. Please finish checkout.")]
        self._save(sender, {"status": "paid", "checkout_session_id": tx})
        return [CompletePayment(transaction_id=tx), await self._propose(sender)]

    async def on_reject(self, sender: str, msg: RejectPayment) -> list[Any]:
        if self._state(sender).get("status") == "paid":
            return []  # already paid: nothing to drop
        self._clear(sender)
        return [STAYS_FREE]

    # ------------------------------------------------------------ the authority Proposal

    async def _propose(self, sender: str) -> Reply | str:
        summary = authority_summary(PAID_AUTHORITY)
        body = {"kind": "authority", "payload": PAID_AUTHORITY, "summary": summary}
        try:
            r = await self._http.post("/api/proposals", json=body, headers=self._headers, timeout=API_TIMEOUT_S)
        except httpx.HTTPError:
            await self._log("concierge", "engine", "error", "Paid plan: authority proposal not posted (API down)")
            return PROPOSE_FAILED
        if r.status_code != 200:
            await self._log("concierge", "engine", "error", f"Paid plan: authority proposal refused: {_detail(r)}")
            return PROPOSE_FAILED
        proposal = r.json()
        self._clear(sender)  # paid and proposed: the owner's confirm / cancel is now the normal proposal path
        await self._log("concierge", "engine", "post", f"Paid plan: proposed Claude authority {proposal['proposal_id']}")
        return Reply.with_card("Payment received.", proposal_card(proposal))

    # ------------------------------------------------------------ per-sender state

    def _state(self, sender: str) -> dict:
        raw = self._storage.get(STATE_PREFIX + sender)
        try:
            return json.loads(raw) if raw else {}
        except (TypeError, ValueError):
            return {}

    def _save(self, sender: str, state: dict) -> None:
        self._storage.set(STATE_PREFIX + sender, json.dumps(state))

    def _clear(self, sender: str) -> None:
        self._storage.set(STATE_PREFIX + sender, "{}")
