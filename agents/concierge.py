"""WattWise Concierge: the owner's chat door in ASI:One (Agent Chat Protocol, mailbox mode).

Step 1 (registration + discoverability): every chat message is acknowledged and answered with a fixed help text.
Claude + engine tools through the API come next (docs/design/AGENTS.md, "Concierge loops").

Context loop (`context_loop.py`): every CONTEXT_INTERVAL_S (600 real s) and whenever a kitchen is built (GET /api/kitchen
polled every KITCHEN_POLL_S), ask Weather, Grid and Events over uAgents → Claude crowd effect → POST /api/context.
Env: API_URL (default http://127.0.0.1:8000), AGENT_TOKEN, CONTEXT_LOOP=0 to switch it off, DEMO_MODE=1 / --recorded
for the recorded crowd effect. The context agents' addresses come from their seeds (common.agent_address).

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
    EndSessionContent,
    TextContent,
    chat_protocol_spec,
)

from common import agent_address, load_dotenv, recorded_mode
from context_loop import ApiClient, ContextLoop, Location
from crowd import create_classifier
from models import EventsResponse, PriceResponse, WeatherResponse

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

# STUB: fixed reply until the Claude agent + engine tools are wired through the API.
HELP_TEXT = (
    "Hi, I'm the WattWise Concierge. I keep a restaurant's electricity peak under the owner's cap "
    "without stopping service, so the demand charge on the utility bill stays low.\n\n"
    "Soon you'll be able to ask me:\n"
    "- What will lunch cost me in power today?\n"
    "- Why did you delay the dishwasher?\n"
    "- Undo that.\n"
    "- Never touch the walk-in after 9 PM.\n"
    "- How much did we save this month?\n"
    "- What did you decide about tonight?\n\n"
    "Live answers from the kitchen are being connected right now."
)


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


def _now() -> datetime:
    return datetime.now(timezone.utc)


@chat_proto.on_message(ChatMessage)
async def handle_chat(ctx: Context, sender: str, msg: ChatMessage):
    await ctx.send(sender, ChatAcknowledgement(timestamp=_now(), acknowledged_msg_id=msg.msg_id))

    text = " ".join(c.text for c in msg.content if isinstance(c, TextContent)).strip()
    if not text:
        # Session start / end markers carry no question; the acknowledgement is enough.
        return
    ctx.logger.info(f"chat from {sender}: {text!r}")

    await ctx.send(
        sender,
        ChatMessage(
            timestamp=_now(),
            msg_id=uuid4(),
            content=[TextContent(type="text", text=HELP_TEXT), EndSessionContent(type="end-session")],
        ),
    )


@chat_proto.on_message(ChatAcknowledgement)
async def handle_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
    ctx.logger.debug(f"ack from {sender} for {msg.acknowledged_msg_id}")


agent.include(chat_proto, publish_manifest=True)


@agent.on_event("startup")
async def announce(ctx: Context):
    ctx.logger.info(f"{AGENT_NAME} address: {agent.address}")


# ---------------------------------------------------------------- context loop

API_URL = os.environ.get("API_URL", "http://127.0.0.1:8000")
CONTEXT_INTERVAL_S = float(os.environ.get("CONTEXT_INTERVAL_S", "600"))
KITCHEN_POLL_S = float(os.environ.get("KITCHEN_POLL_S", "10"))
AGENT_REPLY_TIMEOUT_S = int(os.environ.get("AGENT_REPLY_TIMEOUT_S", "15"))
RESPONSE_TYPES: dict[str, type[Model]] = {"weather": WeatherResponse, "grid": PriceResponse, "events": EventsResponse}

_http = httpx.AsyncClient(base_url=API_URL)
_loop = ContextLoop(ApiClient(_http, os.environ.get("AGENT_TOKEN")), create_classifier(recorded_mode()))
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
