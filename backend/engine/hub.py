"""The hub: the single box every device reports to (CONTRACTS.md section 8, design/SIMULATION.md).

The brain only ever talks to a hub: readings out (`report`), commands in (`deliver`), current state (`devices`).
A real ESP32 replaces this object's outputs without changing the interface. Pure Python, no I/O, no wall clock.
"""

from __future__ import annotations

from typing import Literal, Protocol, TypedDict

# STUB: these mirror the JSON shapes in docs/CONTRACTS.md section 1 until Kritazya's Pydantic models land in
# backend/contracts/. When they do, import those instead and delete these definitions.

Importance = Literal["always_on", "flexible", "deferrable"]
DeviceState = Literal["off", "on", "reduced", "waiting", "running_job"]
CommandAction = Literal["on", "off", "start", "delay", "reduce", "restore"]
Source = Literal["simulated", "measured"]


class DeviceReading(TypedDict):
    device_id: str
    power_kw: float
    state: DeviceState
    source: Source


class HubReport(TypedDict):
    ts: str
    total_kw: float
    devices: list[DeviceReading]
    source: Literal["simulated", "mixed"]


class DeviceView(TypedDict):
    device_id: str
    type_id: str
    name: str
    importance: Importance
    state: DeviceState
    power_kw: float
    rated_kw: float
    source: Source


class Command(TypedDict):
    command_id: str
    ts: str
    device_id: str
    action: CommandAction
    value: float | None
    decision_id: str | None
    issued_by: Literal["engine", "owner"]


class HubLike(Protocol):
    """What the brain may use. Both `Hub` and `FakeHub` implement exactly this."""

    def report(self, ts: str) -> HubReport: ...

    def deliver(self, command: Command) -> None: ...

    def devices(self) -> list[DeviceView]: ...


class UnknownDevice(KeyError):
    """A command named a device this hub doesn't have."""


class Hub:
    """The simulated ESP32 hub over the simulated devices in `engine/devices.py`.

    Besides the three contract calls it has `advance(...)`, which moves every device forward one step. The contract
    doesn't say who drives the devices; `kitchen.py` calls `advance` once per `step()` before `report`.
    QUESTION for Kritazya: is that the split you want, or should `kitchen.py` step the devices itself?
    """

    def __init__(self, devices: list) -> None:  # list[devices.SimDevice]
        self._devices = {d.device_id: d for d in devices}
        self.log: list[Command] = []  # every command delivered, in order
        # Food orders are split evenly across the cooking (demand_driven) equipment.
        cooks = [d for d in devices if d.power_model == "demand_driven"]
        for d in cooks:
            d.cook_share = 1 / len(cooks)

    # ----- contract (section 8) -----

    def report(self, ts: str) -> HubReport:
        readings = [d.reading() for d in self._devices.values()]
        total = round(sum(r["power_kw"] for r in readings), 6)
        measured = any(r["source"] == "measured" for r in readings)
        return {"ts": ts, "total_kw": total, "devices": readings, "source": "mixed" if measured else "simulated"}

    def deliver(self, command: Command) -> None:
        device = self._devices.get(command["device_id"])
        if device is None:
            raise UnknownDevice(command["device_id"])
        device.apply(command)
        self.log.append(command)

    def devices(self) -> list[DeviceView]:
        return [d.view() for d in self._devices.values()]

    # ----- simulation driver -----

    def advance(self, ts: str, minutes: int, orders: float, outdoor_temp_c: float | None) -> None:
        """Step every device `minutes` forward. `orders`: new food orders this step (from customer arrivals)."""
        for d in self._devices.values():
            d.step(ts=ts, minutes=minutes, orders=orders, outdoor_temp_c=outdoor_temp_c)

    def ingest_reading(self, device_id: str, power_kw: float) -> DeviceView:
        """A real ESP32 reading: that device uses `power_kw` (source "measured") on the next advance only (ENGINE.md 6c)."""
        device = self._devices.get(device_id)
        if device is None:
            raise UnknownDevice(device_id)
        device.measured_kw = max(0.0, float(power_kw))
        return device.view()
