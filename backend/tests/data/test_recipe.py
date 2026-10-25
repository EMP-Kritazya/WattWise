"""data/recipe.py: the two-part distribution recipe sums exactly, splits as decided, and raises (never clips) above rated_kw.

Hand numbers use the catalog and assumptions.yaml values written out below (decided 2026-10-25), not engine output:
base_duty  walk_in 2.0 kW x 50 / 33 %, reach_in 0.6 x 32.5 / 20 %, freezer 0.7 x 52.5 / 40 %, ice 1.2 x 60 / 60 % (open / closed)
           -> open 1.0 + 0.195 + 0.3675 + 0.72 = 2.2825 kW, closed 0.66 + 0.12 + 0.28 + 0.72 = 1.78 kW
variable   fryer 6.6, oven 8.2, grill 13.8, dishwasher 5.5, water_heater 17.1, other_equipment 48.8 (remainder) %
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone

import numpy as np
import pytest

from data.comstock import COMSTOCK_FILE, END_USES, TOTAL, ComStockRows, load_comstock
from data.recipe import RatedKwExceeded, distribute, split
from tests.data.helpers import catalog, doc_and_base, needs_comstock, open_of, synthetic_rows

START = datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc)


def two_rows(ie_closed: float, ie_open: float) -> ComStockRows:
    """Row 0 at 03:00 PDT (closed), row 1 at 12:00 PDT (open), 2018-07-10; cooling 3, fans 5.74, lights 1.2 + 0.3."""
    starts = [datetime(2018, 7, 10, 10, 0, tzinfo=timezone.utc), datetime(2018, 7, 10, 19, 0, tzinfo=timezone.utc)]
    kw = {e: np.zeros(2) for e in END_USES}
    kw["cooling"] = np.array([3.0, 3.0])
    kw["fans"] = np.array([5.74, 5.74])
    kw["interior_lighting"] = np.array([1.2, 1.2])
    kw["exterior_lighting"] = np.array([0.3, 0.3])
    kw["interior_equipment"] = np.array([ie_closed, ie_open])
    kw[TOTAL] = sum(kw[e] for e in END_USES)
    return ComStockRows(dataset_id="synthetic", start_utc=starts, kw=kw)


def run(rows, base=None, is_open=None):
    doc, b = doc_and_base()
    return distribute(rows, doc["kitchen"]["equipment"], catalog(), doc["step1"], base or b,
                      open_of(rows, doc) if is_open is None else is_open)


def test_devices_sum_exactly_to_the_total_including_the_float_residual():
    rows = synthetic_rows(START, 3, residual_kw=1.2e-5)
    s = run(rows)
    assert np.max(np.abs(s.kw.sum(axis=1) - rows.kw[TOTAL])) <= 1e-9
    assert len(s.device_ids) == 14 and s.device_ids == sorted(s.device_ids)
    assert (s.kw >= 0).all()


def test_step1_groups_hvac_without_fans_exhaust_and_lights():
    s = run(two_rows(0.7, 20.0), is_open=np.array([False, True]))
    np.testing.assert_allclose(s.column("hvac_1"), [1.5, 1.5], atol=1e-12)  # cooling 3 / 2 units
    np.testing.assert_allclose(s.column("hvac_2"), [1.5, 1.5], atol=1e-12)
    np.testing.assert_allclose(s.column("kitchen_exhaust_1"), [5.74, 5.74], atol=1e-12)
    np.testing.assert_allclose(s.column("lights_1"), [1.5, 1.5], atol=1e-12)


def test_base_is_duty_average_scaled_down_when_the_data_has_less():
    s = run(two_rows(0.7, 20.0), is_open=np.array([False, True]))
    # closed: base 1.78 kW > interior 0.7 kW -> every base type x 0.7 / 1.78; nothing is left for the variable part
    k = 0.7 / 1.78
    assert s.column("walk_in_cooler_1")[0] == pytest.approx(0.66 * k, abs=1e-12)
    assert s.column("reach_in_fridge_1")[0] == pytest.approx(0.12 * k, abs=1e-12)
    assert s.column("freezer_1")[0] == pytest.approx(0.28 * k, abs=1e-12)
    assert s.column("ice_machine_1")[0] == pytest.approx(0.72 * k, abs=1e-12)
    for d in ("fryer_1", "oven_1", "grill_1", "dishwasher_1", "water_heater_1", "other_equipment_1"):
        assert s.column(d)[0] == pytest.approx(0.0, abs=1e-12)
    # open: full duty-average base
    assert s.column("walk_in_cooler_1")[1] == pytest.approx(1.0, abs=1e-12)
    assert s.column("reach_in_fridge_1")[1] == pytest.approx(0.195, abs=1e-12)
    assert s.column("freezer_1")[1] == pytest.approx(0.3675, abs=1e-12)
    assert s.column("ice_machine_1")[1] == pytest.approx(0.72, abs=1e-12)


def test_variable_rest_follows_the_shares():
    s = run(two_rows(0.7, 20.0), is_open=np.array([False, True]))
    rest = 20.0 - 2.2825  # 17.7175 kW
    assert s.column("fryer_1")[1] == pytest.approx(rest * 0.066, abs=1e-12)
    assert s.column("oven_1")[1] == pytest.approx(rest * 0.082, abs=1e-12)
    assert s.column("grill_1")[1] == pytest.approx(rest * 0.138, abs=1e-12)
    assert s.column("dishwasher_1")[1] == pytest.approx(rest * 0.055, abs=1e-12)
    assert s.column("water_heater_1")[1] == pytest.approx(rest * 0.171, abs=1e-12)
    assert s.column("other_equipment_1")[1] == pytest.approx(rest * 0.488, abs=1e-9)  # the remainder


def test_device_above_rated_raises_and_never_clips():
    rows = two_rows(0.7, 40.0)  # other_equipment 48.8 % x (40 - 2.2825) = 18.4 kW > rated 16.4 kW
    before = copy.deepcopy(rows.kw)
    with pytest.raises(RatedKwExceeded, match="other_equipment_1"):
        run(rows, is_open=np.array([False, True]))
    for k in before:  # the baseline is never altered
        np.testing.assert_array_equal(rows.kw[k], before[k])


def test_unmapped_end_use_raises():
    rows = synthetic_rows(START, 1)
    rows.kw["refrigeration"][5] = 0.1
    with pytest.raises(ValueError, match="refrigeration"):
        run(rows)


def test_shares_must_sum_to_100():
    _, base = doc_and_base()
    bad = dict(base, variable_shares=dict(base["variable_shares"], grill=30.0))
    with pytest.raises(ValueError, match="sum"):
        run(synthetic_rows(START, 1), base=bad)


def test_a_type_in_both_parts_or_in_neither_raises():
    _, base = doc_and_base()
    shares = {t: v for t, v in base["variable_shares"].items() if t != "fryer"}
    shares["walk_in_cooler"] = 6.6  # still sums to 100, but walk_in_cooler is also a base type
    both = dict(base, variable_shares=shares)
    with pytest.raises(ValueError, match="both"):
        run(synthetic_rows(START, 1), base=both)
    neither = dict(base, base_duty={t: v for t, v in base["base_duty"].items() if t != "freezer"})
    with pytest.raises(ValueError, match="freezer"):
        run(synthetic_rows(START, 1), base=neither)


def test_is_open_must_have_one_value_per_row():
    with pytest.raises(ValueError, match="is_open"):
        run(two_rows(0.7, 20.0), is_open=np.array([True]))


# ---------------------------------------------------------------------------------------------------------------------
# the real year (dataset/ is gitignored: skipped when absent)
# ---------------------------------------------------------------------------------------------------------------------


@needs_comstock
def test_full_year_hvac_without_fans_fits_the_rated_5_kw_unit():
    """appliance-recheck.md section 6: cooling max 9.974 kW (2018-06-23 18:30-18:45 PST) = 4.987 kW per unit <= 5.0."""
    rows = load_comstock(COMSTOCK_FILE)
    s = run(rows)
    total_hvac = s.column("hvac_1") + s.column("hvac_2")
    i = int(np.argmax(total_hvac))
    assert abs(total_hvac[i] - 9.974) < 1e-3
    assert rows.start_utc[i] == datetime(2018, 6, 24, 2, 30, tzinfo=timezone.utc)  # 18:30 PST start
    assert s.column("hvac_1").max() <= 5.0
    np.testing.assert_allclose(s.column("kitchen_exhaust_1"), 5.739076137542725, atol=1e-6)  # ComStock fans, constant


@needs_comstock
def test_full_year_every_row_sums_and_no_device_is_over_rated():
    rows = load_comstock(COMSTOCK_FILE)
    s = run(rows)  # distribute raises RatedKwExceeded if any device is above its catalog rated_kw
    assert np.max(np.abs(s.kw.sum(axis=1) - rows.kw[TOTAL])) <= 1e-9
    assert (s.kw >= 0).all()
    rated = {c["type_id"]: c["rated_kw"] for c in catalog()}
    peaks = {d: s.column(d).max() for d in s.device_ids}
    assert peaks["other_equipment_1"] == pytest.approx(16.304, abs=1e-3)  # rated 16.4 = this peak rounded up
    assert all(peaks[d] <= rated[s.type_of[d]] for d in s.device_ids)


@needs_comstock
def test_split_and_distribute_agree_when_nothing_is_over_rated():
    doc, base = doc_and_base()
    rows = load_comstock(COMSTOCK_FILE)
    is_open = open_of(rows, doc)
    a = split(rows, doc["kitchen"]["equipment"], catalog(), doc["step1"], base, is_open)
    b = distribute(rows, doc["kitchen"]["equipment"], catalog(), doc["step1"], base, is_open)
    np.testing.assert_array_equal(a.kw, b.kw)
    assert a.device_ids == b.device_ids
