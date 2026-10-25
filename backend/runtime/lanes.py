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

    def build(self, config: dict, seed: int, history: dict | None = None) -> None:
        """Replace both lanes from one shared engine id allocator.

        ``Kitchen.build_lanes`` is the only construction path for a production
        run.  Building first, warming the temporary lanes, and assigning only
        afterwards keeps the previous run intact if construction or warm-up
        rejects its input.
        """
        kitchens = self._engine.build_lanes(config, self._tariff, seed)
        if history is not None:
            for lane in LANES:
                kitchens[lane].warm_up(history)
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
