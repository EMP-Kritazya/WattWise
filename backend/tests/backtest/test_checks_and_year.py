"""backtest/checks.py on synthetic events, and the real-year run (dataset/ is gitignored: skipped when absent)."""
from __future__ import annotations

import copy

import pytest

from backtest import checks
from backtest.run import parse_months
from data.backtest_inputs import load_backtest_inputs, replay_months
from engine.replay import run_backtest_with_diagnostics
from tests.backtest.test_run_backtest import make_inputs
from tests.data.helpers import needs_comstock


@pytest.fixture(scope="module")
def run():
    inp = make_inputs(["2026-06", "2026-07"], days=100)
    events = []
    results, diag = run_backtest_with_diagnostics(inp, ["2026-06", "2026-07"], "base", events.append)
    return inp, events, results, diag


def test_checks_pass_on_a_real_run(run):
    inp, events, results, diag = run
    table = checks.check_table(results, events, deterministic_ok=checks.deterministic(inp, ["2026-06", "2026-07"], "base", events),
                               zero_flex=checks.zero_flex_saves_zero(inp, ["2026-06", "2026-07"]), peek_errors=diag.peek_errors)
    assert all(ok for *_, ok in table), table
    assert len(table) == 8


def test_month_mark_check_catches_a_tampered_point(run):
    _, events, _, _ = run
    bad = copy.deepcopy(events)
    last_june = [e for e in bad if e["type"] == "backtest_point" and e["data"]["month"] == "2026-06"][-1]
    last_june["data"]["saved_month_to_date_usd"] += 0.01
    assert not checks.month_marks_equal_last_points(bad)


def test_year_to_date_check_catches_a_wrong_sum(run):
    _, events, _, _ = run
    bad = copy.deepcopy(events)
    july = [e for e in bad if e["type"] == "backtest_point" and e["data"]["month"] == "2026-07"][3]
    july["data"]["saved_year_to_date_usd"] += 1.0
    assert not checks.year_to_date_consistent(bad)


def test_parse_months():
    assert parse_months("2026-11..2027-02") == ["2026-11", "2026-12", "2027-01", "2027-02"]
    assert parse_months("2026-01,2026-03") == ["2026-01", "2026-03"]
    assert parse_months("all") == replay_months()


@needs_comstock
def test_base_assumptions_load_on_the_real_year():
    """Since the two-part recipe and the re-cited catalog (2026-10-25) no device of the real year exceeds its rated_kw, so
    the base set loads (the loader would raise RatedKwExceeded otherwise, never clip)."""
    inp = load_backtest_inputs(["2026-07"], "base")
    assert inp["series"]["label"] == "calibrated_model" and inp["assumptions"]["assumptions_id"] == "base"


@needs_comstock
@pytest.mark.slow
def test_real_year_pipeline_on_base(tmp_path):
    """The whole 2026 replay calendar on PG&E B-19: 12 marks, January and December partial, every check passes."""
    months = replay_months()
    inp = load_backtest_inputs(months, "base")
    events = []
    results, diag = run_backtest_with_diagnostics(inp, months, "base", events.append)
    assert [r["month"] for r in results] == months
    assert [r["partial"] for r in results] == [True] + [False] * 10 + [True]
    assert diag.scored_days["2026-01"] == 6 and diag.scored_days["2026-12"] == 28
    assert all(r["checks"] == {"baseline_matches_raw": True, "energy_conserved": True, "rule_violations": 0} for r in results)
    assert checks.month_marks_equal_last_points(events) and checks.year_to_date_consistent(events)
    assert sum(e["type"] == "backtest_point" for e in events) == 6 + 28 + 31 + 30 + 31 + 30 + 31 + 31 + 30 + 31 + 30 + 28
