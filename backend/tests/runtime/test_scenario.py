"""The 120-tick Demo Café scenario end to end, at full speed: KITCHEN_IMPL=fake, HUB_IMPL=fake (the recorded sim host on a
real `/ws/hub`), RecordingLive in front of WsLive. Timeline from `contracts/fixtures/scenario/demo_cafe/`: recorded context
posted at tick 0, a judge's surge request after tick 30, the context refresh before tick 61.

Escalation slowdown (clock to 1× while e_0001 is open) and Claude's resolution are not built yet, so the open e_0001 is
published and the slowed / resolved messages of `ws/stream.jsonl` are left out of the comparison.
"""

import json

from api.settings import REPO_ROOT
from runtime.live_port import RecordingLive, WsLive

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


async def run_scenario(srv):
    """Drive the whole scenario through the REST API and `tick_once`. → (RecordingLive, /ws messages)."""
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
    await srv.runtime.flush()
    return live, viewer


async def test_demo_cafe_scenario(serve):
    async with serve(live_transport="ws") as srv:
        live, viewer = await run_scenario(srv)
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

    # Contract question: reducers/publish_escalation.json is e_0001 *resolved* (needs runtime/escalations.py);
    # this step publishes it as opened by the engine at tick 60.
    opened = load("shapes/escalation_open.json")
    resolved_row = json.loads(reducer("publish_escalation")["args"][0])
    assert [json.loads(a[0]) for a in live.calls_to("publish_escalation")] == [{
        **resolved_row, "status": "open", "chosen_option_id": opened["chosen_option_id"],
        "resolved_by": opened["resolved_by"], "rationale": opened["rationale"],
    }]
    assert json.loads(resolved_row["problem_json"]) == opened["problem"]
    assert json.loads(resolved_row["options_json"]) == opened["options"]

    # ---- /ws (LIVE_TRANSPORT=ws): the fixture stream from the play clock on, without the escalation slowdown
    stream = load_jsonl("ws/stream.jsonl")
    slowdown = [i for i, m in enumerate(stream) if m["type"] == "clock" and m["slowed_reason"] == "escalation"]
    assert len(slowdown) == 1
    del stream[slowdown[0]:slowdown[0] + 3]  # slowed clock, resolved e_0001, restored clock
    first_play = next(i for i, m in enumerate(viewer) if m["type"] == "clock" and m["playing"])
    stopped = {"type": "clock", "playing": False, "speed": 120, "sim_ts": SCENARIO["start_sim_ts"], "tick_id": 0,
               "paused_reason": None, "slowed_reason": None}
    assert viewer[:first_play] == [stopped, stopped]  # the host connects, then the build (reset_all) re-sends it
    assert viewer[first_play:] == stream

    # ---- store buffer: decisions with their template explanations (Convex `decisions`)
    assert store.decisions() == load("convex/tables/decisions.json")
