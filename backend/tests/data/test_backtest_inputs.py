"""data/backtest_inputs.py + data/warmup.py: BacktestInputs shape, series window, calendar shift."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from contracts import BacktestInputs, WarmUpHistory
from data.backtest_inputs import build_backtest_inputs, load_backtest_inputs, replay_months
from data.recipe import distribute
from data.tariffs import load_tariff
from data.warmup import warmup_from_series
from tests.data.helpers import catalog, doc_and_base, needs_comstock, synthetic_rows

LA = ZoneInfo("America/Los_Angeles")


def _inputs(months, start=datetime(2018, 5, 1, 8, 0, tzinfo=timezone.utc), days=120):
    doc, base = doc_and_base()
    rows = synthetic_rows(start, days)
    dev = distribute(rows, doc["kitchen"]["equipment"], catalog(), doc["step1"], base)
    return build_backtest_inputs(rows, dev, months, base, doc, load_tariff("demo"), catalog())


def test_inputs_validate_and_series_starts_28_days_before_the_first_month():
    inp = _inputs(["2026-07"])
    BacktestInputs.model_validate(inp)
    s = inp["series"]
    assert s["source"] == "nrel_comstock" and s["label"] == "calibrated_model" and s["day_offset"] == 2919
    assert s["start"] == "2026-06-03T07:00:00Z" and s["end"] == "2026-08-01T07:00:00Z"
    assert inp["assumptions"] == {"assumptions_id": "base", "flex_scale": 1.0, "draw_scale": 1.0, "forecast_noise_pct": 0.0}
    assert inp["config"]["tariff_id"] == "demo_tariff_v1"


def test_series_never_starts_before_the_data():
    inp = _inputs(["2026-05"], days=60)  # data 2018-05-01 08:00Z + 2919 d = 2026-04-28 08:00Z, later than Apr 3
    assert inp["series"]["start"] == "2026-04-28T08:00:00Z"


def test_month_without_scored_days_is_refused():
    with pytest.raises(ValueError, match="no scored days"):
        _inputs(["2026-04"], days=60)


def test_day_offset_keeps_weekdays_and_lines_up_dst():
    assert 2919 % 7 == 0
    assert date(2018, 1, 1) + timedelta(days=2919) == date(2025, 12, 29)
    assert (date(2018, 1, 1) + timedelta(days=2919)).weekday() == date(2018, 1, 1).weekday()
    for d18 in (date(2018, 3, 11), date(2018, 11, 4)):  # 2018 DST switches -> the 2026 ones
        d26 = d18 + timedelta(days=2919)
        before = datetime(d26.year, d26.month, d26.day, 0, 0, tzinfo=LA).utcoffset()
        after = datetime(d26.year, d26.month, d26.day, 12, 0, tzinfo=LA).utcoffset()
        assert before != after, d26


def test_replay_months_are_the_twelve_2026_months():
    assert replay_months() == [f"2026-{m:02d}" for m in range(1, 13)]


def test_warmup_cut_ends_at_the_start():
    inp = _inputs(["2026-07"])
    end = datetime(2026, 7, 1, 7, 0, tzinfo=timezone.utc)
    w = warmup_from_series(inp["series"], end)
    WarmUpHistory.model_validate(w)
    assert w["end"] == "2026-07-01T07:00:00Z" and w["blocks"][-1]["block_start"] == "2026-07-01T06:45:00Z"
    assert len(w["blocks"]) == 28 * 96 * 12


@needs_comstock
def test_full_year_inputs_redistribute_proposal():
    inp = load_backtest_inputs(replay_months(), "base_redistribute_proposal")
    BacktestInputs.model_validate(inp)
    s = inp["series"]
    assert s["start"] == "2025-12-29T08:00:00Z" and s["end"] == "2026-12-29T08:00:00Z"
    assert len(s["blocks"]) == 35040 * 12
    assert inp["tariff"]["tariff_id"] == "pge_b19_secondary_voluntary"
