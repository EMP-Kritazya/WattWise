"""The production service constructs the real facade with canonical data."""
import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from api.service import KitchenService
from runtime.kitchen_factory import load_engine
from store.memory import MemoryStore

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "contracts" / "fixtures"


def config():
    return json.loads((FIXTURES / "shapes" / "kitchen_config.json").read_text())


def test_real_build_uses_canonical_catalog_and_configured_warmup_start(monkeypatch):
    calls = []
    start = "2026-08-02T17:00:00Z"

    def warmup(ts, *, tariff):
        calls.append((ts, tariff))
        return None

    monkeypatch.setattr("data.warmup.build_warmup", warmup)
    service = KitchenService(FIXTURES, load_engine("real"), MemoryStore(), start_sim_ts=start)
    body = config()
    original = copy.deepcopy(body)
    service.build_kitchen(body)

    assert body == original
    assert service.catalog() == json.loads((ROOT / "backend/data/equipment_catalog.json").read_text())
    assert service.get_kitchen()["tariff"]["tariff_id"] == body["tariff_id"]
    assert service.get_kitchen()["devices"]
    assert calls == [(datetime(2026, 8, 2, 17, tzinfo=timezone.utc), "demo")]
    assert service.lanes["without"].ids is service.lanes["with"].ids


def test_failed_tariff_change_preserves_running_kitchen(monkeypatch):
    monkeypatch.setattr("data.warmup.build_warmup", lambda *args, **kwargs: None)
    engine = load_engine("real")
    service = KitchenService(FIXTURES, engine, MemoryStore())
    body = config()
    service.build_kitchen(body)
    lanes = service.lanes
    body["tariff_id"] = "unknown"

    with pytest.raises(engine.RuleError, match="Unknown tariff_id"):
        service.build_kitchen(body)

    assert service.lanes is lanes
    assert service.tariff["tariff_id"] == "demo_tariff_v1"
    assert len(service.store.rows("kitchens")) == 1


def test_real_warmup_drops_history_for_devices_outside_selected_roster(monkeypatch):
    history = json.loads((FIXTURES / "history/warmup_demo_cafe.json").read_text())
    monkeypatch.setattr("data.warmup.build_warmup", lambda *args, **kwargs: history)
    service = KitchenService(FIXTURES, load_engine("real"), MemoryStore())
    body = config()
    body["equipment"] = body["equipment"][:1]

    service.build_kitchen(body)

    expected = {f"{body['equipment'][0]['type_id']}_{n}" for n in range(1, body["equipment"][0]["count"] + 1)}
    assert {d["device_id"] for d in service.get_kitchen()["devices"]} == expected


def test_catalog_calibration_failure_falls_back_to_labelled_fixture(monkeypatch, caplog):
    from data.recipe import RatedKwExceeded

    def exceeds(*args, **kwargs):
        raise RatedKwExceeded("dataset load above rating")

    monkeypatch.setattr("data.warmup.build_warmup", exceeds)
    service = KitchenService(FIXTURES, load_engine("real"), MemoryStore())
    history = service._warm_up_history()

    assert history["source"] == "fixture_synthetic"
    assert history["label"] == "simulated"
    assert "fixture_synthetic" in caplog.text


def test_fixture_fallback_cannot_warm_engine_with_future_blocks(monkeypatch):
    history = json.loads((FIXTURES / "history/warmup_demo_cafe.json").read_text())
    monkeypatch.setattr("data.warmup.build_warmup", lambda *args, **kwargs: history)
    service = KitchenService(FIXTURES, load_engine("real"), MemoryStore(),
                             start_sim_ts="2026-06-01T00:30:00Z")

    service.build_kitchen(config())

    assert service.lanes["with"].snapshot()["sim_ts"] == "2026-06-01T00:30:00Z"
