"""data/comstock.py: timestamp convention (local standard time, interval-ending) and kW = kWh x 4."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np

from data.comstock import COMSTOCK_FILE, ROWS_PER_YEAR, column, load_comstock, utc_start_of
from tests.data.helpers import needs_comstock


def test_interval_ending_standard_time_to_utc_start():
    # 2018-01-01 00:15 (end, PST) -> interval 00:00-00:15 PST -> 08:00Z
    assert utc_start_of(datetime(2018, 1, 1, 0, 15)) == datetime(2018, 1, 1, 8, 0, tzinfo=timezone.utc)
    # in July the stamp is still standard time: 19:00 PST end -> 18:45 PST start -> 02:45Z next day (= 19:45 PDT)
    s = utc_start_of(datetime(2018, 7, 10, 19, 0))
    assert s == datetime(2018, 7, 11, 2, 45, tzinfo=timezone.utc)
    assert s.astimezone(ZoneInfo("America/Los_Angeles")).strftime("%H:%M") == "19:45"


@needs_comstock
def test_full_year_rows_contiguous_and_kw_is_kwh_times_4():
    import pandas as pd

    rows = load_comstock(COMSTOCK_FILE)
    assert len(rows) == ROWS_PER_YEAR
    assert rows.start_utc[0] == datetime(2018, 1, 1, 8, 0, tzinfo=timezone.utc)
    assert rows.start_utc[-1] == datetime(2019, 1, 1, 7, 45, tzinfo=timezone.utc)
    raw = pd.read_parquet(COMSTOCK_FILE, columns=[column("total")])[column("total")].to_numpy(dtype=np.float64)
    np.testing.assert_array_equal(rows.kw["total"], raw * 4.0)
    assert abs(rows.kw["total"].max() - 52.0174) < 1e-3


@needs_comstock
def test_peak_follows_the_wall_clock_so_stamps_are_standard_time():
    """Thursday dinner peak: 20:30 standard time before DST (= 20:30 wall), 19:30 standard time during DST (= 20:30 wall)."""
    rows = load_comstock(COMSTOCK_FILE)
    tz = ZoneInfo("America/Los_Angeles")
    ie = rows.kw["interior_equipment"]

    def peak_wall(day):
        idx = [i for i, s in enumerate(rows.start_utc) if (s - timedelta(hours=8)).date() == day]
        i = max(idx, key=lambda k: ie[k])
        return rows.start_utc[i].astimezone(tz).strftime("%H:%M")

    from datetime import date
    assert peak_wall(date(2018, 3, 8)) == peak_wall(date(2018, 3, 15)) == "20:30"
