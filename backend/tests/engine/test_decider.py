"""Planner hand cases from ENGINE.md §15; expected numbers are independent arithmetic."""
from datetime import timedelta

import pytest

from engine.decider import plan
from engine.tariff import TariffView
from tests.engine.conftest import load_tariff, local_ts


def device(did, importance, rated, limits, state="on", **extra):
    return dict(device_id=did, importance=importance, rated_kw=rated, limits=limits,
                state=state, category="hvac", power_model="thermal", params={}, **extra)


def forecast(now, series):
    return {"block_starts": [now + timedelta(minutes=15*i) for i in range(len(next(iter(series.values()))))],
            "device_kw": series, "total_kw": [sum(x[i] for x in series.values()) for i in range(len(next(iter(series.values()))))],
            "unavoidable_kw": [0]*len(next(iter(series.values())))}


def run(now, fc, devices, **kwargs):
    return plan(now=now, forecast=fc, devices=devices, target=40, tariff=TariffView(load_tariff()),
                operating_hours={"open":"10:00", "close":"22:00"}, **kwargs)


def test_deferrable_moves_three_kwh_into_first_valley():
    now = local_ts(2026, 7, 10, 12)
    fc = forecast(now, {"must": [30,38,40,36,28,22], "dishwasher": [0,6,6,0,0,0]})
    job = device("dishwasher", "deferrable", 6, {"max_delay_min":60,"must_finish_by":"22:00"})
    job.update(power_model="job", params={"cycle_min":30})
    out = run(now, fc, [job])
    assert [a["action"] for a in out["actions"]] == ["delay"]
    assert out["forecast"]["total_kw"] == [30,38,40,36,34,28]
    assert sum(out["forecast"]["device_kw"]["dishwasher"])*.25 == 3
    assert out["actions"][0]["effect"]["peak_before_kw"] == 46
    assert out["actions"][0]["effect"]["peak_after_kw"] == 40


def test_flexible_reduces_only_four_kw_to_sixty_percent():
    now=local_ts(2026,7,10,12)
    fc=forecast(now,{"must":[34]*8,"hvac":[10]*8})
    out=run(now,fc,[device("hvac","flexible",10,{"min_power_pct":40,"max_reduce_min":30})])
    assert out["actions"][0]["value"] == 60
    assert out["forecast"]["total_kw"][0] == 40
    # With no spare capacity before the horizon ends, the 2 kWh remains explicitly owed.
    assert sum(out["forecast"]["device_kw"]["hvac"])*.25 + out["forecast"]["unplaced_kwh"] == pytest.approx(20)


def test_protected_rejected_always_on_and_closed_never_reduced():
    now=local_ts(2026,7,10,12)
    fc=forecast(now,{"hvac":[44]*8})
    flex=device("hvac","flexible",44,{"min_power_pct":40,"max_reduce_min":30})
    for args in ({"protected":{"hvac":now+timedelta(minutes=30)}},{"rejected":{"hvac":now}},{"cooldowns":{"hvac":now+timedelta(minutes=30)}}):
        assert run(now,fc,[flex],**args)["actions"] == []
    assert run(now,fc,[device("hvac","always_on",44,{})])["actions"] == []
    assert run(now.replace(hour=6),fc,[flex])["actions"] == []


def test_effects_are_marginal_and_add_up():
    now=local_ts(2026,7,10,12)
    fc=forecast(now,{"must":[30,30,30,30,0,0,0,0],"a":[10]*8,"b":[10]*8})
    devices=[device(d,"flexible",10,{"min_power_pct":40,"max_reduce_min":30}) for d in ("a","b")]
    out=run(now,fc,devices)
    actions=out["actions"]
    assert len(actions) >= 2
    assert actions[0]["effect"]["peak_after_kw"] == actions[1]["effect"]["peak_before_kw"]
    assert sum(a["effect"]["saving_usd"] for a in actions) == pytest.approx(out["saving_usd"])


def test_partial_block_preserves_already_metered_energy():
    from engine.decider import reduce_forecast
    now=local_ts(2026,7,10,12,5)
    start=now-timedelta(minutes=5)
    # Five minutes at 10 kW already used 5/6 kWh; ten minutes remain.
    fc=forecast(start,{"hvac":[10]*8})
    fc["_metered_kwh"]={"hvac":10*5/60}
    out=reduce_forecast(fc,"hvac",10,40,start+timedelta(minutes=15),now)
    # (10*5 + 4*10)/15 = 6 kW. Past meter samples cannot be reduced.
    assert out["total_kw"][0]==pytest.approx(6)


def test_restore_and_release_early_when_the_valley_has_room():
    now=local_ts(2026,7,10,12)
    flex=device("hvac","flexible",10,{"min_power_pct":40,"max_reduce_min":30})
    fc=forecast(now,{"must":[20]*8,"hvac":[6,6,10,10,10,10,10,10]})
    active={"hvac":{"action":"reduce","value":60,"restore_at":now+timedelta(minutes=30),"expected_kw":10}}
    out=run(now,fc,[flex],active=active)
    assert [a["action"] for a in out["actions"]] == ["restore"]
    job=device("dishwasher","deferrable",6,{"max_delay_min":60,"must_finish_by":"22:00"},state="waiting")
    job.update(params={"cycle_min":30})
    fc=forecast(now,{"must":[20]*8,"dishwasher":[0,0,6,6,0,0,0,0]})
    active={"dishwasher":{"action":"delay","value":30,"release_at":now+timedelta(minutes=30)}}
    out=run(now,fc,[job],active=active)
    assert [a["action"] for a in out["actions"]] == ["start"]
    assert out["forecast"]["device_kw"]["dishwasher"] == [6,6,0,0,0,0,0,0]


def test_job_delay_never_moves_energy_already_consumed_in_current_block():
    now=local_ts(2026,7,10,12,5)
    start=now-timedelta(minutes=5)
    fc=forecast(start,{"must":[38,38,20,20,20,20],"dishwasher":[6,6,0,0,0,0]})
    fc["_metered_kwh"]={"dishwasher":.5}
    job=device("dishwasher","deferrable",6,{"max_delay_min":60,"must_finish_by":"22:00"})
    job.update(params={"cycle_min":30})
    out=run(now,fc,[job])
    assert out["forecast"]["device_kw"]["dishwasher"][0] == 2
    assert sum(out["forecast"]["device_kw"]["dishwasher"])*.25 == 3


def test_future_reduction_preserves_planned_prefix_as_well_as_past_meter():
    from engine.decider import reduce_forecast
    now=local_ts(2026,7,10,12,5)
    start=now-timedelta(minutes=5)
    fc=forecast(start,{"hvac":[10]*8})
    fc["_metered_kwh"]={"hvac":10*5/60}
    fc["_now"]=now
    out=reduce_forecast(fc,"hvac",10,40,start+timedelta(minutes=15),now+timedelta(minutes=5))
    # Ten minutes at10kW precede the hypothetical action; last5min at4kW =>8kW average.
    assert out["total_kw"][0]==pytest.approx(8)


def test_idle_job_expected_value_moves_one_cycle_not_entire_horizon():
    now=local_ts(2026,7,10,12)
    fc=forecast(now,{"must":[39,39,20,20,20,20,20,20],"dishwasher":[1.5]*8})
    job=device("dishwasher","deferrable",6,{"max_delay_min":60,"must_finish_by":"22:00"})
    job.update(params={"cycle_min":30})
    out=run(now,fc,[job])
    assert [a["action"] for a in out["actions"]] == ["delay"]
    assert out["forecast"]["total_kw"][:4] == [39,39,23,23]
    assert sum(out["forecast"]["device_kw"]["dishwasher"])*.25 == 3
