"""Shared by every WattWise uAgent: .env loading, recorded fixtures, seeds/addresses, agent construction.

Seeds: each agent reads its own `<NAME>_AGENT_SEED`; if unset it derives `"<FETCH_AGENT_SEED>/<name>"`, so one secret
fixes every address and the Concierge can compute the context agents' addresses itself (`agent_address`).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

AGENTS_DIR = Path(__file__).resolve().parent
FIXTURES_DIR = AGENTS_DIR.parent / "contracts" / "fixtures" / "agents"

# name → default local port (the Concierge keeps 8001)
PORTS = {"weather": 8002, "grid": 8003, "events": 8004}
# name → default Agentverse @handle (max 20 chars), so ASI:One users can call the agent directly; `<NAME>_AGENT_HANDLE` wins.
HANDLES = {"weather": "wattwiseweather", "grid": "wattwisegrid", "events": "wattwiseevents"}


def load_dotenv(path: Path = AGENTS_DIR / ".env") -> None:
    """KEY=VALUE lines from agents/.env (gitignored); variables already set in the shell win."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key and not key.startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_fixture(name: str) -> Any:
    """A recorded agent fixture from contracts/fixtures/agents/ (read only)."""
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def recorded_mode(argv: list[str] | None = None) -> bool:
    """`--recorded` on the command line, or DEMO_MODE=1: answer from the fixtures, labeled `recorded`."""
    argv = sys.argv[1:] if argv is None else argv
    return "--recorded" in argv or os.environ.get("DEMO_MODE") == "1"


def agent_seed(name: str) -> str | None:
    own = os.environ.get(f"{name.upper()}_AGENT_SEED")
    if own:
        return own
    base = os.environ.get("FETCH_AGENT_SEED")
    return f"{base}/{name}" if base else None


def agent_address(name: str) -> str | None:
    """`<NAME>_AGENT_ADDRESS` if set, else the address the agent's seed gives."""
    explicit = os.environ.get(f"{name.upper()}_AGENT_ADDRESS")
    if explicit:
        return explicit
    seed = agent_seed(name)
    if not seed:
        return None
    from uagents.crypto import Identity

    return Identity.from_seed(seed, 0).address


def make_agent(name: str, display_name: str, description: str):
    """A context agent: mailbox mode by default (Agentverse); AGENT_MAILBOX=0 → local HTTP endpoint only.

    The profile (description, agents/README_<name>.md, handle) is sent to Agentverse on the inspector's Connect."""
    from uagents import Agent

    seed = agent_seed(name)
    if not seed:
        sys.exit(f"Set {name.upper()}_AGENT_SEED or FETCH_AGENT_SEED: the seed fixes the agent's address.")
    port = int(os.environ.get(f"{name.upper()}_PORT", PORTS[name]))
    mailbox = os.environ.get("AGENT_MAILBOX", "1") != "0"
    return Agent(
        name=display_name,
        seed=seed,
        port=port,
        mailbox=mailbox,
        endpoint=None if mailbox else [f"http://127.0.0.1:{port}/submit"],
        description=description,
        readme_path=str(AGENTS_DIR / f"README_{name}.md"),
        handle=os.environ.get(f"{name.upper()}_AGENT_HANDLE", HANDLES[name]),
        publish_agent_details=True,
    )
