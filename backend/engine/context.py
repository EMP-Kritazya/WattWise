"""Context (ENGINE.md section 2): structured context merged as plain data; the engine never fetches it.

Crowd effect -> multiplier on `demand_driven` forecasts; prices -> tie-break only; weather -> kept and returned.
Missing or stale -> last known value, then multiplier 1.00. Numbers are stored unchanged (golden rule 6).
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta
from typing import Any, Optional

from contracts import PartialContext

CROWD_MULTIPLIERS: dict[str, float] = {"none": 1.00, "small": 1.10, "medium": 1.25, "large": 1.40}
SECTIONS = ("weather", "prices", "events", "crowd_effect")
HOUR = timedelta(hours=1)


class ContextState:
    def __init__(self) -> None:
        self._merged: Optional[dict] = None

    def merge(self, context: Any) -> None:
        """Partial post: every section present (non-null) replaces that section; `ts` is the latest post's."""
        data = context.model_dump(mode="json") if hasattr(context, "model_dump") else context
        post = PartialContext.model_validate(data).model_dump(mode="json")
        merged = self._merged or {"ts": None, **{s: None for s in SECTIONS}}
        if post["ts"] is not None:
            merged["ts"] = post["ts"]
        for section in SECTIONS:
            if post[section] is not None:
                merged[section] = post[section]
        self._merged = merged

    def current(self) -> Optional[dict]:
        return copy.deepcopy(self._merged)

    def crowd_multiplier(self) -> float:
        crowd = (self._merged or {}).get("crowd_effect")
        if not crowd:
            return 1.0
        return CROWD_MULTIPLIERS[crowd["value"]]

    def price_usd_per_kwh(self, ts: datetime) -> Optional[float]:
        """Context grid price of the hour containing `ts` (tie-breaks only; never the bill), None if unknown."""
        prices = (self._merged or {}).get("prices")
        if not prices:
            return None
        for hour in prices["hourly"]:
            start = datetime.fromisoformat(hour["ts"].replace("Z", "+00:00"))
            if start <= ts < start + HOUR:
                return hour["usd_per_kwh"]
        return None
