"""Process settings read from the environment once, at app creation."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
# Sim time of tick 1 (CONTRACTS.md §8 example: Friday 17 July 2026, 17:30 local = the Demo Café scenario start).
DEFAULT_SIM_START_TS = "2026-07-18T00:30:00Z"

_CHOICES = {
    "KITCHEN_IMPL": ("fake", "real"),
    "LIVE_TRANSPORT": ("spacetime", "ws"),
    "STORE": ("convex", "memory"),
    "HARDWARE": ("off", "sim_bridge", "esp32"),
    "HUB_IMPL": ("browser", "fake"),
    "CLAUDE_PROVIDER": ("anthropic", "foundry"),
}


def _choice(name: str, default: str) -> str:
    value = os.environ.get(name, default)
    if value not in _CHOICES[name]:
        raise ValueError(f"{name}={value!r}; expected one of {_CHOICES[name]}")
    return value


@dataclass(frozen=True)
class Settings:
    kitchen_impl: str = "fake"
    live_transport: str = "spacetime"
    store: str = "memory"
    hardware: str = "off"
    hub_impl: str = "browser"
    convex_url: str | None = None  # STORE=convex: the deployment URL (`npx convex dev` writes it to .env.local)
    agent_token: str | None = None
    sim_start_ts: str = DEFAULT_SIM_START_TS
    claude_provider: str = "anthropic"
    anthropic_model: str | None = None  # None → agent/claude_agent.py DEFAULT_MODEL
    anthropic_api_key: str | None = field(default=None, repr=False)  # None → Claude off (ASI:One, then templates)
    asi1_model: str | None = None  # None → agent/llm.py ASI1_DEFAULT_MODEL ("asi1")
    asi1_api_key: str | None = field(default=None, repr=False)  # None → no ASI:One fallback for chat / explanations
    demo_mode: bool = False  # DEMO_MODE=1: the clock pauses while Claude decides an escalation
    council_wait_s: float = 0.0  # COUNCIL_WAIT_S (default 5 from the env, 0 in tests): wait for the council's context
    fixtures_dir: Path = field(default_factory=lambda: REPO_ROOT / "contracts" / "fixtures")

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            kitchen_impl=_choice("KITCHEN_IMPL", "fake"),
            live_transport=_choice("LIVE_TRANSPORT", "spacetime"),
            store=_choice("STORE", "memory"),
            hardware=_choice("HARDWARE", "off"),
            hub_impl=_choice("HUB_IMPL", "browser"),
            convex_url=os.environ.get("CONVEX_URL") or None,
            agent_token=os.environ.get("AGENT_TOKEN") or None,
            sim_start_ts=os.environ.get("SIM_START_TS", DEFAULT_SIM_START_TS),
            claude_provider=_choice("CLAUDE_PROVIDER", "anthropic"),
            anthropic_model=os.environ.get("ANTHROPIC_MODEL") or None,
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
            asi1_model=os.environ.get("ASI1_MODEL") or None,
            asi1_api_key=os.environ.get("ASI1_API_KEY") or None,
            demo_mode=os.environ.get("DEMO_MODE") == "1",
            council_wait_s=float(os.environ.get("COUNCIL_WAIT_S", "5")),
            fixtures_dir=Path(os.environ.get("FIXTURES_DIR", REPO_ROOT / "contracts" / "fixtures")),
        )
