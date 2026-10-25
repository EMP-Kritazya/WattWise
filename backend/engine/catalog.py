"""Equipment type facts from the catalog the runtime passes in (CONTRACTS.md section 3; ENGINE.md section 0).

`Kitchen(config, tariff, catalog, control, seed, ids=None)` receives `catalog` = list[EquipmentType] (the runtime loads
`backend/data/equipment_catalog.json`; the engine reads no files, golden rule 7). The engine takes each type's
`category` (food-safety floor), `power_model` (crowd multiplier on `demand_driven`, job holds), `rated_kw` and `params`
(e.g. `cycle_min`) from it, per kitchen, and keeps no module-level copy.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from contracts import EquipmentType

from .rules import RuleError


@dataclass(frozen=True)
class TypeFacts:
    type_id: str
    name: str
    category: str
    power_model: str
    rated_kw: float
    params: Mapping[str, float] = field(default_factory=dict)


# STUB: TickState.indoor_temp_c is a required float, but a kitchen without a thermal device reports no indoor
# temperature. Until the contract says what to send, the engine falls back to this value (design question).
DEFAULT_INDOOR_TEMP_C = 22.5


def type_facts_from(catalog: Iterable[Any]) -> Mapping[str, TypeFacts]:
    """type_id -> TypeFacts for one kitchen. Entries may be EquipmentType models or plain dicts."""
    facts: dict[str, TypeFacts] = {}
    for entry in catalog:
        t = entry if isinstance(entry, EquipmentType) else EquipmentType.model_validate(entry)
        if t.type_id in facts:
            raise RuleError(f"catalog lists type {t.type_id!r} twice")
        facts[t.type_id] = TypeFacts(t.type_id, t.name, t.category, t.power_model, t.rated_kw, MappingProxyType(dict(t.params)))
    return MappingProxyType(facts)


def lookup(facts: Mapping[str, TypeFacts], type_id: str) -> TypeFacts:
    """An unknown type fails loudly (RuleError) rather than guessing a category: a guess could cross the food-safety floor."""
    try:
        return facts[type_id]
    except KeyError:
        raise RuleError(f"equipment type {type_id!r} is not in the catalog passed to the Kitchen") from None
