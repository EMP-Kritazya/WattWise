"""Current 120-tick fixture through REST, the hub, both lanes and live publishing.

Recorded engine output opens an escalation at tick 50. Runtime mirrors the
recording; terminal transitions belong to the engine and are never synthesized.
"""
import json

from agent.claude_agent import ClaudeAgent, Turn
from api.settings import REPO_ROOT
from contracts import PublishTicksPayload
from runtime.live_port import RecordingLive, WsLive

FIXTURES = REPO_ROOT / "contracts" / "fixtures"


def load(rel):
    return json.loads((FIXTURES / rel).read_text())


def lines(rel):
    return [json.loads(line) for line in (FIXTURES / rel).read_text().splitlines() if line.strip()]


SCENARIO = load("scenario/demo_cafe/scenario.json")
STEPS = {(row["returns"]["lane"], row["returns"]["hub"]["tick_id"]): row["returns"]
         for row in lines("facade/step_stream.jsonl")}
ESCALATION_TICK = next(tick for (lane, tick), state in STEPS.items()
                       if lane == "with" and state["new_escalations"])


class ScriptedLLM:
    def __init__(self):
        choice = load("ai_tools/choose_escalation_option.json")["input"]
        use = ("choice", "choose_escalation_option", choice)
        self.turns = [Turn([{"type": "tool_use", "id": use[0], "name": use[1], "input": choice}],
                           [use], "tool_use"),
                      Turn([{"type": "text", "text": "Done."}], [], "end_turn")]

    async def turn(self, **kwargs):
        return self.turns.pop(0)


async def run_scenario(serve, *, claude=False):
    async with serve(live_transport="ws") as srv:
        viewer = []

        async def collect(message):
            viewer.append(message)

        live = RecordingLive(inner=WsLive(collect))
        srv.runtime.live.use(live)
        srv.runtime.autorun = False
        if claude:
            srv.runtime.escalations.agent = ClaudeAgent(srv.app.state.agent_tools, ScriptedLLM(),
                                                        publish=srv.app.state.broadcaster.send_soon)
        await srv.connect_fake_hub()
        assert (await srv.http.post("/api/kitchen", json=SCENARIO["config"])).status_code == 200
        assert (await srv.http.post("/api/context", json=load("shapes/context.json"))).status_code == 200
        assert (await srv.http.post("/api/sim/control", json={"action": "play"})).status_code == 200
        for tick in range(1, SCENARIO["ticks"] + 1):
            assert await srv.runtime.tick_once(), f"tick {tick}"
            if tick == ESCALATION_TICK:
                await srv.runtime.escalations.idle()
        await srv.runtime.flush()
        sent = [msg for msg in srv.hub_client.received if msg["type"] == "sim_tick"]
        assert len(sent) == SCENARIO["ticks"]
        for message in sent:
            tick = message["tick_id"]
            expected = [] if tick == 1 else [command for lane in ("without", "with")
                                             for command in STEPS[(lane, tick - 1)]["new_commands"]]
            assert message["commands"] == expected
            assert message["minutes"] == 1
        payloads = [json.loads(args[0]) for args in live.calls_to("publish_ticks")]
        assert len(payloads) == SCENARIO["ticks"]
        for payload in payloads:
            PublishTicksPayload.model_validate(payload)
        assert payloads == lines("spacetime/rows_stream.jsonl")
        ticks = [message["data"] for message in viewer if message["type"] == "tick"]
        assert ticks == [STEPS[(lane, tick)] for tick in range(1, SCENARIO["ticks"] + 1)
                         for lane in ("without", "with")]
        assert all(args[1] == 120 for args in live.calls_to("set_clock"))
        assert srv.runtime.tick_id == SCENARIO["ticks"]
        escalations = [json.loads(args[0]) for args in live.calls_to("publish_escalation")]
        stored = srv.app.state.store.escalations()
        return escalations, stored


async def test_demo_cafe_scenario_claude_resolves_e_0001(serve):
    escalations, stored = await run_scenario(serve, claude=True)
    assert [row["status"] for row in escalations] == ["open", "resolved"]
    assert escalations[-1]["chosen_option_id"] == "accept_overrun"
    assert escalations[-1]["resolved_by"] == "claude"
    assert [row for row in stored if row["escalation_id"] == "e_0001"] == [
        load("shapes/escalation_resolved_claude.json")]


async def test_demo_cafe_scenario_without_claude_preserves_engine_fallback(serve):
    escalations, stored = await run_scenario(serve)
    assert [row["status"] for row in escalations] == ["open"]
    assert escalations[0]["active_option_id"] == "accept_overrun"
    # Fake mode starts with historical durable records; no terminal update is
    # emitted by this stream, so runtime preserves that seed without alteration.
    assert stored == load("convex/tables/escalations.json")
