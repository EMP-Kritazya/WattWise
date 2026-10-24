"""The equipment catalog matches the EquipmentType contract and its default limits are safe."""

IMPORTANCE = {"always_on", "flexible", "deferrable"}
CATEGORIES = {"cooling", "refrigeration", "cooking", "water_heating", "lighting", "other"}
MODELS = {"fixed", "cycling", "thermal", "demand_driven", "job"}
FIELDS = {
    "type_id", "name", "category", "default_importance", "rated_kw", "min_power_pct",
    "power_model", "params", "default_limits", "source_note",
}


def test_every_entry_has_exactly_the_contract_fields(catalog):
    for t in catalog:
        assert set(t) == FIELDS, t["type_id"]


def test_values_are_in_range(catalog):
    ids = [t["type_id"] for t in catalog]
    assert len(ids) == len(set(ids))
    for t in catalog:
        assert t["default_importance"] in IMPORTANCE
        assert t["category"] in CATEGORIES
        assert t["power_model"] in MODELS
        assert t["rated_kw"] > 0
        assert t["source_note"]


def test_default_limits_match_importance(catalog):
    for t in catalog:
        limits = t["default_limits"]
        if t["default_importance"] == "always_on":
            assert limits == {}, t["type_id"]
        elif t["default_importance"] == "flexible":
            assert 0 < limits["min_power_pct"] <= 100 and limits["max_reduce_min"] > 0, t["type_id"]
        else:
            hh, mm = limits["must_finish_by"].split(":")
            assert limits["max_delay_min"] > 0 and 0 <= int(hh) < 24 and 0 <= int(mm) < 60, t["type_id"]


def test_refrigeration_food_safety_floor(catalog):
    """A refrigeration device set to flexible must keep min_power_pct >= 50 (CONTRACTS.md, ENGINE.md)."""
    for t in catalog:
        if t["category"] == "refrigeration" and t["default_importance"] == "flexible":
            assert t["default_limits"]["min_power_pct"] >= 50, t["type_id"]


def test_job_types_have_a_cycle(catalog):
    for t in catalog:
        if t["power_model"] == "job":
            assert t["params"]["cycle_min"] > 0, t["type_id"]
