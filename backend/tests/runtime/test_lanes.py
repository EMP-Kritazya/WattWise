"""Focused two-lane construction tests for the engine facade seam."""

from types import SimpleNamespace

from runtime.lanes import Lanes


def test_build_uses_shared_factory_and_warms_each_lane_once_in_order():
    events: list[tuple] = []

    class Kitchen:
        def __init__(self, lane: str):
            self.lane = lane

        def warm_up(self, history: dict) -> None:
            events.append(("warm_up", self.lane, history))

    built = {"without": Kitchen("without"), "with": Kitchen("with")}

    def build_lanes(config: dict, tariff: dict, seed: int) -> dict[str, Kitchen]:
        events.append(("build_lanes", config, tariff, seed))
        return built

    lanes = Lanes(SimpleNamespace(build_lanes=build_lanes), {"tariff_id": "test"})
    config, history = {"seed": 9}, {"source": "test", "blocks": []}

    lanes.build(config, 9, history)

    assert events == [
        ("build_lanes", config, {"tariff_id": "test"}, 9),
        ("warm_up", "without", history),
        ("warm_up", "with", history),
    ]
    assert lanes["without"] is built["without"] and lanes["with"] is built["with"]


def test_build_skips_warm_up_when_no_history_is_available():
    calls: list[str] = []

    class Kitchen:
        def warm_up(self, history: dict) -> None:
            calls.append("warm_up")

    kitchens = {"without": Kitchen(), "with": Kitchen()}
    lanes = Lanes(SimpleNamespace(build_lanes=lambda *_: kitchens), {"tariff_id": "test"})

    lanes.build({}, 42)

    assert calls == []
