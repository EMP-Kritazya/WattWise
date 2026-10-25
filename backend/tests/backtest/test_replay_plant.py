"""engine/replay_plant.py (ENGINE.md section 11): hand-computed cases. Energy is moved, never deleted (golden rule 5)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from contracts import HubReport
from engine.replay_plant import BlockInfo, PlantDevice, ReplayPlant

T0 = datetime(2026, 7, 15, 17, 0, tzinfo=timezone.utc)  # 10:00 PDT
B = timedelta(minutes=15)


def info(k: int, *, close_at: int | None = None, last_of_day_at: int | None = None) -> BlockInfo:
    s = T0 + k * B
    return BlockInfo(s, s + B, date(2026, 7, 15), 600 + 15 * k, last_before_close=(k == close_at),
                     last_of_day=(k == last_of_day_at))


HVAC = PlantDevice("hvac_1", "hvac", "HVAC 1", "flexible", "thermal", 10.0, {"min_power_pct": 40, "max_reduce_min": 30})
DISH = PlantDevice("dishwasher_1", "dishwasher", "Dishwasher 1", "deferrable", "job", 6.0,
                   {"max_delay_min": 60, "must_finish_by": "19:30"}, deadline_min=19 * 60 + 30)
FRYER = PlantDevice("fryer_1", "fryer", "Fryer 1", "always_on", "demand_driven", 14.0, {})


def cmd(device, action, value, cid="c_0001", lane="with"):
    return {"command_id": cid, "lane": lane, "ts": T0, "device_id": device, "action": action, "value": value,
            "decision_id": "d_0001", "issued_by": "engine"}


def test_reduce_caps_and_repays_in_the_first_later_block_with_room():
    p = ReplayPlant("with", [HVAC])
    p.deliver([cmd("hvac_1", "reduce", 60)], T0)
    got = [p.block({"hvac_1": 10.0}, info(0))["hvac_1"]]           # capped at 6 kW, owes 4 kW x 0.25 h = 1 kWh
    assert got[0] == (6.0, "reduced") and p.state["hvac_1"].owed_kwh == pytest.approx(1.0)
    p.deliver([cmd("hvac_1", "restore", None, "c_0002")], T0 + B)
    got.append(p.block({"hvac_1": 10.0}, info(1))["hvac_1"])       # no room at rated
    got.append(p.block({"hvac_1": 7.0}, info(2))["hvac_1"])        # room 3 kW -> repays 3 kW (0.75 kWh)
    got.append(p.block({"hvac_1": 7.0}, info(3))["hvac_1"])        # repays the last 0.25 kWh = 1 kW
    assert [g[0] for g in got] == [6.0, 10.0, 10.0, 8.0]
    assert sum(g[0] for g in got) * 0.25 == pytest.approx((10 + 10 + 7 + 7) * 0.25)  # energy conserved
    assert p.state["hvac_1"].owed_kwh == 0.0 and p.violations == 0


def test_owed_energy_is_repaid_at_the_last_block_before_close_even_without_room():
    p = ReplayPlant("with", [HVAC])
    p.deliver([cmd("hvac_1", "reduce", 50)], T0)
    p.block({"hvac_1": 10.0}, info(0))
    p.deliver([cmd("hvac_1", "restore", None, "c_0002")], T0 + B)
    kw = p.block({"hvac_1": 10.0}, info(1, close_at=1))["hvac_1"][0]
    assert kw == pytest.approx(15.0) and p.over_rated_blocks == 1


def test_delay_holds_job_energy_and_releases_it_whole_when_room_allows():
    p = ReplayPlant("with", [DISH])
    p.deliver([cmd("dishwasher_1", "delay", 30)], T0)
    a = p.block({"dishwasher_1": 2.0}, info(0))["dishwasher_1"]
    b = p.block({"dishwasher_1": 2.0}, info(1))["dishwasher_1"]
    c = p.block({"dishwasher_1": 1.0}, info(2))["dishwasher_1"]     # release: 1 + (2+2) = 5 kW <= 6
    assert a == (0.0, "waiting") and b == (0.0, "waiting") and c == (5.0, "running_job")
    assert p.violations == 0


def test_released_energy_spills_into_the_next_blocks_when_above_rated():
    p = ReplayPlant("with", [DISH])
    p.deliver([cmd("dishwasher_1", "delay", 45)], T0)
    for k in range(3):
        p.block({"dishwasher_1": 3.0}, info(k))                     # 9 kW worth held (2.25 kWh)
    d = p.block({"dishwasher_1": 3.0}, info(3))["dishwasher_1"][0]  # 3 + 3 room -> 6
    e = p.block({"dishwasher_1": 3.0}, info(4))["dishwasher_1"][0]  # 3 + 3 -> 6
    f = p.block({"dishwasher_1": 0.0}, info(5))["dishwasher_1"][0]  # remaining 3 kW
    assert (d, e, f) == (6.0, 6.0, 3.0)


def test_start_and_delay_zero_release_at_once():
    p = ReplayPlant("with", [DISH])
    p.deliver([cmd("dishwasher_1", "delay", 60)], T0)
    p.block({"dishwasher_1": 2.0}, info(0))
    p.deliver([cmd("dishwasher_1", "start", None, "c_0002")], T0 + B)
    assert p.block({"dishwasher_1": 1.0}, info(1))["dishwasher_1"][0] == 3.0


def test_acks_are_ok_with_the_value_and_reach_the_next_report():
    p = ReplayPlant("with", [HVAC, FRYER])
    p.deliver([cmd("hvac_1", "reduce", 60)], T0)
    placed = p.block({"hvac_1": 10.0, "fryer_1": 5.0}, info(0))
    rep = HubReport.model_validate(p.report(placed, info(0), tick_id=7))
    assert rep.acks[0].ok and rep.acks[0].applied_value == 60 and rep.acks[0].reason is None
    assert rep.total_kw == pytest.approx(11.0) and rep.ts == T0 + B and rep.tick_id == 7
    assert p.report(placed, info(0), 8)["acks"] == []               # acked once


def test_rule_counters():
    p = ReplayPlant("with", [HVAC, DISH, FRYER])
    p.deliver([cmd("fryer_1", "reduce", 50, "c_1")], T0)            # always_on commanded
    p.deliver([cmd("hvac_1", "reduce", 30, "c_2")], T0)             # below min_power_pct 40
    assert p.violations == 2
    p.deliver([cmd("dishwasher_1", "delay", 60, "c_3")], T0)
    p.deliver([cmd("dishwasher_1", "delay", 60, "c_4")], T0 + 2 * B)  # hold now 90 min > max_delay_min 60
    assert p.violations == 3


def test_job_energy_waiting_past_the_deadline_is_a_violation():
    p = ReplayPlant("with", [DISH])
    late = BlockInfo(T0, T0 + B, date(2026, 7, 15), 19 * 60 + 15, False, False)  # 19:15-19:30 block
    p.deliver([cmd("dishwasher_1", "delay", 30)], T0)
    p.block({"dishwasher_1": 2.0}, late)
    assert p.violations == 1


def test_end_of_day_flush_keeps_the_day_energy():
    p = ReplayPlant("with", [DISH])
    p.deliver([cmd("dishwasher_1", "delay", 60)], T0)
    kw = p.block({"dishwasher_1": 2.0}, info(0, last_of_day_at=0))["dishwasher_1"][0]
    assert kw == 2.0 and p.state["dishwasher_1"].hold_until is None


def test_timer_internal_commands_are_not_acked():
    p = ReplayPlant("timer", [DISH])
    p.deliver([cmd("dishwasher_1", "delay", 30, lane="timer")], T0, internal=True)
    placed = p.block({"dishwasher_1": 2.0}, info(0))
    assert placed["dishwasher_1"] == (0.0, "waiting")
    rep = p.report(placed, info(0), 0)
    assert rep["acks"] == [] and rep["lane"] == "without"
