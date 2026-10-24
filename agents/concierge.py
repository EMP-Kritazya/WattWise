"""WattWise Concierge: the owner's chat door in ASI:One (Agent Chat Protocol, mailbox mode).

Step 1 (registration + discoverability): every chat message is acknowledged and answered with a fixed help text.
Claude + engine tools through the API come next (docs/design/AGENTS.md, "Concierge loops").

Run:  FETCH_AGENT_SEED="<long secret phrase>" python agents/concierge.py
Then open the printed inspector link -> Connect -> Mailbox (see agents/REGISTRATION.md).
The profile (description, README, handle) is sent to Agentverse only on that Connect: after editing them, restart and Connect again.
"""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    EndSessionContent,
    TextContent,
    chat_protocol_spec,
)

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


def _load_dotenv(path: Path) -> None:
    """KEY=VALUE lines from agents/.env (gitignored); variables already set in the shell win."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key and not key.startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(Path(__file__).resolve().parent / ".env")
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


if __name__ == "__main__":
    agent.run()
