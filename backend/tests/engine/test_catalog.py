"""The equipment catalog is passed in, never copied (CONTRACTS.md section 3, ENGINE.md section 0).

    Kitchen(config, tariff, catalog, control, seed, ids=None)
    Kitchen.build_lanes(config, tariff, catalog, seed)

`catalog` = list[EquipmentType] (the runtime loads `backend/data/equipment_catalog.json`; tests load
`contracts/fixtures/shapes/equipment_catalog.json` by path through `conftest.catalog()`). Every `config.equipment[].type_id`
must be in it, else RuleError. The engine takes `category`, `power_model`, `rated_kw` and `params` from it and keeps no copy
(golden rule 7: it reads no files, so it can't load one either).

Written before the code (engine-test-author); no expected value comes from engine output.
"""
from __future__ import annotations

import ast
import copy
import importlib
import pkgutil
from collections.abc import Mapping
from pathlib import Path

import pytest

from contracts import EquipmentType, KitchenConfig

from tests.engine.conftest import catalog, load_config, load_tariff


def _config() -> dict:
    return load_config().model_dump(mode="json")


def _tariff() -> dict:
    return load_tariff().model_dump(mode="json")


def _type_ids() -> set[str]:
    return {e["type_id"] for e in catalog()}


# A type the fixture catalog doesn't have; contract-valid (cycling params, refrigeration flexible >= 50).
BLAST_CHILLER = {
    "type_id": "blast_chiller", "name": "Blast chiller", "category": "refrigeration", "default_importance": "flexible",
    "rated_kw": 2.0, "power_model": "cycling", "params": {"duty_idle_pct": 30, "duty_busy_pct": 60},
    "default_limits": {"min_power_pct": 50, "max_reduce_min": 30}, "source_note": "test-only type",
}


# =====================================================================================================================
# Construction with the catalog argument
# =====================================================================================================================


def test_kitchen_and_build_lanes_take_the_catalog():
    from engine import Kitchen

    Kitchen(_config(), _tariff(), catalog(), "with", 42)
    lanes = Kitchen.build_lanes(_config(), _tariff(), catalog(), 42)
    assert set(lanes) == {"without", "with"}


def test_catalog_accepted_as_contract_models_too():
    from engine import Kitchen

    # plain objects in; a list of EquipmentType models carries the same data
    Kitchen(_config(), _tariff(), [EquipmentType.model_validate(e) for e in catalog()], "without", 42)


def test_unknown_type_id_in_config_raises_rule_error():
    from engine import Kitchen, RuleError

    config = _config()
    config["equipment"].append({"type_id": "pizza_oven", "count": 1, "importance": "always_on", "limits": {}})
    KitchenConfig.model_validate(config)  # the contract shape is fine; only the catalog lookup fails
    with pytest.raises(RuleError):
        Kitchen(config, _tariff(), catalog(), "with", 42)
    with pytest.raises(RuleError):
        Kitchen.build_lanes(config, _tariff(), catalog(), 42)


def test_type_missing_from_the_passed_catalog_raises_rule_error():
    from engine import Kitchen, RuleError

    # Demo Café has lights_1; a catalog without "lights" can't describe it -> RuleError (no fallback to a built-in copy)
    cat = [e for e in catalog() if e["type_id"] != "lights"]
    with pytest.raises(RuleError):
        Kitchen(_config(), _tariff(), cat, "with", 42)


def test_engine_reads_a_type_only_the_passed_catalog_knows():
    from engine import Kitchen, RuleError

    EquipmentType.model_validate(BLAST_CHILLER)
    cat = catalog() + [copy.deepcopy(BLAST_CHILLER)]
    config = _config()
    config["equipment"].append({"type_id": "blast_chiller", "count": 1, "importance": "flexible",
                                "limits": {"min_power_pct": 50, "max_reduce_min": 30}})
    # known only through the argument -> builds (a built-in copy would not know it)
    Kitchen(config, _tariff(), cat, "with", 42)

    # its category comes from the argument too: refrigeration -> flexible needs min_power_pct >= 50; 40 < 50 -> RuleError
    config["equipment"][-1]["limits"] = {"min_power_pct": 40, "max_reduce_min": 30}
    with pytest.raises(RuleError):
        Kitchen(config, _tariff(), cat, "with", 42)

    # and its power_model: refrigeration + cycling set deferrable -> RuleError (ENGINE.md section 8)
    config["equipment"][-1].update(importance="deferrable", limits={"max_delay_min": 30, "must_finish_by": "22:00"})
    with pytest.raises(RuleError):
        Kitchen(config, _tariff(), cat, "with", 42)


def test_category_change_in_passed_catalog_is_honoured():
    from engine import Kitchen, RuleError

    # water_heater is water_heating in the fixture: flexible min 40 is fine. Relabel it refrigeration in the passed
    # catalog -> 40 < 50 food-safety floor -> RuleError. Proves category is read from the argument, not a copy.
    cat = catalog()
    for e in cat:
        if e["type_id"] == "water_heater":
            e["category"] = "refrigeration"
            e["default_limits"] = {"min_power_pct": 50, "max_reduce_min": 30}
    for e in cat:
        EquipmentType.model_validate(e)
    Kitchen(_config(), _tariff(), catalog(), "with", 42)  # original: builds
    with pytest.raises(RuleError):
        Kitchen(_config(), _tariff(), cat, "with", 42)  # Demo Café water_heater flexible {40, 30}


# =====================================================================================================================
# The engine package holds no copy of the catalog
# =====================================================================================================================


def _engine_dir() -> Path:
    import engine

    return Path(engine.__file__).resolve().parent


def _non_docstring_strings(tree: ast.AST) -> set[str]:
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))
    return {
        n.value for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings
    }


def test_no_engine_source_file_embeds_catalog_type_entries():
    # A file whose code literals name 3+ catalog type_ids is a copied catalog (one stray name could be a comment-like
    # constant; a table of types is not). Docstrings and comments are ignored.
    ids = _type_ids()
    offenders = {}
    for py in sorted(_engine_dir().rglob("*.py")):
        found = _non_docstring_strings(ast.parse(py.read_text())) & ids
        if len(found) >= 3:
            offenders[py.name] = sorted(found)
    assert offenders == {}, f"engine modules embed catalog entries: {offenders}"


def _looks_like_catalog(value, ids: set[str]) -> bool:
    if isinstance(value, Mapping):
        return len(ids & {k for k in value.keys() if isinstance(k, str)}) >= 3
    if isinstance(value, (list, tuple, set, frozenset)):
        names = set()
        for item in value:
            tid = item.get("type_id") if isinstance(item, Mapping) else getattr(item, "type_id", None)
            if isinstance(tid, str):
                names.add(tid)
        return len(ids & names) >= 3
    return False


def test_no_engine_module_defines_a_catalog_constant():
    # e.g. engine.catalog.CATALOG / TYPE_FACTS / _TYPES: no module-level mapping or sequence describing catalog types
    import engine

    ids = _type_ids()
    offenders = []
    for info in pkgutil.walk_packages(engine.__path__, prefix="engine."):
        mod = importlib.import_module(info.name)
        for name, value in vars(mod).items():
            if _looks_like_catalog(value, ids):
                offenders.append(f"{info.name}.{name}")
    assert offenders == []


def test_two_kitchens_with_different_catalogs_do_not_share_type_facts():
    from engine import Kitchen, RuleError

    # building one kitchen with a relabelled catalog must not leak into the next kitchen (no module-level cache)
    cat = catalog()
    for e in cat:
        if e["type_id"] == "water_heater":
            e["category"] = "refrigeration"
            e["default_limits"] = {"min_power_pct": 50, "max_reduce_min": 30}
    with pytest.raises(RuleError):
        Kitchen(_config(), _tariff(), cat, "with", 42)
    Kitchen(_config(), _tariff(), catalog(), "with", 42)  # fixture catalog again: water_heating, min 40 ok
