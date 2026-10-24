"""The one door to the engine (CONTRACTS.md §3), switched by `KITCHEN_IMPL=fake|real`.

`real` → `from engine import Kitchen, run_backtest, compare_lanes, RuleError` (the only engine import in the backend).
`fake` → `fakes.fake_kitchen`: canned answers from `contracts/fixtures/facade/`, plus the local `RuleError` below.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable


class RuleError(Exception):
    """Fake-mode RuleError: same name and meaning as the engine's (unsafe limits or moves). Mapped to HTTP 422."""


class NotRecordedError(LookupError):
    """STUB: fake mode has no recorded answer for this call. Mapped to HTTP 501; never answered with made-up data."""


@dataclass(frozen=True)
class EngineApi:
    impl: str
    Kitchen: Callable[..., Any]
    run_backtest: Callable[..., list[dict]]
    compare_lanes: Callable[[dict, dict], dict]
    RuleError: type[Exception]


def load_engine(impl: str | None = None) -> EngineApi:
    impl = impl or os.environ.get("KITCHEN_IMPL", "fake")
    if impl == "real":
        from engine import Kitchen, RuleError as EngineRuleError, compare_lanes, run_backtest

        return EngineApi("real", Kitchen, run_backtest, compare_lanes, EngineRuleError)
    if impl == "fake":
        from fakes.fake_kitchen import FakeKitchen, fake_compare_lanes, fake_run_backtest

        return EngineApi("fake", FakeKitchen, fake_run_backtest, fake_compare_lanes, RuleError)
    raise ValueError(f"KITCHEN_IMPL={impl!r}; expected 'fake' or 'real'")
