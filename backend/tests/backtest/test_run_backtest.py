"""engine.run_backtest (CONTRACTS.md section 3): event order, month marks, checks, knobs, determinism.

Synthetic ComStock-shaped rows (tests/data/helpers.py) go through the real loader path (`build_backtest_inputs`) and the real
Kitchen (with the real decider). No test fakes a saving.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from contracts import BacktestPoint, BacktestResult
from data.backtest_inputs import build_backtest_inputs
from data.recipe import distribute
from data.tariffs import load_tariff
from engine import run_backtest
from engine.replay import run_backtest_with_diagnostics
from tests.data.helpers import catalog, doc_and_base, open_of, synthetic_rows

REPO = Path(__file__).resolve().parents[3]
B19_FIXTURE = json.loads((REPO / "contracts" / "fixtures" / "shapes" / "tariff_pge_b19.json").read_text())


def make_inputs(months, *, start=datetime(2018, 5, 6, 7, 0, tzinfo=timezone.utc), days=90, tariff=None,
                assumptions_id="base", **knobs):
    from backtest.assumptions import resolve

    doc, _ = doc_and_base()
    base = dict(resolve(assumptions_id, doc), **knobs)
    rows = synthetic_rows(start, days)
    dev = distribute(rows, doc["kitchen"]["equipment"], catalog(), doc["step1"], base, open_of(rows, doc))
    return build_backtest_inputs(rows, dev, months, base, doc, tariff or load_tariff("demo"), catalog())


@pytest.fixture(scope="module")
def june_run():
    inp = make_inputs(["2026-06"])
    events = []
    results, diag = run_backtest_with_diagnostics(inp, ["2026-06"], "base", events.append)
    return inp, events, results, diag


def test_events_follow_the_contract_order(june_run):
    _, events, results, _ = june_run
    kinds = [e["type"] for e in events]
    points = [e for e in events if e["type"] == "backtest_point"]
    assert len(points) == 30 and [p["data"]["day"] for p in points] == [f"2026-06-{d:02d}" for d in range(1, 31)]
    assert kinds[-3:] == ["backtest_point", "backtest_month", "backtest_progress"]
    progress = [e for e in events if e["type"] == "backtest_progress"]
    assert [p["pct"] for p in progress] == [26, 50, 76, 100]  # GAPS 28: after each quarter of the month's days
    assert all(set(p) == {"type", "month", "pct"} for p in progress)
    assert kinds.index("backtest_progress") == 8  # after the 8th day
    for e in events:
        if e["type"] == "backtest_point":
            BacktestPoint.model_validate(e["data"])
        elif e["type"] == "backtest_month":
            BacktestResult.model_validate(e["data"])
    assert len(results) == 1 and results[0] == [e for e in events if e["type"] == "backtest_month"][0]["data"]


def test_last_point_equals_the_month_mark_to_the_cent(june_run):
    _, events, results, _ = june_run
    last = [e["data"] for e in events if e["type"] == "backtest_point"][-1]
    res = results[0]
    assert last["saved_month_to_date_usd"] == res["saved_usd"]
    assert last["saved_vs_timer_month_to_date_usd"] == res["saved_vs_timer_usd"]
    for p in ("without", "timer", "with"):
        assert last["cost_to_date_usd"][p] == res["policies"][p]["total_usd"]
    assert last["ts"] == "2026-07-01T07:00:00Z"  # end of the local day


def test_checks_and_labels(june_run):
    _, events, results, diag = june_run
    res = results[0]
    assert res["checks"] == {"baseline_matches_raw": True, "energy_conserved": True, "rule_violations": 0}
    assert res["dataset"] == "DOE-calibrated restaurant profile (NREL ComStock)" and res["tariff_id"] == "demo_tariff_v1"
    assert res["partial"] is False and res["assumptions_id"] == "base"
    assert diag.peek_errors == 0 and diag.commands_issued["without"] == 0


def test_with_lane_moves_energy_and_never_deletes_it(june_run):
    """Golden rule 5: every policy uses the same month energy; saved_usd is the bill difference, computed in backend code."""
    _, _, results, diag = june_run
    res = results[0]
    pol = res["policies"]
    assert pol["with"]["energy_kwh"] == pytest.approx(pol["without"]["energy_kwh"], abs=1e-6)
    assert pol["timer"]["energy_kwh"] == pytest.approx(pol["without"]["energy_kwh"], abs=1e-6)
    assert res["saved_usd"] == round(pol["without"]["total_usd"] - pol["with"]["total_usd"], 2)
    assert res["checks"] == {"baseline_matches_raw": True, "energy_conserved": True, "rule_violations": 0}
    assert diag.over_rated_blocks["with"] == 0  # repay-room check: no close-time dump above a device's rating


def test_month_to_date_grows_and_costs_are_month_to_date(june_run):
    _, events, _, _ = june_run
    costs = [e["data"]["cost_to_date_usd"]["without"] for e in events if e["type"] == "backtest_point"]
    assert all(b > a for a, b in zip(costs, costs[1:]))


def test_year_to_date_accumulates_month_marks():
    inp = make_inputs(["2026-06", "2026-07"], days=100)
    events = []
    results = run_backtest(inp, ["2026-06", "2026-07"], "base", events.append)
    assert [r["month"] for r in results] == ["2026-06", "2026-07"]
    july = [e["data"] for e in events if e["type"] == "backtest_point" and e["data"]["month"] == "2026-07"]
    assert july[0]["saved_year_to_date_usd"] == round(results[0]["saved_usd"] + july[0]["saved_month_to_date_usd"], 2)


def test_first_month_after_warm_up_is_partial():
    inp = make_inputs(["2026-05"], start=datetime(2018, 4, 15, 7, 0, tzinfo=timezone.utc), days=50)
    events = []
    results = run_backtest(inp, ["2026-05"], "base", events.append)
    assert results[0]["partial"] is True
    first = [e["data"] for e in events if e["type"] == "backtest_point"][0]
    assert first["day"] == "2026-05-10" and first["partial"] is True  # 2026-04-12 + 28 days


def test_zero_flexibility_saves_nothing():
    inp = make_inputs(["2026-06"], assumptions_id="zero_flex")
    assert inp["assumptions"]["flex_scale"] == 0.0
    res = run_backtest(inp, ["2026-06"], "zero_flex", None)[0]
    assert res["saved_usd"] == 0.0 and res["saved_vs_timer_usd"] == 0.0
    assert res["policies"]["timer"] == res["policies"]["without"] == res["policies"]["with"]


def test_deterministic_rerun_is_byte_identical():
    inp = make_inputs(["2026-06"], days=70)
    a, b = [], []
    run_backtest(inp, ["2026-06"], "base", a.append)
    run_backtest(inp, ["2026-06"], "base", b.append)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_b19_tariff_summer_month_bills_every_charge():
    inp = make_inputs(["2026-07"], days=100, tariff=B19_FIXTURE)
    res = run_backtest(inp, ["2026-07"], "base")[0]
    names = [c["name"] for c in res["policies"]["without"]["demand_charges"]]
    assert names == ["max_demand", "peak_demand_summer", "part_peak_demand_summer"]
    assert res["policies"]["without"]["fixed_usd"] == round(31 * 11.36882, 2)
    assert res["checks"]["baseline_matches_raw"] and res["checks"]["energy_conserved"]


def test_knob_and_argument_guards():
    inp = make_inputs(["2026-06"], days=70)
    with pytest.raises(ValueError, match="assumptions_id"):
        run_backtest(inp, ["2026-06"], "low_flex")
    with pytest.raises(ValueError, match="sorted"):
        run_backtest(inp, ["2026-07", "2026-06"], "base")
    with pytest.raises(ValueError, match="no scored blocks"):
        run_backtest(inp, ["2026-09"], "base")
    with pytest.raises(ValueError, match="rated_kw"):
        run_backtest(make_inputs(["2026-06"], days=70, draw_scale=5.0), ["2026-06"], "base")
    with pytest.raises(NotImplementedError, match="STUB"):
        run_backtest(make_inputs(["2026-06"], days=70, forecast_noise_pct=20.0), ["2026-06"], "base")
