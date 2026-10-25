"""engine/policies.py: the timer baseline (fixed daily hold windows, fitted on earlier data)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np

from contracts import Tariff
from data.tariffs import DEMO_TARIFF
from engine import block_bill
from engine.policies import candidate_windows, fit_timer, timer_commands
from engine.replay_plant import BlockInfo, PlantDevice

DISH = PlantDevice("dishwasher_1", "dishwasher", "Dishwasher 1", "deferrable", "job", 6.0,
                   {"max_delay_min": 30, "must_finish_by": "19:30"}, deadline_min=19 * 60 + 30)
BASE = PlantDevice("fryer_1", "fryer", "Fryer 1", "always_on", "demand_driven", 14.0, {})


def test_candidate_windows_respect_max_delay_and_deadline():
    w = candidate_windows(DISH, 10 * 60, 22 * 60)
    assert w[0] == (600, 615) and (600, 630) in w and (600, 645) not in w  # max_delay 30
    assert max(b for _, b in w) == 19 * 60 + 15 and all(b - a <= 30 for a, b in w)  # release block ends by 19:30


def test_timer_commands_fire_at_the_window_start():
    s = datetime(2026, 7, 15, 1, 0, tzinfo=timezone.utc)
    i_on = BlockInfo(s, s + timedelta(minutes=15), s.date(), 18 * 60, False, False)
    i_off = BlockInfo(s, s + timedelta(minutes=15), s.date(), 18 * 60 + 15, False, False)
    cmds = timer_commands({"dishwasher_1": (1080, 1110)}, i_on)
    assert len(cmds) == 1 and cmds[0]["action"] == "delay" and cmds[0]["value"] == 30
    assert timer_commands({"dishwasher_1": (1080, 1110)}, i_off) == []


def _days(n_days: int, dish_at_peak: bool):
    """Demo tariff (max demand $20 + 16-21 $8). Fryer 30 kW at 18:00-18:15 local daily; dishwasher 4 kW in that block
    (or at 12:00 if not at peak)."""
    tz_start = datetime(2026, 7, 1, 7, 0, tzinfo=timezone.utc)  # local midnight PDT
    starts = [tz_start + timedelta(minutes=15 * i) for i in range(96 * n_days)]
    tariff = Tariff.model_validate(DEMO_TARIFF)
    cal = block_bill.calendar(tariff, starts)
    kw = np.zeros((len(starts), 2))
    for i in range(len(starts)):
        m = int(cal.minute_of_day[i])
        kw[i, 1] = 30.0 if m == 18 * 60 else 5.0
        if (m == 18 * 60) if dish_at_peak else (m == 12 * 60):
            kw[i, 0] = 4.0
    infos = [BlockInfo(s, s + timedelta(minutes=15), cal.local_date[i], int(cal.minute_of_day[i]), False,
                       int(cal.minute_of_day[i]) == 23 * 60 + 45) for i, s in enumerate(starts)]
    devices = {"dishwasher_1": DISH, "fryer_1": BASE}
    return kw, infos, cal, tariff, devices


def test_fit_moves_the_dishwasher_out_of_the_peak_block():
    kw, infos, cal, tariff, devices = _days(3, dish_at_peak=True)
    sched = fit_timer(kw, ["dishwasher_1", "fryer_1"], devices, infos, cal, tariff, 600, 1320)
    a, b = sched["dishwasher_1"]
    assert a <= 18 * 60 < b and b <= 19 * 60 + 15  # the window covers the 18:00 block and releases before the deadline


def test_fit_keeps_no_window_when_nothing_helps():
    kw, infos, cal, tariff, devices = _days(3, dish_at_peak=False)
    # moving the 12:00 dishwasher only adds energy in a later block: never cheaper on the demo tariff (flat off-peak)
    assert fit_timer(kw, ["dishwasher_1", "fryer_1"], devices, infos, cal, tariff, 600, 1320) == {}
