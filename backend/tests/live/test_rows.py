"""Live payloads equal the fixtures (CONTRACTS.md section 5): the row builders fed the fixture's engine / runtime objects
produce byte-identical reducer arguments (`contracts/fixtures/spacetime/reducers/*.json`) and the 120-tick
`spacetime/rows_stream.jsonl`."""
from __future__ import annotations

import json

from contracts import (
    BacktestMonthRow,
    BacktestPointRow,
    LiveAgentLogRow,
    LiveClockRow,
    LiveContextRow,
    LiveEscalationRow,
    LiveFeedRow,
    PublishTicksPayload,
)
from live import rows as R

from tests.engine.conftest import FIXTURES

SP = FIXTURES / "spacetime"


def reducer_args(name: str) -> list:
    return json.loads((SP / "reducers" / f"{name}.json").read_text())["args"]


def jsonl(path):
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def ws_stream():
    return jsonl(FIXTURES / "ws" / "stream.jsonl")


def step_states_by_tick():
    """{tick_id: {lane: TickState}} from the committed step stream (the fixture engine's outputs)."""
    out: dict[int, dict] = {}
    for rec in jsonl(FIXTURES / "facade" / "step_stream.jsonl"):
        st = rec["returns"]
        out.setdefault(st["hub"]["tick_id"], {})[st["lane"]] = st
    return out


def build_rows_stream() -> list[str]:
    states = step_states_by_tick()
    comparisons = [m["data"] for m in ws_stream() if m["type"] == "comparison"]
    forecasts = {lane: (None, None) for lane in R.LANES}
    out = []
    for i, tick in enumerate(sorted(states)):
        for lane in R.LANES:
            if states[tick][lane]["forecast_kw"] is not None:
                forecasts[lane] = (states[tick][lane]["forecast_kw"], states[tick][lane]["ts"])
        out.append(R.cj(R.publish_ticks_payload(states[tick], comparisons[i], forecasts)))
    return out


def test_rows_stream_byte_identical():
    built = build_rows_stream()
    want = [x for x in (SP / "rows_stream.jsonl").read_text().splitlines() if x.strip()]
    assert len(built) == len(want) == 120
    for i, (a, b) in enumerate(zip(built, want)):
        assert a == b, f"tick {i + 1}"
        PublishTicksPayload.model_validate(json.loads(a))


def test_publish_ticks_args_equal_fixture():
    assert [build_rows_stream()[-1]] == reducer_args("publish_ticks")


def test_publish_feed_args_equal_fixture():
    msg = next(m for m in ws_stream() if m["type"] == "decision")
    lane = next(st["lane"] for t in step_states_by_tick().values() for st in t.values()
                for d in st["new_decisions"] if d["decision_id"] == msg["data"]["decision_id"])
    row = R.feed_row(msg["data"], lane, msg["explanation"], msg["explanation_source"])
    LiveFeedRow.model_validate(row)
    assert [R.cj(row)] == reducer_args("publish_feed")


def test_set_clock_args_equal_fixture():
    table = json.loads((SP / "tables" / "live_clock.json").read_text())[0]
    clock = {k: v for k, v in table.items() if k not in ("id", "sim_host")}
    args = R.set_clock_args(clock, table["sim_host"])
    LiveClockRow.model_validate({"id": 0, **dict(zip(R.SET_CLOCK_ARGS, args))})
    assert args == reducer_args("set_clock")


def test_publish_context_args_equal_fixture():
    ctx = [m["data"] for m in ws_stream() if m["type"] == "context"][-1]
    row = R.context_row(ctx)
    LiveContextRow.model_validate(row)
    assert [R.cj(row)] == reducer_args("publish_context")


def test_publish_escalation_args_equal_fixture():
    esc = [m["data"] for m in ws_stream() if m["type"] == "escalation"][-1]
    row = R.escalation_row(esc)
    LiveEscalationRow.model_validate(row)
    assert [R.cj(row)] == reducer_args("publish_escalation")


def test_log_agent_args_equal_fixture():
    first = jsonl(FIXTURES / "agents" / "agent_log.jsonl")[0]
    row = R.agent_log_row(first)
    LiveAgentLogRow.model_validate({"id": 1, **row})
    assert [R.cj(row)] == reducer_args("log_agent")


def test_backtest_rows_equal_fixture():
    point = json.loads((FIXTURES / "ws" / "backtest_point.json").read_text())
    row = R.backtest_point_row(point["run_id"], point["data"])
    BacktestPointRow.model_validate(row)
    assert [R.cj(row)] == reducer_args("publish_backtest_point")
    month = json.loads((FIXTURES / "ws" / "backtest_month.json").read_text())
    row = R.backtest_month_row(month["run_id"], month["data"])
    BacktestMonthRow.model_validate(row)
    assert [R.cj(row)] == reducer_args("publish_backtest_month")
    assert reducer_args("reset_backtest") == [point["run_id"]]


def test_fixture_tables_are_what_the_builders_make():
    # every backtest table row comes from the backtest events in order
    events = jsonl(FIXTURES / "facade" / "run_backtest_on_progress.jsonl")
    points = [R.backtest_point_row("run_0001", e["data"]) for e in events if e["type"] == "backtest_point"]
    months = [R.backtest_month_row("run_0001", e["data"]) for e in events if e["type"] == "backtest_month"]
    assert points == json.loads((SP / "tables" / "backtest_point.json").read_text())
    assert months == json.loads((SP / "tables" / "backtest_month.json").read_text())
