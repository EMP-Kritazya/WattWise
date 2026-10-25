"""The runtime adapter drives the canonical client and preserves contract rows."""
import json
from pathlib import Path
import pytest
from contracts import PublishTicksPayload, LiveEscalationRow
from live.spacetime_client import SpacetimeClient
from runtime.live_port import SpacetimeLive, LivePublisher, WsLive

FIX = Path(__file__).resolve().parents[3] / "contracts" / "fixtures"
def load(name):
    return json.loads((FIX / name).read_text())

class Transport:
    def __init__(self): self.calls = []
    def call(self, reducer, args): self.calls.append((reducer, args))
    def sql(self, query): return []

async def test_actual_client_receives_canonical_ticks_and_escalation_rows():
    transport = Transport()
    client = SpacetimeClient(transport, autostart=False)
    port = SpacetimeLive(client)
    port.start()
    try:
        stream = [json.loads(line) for line in (FIX / "facade/step_stream.jsonl").read_text().splitlines()]
        states = {line["returns"]["lane"]: line["returns"] for line in stream[:2]}
        comparison = load("shapes/lane_comparison.json")
        await port.publish_ticks(1, states, comparison)
        await port.publish_escalation(load("shapes/escalation_open.json"))
        assert client.flush()
        tick_args = next(args for name, args in transport.calls if name == "publish_ticks")
        payload = PublishTicksPayload.model_validate_json(tick_args[0])
        assert all(row.demand_peaks_json is not None for row in payload.live_tick)
        escalation = next(args for name, args in transport.calls if name == "publish_escalation")
        assert LiveEscalationRow.model_validate_json(escalation[0]).claude_attempts_json == "[]"
    finally:
        await port.close()

async def test_failed_client_switches_to_ws_and_retains_warning_for_new_viewers():
    from api.ws import Broadcaster
    class FailedClient:
        def stats(self):
            from types import SimpleNamespace
            return SimpleNamespace(healthy=False)
    broadcaster = Broadcaster()
    publisher = LivePublisher(SpacetimeLive(FailedClient()), fallback=WsLive(broadcaster.broadcast),
                              on_warning=broadcaster.broadcast)
    publisher.send("publish_context", load("shapes/context.json"))
    await publisher.flush()
    assert isinstance(publisher.port, WsLive)
    assert broadcaster._live_warning["code"] == "live_transport_down"
    await publisher.stop()
