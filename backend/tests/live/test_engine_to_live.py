"""End to end through the live layer (M1 check): replay `hub_protocol/hub_to_server.jsonl` through the real engine
(both lanes, runtime order), `compare_lanes`, the live client (FakeLive) -> every payload validates against the section 5
row models and equals `spacetime/rows_stream.jsonl` in shape (same rows, keys, lanes, devices, ts and tick ids; meter
values to rounding). Values the engine does not compute yet (forecast: placeholder until the forecaster) are compared in
shape only."""
from __future__ import annotations

import json

from contracts import PublishTicksPayload, WarmUpHistory
from engine import Kitchen, compare_lanes
from fakes.fake_live import FakeLive

from tests.engine.conftest import FIXTURES, catalog

TOL = 0.0051


def run_engine_into_live():
    scenario = json.loads((FIXTURES / "scenario" / "demo_cafe" / "scenario.json").read_text())
    lanes = Kitchen.build_lanes(scenario["config"], scenario["tariff"], catalog(), scenario["seed"])
    history = WarmUpHistory.model_validate(json.loads((FIXTURES / scenario["warm_up"]["history"]).read_text()))
    for lane in ("without", "with"):
        lanes[lane].warm_up(history.model_dump(mode="json"))
    client = FakeLive(surge_poll_s=0)
    payloads = []
    for line in (FIXTURES / "hub_protocol" / "hub_to_server.jsonl").read_text().splitlines():
        msg = json.loads(line)
        if msg["type"] != "hub_report":
            continue
        states = {}
        for lane in ("without", "with"):
            states[lane] = lanes[lane].step(1, msg["reports"][lane])  # the hub's report as sent (runtime passes it on)
        payloads.append(client.publish(states, compare_lanes(states["without"], states["with"])))
        assert client.flush(5)  # one tick at a time here (live, a slow network would drop intermediate ticks)
    assert client.flush(5)
    return client, payloads


def test_engine_rows_validate_and_match_fixture_shape():
    client, payloads = run_engine_into_live()
    want = [json.loads(x) for x in (FIXTURES / "spacetime" / "rows_stream.jsonl").read_text().splitlines() if x.strip()]
    assert len(payloads) == len(want) == 120
    for got, exp in zip(payloads, want):
        PublishTicksPayload.model_validate(got)
        assert got.keys() == exp.keys()
        for table in ("live_tick", "tick_history", "live_device"):
            assert len(got[table]) == len(exp[table])
            for g, e in zip(got[table], exp[table]):
                assert g.keys() == e.keys(), table
        for g, e in zip(got["live_tick"], exp["live_tick"]):
            for k in ("lane", "ts", "tick_id", "peak_mode", "peak_cap_kw", "customers_per_hour", "indoor_temp_c"):
                assert g[k] == e[k], k
            for k in ("total_kw", "month_peak_kw", "on_peak_month_peak_kw", "energy_kwh_today", "energy_kwh_month",
                      "cost_usd_today", "cost_usd_month", "price_usd_per_kwh_now"):
                assert abs(g[k] - e[k]) <= TOL, (g["tick_id"], k, g[k], e[k])
            gp, ep = json.loads(g["demand_peaks_json"]), json.loads(e["demand_peaks_json"])
            assert [d["name"] for d in gp] == [d["name"] for d in ep]
            for a, b in zip(gp, ep):
                assert abs(a["cost_usd"] - b["cost_usd"]) <= TOL
            # forecast: the engine's own (placeholder until M3) appears on the same decision ticks
            assert (g["forecast_kw_json"] is None) == (e["forecast_kw_json"] is None)
            assert g["forecast_ts"] == e["forecast_ts"]
        assert [d["key"] for d in got["live_device"]] == [d["key"] for d in exp["live_device"]]
        for g, e in zip(got["live_device"], exp["live_device"]):
            # devices are the hub's state, echoed unchanged (the contract model types 62 as 62.0: same number)
            parse = lambda r: {**r, "physical_json": json.loads(r["physical_json"]) if r["physical_json"] else None}  # noqa: E731
            assert parse(g) == parse(e)
        # the recording predates saved_month_usd (optional, added 2026-10-25); the engine now always sends it
        assert got["live_comparison"].keys() == exp["live_comparison"].keys() | {"saved_month_usd"}
    # the in-memory tables hold the last tick and 120 minutes of history per lane
    assert [r["tick_id"] for r in client.transport.rows("live_tick")] == [120, 120]
    assert len(client.transport.rows("tick_history")) == 240
    client.close()
