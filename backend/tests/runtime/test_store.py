"""MemoryStore: seeded from contracts/fixtures/convex/tables/, writes match the convex/functions/ fixtures."""

import json

import pytest

from api.settings import REPO_ROOT
from store import MemoryStore, create_store

CONVEX = REPO_ROOT / "contracts" / "fixtures" / "convex"
TABLE_FILES = sorted((CONVEX / "tables").glob("*.json"))


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _fn(name):
    return _load(CONVEX / "functions" / f"{name}.json")["args"]


def _table(name):
    return _load(CONVEX / "tables" / f"{name}.json")


@pytest.fixture
def seeded():
    return MemoryStore(CONVEX / "tables")


@pytest.mark.parametrize("table_file", TABLE_FILES, ids=[f.stem for f in TABLE_FILES])
def test_seed_loads_every_table_unchanged(seeded, table_file):
    assert seeded.rows(table_file.stem) == _load(table_file)


def test_unseeded_store_is_empty():
    store = MemoryStore()
    assert store.latest_kitchen() is None
    assert store.decisions() == [] and store.proposals() == [] and store.escalations() == []
    assert store.backtest_run_ids() == []


def test_record_decisions_like_convex_function():
    store = MemoryStore()
    args = _fn("decisions_record")
    store.record_decisions(args["decisions"])
    assert store.rows("decisions") == args["decisions"]


def test_record_decisions_upserts_by_id(seeded):
    first = seeded.decisions()[0]
    seeded.record_decisions([{**first, "status": "undone"}])
    assert len(seeded.decisions()) == len(_table("decisions"))
    assert seeded.decisions()[0]["status"] == "undone"
    assert seeded.decisions(lane="without") == [d for d in _table("decisions") if d["lane"] == "without"]


def test_record_command_like_convex_function():
    store = MemoryStore()
    args = _fn("commands_enqueue")
    store.record_command(args["command"], args["lane"], args["hub_id"])
    assert store.rows("commands") == [{**args["command"], "lane": args["lane"], "hub_id": args["hub_id"], "delivery": "queued"}]


def test_upsert_proposal_like_convex_function(seeded):
    proposal = _fn("proposals_upsert")["proposal"]
    store = MemoryStore()
    store.upsert_proposal({**proposal, "status": "pending", "confirmed_via": None})
    store.upsert_proposal(proposal)
    assert store.rows("proposals") == [proposal]
    assert store.proposal(proposal["proposal_id"]) == proposal
    assert store.proposal("p_9999") is None
    assert store.proposals("confirmed") == [proposal] and store.proposals("pending") == []


def test_save_bill_like_convex_function():
    store = MemoryStore()
    args = _fn("bills_save")
    store.save_bill(args["bill"], args["lane"])
    assert store.rows("bills") == [{**args["bill"], "lane": args["lane"]}]


def test_save_backtest_like_convex_function():
    store = MemoryStore()
    args = _fn("backtest_save")
    store.save_backtest(args["run_id"], args["results"])
    assert store.rows("backtest_results") == [{**r, "run_id": args["run_id"]} for r in args["results"]]
    assert store.backtest(args["run_id"]) == args["results"]
    assert store.backtest("run_9999") is None
    assert store.backtest_run_ids() == [args["run_id"]]


def test_seeded_backtest_strips_run_id(seeded):
    rows = _table("backtest_results")
    assert seeded.backtest("run_0001") == [{k: v for k, v in r.items() if k != "run_id"} for r in rows]


def test_blocks_escalations_context_kitchens():
    store = MemoryStore()
    store.record_device_blocks(_table("device_blocks"))
    assert store.rows("device_blocks") == _table("device_blocks")

    escalation = _table("escalations")[0]
    store.record_escalation({**escalation, "status": "open"})
    store.record_escalation(escalation)
    assert store.escalations() == [escalation]

    store.record_context_snapshot(_table("context_snapshots")[0])
    assert store.rows("context_snapshots") == _table("context_snapshots")

    kitchen = _table("kitchens")[0]
    store.record_kitchen(kitchen["config"], kitchen["created_at"])
    assert store.latest_kitchen() == kitchen


def test_reads_are_copies(seeded):
    seeded.proposals()[0]["status"] = "expired"
    seeded.rows("decisions").clear()
    assert seeded.proposals() == _table("proposals")
    assert seeded.decisions() == _table("decisions")


def test_create_store():
    assert isinstance(create_store("memory"), MemoryStore)
    # No CONVEX_URL: same fallback as Convex being unreachable.
    assert isinstance(create_store("convex"), MemoryStore)
    with pytest.raises(ValueError):
        create_store("sqlite")


def test_command_ack_like_convex_function():
    store = MemoryStore()
    enqueue, ack = _fn("commands_enqueue"), _fn("commands_ack")
    store.record_command(enqueue["command"], enqueue["lane"], "esp32_1")
    assert store.commands_for_hub("esp32_1") == [enqueue["command"]]
    assert store.ack_command(**ack) is None
    assert store.rows("commands")[0]["delivery"] == "acked"
    assert store.commands_for_hub("esp32_1") == []  # executed: no longer waiting
    store.ack_command("c_9999", True, None, None)  # unknown id: ignored


def test_failed_ack_marks_failed():
    store = MemoryStore()
    enqueue = _fn("commands_enqueue")
    store.record_command(enqueue["command"], enqueue["lane"], "esp32_1")
    store.ack_command(enqueue["command"]["command_id"], False, None, "job_running")
    assert store.rows("commands")[0]["delivery"] == "failed"


def test_commands_for_device_like_convex_function(seeded):
    fixture = _load(CONVEX / "functions" / "commands_forDevice.json")
    # The recorded commands are simulated only (hub_id null), so the ESP32 has nothing waiting.
    assert seeded.commands_for_hub(**fixture["args"]) == fixture["returns"]


def test_devices_report_and_latest_like_convex_function(seeded):
    reading = _fn("devices_report")["reading"]
    store = MemoryStore()
    for row in _table("device_map"):
        store.map_channel(row)
    assert store.latest_readings("esp32_1") == []
    store.report_reading({**reading, "ts": "2026-07-18T02:24:00Z", "raw_w": 5.1, "power_kw": 5.1})
    assert store.report_reading(reading) is None
    assert store.latest_readings("esp32_1") == [reading]
    assert store.latest_readings("esp32_2") == []
    assert seeded.latest_readings("esp32_1") == _table("readings")


def test_map_channel_replaces_the_same_channel():
    store = MemoryStore()
    row = _table("device_map")[0]
    store.map_channel(row)
    store.map_channel({**row, "device_id": "ice_machine_1"})
    assert store.device_map() == [{**row, "device_id": "ice_machine_1"}]
