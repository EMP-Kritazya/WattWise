"""CustomerSource: seeded customer arrivals from an hourly profile, plus surges (design/SIMULATION.md).

The run loop creates ONE source and passes the same events to both lanes. Labelled "simulated customer flow".
Deterministic: same seed + same calls → same arrivals.

Rate (customers/hour) = profile at the local time (linear between hours, 0 when closed) × crowd multiplier
+ each active surge's customers spread evenly over its duration. Arrivals in a step are a seeded Poisson draw;
each customer places one food order.
"""

from __future__ import annotations

import math
import random
from datetime import timedelta
from typing import TypedDict

from engine.devices import local_hour, parse_ts


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

    def rate_per_hour(self, ts: str, surges: list[Surge]) -> float:
        """Customers/hour at `ts`: the profile (× crowd multiplier) plus every active surge."""
        h = local_hour(ts)
        lo = int(math.floor(h))
        base = 0.0
        if lo in self.profile:  # closed hours aren't in the profile → 0; ramps toward the next hour's value
            base = self.profile[lo] + (self.profile.get(lo + 1, 0.0) - self.profile[lo]) * (h - lo)
        rate = base * self.crowd_multiplier
        now = parse_ts(ts)
        for s in surges:
            start = parse_ts(s["start_ts"])
            if start <= now < start + timedelta(minutes=s["duration_min"]):
                rate += s["customers"] * 60 / s["duration_min"]
        return rate

    def events(self, ts: str, minutes: int, surges: list[Surge]) -> list[CustomerEvent]:
        """Arrivals for the step starting at `ts` lasting `minutes`, including any active surges."""
        rate = self.rate_per_hour(ts, surges)
        arrivals = self._poisson(rate * minutes / 60)
        return [
            {
                "ts": ts,
                "minutes": minutes,
                "arrivals": arrivals,
                "orders": float(arrivals),
                "customers_per_hour": round(rate, 2),
            }
        ]

    def _poisson(self, mean: float) -> int:
        # Knuth's method; means here are small (a few customers per minute), so this is fast and exact.
        if mean <= 0:
            return 0
        limit, k, prod = math.exp(-mean), 0, self._rng.random()
        while prod > limit:
            k += 1
            prod *= self._rng.random()
        return k
