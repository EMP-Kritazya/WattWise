"""The 120-tick Demo Café scenario end to end, at full speed: KITCHEN_IMPL=fake, HUB_IMPL=fake (the recorded sim host on a
real `/ws/hub`), RecordingLive in front of WsLive. Timeline from `contracts/fixtures/scenario/demo_cafe/`: recorded context
posted at tick 0, a judge's surge request after tick 30, the context refresh before tick 61.

e_0001 opens at tick 60. With Claude (mocked) it chooses `extend_delay_dishwasher` before tick 61; with Claude off it
expires to the engine's default after tick 70 (its deadline). The escalation slowdown (clock to 1×) is not built (open
question Q1), so the slowed / restored clock messages of `ws/stream.jsonl` are left out of the comparison.
"""

import json

import pytest

from agent.claude_agent import ClaudeAgent, Turn
from api.settings import REPO_ROOT
from runtime.live_port import LiveRows, RecordingLive, WsLive, compact_json

FIXTURES = REPO_ROOT / "contracts" / "fixtures"
SCENARIO = json.loads((FIXTURES / "scenario" / "demo_cafe" / "scenario.json").read_text(encoding="utf-8"))
TICKS = SCENARIO["ticks"]


def load(rel):
    return json.loads((FIXTURES / rel).read_text(encoding="utf-8"))


def load_jsonl(rel):
    return [json.loads(line) for line in (FIXTURES / rel).read_text(encoding="utf-8").splitlines() if line.strip()]


def reducer(name):
    return load(f"spacetime/reducers/{name}.json")


AGENT_LOG = load_jsonl("agents/agent_log.jsonl")
FIRST_FETCH, REFRESH = AGENT_LOG[:9], AGENT_LOG[9:]
SURGE_REQUEST = {**load("spacetime/tables/surge_request.json")[0], "consumed": False}  # as inserted by request_surge
SURGE_REQUESTED_AFTER_TICK = 30
CONTEXT_REFRESH_BEFORE_TICK = 61
ESCALATION_TICK = 60
CHOICE = load("ai_tools/choose_escalation_option.json")["input"]


class ScriptedLLM:
    """Stands in for AnthropicLLM: plays back Turns in order."""

    def __init__(self, *turns):
        self.turns = list(turns)

    async def turn(self, **_):
        return self.turns.pop(0)


def claude_choosing(tool_input):
    """Claude's two turns on an escalation: the enum tool with `tool_input`, then a closing sentence."""
    use = ("t1", "choose_escalation_option", tool_input)
    return ScriptedLLM(Turn([{"type": "tool_use", "id": use[0], "name": use[1], "input": use[2]}], [use], "tool_use"),
                       Turn([{"type": "text", "text": "Done."}], [], "end_turn"))


async def run_scenario(srv, llm=None):
    """Drive the whole scenario through the REST API and `tick_once`. → (RecordingLive, /ws messages).
    `llm` set → Claude (mocked) decides e_0001; the test waits for it before tick 61, as the slowed clock would."""
    if llm is not None:
        app = srv.app
        srv.runtime.escalations.agent = ClaudeAgent(app.state.agent_tools, llm, publish=app.state.broadcaster.send_soon)
    viewer = []

    async def collect(message):
        viewer.append(json.loads(json.dumps(message)))

    live = RecordingLive(inner=WsLive(collect))
    srv.runtime.live.use(live)
    srv.runtime.autorun = False  # the test is the clock: one tick_once per sim minute, no sleeping
    await srv.connect_fake_hub()

    assert (await srv.http.post("/api/kitchen", json=SCENARIO["config"])).json() == {"kitchen_id": SCENARIO["kitchen_id"]}
    play = load("rest/post_sim_control.json")
    assert (await srv.http.post(play["path"], json=play["request"])).json() == play["response"]
    assert (await srv.http.post("/api/context", json=load("shapes/context.json"))).json() == {"ok": True}
    for entry in FIRST_FETCH:
        assert (await srv.http.post("/api/agent-log", json=entry)).json() == {"ok": True}

    for n in range(1, TICKS + 1):
        if n == SURGE_REQUESTED_AFTER_TICK + 1:
            live.surge_requests.append(dict(SURGE_REQUEST))
        if n == CONTEXT_REFRESH_BEFORE_TICK:
            for entry in REFRESH:
                await srv.http.post("/api/agent-log", json=entry)
            assert (await srv.http.post("/api/context", json=load("agents/context_post.json")["body"])).status_code == 200
        assert await srv.runtime.tick_once() is True, f"tick {n}"
        if n == ESCALATION_TICK:
            await srv.runtime.escalations.idle()
    await srv.runtime.flush()
    return live, viewer


async def scenario(serve, llm=None):
    """The scenario run plus every check that does not depend on how e_0001 ends."""
    async with serve(live_transport="ws") as srv:
        live, viewer = await run_scenario(srv, llm)
        received = list(srv.hub_client.received)
        store = srv.app.state.store
        calls, viewer = list(live.calls), list(viewer)  # before shutdown publishes sim_host_offline
    live.calls = calls

    # ---- hub: the sim_tick stream, incl. commands at n + 1 and surge s_0001 in tick 31
    sent = [m for m in received if m["type"] in ("hub_welcome", "sim_build", "sim_tick")]
    expected = load_jsonl("hub_protocol/server_to_hub.jsonl")
    assert len(sent) == len(expected)
    for got, want in zip(sent, expected):
        assert got == want, f"{want['type']} {want.get('tick_id')}"
    assert [m for m in received if m["type"] == "sim_control"] == [load("hub_protocol/sim_control.json")]
    assert sent[2 + 30]["surges"] == [{"surge_id": "s_0001", "customers": 40, "duration_min": 60}]

    # ---- SpacetimeDB reducer calls
    assert {c["reducer"] for c in live.calls} == {
        "reset_all", "set_clock", "publish_context", "log_agent", "consume_surge", "publish_ticks", "publish_feed",
        "publish_escalation",
    }
    assert live.calls_to("reset_all") == [reducer("reset_all")["args"]]
    assert live.calls_to("consume_surge") == [reducer("consume_surge")["args"]]

    ticks = live.calls_to("publish_ticks")
    assert [json.loads(args[0]) for args in ticks] == load_jsonl("spacetime/rows_stream.jsonl")
    assert ticks[-1] == reducer("publish_ticks")["args"]

    feed = live.calls_to("publish_feed")
    assert [json.loads(args[0]) for args in feed] == load("spacetime/tables/live_feed.json")
    assert feed[0] == reducer("publish_feed")["args"]

    assert live.calls_to("set_clock")[-1] == reducer("set_clock")["args"]
    assert live.calls_to("set_clock")[0] == [False, 120, SCENARIO["start_sim_ts"], 0, None, None, "connected"]  # built

    contexts = live.calls_to("publish_context")
    assert len(contexts) == 2
    assert contexts[-1] == reducer("publish_context")["args"]
    assert [json.loads(a[0]) for a in contexts[-1:]] == load("spacetime/tables/live_context.json")

    logs = live.calls_to("log_agent")
    assert logs[0] == reducer("log_agent")["args"]
    assert [json.loads(a[0]) for a in logs] == [
        {k: v for k, v in row.items() if k != "id"} for row in load("spacetime/tables/live_agent_log.json")
    ]

    # ---- store buffer: decisions with their template explanations (Convex `decisions`)
    assert store.decisions() == load("convex/tables/decisions.json")
    return live, viewer, received, store


def viewer_after_play(viewer):
    first_play = next(i for i, m in enumerate(viewer) if m["type"] == "clock" and m["playing"])
    stopped = {"type": "clock", "playing": False, "speed": 120, "sim_ts": SCENARIO["start_sim_ts"], "tick_id": 0,
               "paused_reason": None, "slowed_reason": None}
    assert viewer[:first_play] == [stopped, stopped]  # the host connects, then the build (reset_all) re-sends it
    return viewer[first_play:]


def stream_without_slowdown():
    """`ws/stream.jsonl` without the slowed / restored clock around e_0001 → (stream, index of the resolved e_0001)."""
    stream = load_jsonl("ws/stream.jsonl")
    slowdown = [i for i, m in enumerate(stream) if m["type"] == "clock" and m["slowed_reason"] == "escalation"]
    assert len(slowdown) == 1
    at = slowdown[0]
    assert stream[at + 1]["type"] == "escalation" and stream[at + 2]["type"] == "clock"
    del stream[at + 2], stream[at]
    return stream, at


@pytest.mark.xfail(reason="fixtures predate CONTRACTS 10528e2", strict=False)
async def test_demo_cafe_scenario_claude_resolves_e_0001(serve):
    live, viewer, received, store = await scenario(serve, claude_choosing(CHOICE))

    # ---- SpacetimeDB: e_0001 opened at tick 60, then resolved by Claude (reducers/publish_escalation.json)
    opened, resolved = load("shapes/escalation_open.json"), load("shapes/escalation_resolved_claude.json")
    assert live.calls_to("publish_escalation") == [
        [compact_json(LiveRows.escalation(opened))],
        reducer("publish_escalation")["args"],
    ]
    assert json.loads(reducer("publish_escalation")["args"][0]) == LiveRows.escalation(resolved)

    # ---- the chosen option's Command (a new one, with its Decision) goes out after the engine's next step: tick 62
    option = next(o for o in resolved["options"] if o["option_id"] == CHOICE["option_id"])
    device_id = option["actions"][0]["device_id"]
    ticks = {m["tick_id"]: m for m in received if m["type"] == "sim_tick"}
    delivered = [c for c in ticks[62]["commands"] if c["device_id"] == device_id]
    assert [(c["action"], c["value"]) for c in delivered] == [(a["action"], a["value"]) for a in option["actions"]]
    assert (delivered[0]["command_id"], delivered[0]["decision_id"]) == ("c_0008", "d_0005")
    assert not any(c["device_id"] == device_id for n in range(55, 62) for c in ticks[n]["commands"])

    # ---- /ws: the fixture stream (open + resolved e_0001), without the slowdown clock messages
    stream, _ = stream_without_slowdown()
    assert viewer_after_play(viewer) == stream

    # ---- Convex `escalations`: the final state
    assert [e for e in store.escalations() if e["escalation_id"] == "e_0001"] == [resolved]


@pytest.mark.xfail(reason="fixtures predate CONTRACTS 10528e2", strict=False)
async def test_demo_cafe_scenario_without_claude_expires_to_the_default(serve):
    """No ANTHROPIC_API_KEY: the loop never waits, e_0001 stays open, and once its deadline has passed (after tick 70)
    the engine's default stands: `expired_default`, stored and published."""
    live, viewer, _, store = await scenario(serve)

    opened, expired = load("shapes/escalation_open.json"), load("shapes/escalation_expired_default.json")
    assert [json.loads(a[0]) for a in live.calls_to("publish_escalation")] == [
        LiveRows.escalation(opened), LiveRows.escalation(expired)]
    assert [e for e in store.escalations() if e["escalation_id"] == "e_0001"] == [expired]

    stream, at = stream_without_slowdown()
    del stream[at]  # no resolved e_0001 before tick 61
    after_deadline = next(i for i, m in enumerate(stream)
                          if m["type"] == "tick" and m["data"]["ts"] > expired["deadline_sim_ts"])
    stream.insert(after_deadline, {"type": "escalation", "data": expired})
    assert viewer_after_play(viewer) == stream
