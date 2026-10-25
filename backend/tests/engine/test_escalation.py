"""Hand-computed G73 cases; no runtime, network, or Claude required."""
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

import pytest
from contracts import Escalation
from engine import escalation
from engine.ids import IdAllocator
from engine.rules import RuleError
from engine.tariff import TariffView
from tests.engine.conftest import local_ts, load_tariff

NOW = local_ts(2026, 7, 17, 12)


def kitchen(overrun=5, devices=None):
    k = SimpleNamespace(control='with', ids=IdAllocator(), _now=NOW, _escalations={},
        authority={'enabled': True, 'max_cap_overrun_kw': overrun, 'max_extra_delay_min': 20,
                   'max_extra_reduce_min': 15, 'may_go_below_min_power': False},
        _tariff=TariffView(load_tariff()), _active_commands=[], _protected={}, _rejected={},
        config=SimpleNamespace(operating_hours=SimpleNamespace(open='09:00', close='22:00')),
        issued=[], _recent_decisions=[])
    k._planning_devices = lambda: deepcopy(devices or [])
    k._meter_now = lambda: {'target_kw': 40, 'demand_peaks': []}
    def issue(did, action, value, reason_code, **kw):
        k.issued.append((did, action, value, reason_code, kw))
    k._issue = issue
    return k


def forecast(load=44, block=1, device_kw=None):
    rates = [30.] * 8
    rates[block] = float(load)
    return {'block_starts': [NOW + timedelta(minutes=15*i) for i in range(8)],
            'total_kw': rates, 'device_kw': device_kw or {'fixed': rates},
            'unavoidable_kw': rates.copy()}


def opened(k, fc=None):
    rows = escalation.update(k, NOW, fc or forecast(), replan=True)
    assert len(rows) == 1
    Escalation.model_validate(rows[0])
    return rows[0]


def test_authorized_overrun_and_no_authority_fallback():
    for cap, expected in [(5, True), (3, False)]:
        k = kitchen(cap)
        e = opened(k)
        assert e['default_option_id'] == e['active_option_id'] == 'accept_overrun'
        assert e['options'][0]['within_authority'] is expected
        assert e['options'][0]['harm_score'] == pytest.approx(4/cap)
        assert e['deadline_sim_ts'] == NOW + timedelta(minutes=10)
        assert k.issued == []


def test_rejected_then_accepted_retry_and_unknown_option():
    k = kitchen(3); e = opened(k)
    result = escalation.resolve(k, e['escalation_id'], 'accept_overrun', 'claude', 'context')
    assert result['status'] == 'open'
    assert result['claude_attempts'][-1]['reason'] == 'outside_authority'
    assert result['chosen_option_id'] is None
    k.authority['max_cap_overrun_kw'] = 5
    result = escalation.resolve(k, e['escalation_id'], 'accept_overrun', 'claude', 'updated')
    assert result['status'] == 'resolved'
    assert len(result['claude_attempts']) == 2
    assert result['claude_attempts'][-1]['accepted'] is True
    with pytest.raises(RuleError):
        escalation.resolve(k, e['escalation_id'], 'unknown', 'claude', None)
    with pytest.raises(RuleError):
        escalation.resolve(k, e['escalation_id'], 'accept_overrun', 'owner', None)


def test_retry_budget_and_deadline_at_non_decision_tick():
    k = kitchen(3); e = opened(k)
    for _ in range(2):
        escalation.resolve(k, e['escalation_id'], 'accept_overrun', 'claude', None)
    with pytest.raises(RuleError):
        escalation.resolve(k, e['escalation_id'], 'accept_overrun', 'claude', None)
    k._now = NOW + timedelta(minutes=10)
    rows = escalation.update(k, k._now, forecast(), replan=False)
    assert rows[0]['status'] == 'expired_default'
    result = escalation.resolve(k, e['escalation_id'], 'accept_overrun', 'claude', None)
    assert result['claude_attempts'][-1]['reason'] == 'after_deadline'
    assert result['resolved_by'] == 'default'


def test_future_risk_update_obsolete_and_reopen():
    k = kitchen()
    assert escalation.update(k, NOW, forecast(block=3), replan=True) == []
    e = opened(k)
    rows = escalation.update(k, NOW + timedelta(minutes=5), forecast(46), replan=True)
    assert rows[0]['escalation_id'] == e['escalation_id']
    assert rows[0]['problem']['excess_kw'] == 6
    assert rows[0]['deadline_sim_ts'] == e['deadline_sim_ts']
    rows = escalation.update(k, NOW + timedelta(minutes=5), forecast(39), replan=True)
    assert rows[0]['status'] == 'obsolete'
    rows = escalation.update(k, NOW + timedelta(minutes=5), forecast(44), replan=True)
    assert rows[0]['escalation_id'] != e['escalation_id']


def test_food_floor_and_harm_rank_immediate_fallback():
    device = {'device_id':'cooler_1', 'type_id':'cooler','importance':'flexible',
              'category':'refrigeration','state':'on','rated_kw':10.,'power_kw':8.,
              'limits':{'min_power_pct':80,'max_reduce_min':30},'params':{}}
    k = kitchen(0, [device]); k.authority['may_go_below_min_power'] = True
    fc = forecast(44, device_kw={'fixed':[36.]*8,'cooler_1':[8.]*8})
    fc['total_kw'] = [44.]*8
    options = escalation.options(k, NOW, fc, 1, 40)
    deep = next(o for o in options if o['option_id'] == 'deep_reduce_cooler')
    assert all(a['value'] >= 50 for a in deep['actions'])
    assert deep['rule_breaks'][0]['amount'] == 30
    # Remaining 1 kW overrun exceeds zero authority; neither option is authorized.
    assert not deep['within_authority']
    k.authority['max_cap_overrun_kw'] = 2
    e = opened(k, forecast(42, device_kw={'fixed':[34.]*8,'cooler_1':[8.]*8}))
    assert e['default_option_id'] == 'deep_reduce_cooler'
    assert k.issued[0][3] == 'escalation_fallback'


def test_disabled_authority_and_snapshot_copy():
    k = kitchen(); k.authority['enabled'] = False
    e = opened(k)
    assert not any(o['within_authority'] for o in e['options'])
    e['options'].clear()
    assert k._escalations[e['escalation_id']]['options']


def test_extend_delay_harm_and_future_fallback_lifetime():
    d = {'device_id':'dish_1','type_id':'dish','importance':'deferrable','category':'cleaning',
         'state':'waiting','rated_kw':6.,'power_kw':6.,
         'limits':{'max_delay_min':20,'must_finish_by':'22:00'},'params':{'cycle_min':15}}
    k = kitchen(3,[d])
    fc = forecast(42,device_kw={'fixed':[30.,36.,30.,30.,30.,30.,30.,30.],
                               'dish_1':[0.,6.,0.,0.,0.,0.,0.,0.]})
    e=opened(k,fc)
    assert e['default_option_id']=='extend_delay_dish'
    assert e['options'][0]['harm_score']==pytest.approx(.5)  # 30 min hold - 20 allowed / 20 extra
    assert k.issued[0][1:3]==('delay',30)
    assert k.issued[0][4]['release_at']==NOW+timedelta(minutes=30)


def test_future_reduction_lasts_through_problem_block():
    d={'device_id':'hvac_1','type_id':'hvac','importance':'flexible','category':'hvac','state':'on',
       'rated_kw':10.,'power_kw':8.,'limits':{'min_power_pct':80,'max_reduce_min':30},'params':{}}
    k=kitchen(3,[d]); k.authority['may_go_below_min_power']=True
    fc=forecast(42,device_kw={'fixed':[22.,34.,22.,22.,22.,22.,22.,22.], 'hvac_1':[8.]*8})
    e=opened(k,fc)
    assert e['default_option_id']=='deep_reduce_hvac'
    assert k.issued[0][4]['restore_at']==NOW+timedelta(minutes=30)


def test_resolve_revalidates_new_engine_forecast():
    k=kitchen(5); e=opened(k)
    k._escalation_forecast=lambda: forecast(48)
    result=escalation.resolve(k,e['escalation_id'],'accept_overrun','claude',None)
    assert result['status']=='open'
    assert result['claude_attempts'][-1]['reason']=='outside_authority'
    assert result['problem']['excess_kw']==8


def test_switch_restores_in_rules_cap_and_keeps_debt():
    d={'device_id':'hvac_1','type_id':'hvac','importance':'flexible','category':'hvac','state':'on',
       'rated_kw':10.,'power_kw':8.,'limits':{'min_power_pct':80,'max_reduce_min':30},'params':{}}
    k=kitchen(3,[d]);k.authority['may_go_below_min_power']=True
    k._active_meta={'hvac_1':{'action':'reduce','value':80,'restore_at':NOW+timedelta(minutes=30)}}
    fc=forecast(42,device_kw={'fixed':[22.,34.,22.,22.,22.,22.,22.,22.], 'hvac_1':[8.]*8})
    e=opened(k,fc)
    k._active_meta['hvac_1']['value']=60  # hub acknowledged the fallback
    k.issued.clear()
    result=escalation.resolve(k,e['escalation_id'],'accept_overrun','claude',None)
    assert result['status']=='resolved'
    assert k.issued[0][1:3]==('reduce',80)
    assert k.issued[0][4]['escalation'] is False


def test_delayed_pick_preserves_evaluated_absolute_job_release():
    d={'device_id':'dish_1','type_id':'dish','importance':'deferrable','category':'cleaning','state':'waiting',
       'rated_kw':6.,'power_kw':6.,'limits':{'max_delay_min':20,'must_finish_by':'22:00'},'params':{'cycle_min':15}}
    k=kitchen(0,[d]); k.authority['max_extra_delay_min']=10
    fc=forecast(42,device_kw={'fixed':[30.,36.,30.,30.,30.,30.,30.,30.], 'dish_1':[0.,6.,0.,0.,0.,0.,0.,0.]})
    e=opened(k,fc)
    # Test the switch path: fallback was physically overrun, Claude chooses the evaluated delay 5 min later.
    k._escalations[e['escalation_id']]['active_option_id']='accept_overrun'
    k.issued.clear();k._now=NOW+timedelta(minutes=5)
    result=escalation.resolve(k,e['escalation_id'],'extend_delay_dish','claude',None)
    assert result['status']=='resolved'
    assert k.issued[0][1:3]==('delay',25)
    assert k.issued[0][4]['release_at']==NOW+timedelta(minutes=30)


def test_partial_block_deep_option_changes_only_future_power():
    d={'device_id':'hvac_1','type_id':'hvac','importance':'flexible','category':'hvac','state':'on',
       'rated_kw':10.,'power_kw':6.,'limits':{'min_power_pct':60,'max_reduce_min':30},'params':{}}
    k=kitchen(0,[d]); k.authority['may_go_below_min_power']=True
    fc=forecast(0,block=0,device_kw={'fixed':[34.,20.,20.,20.,20.,20.,20.,20.],
                                   'hvac_1':[110/15,6.,6.,6.,6.,6.,6.,6.]})
    fc['total_kw']=[34+110/15]+[26.]*7
    fc['_metered_kwh']={'hvac_1':10*5/60}
    opts=escalation.options(k,NOW+timedelta(minutes=5),fc,0,40)
    deep=next(o for o in opts if o['option_id']=='deep_reduce_hvac')
    assert deep['actions'][0]['value']==40
    assert deep['projected']['peak_kw']==pytest.approx(40)


def test_resolved_block_can_reopen_only_after_risk_clears_and_returns():
    k=kitchen(); e=opened(k)
    escalation.resolve(k,e['escalation_id'],'accept_overrun','claude',None)
    assert escalation.update(k,NOW+timedelta(minutes=5),forecast(44),replan=True)==[]
    assert escalation.update(k,NOW+timedelta(minutes=5),forecast(39),replan=True)==[]
    rows=escalation.update(k,NOW+timedelta(minutes=5),forecast(46),replan=True)
    assert len(rows)==1
    assert rows[0]['escalation_id']!=e['escalation_id']


def test_job_delay_never_moves_already_metered_energy():
    d={'device_id':'dish_1','type_id':'dish','importance':'deferrable','category':'cleaning','state':'waiting',
       'rated_kw':6.,'power_kw':6.,'limits':{'max_delay_min':0,'must_finish_by':'22:00'},'params':{'cycle_min':15}}
    k=kitchen(5,[d])
    fc=forecast(42,block=0,device_kw={'fixed':[38.,30.,30.,30.,30.,30.,30.,30.],
                                   'dish_1':[4.,0.,0.,0.,0.,0.,0.,0.]})
    fc['total_kw']=[42.]+[30.]*7
    fc['_metered_kwh']={'dish_1':.5}  # 2kW of the 4kW block-average is already used
    opts=escalation.options(k,NOW+timedelta(minutes=5),fc,0,40)
    delayed=next(o for o in opts if o['option_id']=='extend_delay_dish')
    assert delayed['projected']['peak_kw']==40  # only future 2kW moved


def test_switch_does_not_undo_another_blocks_active_control():
    d={'device_id':'hvac_1','type_id':'hvac','importance':'flexible','category':'hvac','state':'on',
       'rated_kw':10.,'power_kw':8.,'limits':{'min_power_pct':80,'max_reduce_min':30},'params':{}}
    k=kitchen(3,[d]);k.authority['may_go_below_min_power']=True
    fc=forecast(42,device_kw={'fixed':[22.,34.,22.,22.,22.,22.,22.,22.], 'hvac_1':[8.]*8})
    e=opened(k,fc)
    other=deepcopy(k._escalations[e['escalation_id']]); other['escalation_id']='e_0002'
    other['block_start']+=timedelta(minutes=15)
    k._escalations['e_0002']=other
    k._active_meta={'hvac_1':{'action':'reduce','value':60,'restore_at':NOW+timedelta(minutes=30)}}
    k.issued.clear()
    escalation.resolve(k,e['escalation_id'],'accept_overrun','claude',None)
    assert not any(row[1]=='restore' for row in k.issued)
    assert k._active_meta['hvac_1']['restore_at']==NOW+timedelta(minutes=45)


def test_multidevice_fallback_effects_are_marginal_and_use_actual_duration():
    from engine.decider import horizon_cost, reduce_forecast
    devices=[{'device_id':did,'type_id':'cooler','importance':'flexible','category':'refrigeration','state':'on',
              'rated_kw':5.,'power_kw':5.,'limits':{'min_power_pct':80,'max_reduce_min':15},'params':{}}
             for did in ('a','b')]
    k=kitchen(5,devices);k.authority['may_go_below_min_power']=True
    fc=forecast(44,device_kw={'fixed':[34.]*8,'a':[5.]*8,'b':[5.]*8});fc['total_kw']=[44.]*8
    k._forecast_detail=deepcopy(fc)
    def project(before,did,action,value,at,restore_at=None,release_at=None):
        return reduce_forecast(before,did,5,value,restore_at,at)
    k._project_action=project
    option=next(o for o in escalation.options(k,NOW,fc,1,40) if o['option_id']=='deep_reduce_cooler')
    escalation._apply(k,NOW,option,'escalation_fallback',until=NOW+timedelta(minutes=30))
    assert len(k.issued)==2
    effects=[row[4]['effect'] for row in k.issued]
    assert effects[0]['peak_after_kw']==effects[1]['peak_before_kw']
    assert sum(e['saving_usd'] for e in effects)==pytest.approx(
        horizon_cost(fc,k._tariff)-horizon_cost(k._forecast_detail,k._tariff))


def test_owner_supersession_does_not_break_accept_overrun():
    d={'device_id':'hvac_1','type_id':'hvac','importance':'flexible','category':'hvac','state':'on',
       'rated_kw':10.,'power_kw':8.,'limits':{'min_power_pct':80,'max_reduce_min':30},'params':{}}
    k=kitchen(3,[d]);k.authority['may_go_below_min_power']=True
    fc=forecast(42,device_kw={'fixed':[22.,34.,22.,22.,22.,22.,22.,22.], 'hvac_1':[8.]*8})
    e=opened(k,fc)
    k._protected['hvac_1']=NOW+timedelta(minutes=30)
    k.issued.clear()
    result=escalation.resolve(k,e['escalation_id'],'accept_overrun','claude',None)
    assert result['status']=='resolved'
    assert not k.issued


def test_stronger_cap_ends_into_remaining_weaker_cap():
    d={'device_id':'hvac_1','type_id':'hvac','importance':'flexible','category':'hvac','state':'on',
       'rated_kw':10.,'power_kw':8.,'limits':{'min_power_pct':80,'max_reduce_min':30},'params':{}}
    k=kitchen(3,[d]);k.authority['may_go_below_min_power']=True
    fc=forecast(42,device_kw={'fixed':[22.,34.,22.,22.,22.,22.,22.,22.], 'hvac_1':[8.]*8})
    e=opened(k,fc)
    old=k._escalations[e['escalation_id']]
    old['block_start']=NOW
    old['options'][0]['actions'][0]['value']=40
    other=deepcopy(old);other['escalation_id']='e_0002';other['block_start']=NOW+timedelta(minutes=15)
    other['options'][0]['actions'][0]['value']=60
    k._escalations['e_0002']=other
    k._active_meta={'hvac_1':{'action':'reduce','value':40,'restore_at':NOW+timedelta(minutes=15)}}
    k.issued.clear()
    escalation.update(k,NOW+timedelta(minutes=15),None,replan=False)
    assert k.issued[0][1:3]==('reduce',60)
    assert k.issued[0][4]['restore_at']==NOW+timedelta(minutes=30)


def test_claude_confirming_the_active_fallback_is_accepted_without_reapplying():
    """Claude agrees with the engine's own fallback, already in force: the fresh replan no longer offers it (the reduction
    is in the forecast), but the pick is the active, authorized option, so it is accepted as is; nothing is re-issued."""
    d={'device_id':'hvac_1','type_id':'hvac','importance':'flexible','category':'hvac','state':'on',
       'rated_kw':10.,'power_kw':8.,'limits':{'min_power_pct':80,'max_reduce_min':30},'params':{}}
    k=kitchen(3,[d]); k.authority['may_go_below_min_power']=True
    e=opened(k,forecast(42,device_kw={'fixed':[22.,34.,22.,22.,22.,22.,22.,22.], 'hvac_1':[8.]*8}))
    assert e['default_option_id']==e['active_option_id']=='deep_reduce_hvac'
    issued=len(k.issued)
    # The fallback now holds the block: hvac at its reduced 4 kW -> 38 kW, no deep reduction is offered any more.
    fresh=forecast(38,device_kw={'fixed':[22.,34.,22.,22.,22.,22.,22.,22.], 'hvac_1':[8.,4.,8.,8.,8.,8.,8.,8.]})
    k._escalation_forecast=lambda: fresh
    assert all(o['option_id']!='deep_reduce_hvac' for o in escalation.options(k,NOW,fresh,1,40))
    result=escalation.resolve(k,e['escalation_id'],'deep_reduce_hvac','claude','agree with the fallback')
    assert result['status']=='resolved' and result['resolved_by']=='claude'
    assert result['chosen_option_id']==result['active_option_id']=='deep_reduce_hvac'
    assert result['claude_attempts'][-1]=={'ts':'2026-07-17T19:00:00Z','option_id':'deep_reduce_hvac','accepted':True,'reason':None,
                                            'rationale':'agree with the fallback'}
    assert len(k.issued)==issued
