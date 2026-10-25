"""Facade executor tests: commands leave once, become active only through hub acks."""
from datetime import timedelta

import pytest

from engine import Kitchen, RuleError
from tests.engine.conftest import catalog, hub_report, load_config, load_catalog, load_tariff, local_ts, roster


def kitchen(control="with", cap=100):
    cfg=load_config().model_copy(update={"peak_cap_kw":cap})
    k=Kitchen(cfg,load_tariff(),catalog(),control,42)
    devs=roster(cfg,load_catalog())
    return k,devs


def tick(k,devs,n,acks=None, powers=None):
    now=local_ts(2026,7,10,12)+timedelta(minutes=n)
    return k.step(1,hub_report(lane=k.control,tick_id=n,ts=now,total_kw=0,devices=devs,acks=acks,power_by_device=powers or {}))


def ack(command, **changes):
    return dict(command_id=command["command_id"],lane=command["lane"],ok=True,
                applied_value=changes.pop("applied_value",command["value"]),reason=None,**changes)


def test_owner_command_delivered_once_and_clamped_ack_active():
    k,devs=kitchen()
    tick(k,devs,1)
    command=k.owner_command("hvac_1","reduce",60)
    out=tick(k,devs,2)
    assert out["new_commands"] == [command]
    assert k.snapshot()["active_commands"] == []
    tick(k,devs,3,[ack(command,applied_value=65)])
    assert k.snapshot()["active_commands"][0]["value"] == 65
    assert tick(k,devs,4)["new_commands"] == []


def test_missing_and_negative_ack_do_not_activate():
    for reason in (None,"job_running","unknown_device"):
        k,devs=kitchen()
        tick(k,devs,1)
        c=k.owner_command("dishwasher_1","delay",10)
        tick(k,devs,2)
        acks=[] if reason is None else [dict(command_id=c["command_id"],lane="with",ok=False,applied_value=None,reason=reason)]
        tick(k,devs,3,acks)
        assert k.snapshot()["active_commands"] == []


def test_undo_requires_active_reduce_and_protects_device():
    k,devs=kitchen()
    tick(k,devs,1)
    c=k.owner_command("hvac_1","reduce",60)
    tick(k,devs,2)
    with pytest.raises(RuleError):
        k.undo(c["decision_id"])
    tick(k,devs,3,[ack(c)])
    revert=k.undo(c["decision_id"])
    assert revert["action"] == "restore"
    assert revert["issued_by"] == "owner"
    assert revert["decision_id"] == c["decision_id"]
    assert k.snapshot()["recent_decisions"][0]["status"] == "undone"
    with pytest.raises(RuleError):
        k.undo(c["decision_id"])


def test_engine_reduction_cadence_and_ack_no_repeat():
    k,devs=kitchen(cap=4)
    powers={"hvac_1":7.5}
    assert tick(k,devs,1,powers=powers)["new_commands"] == []
    out=tick(k,devs,5,powers=powers)
    commands=[c for c in out["new_commands"] if c["action"]=="reduce"]
    assert commands and commands[0]["device_id"]=="hvac_1"
    c=commands[0]
    tick(k,devs,6,[ack(c)],powers=powers)
    again=tick(k,devs,10,powers={"hvac_1":3})
    assert not [c for c in again["new_commands"] if c["action"]=="reduce" and c["value"]==commands[0]["value"]]
    assert not tick(k,devs,11,powers=powers)["new_commands"]


def test_snapshot_and_what_if_are_pure():
    k,devs=kitchen()
    tick(k,devs,5,powers={"hvac_1":7.5})
    before=k.snapshot()
    k.what_if("hvac_1","reduce",60,k._now)
    assert k.snapshot()==before
    with pytest.raises(RuleError):
        k.what_if("hvac_1","reduce",60,k._now+timedelta(minutes=120))


def test_reduction_restores_at_thirty_minutes_and_cools_down():
    k,devs=kitchen(cap=4)
    out=tick(k,devs,5,powers={"hvac_1":7.5})
    c=next(c for c in out["new_commands"] if c["action"]=="reduce")
    tick(k,devs,6,[ack(c)],powers={"hvac_1":3})
    # At t=35, the reduction issued at t=5 has reached its 30-minute limit.
    restore=tick(k,devs,35,powers={"hvac_1":3})
    r=next(c for c in restore["new_commands"] if c["device_id"]=="hvac_1" and c["action"]=="restore")
    tick(k,devs,36,[ack(r)],powers={"hvac_1":7.5})
    assert not [c for c in tick(k,devs,40,powers={"hvac_1":7.5})["new_commands"] if c["device_id"]=="hvac_1" and c["action"]=="reduce"]


def test_unknown_device_never_recommanded_and_snapshot_escalations_json_ready():
    import json
    k,devs=kitchen(cap=4)
    out=tick(k,devs,5,powers={"hvac_1":7.5})
    c=next(c for c in out["new_commands"] if c["action"]=="reduce")
    reject=dict(command_id=c["command_id"],lane="with",ok=False,applied_value=None,reason="unknown_device")
    tick(k,devs,6,[reject],powers={"hvac_1":7.5})
    assert not [c for c in tick(k,devs,20,powers={"hvac_1":7.5})["new_commands"] if c["device_id"]=="hvac_1"]
    json.dumps(k.snapshot())


def test_what_if_validates_hold_at_hypothetical_timestamp():
    k,devs=kitchen()
    # Dishwasher's configured deadline is 19:30 local; a 30-minute cycle started after 19:00 is late.
    now=local_ts(2026,7,10,18)
    k.step(1,hub_report(lane="with",tick_id=5,ts=now,total_kw=0,devices=devs,power_by_device={}))
    with pytest.raises(RuleError):
        k.what_if("dishwasher_1","delay",30,local_ts(2026,7,10,19))
    with pytest.raises(RuleError):
        k.what_if("missing","reduce",60,now)


def test_rejected_engine_command_is_not_resent_in_same_block():
    k,devs=kitchen(cap=4)
    out=tick(k,devs,5,powers={"hvac_1":7.5})
    c=next(c for c in out["new_commands"] if c["action"]=="reduce")
    reject=dict(command_id=c["command_id"],lane="with",ok=False,applied_value=None,reason="already_off")
    tick(k,devs,6,[reject],powers={"hvac_1":7.5})
    assert not [c for c in tick(k,devs,10,powers={"hvac_1":7.5})["new_commands"] if c["device_id"]=="hvac_1"]


def test_same_step_replacement_acks_follow_command_order():
    k,devs=kitchen()
    tick(k,devs,1,powers={"hvac_1":7.5})
    _,first=k._issue("hvac_1","reduce",60,"stay_under_cap")
    _,second=k._issue("hvac_1","reduce",50,"stay_under_cap")
    tick(k,devs,2,powers={"hvac_1":7.5})
    tick(k,devs,3,[ack(second),ack(first)],powers={"hvac_1":3.75})
    assert k.snapshot()["active_commands"] == [second]


def test_compare_lanes_hand_computed_eighteen_dollars_forty_and_six_kw():
    from copy import deepcopy
    from engine import compare_lanes
    from tests.engine.conftest import load_json
    without=load_json("shapes/tick_state_without.json")
    with_=deepcopy(without)
    with_.update(lane="with")
    without["meter"].update(cost_usd_today=61.20,month_peak_kw=46)
    with_["meter"].update(cost_usd_today=42.80,month_peak_kw=40)
    result=compare_lanes(without,with_)
    assert result["saved_today_usd"]==pytest.approx(18.40)
    assert result["peak_avoided_kw"]==6


def test_real_kitchen_fallback_commands_leave_in_opening_step():
    import json
    k,devs=kitchen(cap=4)
    k.authority.update(max_cap_overrun_kw=0,may_go_below_min_power=True,max_extra_reduce_min=60)
    out=tick(k,devs,5,powers={"hvac_1":8,"lights_1":2.4})
    assert out["new_escalations"]
    fallback=[d for d in out["new_decisions"] if d["reason_code"]=="escalation_fallback"]
    assert fallback
    for d in fallback:
        assert any(c["decision_id"]==d["decision_id"] for c in out["new_commands"])
    json.dumps(k.snapshot())
    json.dumps(out)


def test_real_kitchen_rejects_then_accepts_choice_and_delivers_next_tick():
    import json
    k,devs=kitchen(cap=4)
    k.authority.update(max_cap_overrun_kw=0,may_go_below_min_power=False,max_extra_reduce_min=60)
    out=tick(k,devs,5,powers={"hvac_1":8,"lights_1":2.4})
    e=next(e for e in out["new_escalations"] if any(o["option_id"].startswith("deep_reduce") for o in e["options"]))
    option=next(o for o in e["options"] if o["option_id"].startswith("deep_reduce"))
    denied=k.resolve_escalation(e["escalation_id"],option["option_id"],"claude","first try")
    assert denied["claude_attempts"][-1]["reason"]=="outside_authority"
    k.authority["may_go_below_min_power"]=True
    accepted=k.resolve_escalation(e["escalation_id"],option["option_id"],"claude","retry")
    assert accepted["status"]=="resolved"
    assert len(accepted["claude_attempts"])==2
    json.dumps(accepted)
    next_tick=tick(k,devs,6,[ack(c) for c in out["new_commands"]],powers={"hvac_1":3.2,"lights_1":2.4})
    assert any(d["reason_code"]=="escalation_choice" for d in next_tick["new_decisions"])
    assert any(c["value"]==option["actions"][0]["value"] for c in next_tick["new_commands"])


def test_deadline_forced_waiting_job_is_unavoidable():
    k,devs=kitchen(cap=4)
    now=local_ts(2026,7,10,19)
    report=hub_report(lane="with",tick_id=5,ts=now,total_kw=0,devices=devs,power_by_device={"lights_1":2.4}).model_dump(mode="json")
    for d in report["devices"]:
        if d["device_id"]=="dishwasher_1":
            d.update(state="waiting",physical={"job_remaining_min":30})
    out=k.step(1,report)
    assert any(w["code"]=="cap_unreachable" and w["data"]["unavoidable_kw"]>=6 for w in out["warnings"])
    assert not [d for d in out["new_decisions"] if d["device_id"]=="dishwasher_1" and d["reason_code"]=="stay_under_cap"]
