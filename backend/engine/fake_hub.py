"""FakeHub: same interface as `hub.Hub` (CONTRACTS.md section 8), with simple deterministic power and commands honoured
trivially. Kritazya builds the brain against this until the real devices exist (design/SIMULATION.md).

Power per device is a smooth daily curve (busier at lunch and dinner) scaled by its rated kW. No randomness, no clock:
the same `ts` always gives the same report.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from engine.hub import Command, DeviceReading, DeviceState, DeviceView, HubReport, UnknownDevice

# Local restaurant time for the daily curve (PDT in the July demo; good enough for a fake).
_LOCAL = timezone(timedelta(hours=-7))


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _busy(ts: str) -> float:
    """0..1: quiet morning, lunch peak ~12:45, dinner peak ~19:30, closed overnight."""
    local = _parse(ts).astimezone(_LOCAL)
    h = local.hour + local.minute / 60
    if h < 10 or h >= 22:
        return 0.0
    bump = lambda mu, s: math.exp(-0.5 * ((h - mu) / s) ** 2)  # noqa: E731
    return min(1.0, 0.25 + 0.7 * bump(12.75, 0.8) + 0.8 * bump(19.5, 1.0))


class FakeHub:
    """Fake devices built from a KitchenConfig and the equipment catalog (both plain dicts, contract-shaped)."""

    def __init__(self, config: dict, catalog: list[dict]) -> None:
        types = {t["type_id"]: t for t in catalog}
        self._units: dict[str, dict] = {}
        for entry in config["equipment"]:
            t = types[entry["type_id"]]
            for n in range(1, entry["count"] + 1):
                device_id = f"{t['type_id']}_{n}"
                self._units[device_id] = {
                    "device_id": device_id,
                    "type_id": t["type_id"],
                    "name": f"{t['name']} {n}",
                    "importance": entry["importance"],
                    "rated_kw": float(t["rated_kw"]),
                    # owner/engine overrides, set by deliver()
                    "override": None,  # None | "off" | ("reduce", pct) | ("delay", until_dt) | ("start", until_dt)
                }
        self._last_ts: str | None = None
        self.log: list[Command] = []

    # ----- contract (section 8) -----

    def report(self, ts: str) -> HubReport:
        self._last_ts = ts
        readings = [self._reading(u, ts) for u in self._units.values()]
        total = round(sum(r["power_kw"] for r in readings), 6)
        return {"ts": ts, "total_kw": total, "devices": readings, "source": "simulated"}

    def deliver(self, command: Command) -> None:
        unit = self._units.get(command["device_id"])
        if unit is None:
            raise UnknownDevice(command["device_id"])
        at = _parse(command["ts"])
        action, value = command["action"], command["value"]
        if action == "off":
            unit["override"] = "off"
        elif action in ("on", "restore"):
            unit["override"] = None
        elif action == "reduce":
            unit["override"] = ("reduce", float(value if value is not None else 50))
        elif action == "delay":
            unit["override"] = ("delay", at + timedelta(minutes=float(value or 0)))
        elif action == "start":
            unit["override"] = ("start", at + timedelta(minutes=30))
        self.log.append(command)

    def devices(self) -> list[DeviceView]:
        ts = self._last_ts
        out: list[DeviceView] = []
        for u in self._units.values():
            r = self._reading(u, ts) if ts else {"power_kw": 0.0, "state": "off"}
            out.append(
                {
                    "device_id": u["device_id"],
                    "type_id": u["type_id"],
                    "name": u["name"],
                    "importance": u["importance"],
                    "state": r["state"],
                    "power_kw": r["power_kw"],
                    "rated_kw": u["rated_kw"],
                    "source": "simulated",
                }
            )
        return out

    # ----- internals -----

    def _reading(self, u: dict, ts: str) -> DeviceReading:
        natural = round(u["rated_kw"] * (0.15 + 0.6 * _busy(ts)), 4)
        state: DeviceState = "on"
        power = natural
        o = u["override"]
        now = _parse(ts)
        if o == "off":
            state, power = "off", 0.0
        elif isinstance(o, tuple) and o[0] == "reduce":
            state, power = "reduced", round(natural * o[1] / 100, 4)
        elif isinstance(o, tuple) and o[0] == "delay":
            if now < o[1]:
                state, power = "waiting", 0.0
            else:
                u["override"] = None
        elif isinstance(o, tuple) and o[0] == "start":
            if now < o[1]:
                state, power = "running_job", u["rated_kw"]
            else:
                u["override"] = None
        return {"device_id": u["device_id"], "power_kw": power, "state": state, "source": "simulated"}
