"""WattWise Concierge: the owner's chat door in ASI:One (Agent Chat Protocol, mailbox mode).

Chat (`owner_chat.py`): every message is acknowledged, then answered through the API by the same Claude agent and engine
tools as the dashboard chat (POST /api/chat, reply joined from /ws). `confirm` / `yes` / `no` / `cancel` are matched by
code and confirm or cancel the newest pending Proposal; the model never confirms. Sessions stay open (no end-session).
Interactive Cards (`cards.py`): escalation, proposal, forecast and upgrade replies carry one card (a MetadataContent)
after the text; the text holds the card's fallback, and every button press is matched by code.

Paid plan (`upgrade.py`, AgentPaymentProtocol seller role, Stripe TEST mode): "let Claude handle tonight's decisions"
→ RequestPayment → verified CommitPayment → CompletePayment → an `authority` Proposal the owner confirms. Without
STRIPE_SECRET_KEY / STRIPE_PUBLISHABLE_KEY test keys the plan is unavailable and the kitchen stays on the free tier.

Context loop (`context_loop.py`): every CONTEXT_INTERVAL_S (600 real s) and whenever a kitchen is built (GET /api/kitchen
polled every KITCHEN_POLL_S), ask Weather, Grid and Events over uAgents → Claude crowd effect → POST /api/context.
Env: API_URL (default http://127.0.0.1:8000), AGENT_TOKEN, CHAT_REPLY_TIMEOUT_S (30), CONTEXT_LOOP=0 to switch it off,
DEMO_MODE=1 / --recorded for the recorded crowd effect. The context agents' addresses come from their seeds (common.agent_address).

Run:  FETCH_AGENT_SEED="<long secret phrase>" python agents/concierge.py [--recorded]
Then open the printed inspector link -> Connect -> Mailbox (see agents/REGISTRATION.md).
The profile (description, README, handle) is sent to Agentverse only on that Connect: after editing them, restart and Connect again.
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx
from uagents import Agent, Context, Model, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    MetadataContent,
    TextContent,
    chat_protocol_spec,
)
from uagents_core.contrib.protocols.payment import CommitPayment, RejectPayment, payment_protocol_spec

from cards import Reply
from common import agent_address, load_dotenv, recorded_mode
from context_loop import ApiClient, ContextLoop, Location
from crowd import create_classifier
from models import EventsResponse, PriceResponse, WeatherResponse
from owner_chat import OwnerChat, ws_url
from stripe_checkout import StripeCheckout, StripeConfig
from upgrade import Upgrade

AGENT_NAME = "WattWise Concierge"
DESCRIPTION = (
    "Lowers a restaurant's electricity demand charges by forecasting and shifting appliance load. "
    "Connected to your kitchen: ask why your restaurant electricity bill is high, how to lower demand charges, "
    "or what lunch will cost you in power today."
)
README_PATH = Path(__file__).resolve().parent / "README_concierge.md"
PORT = int(os.environ.get("CONCIERGE_PORT", "8001"))
# Agentverse @handle (max 20 chars), so the owner can call the agent directly in ASI:One.
HANDLE = os.environ.get("CONCIERGE_HANDLE", "wattwise")

load_dotenv()
seed = os.environ.get("FETCH_AGENT_SEED")
if not seed:
    sys.exit("FETCH_AGENT_SEED is not set: it fixes the agent's address, so set it before starting the Concierge.")

agent = Agent(
    name=AGENT_NAME,
    seed=seed,
    port=PORT,
    mailbox=True,
    description=DESCRIPTION,
    readme_path=str(README_PATH),
    handle=HANDLE,
    publish_agent_details=True,
)

chat_proto = Protocol(spec=chat_protocol_spec)
payment_proto = Protocol(spec=payment_protocol_spec, role="seller")

API_URL = os.environ.get("API_URL", "http://127.0.0.1:8000")
AGENT_TOKEN = os.environ.get("AGENT_TOKEN")
CHAT_REPLY_TIMEOUT_S = float(os.environ.get("CHAT_REPLY_TIMEOUT_S", "30"))

_http = httpx.AsyncClient(base_url=API_URL)
_owner_chat = OwnerChat(_http, ws_url(API_URL), AGENT_TOKEN, reply_timeout_s=CHAT_REPLY_TIMEOUT_S)
_stripe_config = StripeConfig.from_env()
_upgrade = Upgrade(_http, AGENT_TOKEN, StripeCheckout(_stripe_config) if _stripe_config else None, agent.storage,
                   _owner_chat.log)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _chat(reply: Reply | str) -> ChatMessage:
    """The text first (it carries the card's fallback), then the card declaration when there is one."""
    reply = Reply(reply) if isinstance(reply, str) else reply
    content = [TextContent(type="text", text=reply.text)]
    if reply.card is not None:
        content.append(MetadataContent(type="metadata", metadata=reply.card.metadata()))
    return ChatMessage(timestamp=_now(), msg_id=uuid4(), content=content)


async def _send_all(ctx: Context, sender: str, messages: list) -> None:
    """Payment protocol models as they are; Replies and plain strings as chat messages."""
    for message in messages:
        await ctx.send(sender, _chat(message) if isinstance(message, (str, Reply)) else message)


@chat_proto.on_message(ChatMessage)
async def handle_chat(ctx: Context, sender: str, msg: ChatMessage):
    await ctx.send(sender, ChatAcknowledgement(timestamp=_now(), acknowledged_msg_id=msg.msg_id))

    text = " ".join(c.text for c in msg.content if isinstance(c, TextContent)).strip()
    if not text:
        # Session start / end markers carry no question; the acknowledgement is enough.
        return
    ctx.logger.info(f"chat from {sender}: {text!r}")

    if _upgrade.handles(sender, text):
        await _send_all(ctx, sender, await _upgrade.on_chat(sender, text, agent_address=agent.address,
                                                           chat_session=str(ctx.session)))
        return

    reply = await _owner_chat.answer_reply(sender, text)
    await ctx.send(sender, _chat(reply))


@chat_proto.on_message(ChatAcknowledgement)
async def handle_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
    ctx.logger.debug(f"ack from {sender} for {msg.acknowledged_msg_id}")


@payment_proto.on_message(CommitPayment)
async def handle_commit(ctx: Context, sender: str, msg: CommitPayment):
    ctx.logger.info(f"payment commit from {sender}: {msg.transaction_id}")
    await _send_all(ctx, sender, await _upgrade.on_commit(sender, msg))


@payment_proto.on_message(RejectPayment)
async def handle_reject(ctx: Context, sender: str, msg: RejectPayment):
    ctx.logger.info(f"payment rejected by {sender}: {msg.reason!r}")
    await _send_all(ctx, sender, await _upgrade.on_reject(sender, msg))


agent.include(chat_proto, publish_manifest=True)
agent.include(payment_proto, publish_manifest=True)


@agent.on_event("startup")
async def announce(ctx: Context):
    ctx.logger.info(f"{AGENT_NAME} address: {agent.address}")
    ctx.logger.info("paid plan: " + ("Stripe test mode" if _stripe_config else "off (no Stripe test keys)"))


# ---------------------------------------------------------------- context loop

CONTEXT_INTERVAL_S = float(os.environ.get("CONTEXT_INTERVAL_S", "600"))
KITCHEN_POLL_S = float(os.environ.get("KITCHEN_POLL_S", "10"))
AGENT_REPLY_TIMEOUT_S = int(os.environ.get("AGENT_REPLY_TIMEOUT_S", "15"))
RESPONSE_TYPES: dict[str, type[Model]] = {"weather": WeatherResponse, "grid": PriceResponse, "events": EventsResponse}

_loop = ContextLoop(ApiClient(_http, AGENT_TOKEN), create_classifier(recorded_mode()))
_round_lock = asyncio.Lock()
_kitchen_seen: str | None = None  # the last kitchen config seen (JSON), to spot a new build


def _asker(ctx: Context):
    async def ask(name: str, request: Model) -> Model | None:
        address = agent_address(name)
        if address is None:
            ctx.logger.warning(f"no address for the {name} agent (set FETCH_AGENT_SEED or {name.upper()}_AGENT_ADDRESS)")
            return None
        reply, status = await ctx.send_and_receive(address, request, response_type=RESPONSE_TYPES[name],
                                                   timeout=AGENT_REPLY_TIMEOUT_S)
        if reply is None:
            ctx.logger.warning(f"{name} did not answer: {status.detail}")
        return reply

    return ask


async def _kitchen_config() -> dict | None:
    """The built kitchen's config, or None (no kitchen yet, or the API is down)."""
    try:
        r = await _http.get("/api/kitchen", timeout=5.0)
    except httpx.HTTPError:
        return None
    return r.json().get("config") if r.status_code == 200 else None


async def _round(ctx: Context, config: dict) -> bool:
    """One context round; False when another round is still running (the caller retries on its next trigger)."""
    if _round_lock.locked():
        return False
    async with _round_lock:
        loc = config.get("location") or {}
        if "lat" not in loc or "lon" not in loc:
            ctx.logger.warning("kitchen config has no location; skipping the context round")
            return True
        body = await _loop.run_once(Location(lat=loc["lat"], lon=loc["lon"]), _asker(ctx))
        ctx.logger.info("context posted" if body else "context round posted nothing (last known kept)")
        return True


if os.environ.get("CONTEXT_LOOP", "1") != "0":

    @agent.on_interval(period=CONTEXT_INTERVAL_S)
    async def context_every_interval(ctx: Context):
        config = await _kitchen_config()
        if config is not None:
            await _round(ctx, config)

    @agent.on_interval(period=KITCHEN_POLL_S)
    async def context_on_kitchen_build(ctx: Context):
        global _kitchen_seen
        config = await _kitchen_config()
        if config is None:
            return
        seen = json.dumps(config, sort_keys=True)
        if seen != _kitchen_seen and await _round(ctx, config):
            _kitchen_seen = seen


if __name__ == "__main__":
    agent.run()
