"""data/tariff_urdb.py: URDB record -> CONTRACTS.md Tariff (golden rule 6: values unchanged)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from contracts import Tariff
from data.tariff_urdb import B19_FILE, convert_urdb, load_urdb_tariff
from data.tariffs import DEMO_TARIFF, load_tariff

REPO = Path(__file__).resolve().parents[3]
B19_FIXTURE = REPO / "contracts" / "fixtures" / "shapes" / "tariff_pge_b19.json"
needs_b19 = pytest.mark.skipif(not B19_FILE.exists(), reason=f"dataset/ is gitignored: {B19_FILE} is absent")


@needs_b19
def test_b19_conversion_equals_the_fixture_exactly():
    """Same entry names, order and values as contracts/fixtures/shapes/tariff_pge_b19.json (Kritazya's decision 2)."""
    assert load_urdb_tariff(B19_FILE) == json.loads(B19_FIXTURE.read_text())


@needs_b19
def test_b19_fixed_charge_is_per_day_from_the_structured_field():
    t = load_urdb_tariff(B19_FILE)
    assert t["fixed_charges"] == [{"name": "customer_charge", "usd": 11.36882, "per": "day"}]
    assert t["label"] == "urdb" and t["tariff_id"] == "pge_b19_secondary_voluntary"


@needs_b19
def test_b19_demand_charges_and_seasons():
    t = load_urdb_tariff(B19_FILE)
    by = {c["name"]: c for c in t["demand"]}
    assert [c["name"] for c in t["demand"]] == ["max_demand", "peak_demand_winter", "peak_demand_summer",
                                                "part_peak_demand_summer"]
    assert by["max_demand"]["usd_per_kw"] == 37.37 and by["max_demand"]["months"] is None
    assert by["peak_demand_summer"]["months"] == [6, 7, 8, 9] and by["peak_demand_summer"]["usd_per_kw"] == 46.16
    assert by["part_peak_demand_summer"]["windows"] == [{"start": "14:00", "end": "16:00"}, {"start": "21:00", "end": "23:00"}]
    assert by["peak_demand_winter"]["months"] == [1, 2, 3, 4, 5, 10, 11, 12] and by["peak_demand_winter"]["usd_per_kw"] == 2.31


def _record(**over):
    flat = [[0] * 24 for _ in range(12)]
    rec = {
        "label": "test_rate", "name": "Test rate",
        "energyratestructure": [[{"rate": 0.10}], [{"rate": 0.30}]],
        "energyweekdayschedule": [[0] * 16 + [1] * 5 + [0] * 3 for _ in range(12)],
        "energyweekendschedule": [[0] * 24 for _ in range(12)],
        "flatdemandstructure": [[{"rate": 10.0}]], "flatdemandmonths": [0] * 12,
        "demandratestructure": [[{"rate": 0}], [{"rate": 5.0}]],
        "demandweekdayschedule": [[0] * 16 + [1] * 5 + [0] * 3 for _ in range(12)],
        "demandweekendschedule": flat,
        "fixedchargefirstmeter": 20.0, "fixedchargeunits": "$/month",
    }
    rec.update(over)
    return rec


def test_unknown_rate_gets_generic_names_and_weekday_weekend_split():
    t = convert_urdb(_record())
    Tariff.model_validate(t)
    assert t["tariff_id"] == "urdb_test_rate"
    # weekdays: wrap-around off-peak 21:00-16:00 then peak; weekends: one all-day entry
    assert [(e["name"], e["start"], e["end"], e["days"]) for e in t["energy"]] == [
        ("period_0", "21:00", "16:00", "weekdays"), ("period_1", "16:00", "21:00", "weekdays"),
        ("period_0", "00:00", "24:00", "weekends")]
    assert t["demand"][0] == {"name": "max_demand", "windows": None, "months": None, "days": "all", "usd_per_kw": 10.0}
    assert t["demand"][1]["days"] == "weekdays" and t["demand"][1]["windows"] == [{"start": "16:00", "end": "21:00"}]
    assert t["fixed_charges"] == [{"name": "customer_charge", "usd": 20.0, "per": "month"}]


def test_tiered_energy_is_refused():
    with pytest.raises(ValueError, match="tiered"):
        convert_urdb(_record(energyratestructure=[[{"rate": 0.1}, {"rate": 0.2}], [{"rate": 0.3}]]))


def test_demo_tariff_is_the_contract_example_and_validates():
    t = load_tariff("demo")
    Tariff.model_validate(t)
    assert t == DEMO_TARIFF and t["label"] == "illustrative" and t["tariff_id"] == "demo_tariff_v1"
