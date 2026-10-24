"""CustomerSource: seeded customer arrivals from an hourly profile, plus surges (design/SIMULATION.md).

The run loop creates ONE source and passes the same events to both lanes. Labelled "simulated customer flow".
Deterministic: same seed + same calls → same arrivals.

SKELETON (Phase 1): interface final; the Poisson draw and crowd multiplier are Phase 2.
"""

from __future__ import annotations

import random
from typing import TypedDict


class Surge(TypedDict):
    customers: int
    duration_min: int
    start_ts: str


class CustomerEvent(TypedDict):
    """Arrivals in one step. `orders` is what the cooking devices react to."""

    ts: str
    minutes: int
    arrivals: int
    orders: float
    customers_per_hour: float


# Weekday profile, customers per hour by local hour (synthetic: lunch ~12:00–13:30, dinner ~18:30–20:30).
DEFAULT_PROFILE: dict[int, float] = {
    10: 10, 11: 25, 12: 60, 13: 55, 14: 20, 15: 12, 16: 15, 17: 30, 18: 55, 19: 70, 20: 60, 21: 25,
}


class CustomerSource:
    def __init__(self, seed: int, profile: dict[int, float] | None = None, crowd_multiplier: float = 1.0) -> None:
        self._rng = random.Random(f"customers:{seed}")
        self.profile = dict(profile or DEFAULT_PROFILE)
        self.crowd_multiplier = crowd_multiplier  # from context (events nearby); 1.0 without context

    def events(self, ts: str, minutes: int, surges: list[Surge]) -> list[CustomerEvent]:
        """Arrivals for the step starting at `ts` lasting `minutes`, including any active surges."""
        raise NotImplementedError("Phase 2: seeded Poisson arrivals + surges + crowd multiplier")
