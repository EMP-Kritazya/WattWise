"""data/recipe.py: the distribution recipe sums exactly, splits as decided, and raises (never clips) above rated_kw."""
from __future__ import annotations

import copy
from datetime import datetime, timezone

import numpy as np
import pytest

from data.comstock import COMSTOCK_FILE, TOTAL, load_comstock
from data.recipe import RatedKwExceeded, distribute, split
from tests.data.helpers import catalog, doc_and_base, needs_comstock, synthetic_rows

START = datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc)


def test_devices_sum_exactly_to_the_total_including_the_float_residual():
    doc, base = doc_and_base()
    rows = synthetic_rows(START, 3, residual_kw=1.2e-5)
    s = distribute(rows, doc["kitchen"]["equipment"], catalog(), doc["step1"], base)
    assert np.max(np.abs(s.kw.sum(axis=1) - rows.kw[TOTAL])) <= 1e-9
    assert len(s.device_ids) == 12 and s.device_ids == sorted(s.device_ids)


def test_hvac_is_cooling_plus_fans_split_equally_and_shares_follow_assumptions():
    doc, base = doc_and_base()
    rows = synthetic_rows(START, 1)
    s = distribute(rows, doc["kitchen"]["equipment"], catalog(), doc["step1"], base)
    hv = rows.kw["cooling"] + rows.kw["fans"]
    np.testing.assert_allclose(s.column("hvac_1"), hv / 2, atol=1e-12)
    np.testing.assert_allclose(s.column("hvac_2"), hv / 2, atol=1e-12)
    np.testing.assert_allclose(s.column("lights_1"), rows.kw["interior_lighting"] + rows.kw["exterior_lighting"], atol=1e-12)
    ie = rows.kw["interior_equipment"]
    np.testing.assert_allclose(s.column("grill_1"), ie * 0.217, atol=1e-12)
    np.testing.assert_allclose(s.column("dishwasher_1"), ie * 0.086, atol=1e-12)


def test_device_above_rated_raises_and_never_clips():
    doc, base = doc_and_base()
    rows = synthetic_rows(START, 1, interior_peak_kw=30.0)  # water heater 27 % x 30 = 8.1 kW > catalog 4.5 kW
    before = copy.deepcopy(rows.kw)
    with pytest.raises(RatedKwExceeded, match="water_heater_1"):
        distribute(rows, doc["kitchen"]["equipment"], catalog(), doc["step1"], base)
    for k in before:  # the baseline is never altered
        np.testing.assert_array_equal(rows.kw[k], before[k])


def test_unmapped_end_use_raises():
    doc, base = doc_and_base()
    rows = synthetic_rows(START, 1)
    rows.kw["refrigeration"][5] = 0.1
    with pytest.raises(ValueError, match="refrigeration"):
        distribute(rows, doc["kitchen"]["equipment"], catalog(), doc["step1"], base)


def test_shares_must_sum_to_100():
    doc, base = doc_and_base()
    bad = dict(base, interior_equipment=dict(base["interior_equipment"], grill=30.0))
    with pytest.raises(ValueError, match="sum"):
        split(synthetic_rows(START, 1), doc["kitchen"]["equipment"], catalog(), doc["step1"], bad)


def test_redistribute_proposal_keeps_the_row_total_and_respects_rated():
    doc, _ = doc_and_base()
    from backtest.assumptions import resolve
    prop = resolve("base_redistribute_proposal", doc)
    rows = synthetic_rows(START, 1, interior_peak_kw=30.0)
    s = distribute(rows, doc["kitchen"]["equipment"], catalog(), doc["step1"], prop)
    assert np.max(np.abs(s.kw.sum(axis=1) - rows.kw[TOTAL])) <= 1e-9
    rated = {c["type_id"]: c["rated_kw"] for c in catalog()}
    for j, d in enumerate(s.device_ids):
        assert s.kw[:, j].max() <= rated[s.type_of[d]] + 1e-9


# ---------------------------------------------------------------------------------------------------------------------
# the real year (dataset/ is gitignored: skipped when absent)
# ---------------------------------------------------------------------------------------------------------------------


@needs_comstock
def test_full_year_hvac_never_exceeds_rated_kw():
    """Kritazya's decision 3: replay the whole year's HVAC series through the recipe; no hvac block above the catalog's 8.0 kW.
    Worst block 15.714 kW (2018-06-23 18:30-18:45 standard time) = 7.857 kW per unit."""
    doc, base = doc_and_base()
    rows = load_comstock(COMSTOCK_FILE)
    s = split(rows, doc["kitchen"]["equipment"], catalog(), doc["step1"], base)
    rated = {c["type_id"]: c["rated_kw"] for c in catalog()}["hvac"]
    for d in ("hvac_1", "hvac_2"):
        col = s.column(d)
        assert col.max() <= rated, f"{d} max {col.max():.3f} > {rated}"
    total_hvac = s.column("hvac_1") + s.column("hvac_2")
    i = int(np.argmax(total_hvac))
    assert abs(total_hvac[i] - 15.714) < 1e-3
    assert rows.start_utc[i] == datetime(2018, 6, 24, 2, 30, tzinfo=timezone.utc)  # 18:30 PST start, stamp 18:45
    assert abs(s.column("hvac_1").max() - 7.857) < 1e-3


@needs_comstock
def test_full_year_every_row_sums_to_the_dataset_total():
    doc, base = doc_and_base()
    rows = load_comstock(COMSTOCK_FILE)
    s = split(rows, doc["kitchen"]["equipment"], catalog(), doc["step1"], base)
    assert np.max(np.abs(s.kw.sum(axis=1) - rows.kw[TOTAL])) <= 1e-9
    assert (s.kw >= 0).all()


@needs_comstock
def test_full_year_base_shares_raise_exactly_when_a_device_is_over_rated():
    """The loader raises (never clips) if any device would exceed rated_kw. With the current catalog this is the case for
    base (freezer, ice machine, water heater; see the report): the test pins the behaviour, whichever way the data falls."""
    doc, base = doc_and_base()
    rows = load_comstock(COMSTOCK_FILE)
    s = split(rows, doc["kitchen"]["equipment"], catalog(), doc["step1"], base)
    rated = {c["type_id"]: c["rated_kw"] for c in catalog()}
    over = [d for j, d in enumerate(s.device_ids) if s.kw[:, j].max() > rated[s.type_of[d]]]
    if over:
        with pytest.raises(RatedKwExceeded) as e:
            distribute(rows, doc["kitchen"]["equipment"], catalog(), doc["step1"], base)
        for d in over:
            assert d in str(e.value)
    else:
        distribute(rows, doc["kitchen"]["equipment"], catalog(), doc["step1"], base)
