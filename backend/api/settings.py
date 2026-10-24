"""Process settings read from the environment once, at app creation."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

_CHOICES = {
    "KITCHEN_IMPL": ("fake", "real"),
    "LIVE_TRANSPORT": ("spacetime", "ws"),
    "STORE": ("convex", "memory"),
    "HARDWARE": ("off", "sim_bridge", "esp32"),
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
    agent_token: str | None = None
    fixtures_dir: Path = field(default_factory=lambda: REPO_ROOT / "contracts" / "fixtures")

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            kitchen_impl=_choice("KITCHEN_IMPL", "fake"),
            live_transport=_choice("LIVE_TRANSPORT", "spacetime"),
            store=_choice("STORE", "memory"),
            hardware=_choice("HARDWARE", "off"),
            agent_token=os.environ.get("AGENT_TOKEN") or None,
            fixtures_dir=Path(os.environ.get("FIXTURES_DIR", REPO_ROOT / "contracts" / "fixtures")),
        )
