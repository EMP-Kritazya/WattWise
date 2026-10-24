"""The two kitchens side by side (CONTRACTS.md §3): `without` (no control) and `with` (WattWise).

Both are built from the same KitchenConfig, tariff and seed through `runtime/kitchen_factory.py`, and step on the same
hub_report (each on its own lane's HubReport), so the only difference between them is the engine's control.
"""

from __future__ import annotations

from typing import Any, Iterator

from runtime.kitchen_factory import EngineApi

LANES = ("without", "with")


class Lanes:
    def __init__(self, engine: EngineApi, tariff: dict):
        self._engine = engine
        self._tariff = tariff
        self._kitchens: dict[str, Any] = {}
        self.config: dict | None = None
        self.seed: int | None = None

    def build(self, config: dict, seed: int) -> None:
        """Replace both lanes. A RuleError from either leaves the previous lanes untouched."""
        # warm_up(...) is TBD (CONTRACTS.md §3); not called until its signature exists.
        kitchens = {lane: self._engine.Kitchen(config, self._tariff, lane, seed) for lane in LANES}
        self._kitchens, self.config, self.seed = kitchens, config, seed

    def step(self, minutes: int, hub_report: dict) -> dict[str, dict]:
        """`step(minutes, report)` on both lanes, each with its own HubReport → {lane: TickState}."""
        return {lane: self._kitchens[lane].step(minutes, hub_report["reports"][lane]) for lane in LANES}

    def compare(self, states: dict[str, dict]) -> dict:
        return self._engine.compare_lanes(states["without"], states["with"])

    def __getitem__(self, lane: str) -> Any:
        return self._kitchens[lane]

    def __bool__(self) -> bool:
        return bool(self._kitchens)

    def __iter__(self) -> Iterator[Any]:
        return (self._kitchens[lane] for lane in LANES)
