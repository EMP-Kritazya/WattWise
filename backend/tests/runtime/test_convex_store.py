"""store/convex_store.py: the Store interface over Convex. Every write lands in the mirror at once and goes out as the
matching mutation with exactly the `contracts/fixtures/convex/functions/` args, in order inside one `batch:apply` per flush;
Convex unreachable → `store_down` once and memory from then on; a rejected write is skipped.

The live check against a real deployment runs only with CONVEX_TEST_URL set (it writes the fixture rows there)."""

import json
import os
import threading
import time
import uuid

import httpx
import pytest

from api.settings import REPO_ROOT
from store import ConvexHttp, ConvexStore, MemoryStore, STORE_DOWN_WARNING, create_store

CONVEX = REPO_ROOT / "contracts" / "fixtures" / "convex"
FUNCTIONS = {f.stem: json.loads(f.read_text(encoding="utf-8")) for f in sorted((CONVEX / "functions").glob("*.json"))}

# Fixture function → the Store call that sends it.
WRITES = {
    "commands_enqueue": lambda s, a: s.record_command(a["command"], a["lane"], a["hub_id"]),
    "commands_ack": lambda s, a: s.ack_command(**a),
    "devices_report": lambda s, a: s.report_reading(a["reading"]),
    "decisions_record": lambda s, a: s.record_decisions(a["decisions"]),
    "proposals_upsert": lambda s, a: s.upsert_proposal(a["proposal"]),
    "bills_save": lambda s, a: s.save_bill(a["bill"], a["lane"]),
    "backtest_save": lambda s, a: s.save_backtest(a["run_id"], a["results"]),
}
ESP32_ONLY = {"hubs_heartbeat"}  # the runtime never calls it; covered by the live check


class Double:
    """Records calls like `convex.ConvexClient`; `fail` raises on every call."""

    def __init__(self, fail: Exception | None = None, answers: dict | None = None):
        self.calls: list[tuple[str, str, dict]] = []
        self.fail = fail
        self.answers = answers or {}

    def mutation(self, name, args=None):
        self.calls.append(("mutation", name, args))
        if self.fail:
            raise self.fail
        return None

    def query(self, name, args=None):
        self.calls.append(("query", name, args))
        if self.fail:
            raise self.fail
        return self.answers.get(name, [])


def batch(*writes):
    """The one call a flush makes: `batch:apply` with (function, args) pairs in order."""
    return ("mutation", "batch:apply", {"writes": [{"name": n, "args": a} for n, a in writes]})


def batched_names(client):
    return [w["name"] for kind, name, args in client.calls if name == "batch:apply" for w in args["writes"]]


def make(client, **kw):
    warnings = []
    store = ConvexStore(client=client, on_warning=warnings.append, autostart=False, **kw)
    return store, warnings


def test_every_function_fixture_is_covered():
    assert set(FUNCTIONS) == set(WRITES) | ESP32_ONLY | {"commands_forDevice"}


@pytest.mark.parametrize("name", sorted(WRITES))
def test_write_sends_the_fixture_mutation(name):
    fixture = FUNCTIONS[name]
    client = Double()
    store, warnings = make(client)
    assert WRITES[name](store, fixture["args"]) is None
    assert client.calls == []  # batched, not sent inline
    store.flush()
    assert client.calls == [batch((fixture["function"], fixture["args"]))]
    assert warnings == [] and store.kind == "convex"


def test_writes_land_in_the_mirror_before_any_flush():
    store, _ = make(Double())
    args = FUNCTIONS["decisions_record"]["args"]
    store.record_decisions(args["decisions"])
    assert store.decisions() == args["decisions"]


def test_large_queues_go_in_chunks():
    client = Double()
    store, _ = make(client)
    bill = FUNCTIONS["bills_save"]["args"]["bill"]
    for _ in range(250):
        store.save_bill(bill, "without")
    store.flush()
    assert [len(args["writes"]) for _, _, args in client.calls] == [100, 100, 50]


def test_batch_keeps_call_order():
    client = Double()
    store, _ = make(client)
    enqueue, ack = FUNCTIONS["commands_enqueue"]["args"], FUNCTIONS["commands_ack"]["args"]
    store.record_command(enqueue["command"], enqueue["lane"], "esp32_1")
    store.ack_command(**ack)
    store.flush()
    assert len(client.calls) == 1 and batched_names(client) == ["commands:enqueue", "commands:ack"]
    assert store.rows("commands")[0]["delivery"] == "acked"


def test_for_device_query_like_the_fixture():
    fixture = FUNCTIONS["commands_forDevice"]
    client = Double(answers={"commands:forDevice": fixture["returns"]})
    store, _ = make(client)
    assert store.commands_for_hub(**fixture["args"]) == fixture["returns"]
    assert client.calls == [("query", "commands:forDevice", fixture["args"])]


def test_readings_and_map_are_read_from_convex():
    reading = FUNCTIONS["devices_report"]["args"]["reading"]
    as_floats = {**reading, "channel": 0.0, "scale": 1000.0}  # Convex numbers come back as floats
    row = {"hub_id": "esp32_1", "channel": 0.0, "device_id": "dishwasher_1", "scale": 1000.0}
    client = Double(answers={"devices:latest": [as_floats], "devices:map": [row]})
    store, _ = make(client)
    assert store.latest_readings("esp32_1") == [reading]
    assert store.device_map() == [{**row, "channel": 0}]
    assert type(store.latest_readings("esp32_1")[0]["channel"]) is int


def test_unreachable_convex_switches_to_memory_once():
    client = Double(fail=RuntimeError("channel closed"))
    store, warnings = make(client)
    decisions = FUNCTIONS["decisions_record"]["args"]["decisions"]
    store.record_decisions(decisions)
    store.save_bill(FUNCTIONS["bills_save"]["args"]["bill"], "without")
    store.flush()
    assert warnings == [STORE_DOWN_WARNING]
    assert store.kind == "memory"
    assert len(client.calls) == 1  # the rest of the batch is dropped: the mirror already has it
    store.upsert_proposal(FUNCTIONS["proposals_upsert"]["args"]["proposal"])
    store.flush()
    assert len(client.calls) == 1 and warnings == [STORE_DOWN_WARNING]
    assert store.decisions() == decisions and len(store.proposals()) == 1 and len(store.bills()) == 1


def test_unreachable_on_a_read_falls_back_to_the_mirror():
    client = Double(fail=RuntimeError("channel closed"))
    store, warnings = make(client, seed_dir=CONVEX / "tables")
    assert store.device_map() == MemoryStore(CONVEX / "tables").device_map()
    assert warnings == [STORE_DOWN_WARNING] and store.kind == "memory"


def test_rejected_write_is_skipped_and_convex_stays_up():
    client = Double()
    store, warnings = make(client)
    calls = []

    def mutation(name, args=None):
        calls.append(name)
        if name in ("batch:apply", "bills:save"):  # the batch holds the bad bill, so it fails as a whole
            raise Exception("[Request ID: 1] Server Error\nArgumentValidationError: Value does not match validator.")

    client.mutation = mutation
    store.save_bill(FUNCTIONS["bills_save"]["args"]["bill"], "without")
    store.record_decisions(FUNCTIONS["decisions_record"]["args"]["decisions"])
    store.flush()
    assert calls == ["batch:apply", "bills:save", "decisions:record"]  # resent one by one; only the bill is lost
    assert warnings == [] and store.kind == "convex"


def test_a_stuck_call_counts_as_unreachable():
    release = threading.Event()
    client = Double()
    client.mutation = lambda name, args=None: release.wait(5)
    store, warnings = make(client, call_timeout_s=0.1)
    store.save_bill(FUNCTIONS["bills_save"]["args"]["bill"], "without")
    started = time.monotonic()
    store.flush()
    release.set()
    assert time.monotonic() - started < 2
    assert warnings == [STORE_DOWN_WARNING] and store.kind == "memory"


def test_background_thread_flushes_once_per_interval():
    client = Double()
    store = ConvexStore(client=client, flush_s=0.05)
    try:
        store.save_bill(FUNCTIONS["bills_save"]["args"]["bill"], "without")
        deadline = time.monotonic() + 2
        while not client.calls and time.monotonic() < deadline:
            time.sleep(0.01)
        assert batched_names(client) == ["bills:save"]
    finally:
        store.close()


def test_seed_fills_the_mirror_only():
    client = Double()
    store, _ = make(client, seed_dir=CONVEX / "tables")
    assert store.decisions() == MemoryStore(CONVEX / "tables").decisions()
    store.flush()
    assert client.calls == []


def test_create_store_with_a_url_builds_the_convex_store():
    store = create_store("convex", convex_url="https://example.convex.cloud")
    try:
        assert isinstance(store, ConvexStore) and store.kind == "convex"
        assert isinstance(store._client, ConvexHttp)  # not the GIL-holding Rust client
    finally:
        store.close()  # nothing queued: nothing is sent to the made-up deployment


def _http(handler):
    client = ConvexHttp("https://example.convex.cloud")
    client._http = httpx.Client(base_url="https://example.convex.cloud", transport=httpx.MockTransport(handler))
    return client


def test_http_transport_speaks_the_convex_http_api():
    seen = []

    def handler(request):
        seen.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={"status": "success", "value": None})

    store, _ = make(_http(handler))
    args = FUNCTIONS["bills_save"]["args"]
    store.save_bill(args["bill"], args["lane"])
    store.flush()
    assert seen == [("/api/mutation", {"path": "batch:apply", "args": batch(("bills:save", args))[2], "format": "json"})]


def test_http_error_answer_is_a_rejected_write():
    def handler(request):
        return httpx.Response(200, json={"status": "error", "errorMessage": "Server Error\nArgumentValidationError"})

    store, warnings = make(_http(handler))
    store.save_bill(FUNCTIONS["bills_save"]["args"]["bill"], "without")
    store.flush()
    assert warnings == [] and store.kind == "convex"


def test_http_transport_failure_is_store_down():
    def handler(request):
        raise httpx.ConnectError("connection refused")

    store, warnings = make(_http(handler))
    store.save_bill(FUNCTIONS["bills_save"]["args"]["bill"], "without")
    store.flush()
    assert warnings == [STORE_DOWN_WARNING] and store.kind == "memory"


def test_http_gateway_error_page_is_store_down():
    store, warnings = make(_http(lambda request: httpx.Response(502, text="<html>Bad Gateway</html>")))
    store.save_bill(FUNCTIONS["bills_save"]["args"]["bill"], "without")
    store.flush()
    assert warnings == [STORE_DOWN_WARNING]


# ---------------------------------------------------------------- live deployment (opt in)

LIVE_URL = os.environ.get("CONVEX_TEST_URL")


@pytest.mark.skipif(not LIVE_URL, reason="CONVEX_TEST_URL not set")
@pytest.mark.parametrize("name", sorted(FUNCTIONS))
def test_live_function_matches_the_fixture(name):
    from convex import ConvexClient

    fixture = FUNCTIONS[name]
    client = ConvexClient(LIVE_URL)
    args = fixture["args"]
    if name == "commands_forDevice":
        args = {"hub_id": f"test_{uuid.uuid4().hex[:8]}"}  # a hub nobody has queued for
    call = client.query if fixture["type"] == "query" else client.mutation
    assert call(fixture["function"], args) == fixture["returns"]


@pytest.mark.skipif(not LIVE_URL, reason="CONVEX_TEST_URL not set")
def test_live_batch_accepts_every_write_fixture():
    from convex import ConvexClient

    writes = [(FUNCTIONS[n]["function"], FUNCTIONS[n]["args"]) for n in sorted(WRITES)]
    assert ConvexClient(LIVE_URL).mutation("batch:apply", batch(*writes)[2]) is None


@pytest.mark.skipif(not LIVE_URL, reason="CONVEX_TEST_URL not set")
def test_live_store_round_trip():
    hub_id = f"test_{uuid.uuid4().hex[:8]}"
    store = ConvexStore(LIVE_URL, autostart=False)  # over the HTTP API
    try:
        # A device no kitchen has, so the test row never feeds a device bridge.
        row = {"hub_id": hub_id, "channel": 0, "device_id": f"{hub_id}_device", "scale": 1000}
        reading = {**FUNCTIONS["devices_report"]["args"]["reading"], "hub_id": hub_id, "device_id": row["device_id"]}
        command = {**FUNCTIONS["commands_enqueue"]["args"]["command"], "command_id": f"c_{hub_id}"}
        store.map_channel(row)
        store.report_reading(reading)
        store.record_command(command, "with", hub_id)
        store.flush()
        assert store.kind == "convex"
        assert row in store.device_map()
        assert store.latest_readings(hub_id) == [reading]
        assert store.commands_for_hub(hub_id) == [command]
        store.ack_command(command["command_id"], True, command["value"], None)
        store.flush()
        assert store.commands_for_hub(hub_id) == []
    finally:
        store.close()
