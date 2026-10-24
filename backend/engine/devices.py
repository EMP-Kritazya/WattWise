"""Simulated devices: one object per unit, power from its power model each step (design/SIMULATION.md).

Physical, not clever: no optimisation here. Deterministic (seeded), no clock, no I/O. Power is never negative and never
above `rated_kw`. Commands arrive only through the hub.

SKELETON (Phase 1): interfaces and shapes are final; the power models are Phase 2.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from engine.hub import Command, DeviceReading, DeviceState, DeviceView, Importance

POWER_MODELS = ("fixed", "cycling", "thermal", "demand_driven", "job")


@dataclass
class SimDevice:
    """One unit, e.g. `hvac_1`. Built from a KitchenConfig entry plus its EquipmentType."""

    device_id: str
    type_id: str
    name: str
    importance: Importance
    limits: dict
    rated_kw: float
    power_model: str
    params: dict
    rng: random.Random = field(repr=False)

    # live state
    state: DeviceState = "on"
    power_kw: float = 0.0
    source: str = "simulated"
    owed_kwh: float = 0.0  # flexible only: energy not drawn while reduced, repaid the same day (ENGINE.md 6b)
    measured_kw: float | None = None  # set by ingest of a real Reading; used for the next step only

    def step(self, *, ts: str, minutes: int, orders: float, outdoor_temp_c: float | None) -> None:
        """Advance `minutes`. `orders`: new food orders this step; `outdoor_temp_c`: for the thermal model (None → fixed
        summer-day curve). Updates `power_kw` and `state`, honouring any active command (reduce / delay / off / start)."""
        raise NotImplementedError("Phase 2: power models (fixed, cycling, thermal, demand_driven, job)")

    def apply(self, command: Command) -> None:
        """Take a command from the hub: on | off | start | delay (min) | reduce (power %) | restore."""
        raise NotImplementedError("Phase 2: command handling")

    def reading(self) -> DeviceReading:
        return {"device_id": self.device_id, "power_kw": round(self.power_kw, 6), "state": self.state, "source": self.source}  # type: ignore[typeddict-item]

    def view(self) -> DeviceView:
        return {
            "device_id": self.device_id,
            "type_id": self.type_id,
            "name": self.name,
            "importance": self.importance,
            "state": self.state,
            "power_kw": round(self.power_kw, 6),
            "rated_kw": self.rated_kw,
            "source": self.source,  # type: ignore[typeddict-item]
        }


def build_devices(config: dict, catalog: list[dict], seed: int) -> list[SimDevice]:
    """One SimDevice per unit in `config["equipment"]` (count 0 = absent). Ids are `<type_id>_<n>`.
    Each device gets its own RNG derived from `seed` and its id, so adding a device never changes another's run."""
    types = {t["type_id"]: t for t in catalog}
    out: list[SimDevice] = []
    for entry in config["equipment"]:
        t = types[entry["type_id"]]
        if t["power_model"] not in POWER_MODELS:
            raise ValueError(f"unknown power_model {t['power_model']!r} for {t['type_id']}")
        for n in range(1, entry["count"] + 1):
            device_id = f"{t['type_id']}_{n}"
            out.append(
                SimDevice(
                    device_id=device_id,
                    type_id=t["type_id"],
                    name=f"{t['name']} {n}",
                    importance=entry["importance"],
                    limits=dict(entry.get("limits") or t.get("default_limits") or {}),
                    rated_kw=float(t["rated_kw"]),
                    power_model=t["power_model"],
                    params=dict(t.get("params") or {}),
                    rng=random.Random(f"{seed}:{device_id}"),
                )
            )
    return out
