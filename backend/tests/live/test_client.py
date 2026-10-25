"""SpacetimeClient behaviour (SPACETIMEDB.md "Python client"): never blocks, latest tick wins, events never dropped,
retries after a transport error, surges read once and consumed, wire encoding of Option args. Uses FakeLive (in-memory
transport) and a gated transport that blocks until the test releases it."""
from __future__ import annotations

import json
import threading
import time

import pytest

from fakes.fake_live import FakeLive, InMemoryTransport
from live import SpacetimeClient
from live.spacetime_client import decode_value, encode_option

from tests.engine.conftest import FIXTURES
from tests.live.test_rows import reducer_args, step_states_by_tick, ws_stream

SP = FIXTURES / "spacetime"


class GatedTransport(InMemoryTransport):
    """Every call waits on `gate` (a stalled network)."""

    def __init__(self) -> None:
        super().__init__()
        self.gate = threading.Event()
        self.entered = threading.Event()

    def call(self, reducer, args):
        self.entered.set()
        assert self.gate.wait(5), "test never released the gate"
        super().call(reducer, args)


def tick_pairs():
    states = step_states_by_tick()
    comps = [m["data"] for m in ws_stream() if m["type"] == "comparison"]
    return [(states[t], comps[i]) for i, t in enumerate(sorted(states))]


def test_publish_never_blocks_on_a_stalled_transport_and_latest_tick_wins():
    transport = GatedTransport()
    client = SpacetimeClient(transport, surge_poll_s=0)
    pairs = tick_pairs()
    client.publish(*pairs[0])
    assert transport.entered.wait(2)  # tick 1 is in flight, stuck
    t0 = time.monotonic()
    for st, cmp in pairs[1:]:
        client.publish(st, cmp)
    assert time.monotonic() - t0 < 0.5  # 119 publishes while the network is stuck: no waiting
    assert client.stats().dropped_ticks == 118  # ticks 2..119 replaced by the next one
    transport.gate.set()
    assert client.flush(5)
    sent = [json.loads(a[0]) for r, a in transport.calls if r == "publish_ticks"]
    assert [p["live_tick"][0]["tick_id"] for p in sent] == [1, 120]  # in-flight tick, then the latest
    client.close()


def test_events_are_never_dropped_and_keep_their_order():
    transport = GatedTransport()
    client = SpacetimeClient(transport, surge_poll_s=0)
    decisions = [m for m in ws_stream() if m["type"] == "decision"]
    for st, cmp in tick_pairs()[:3]:
        client.publish(st, cmp)
    for m in decisions:
        client.publish_feed(m["data"], "with", m["explanation"])
    transport.gate.set()
    assert client.flush(5)
    feed = [json.loads(a[0])["decision_id"] for r, a in transport.calls if r == "publish_feed"]
    assert feed == [m["data"]["decision_id"] for m in decisions]  # all 16, in order
    assert len(transport.rows("live_feed")) == 16
    client.close()


def test_transport_error_is_retried_and_stats_report_it():
    transport = InMemoryTransport()
    transport.fail_next = 2
    client = FakeLive(transport, surge_poll_s=0)
    msg = next(m for m in ws_stream() if m["type"] == "decision")
    client.publish_feed(msg["data"], "with", msg["explanation"])
    assert client.flush(5)
    s = client.stats()
    assert s.errors == 2 and s.sent == 1 and s.healthy and s.backlog == 0
    assert [r for r, _ in transport.calls] == ["publish_feed"]
    client.close()


def test_failed_tick_is_superseded_by_a_newer_one():
    transport = InMemoryTransport()
    transport.fail_next = 1
    client = SpacetimeClient(transport, surge_poll_s=0, retry_backoff_s=0.2)
    pairs = tick_pairs()
    client.publish(*pairs[0])
    time.sleep(0.05)  # first attempt fails; worker backs off
    client.publish(*pairs[1])
    assert client.flush(5)
    sent = [json.loads(a[0])["live_tick"][0]["tick_id"] for r, a in transport.calls if r == "publish_ticks"]
    assert sent[-1] == 2
    assert transport.rows("live_tick")[0]["tick_id"] == 2
    client.close()


def test_surges_read_once_consumed_and_never_block():
    client = FakeLive()
    ids = client.seed_fixture_surges()
    sid = client.request_surge(20, 30)
    deadline = time.monotonic() + 2
    got = []
    while time.monotonic() < deadline and len(got) < 2:
        got += client.consume_surges()
        time.sleep(0.02)
    assert [s["id"] for s in got] == ids + [sid]
    assert got[0]["customers"] == 40 and got[0]["duration_min"] == 60
    assert client.flush(2)
    assert all(r["consumed"] for r in client.transport.rows("surge_request"))
    time.sleep(0.15)
    assert client.consume_surges() == []  # each id once
    client.close()


def test_reset_all_drops_pending_state_and_clears_tables():
    client = FakeLive(surge_poll_s=0)
    pairs = tick_pairs()
    for st, cmp in pairs[:5]:
        client.publish(st, cmp)
    assert client.flush(2)
    client.reset_all()
    assert client.flush(2)
    for table in ("live_tick", "live_device", "live_comparison", "tick_history"):
        assert client.transport.rows(table) == []
    client.close()


def test_wire_encoding_of_set_clock_option():
    table = json.loads((SP / "tables" / "live_clock.json").read_text())[0]
    clock = {k: v for k, v in table.items() if k not in ("id", "sim_host")}
    for encoding, want in (("sats", {"none": []}), ("null", None)):
        transport = InMemoryTransport()
        client = SpacetimeClient(transport, surge_poll_s=0, option_encoding=encoding)
        args = client.set_clock(clock, "connected")
        assert args == reducer_args("set_clock")  # the payload is the fixture's
        assert client.flush(2)
        assert transport.calls[0][1][4] == want  # the wire carries the encoding
        assert transport.rows("live_clock")[0]["paused_reason"] is None
        client.close()
    assert encode_option("manual", "sats") == {"some": "manual"}
    assert decode_value({"some": 3}) == 3 and decode_value({"none": []}) is None


def test_invalid_rows_are_refused_before_queueing():
    client = FakeLive(surge_poll_s=0)
    msg = next(m for m in ws_stream() if m["type"] == "decision")
    with pytest.raises(Exception):
        client.publish_feed(msg["data"], "both", msg["explanation"])  # lane must be without | with
    assert client.stats().backlog == 0
    client.close()


def test_every_reducer_fixture_through_fake_live():
    client = FakeLive(surge_poll_s=0)
    pairs = tick_pairs()
    for st, cmp in pairs:
        client.publish(st, cmp)
        client.flush(2)
    esc = [m["data"] for m in ws_stream() if m["type"] == "escalation"][-1]
    client.publish_escalation(esc)
    ctx = [m["data"] for m in ws_stream() if m["type"] == "context"][-1]
    client.publish_context(ctx)
    point = json.loads((FIXTURES / "ws" / "backtest_point.json").read_text())
    client.reset_backtest(point["run_id"])
    client.publish_backtest_point(point["run_id"], point["data"])
    assert client.flush(2)
    calls = {r: a for r, a in client.transport.calls}
    for name in ("publish_ticks", "publish_escalation", "publish_context", "publish_backtest_point", "reset_backtest"):
        assert calls[name] == reducer_args(name), name
    want_tick = json.loads((SP / "tables" / "live_tick.json").read_text())
    assert client.transport.rows("live_tick") == sorted(want_tick, key=lambda r: r["lane"])
    client.close()


def test_g73_escalation_notification_is_published_with_attempt_verdict():
    esc = next(m["data"] for m in ws_stream() if m["type"] == "escalation")
    client = FakeLive(surge_poll_s=0)
    try:
        row = client.publish_escalation(esc, "Claude explained the engine verdict.", "ai")
        assert row["explanation"] == "Claude explained the engine verdict."
        assert row["explanation_source"] == "ai"
        assert json.loads(row["claude_attempts_json"]) == esc["claude_attempts"]
        assert client.flush(5)
        assert client.transport.rows("live_escalation")[0]["explanation_source"] == "ai"
    finally:
        client.close()
