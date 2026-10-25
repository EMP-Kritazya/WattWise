"""Common building blocks for every contract model (docs/CONTRACTS.md).

Rules applied everywhere:
- `extra="forbid"`: an unknown key is a contract violation (one exception: `DevicePhysical`, see shapes.py).
- Enums are `Literal[...]`. Units live in field names.
- Timestamps are timezone-aware and must be UTC (`...Z`); local wall-clock times are `"HH:MM"` strings.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field


class ContractModel(BaseModel):
    """Base for every shared shape: unknown keys are rejected."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


def _require_utc(value: datetime) -> datetime:
    if value.utcoffset() != timedelta(0):
        raise ValueError("timestamps must be UTC (ISO 8601 with 'Z' or +00:00)")
    return value.astimezone(timezone.utc)


UtcDatetime = Annotated[AwareDatetime, AfterValidator(_require_utc)]
"""ISO 8601 timestamp in UTC. Sim time and real time use the same type."""

LocalTime = Annotated[str, Field(pattern=r"^(([01]\d|2[0-3]):[0-5]\d|24:00)$")]
"""Local wall-clock time `"HH:MM"` (`"24:00"` allowed as an end of day), in the kitchen's / tariff's timezone."""

YearMonth = Annotated[str, Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]
"""Billing / backtest month `"YYYY-MM"` (local calendar month)."""

Pct = Annotated[int, Field(ge=0, le=100)]
NonNegInt = Annotated[int, Field(ge=0)]
NonNegFloat = Annotated[float, Field(ge=0)]

Lane = Literal["without", "with"]
Importance = Literal["always_on", "flexible", "deferrable"]
PeakMode = Literal["cap", "minimize"]
