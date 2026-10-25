"""G73 escalation lifecycle: immediate fallback, bounded Claude choice, no owner wait or I/O."""
from __future__ import annotations

import copy
import math
from datetime import datetime

from contracts import Escalation
from .decider import horizon_cost, reduce_forecast, totals
from .rules import RuleError, power_floor_pct, effective_deadline_min
from .tariff import BLOCK, MINUTE, block_start_of

EPS = 1e-8


def _time(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else value


def _peaks(kitchen):
    return {p['name']: p['peak_kw'] for p in kitchen._meter_now().get('demand_peaks', [])}


def authorized(option, authority):
    if not authority['enabled']:
        return False
    bounds = {'cap_overrun': 'max_cap_overrun_kw', 'past_deadline': 'max_extra_delay_min',
              'over_max_delay': 'max_extra_delay_min', 'over_max_reduce': 'max_extra_reduce_min'}
    for br in option['rule_breaks']:
        if br['kind'] == 'below_min_power':
            if not authority['may_go_below_min_power']:
                return False
        elif br['amount'] > authority[bounds[br['kind']]] + EPS:
            return False
    return True


def harm(option, authority, devices):
    score = 0.
    for br in option['rule_breaks']:
        kind = br['kind']
        if kind == 'below_min_power':
            d = devices[br['device_id']]
            tolerance = max(1, d['limits']['min_power_pct'] - power_floor_pct(d['category']))
        else:
            key, reference = {'cap_overrun': ('max_cap_overrun_kw', 3),
                'past_deadline': ('max_extra_delay_min', 20), 'over_max_delay': ('max_extra_delay_min', 20),
                'over_max_reduce': ('max_extra_reduce_min', 15)}[kind]
            tolerance = authority[key] or reference
        score += br['amount'] / tolerance
    return score


def _template(now, did, action, value):
    return {'command_id': f'option_{did}_{action}', 'lane': 'with', 'ts': now, 'device_id': did,
            'action': action, 'value': value, 'decision_id': None, 'issued_by': 'engine'}


def _movable(k, d, now):
    did = d['device_id']
    return (d['importance'] != 'always_on' and d.get('state') != 'running_job'
            and not d.get('disabled', False)
            and getattr(k, '_protected', {}).get(did, now) <= now
            and getattr(k, '_rejected', {}).get(did) != block_start_of(now))


def options(k, now, forecast, index, target):
    """Evaluate all type candidates, retain best reduction and delay plus accept_overrun."""
    devices = {d['device_id']: d for d in k._planning_devices()}
    baseline = copy.deepcopy(forecast)
    baseline['total_kw'][index] = target
    tariff, peaks = k._tariff, _peaks(k)
    baseline_cost = horizon_cost(baseline, tariff, peaks)

    def evaluated(oid, summary, actions, projected, breaks):
        # Each escalation addresses its block; other future risks have their own escalation.
        peak = projected['total_kw'][index]
        if peak > target + EPS:
            breaks.append({'kind': 'cap_overrun', 'amount': peak - target, 'unit': 'kW'})
        option = {'option_id': oid, 'summary': summary, 'actions': actions,
                  'projected': {'peak_kw': peak,
                    'cost_delta_usd': horizon_cost(projected, tariff, peaks) - baseline_cost,
                    'max_indoor_temp_change_c': None}, 'rule_breaks': breaks,
                  'within_authority': False, 'harm_score': 0., 'rank': 1}
        option['within_authority'] = authorized(option, k.authority)
        option['harm_score'] = harm(option, k.authority, devices)
        return option

    accept = evaluated('accept_overrun', 'Keep the in-rules plan and accept the projected peak.', [],
                       copy.deepcopy(forecast), [])
    candidates = {'flexible': [], 'deferrable': []}
    types = sorted({d['type_id'] for d in devices.values()})
    end = forecast['block_starts'][index] + BLOCK
    for tid in types:
        for importance in candidates:
            group = [d for d in devices.values() if d['type_id'] == tid and d['importance'] == importance
                     and _movable(k, d, now)]
            current, actions, breaks = copy.deepcopy(forecast), [], []
            for d in sorted(group, key=lambda d: d['device_id']):
                excess = current['total_kw'][index] - target
                if excess <= EPS:
                    break
                did = d['device_id']
                if did not in current['device_kw']:
                    continue
                if importance == 'flexible':
                    floor = power_floor_pct(d['category'])
                    kw = current['device_kw'][did][index]
                    fraction = max(0., (end - max(now, forecast['block_starts'][index])) / MINUTE) / 15
                    if fraction <= 0:
                        continue
                    metered = forecast.get('_metered_kwh', {}).get(did, 0.) * 4 if index == 0 else 0.
                    future_kw = max(0., (kw-metered)/fraction) if index == 0 else kw
                    value = max(floor, min(100, math.ceil((future_kw-excess/fraction)/d['rated_kw']*100-EPS)))
                    if value >= d['limits']['min_power_pct']:
                        # Normal caps were exhausted: allow a longer reduction when that was the binding limit.
                        value = max(floor, min(d['limits']['min_power_pct'], value))
                    projected = reduce_forecast(current, did, d['rated_kw'], value, end, now)
                    if projected['total_kw'][index] >= current['total_kw'][index] - EPS:
                        continue
                    if value < d['limits']['min_power_pct']:
                        breaks.append({'kind':'below_min_power','device_id':did,
                                       'amount':d['limits']['min_power_pct']-value,'unit':'pct'})
                    active = getattr(k, '_active_meta', {}).get(did, {})
                    first = active.get('first_applied', now)
                    extra = max(0., (end-first)/MINUTE-d['limits']['max_reduce_min'])
                    if extra:
                        breaks.append({'kind':'over_max_reduce','device_id':did,'amount':extra,'unit':'min'})
                    actions.append(_template(now, did, 'reduce', value))
                    current = projected
                else:
                    series = current['device_kw'][did]
                    if series[index] <= EPS:
                        continue
                    cycle = int(d.get('params', {}).get('cycle_min', 15))
                    count = max(1, math.ceil(cycle/15))
                    best = None
                    for dest in range(index+1, len(series)-count+1):
                        release = forecast['block_starts'][dest]
                        if tariff.local_date(release) != tariff.local_date(now):
                            continue
                        candidate = copy.deepcopy(current)
                        moved = list(series[index:index+count])
                        for j in range(len(moved)):
                            consumed = forecast.get('_metered_kwh', {}).get(did, 0.)*4 if index+j==0 else 0.
                            moved[j] = max(0., moved[j]-consumed)
                            candidate['device_kw'][did][index+j] = consumed
                        for j, kw in enumerate(moved):
                            candidate['device_kw'][did][dest+j] += kw
                        totals(candidate)
                        if any(candidate['total_kw'][dest+j] > target+EPS for j in range(count)):
                            continue
                        best = (release, candidate)
                        break
                    if best is None:
                        continue
                    release, current = best
                    first = getattr(k, '_active_meta', {}).get(did, {}).get('first_applied', now)
                    delay = math.ceil((release-now)/MINUTE)
                    extra = max(0., (release-first)/MINUTE-d['limits']['max_delay_min'])
                    past = max(0, tariff.minute_of_day(release)+cycle-effective_deadline_min(
                        d['limits']['must_finish_by'], k.config.operating_hours.close))
                    for kind, amount in [('over_max_delay',extra), ('past_deadline',past)]:
                        if amount:
                            breaks.append({'kind':kind,'device_id':did,'amount':amount,'unit':'min'})
                    actions.append(_template(now,did,'delay',delay))
            if actions and breaks:
                prefix = 'deep_reduce' if importance == 'flexible' else 'extend_delay'
                candidates[importance].append(evaluated(f'{prefix}_{tid}',
                    f'Apply the evaluated {prefix.replace("_", " ")} for {tid}.', actions, current, breaks))
    def ordering(o):
        return (not o['within_authority'], o['harm_score'], o['projected']['cost_delta_usd'],
                len(o['actions']), o['option_id'])
    result = [accept] + [min(group, key=ordering) for group in candidates.values() if group]
    result.sort(key=ordering)
    for i, o in enumerate(result,1):
        o['rank'] = i
    return result


def _apply(k, now, option, reason, previous=None, *, until=None, baseline=None, escalation_id=None):
    """Reconcile this choice with other live block controls before emitting device changes."""
    baseline = baseline or {}
    old = {a['device_id']:a for a in (previous or {}).get('actions', [])}
    new = {a['device_id']:a for a in option['actions']}
    working = copy.deepcopy(getattr(k, '_forecast_detail', None))
    devices = {d['device_id']:d for d in k._planning_devices()}

    def issue(did, action, value, *, extra=True, **metadata):
        nonlocal working
        # Manual control and hub rejection supersede every escalation requirement.
        if did not in devices or not _movable(k,devices[did],now):
            return
        # Extend the plan metadata without re-sending an unchanged device cap.
        current = getattr(k, '_active_meta', {}).get(did)
        for cid, cmd in getattr(k, '_pending_commands', {}).items():
            if cmd['device_id']==did:
                current = getattr(k, '_command_meta', {}).get(cid, cmd)
        if action=='delay' and current and current['action']=='delay' and current.get('release_at')==metadata.get('release_at'):
            return
        if action=='reduce' and current and current['action']==action and current['value']==value:
            if 'restore_at' in metadata:
                current['restore_at'] = metadata['restore_at']
            return
        effect_args = {}
        if working is not None and hasattr(k, '_project_action'):
            projected = k._project_action(working,did,action,value,now,**metadata)
            from .decider import effect
            effect_args['effect'] = effect(working,projected,k._tariff,_peaks(k))
            working = projected
        k._issue(did,action,value,reason,escalation=extra,**metadata,**effect_args)

    for did in sorted(set(old) | set(new)):
        required = []
        if did in new:
            required.append((new[did], until or block_start_of(now)+BLOCK))
        for eid, other in k._escalations.items():
            end = _time(other['block_start'])+BLOCK
            if eid==escalation_id or end<=now:
                continue
            active = next((o for o in other['options'] if o['option_id']==other['active_option_id']),None)
            if active:
                required.extend((a,end) for a in active['actions'] if a['device_id']==did)
        if required:
            reductions = [(a,end) for a,end in required if a['action']=='reduce']
            if reductions:
                value = min(a['value'] for a,end in reductions)
                end = max(end for a,end in reductions if a['value']==value)
                issue(did,'reduce',value,restore_at=end)
            else:
                release = max(_time(a['ts'])+a['value']*MINUTE for a,end in required)
                issue(did,'delay',max(0,math.ceil((release-now)/MINUTE)),release_at=release)
        else:
            normal = baseline.get(did)
            if normal and normal['action'] in ('reduce','delay'):
                value = normal['value']
                metadata = {}
                if normal['action']=='delay':
                    value = max(0,math.ceil((_time(normal['release_at'])-now)/MINUTE))
                    metadata['release_at'] = _time(normal['release_at'])
                else:
                    metadata['restore_at'] = _time(normal['restore_at'])
                issue(did,normal['action'],value,extra=False,**metadata)
            else:
                issue(did,'restore' if old[did]['action']=='reduce' else 'delay',
                      None if old[did]['action']=='reduce' else 0)
    if working is not None:
        k._forecast_detail = working
        k._forecast_kw = list(working['total_kw'])


def update(k, now, forecast, *, replan):
    """Advance deadlines each tick; re-evaluate and open risks only at decision ticks."""
    if k.control != 'with':
        return []
    changed = []
    if not hasattr(k, "_escalation_cleared"):
        k._escalation_cleared = set()
    k._escalation_cleared = {b for b in k._escalation_cleared if b + BLOCK > now}
    for e in k._escalations.values():
        if e['status']=='open' and now >= _time(e['deadline_sim_ts']):
            e.update(status='expired_default',resolved_by='default',updated_ts=now)
            changed.append(copy.deepcopy(e))
    if not replan or forecast is None:
        _reconcile(k,now)
        return changed
    target = k._meter_now()['target_kw']
    for i, start in enumerate(forecast['block_starts']):
        if start > now + 30*MINUTE or start + BLOCK <= now:
            continue
        existing = next((e for e in k._escalations.values() if e['status']=='open'
                         and _time(e['block_start'])==start), None)
        if forecast['total_kw'][i] <= target + EPS:
            k._escalation_cleared.add(start)
            if existing:
                existing.update(status='obsolete',updated_ts=now)
                changed.append(copy.deepcopy(existing))
            continue
        # A resolved or expired choice stays authoritative for the remainder of this block.
        # Open a fresh escalation only if a prior one was obsolete (risk genuinely returned).
        if existing is None and start not in k._escalation_cleared and any(_time(e['block_start'])==start and e['status'] in ('resolved','expired_default')
                                    for e in k._escalations.values()):
            continue
        opts = options(k,now,forecast,i,target)
        problem = {'forecast_peak_kw':forecast['total_kw'][i], 'target_kw':target,
                   'excess_kw':forecast['total_kw'][i]-target, 'reason':'No in-rules move holds this block.'}
        if existing:
            # Keep active/default templates available if a type candidate disappeared after execution.
            for oid in (existing['active_option_id'],existing['default_option_id']):
                if oid not in {o['option_id'] for o in opts}:
                    retained = next(o for o in existing['options'] if o['option_id']==oid)
                    # Do not add beyond the three alternative slots; replace same-family candidate.
                    family = 'deep_reduce_' if oid.startswith('deep_reduce_') else 'extend_delay_'
                    opts = [o for o in opts if not o['option_id'].startswith(family)]
                    opts.append(copy.deepcopy(retained))
            opts.sort(key=lambda o:(not o['within_authority'],o['harm_score'],o['projected']['cost_delta_usd'],len(o['actions']),o['option_id']))
            for rank,o in enumerate(opts,1): o['rank']=rank
            existing.update(problem=problem,options=opts,updated_ts=now)
            changed.append(copy.deepcopy(existing))
        else:
            fallback = next((o for o in opts if o['within_authority']),next(o for o in opts if o['option_id']=='accept_overrun'))
            e = {'escalation_id':k.ids.next('e'),'lane':k.control,'ts':now,'updated_ts':now,'block_start':start,
                 'problem':problem,'options':opts,'default_option_id':fallback['option_id'],
                 'active_option_id':fallback['option_id'],
                 'deadline_sim_ts':max(now+5*MINUTE,min(now+15*MINUTE,start-5*MINUTE)),
                 'status':'open','resolved_by':None,'chosen_option_id':None,'rationale':None,'claude_attempts':[]}
            Escalation.model_validate(e)
            k._escalation_cleared.discard(start)
            k._escalations[e['escalation_id']] = e
            if not hasattr(k, '_escalation_baselines'):
                k._escalation_baselines = {}
            controls = copy.deepcopy(getattr(k, '_active_meta', {}))
            for cid, cmd in getattr(k, '_pending_commands', {}).items():
                meta = getattr(k, '_command_meta', {}).get(cid, cmd)
                if not meta.get('escalation'):
                    controls[cmd['device_id']] = copy.deepcopy(meta)
            k._escalation_baselines[e['escalation_id']] = controls
            _apply(k,now,fallback,'escalation_fallback',until=start+BLOCK,escalation_id=e['escalation_id'])
            changed.append(copy.deepcopy(e))
    _reconcile(k,now)
    return changed


def _reconcile(k,now):
    # Relax an ending stronger cap to any weaker control still required by another block.
    actions = {}
    for e in k._escalations.values():
        if _time(e['block_start'])+BLOCK<=now:
            continue
        option = next((o for o in e['options'] if o['option_id']==e['active_option_id']),None)
        if option:
            actions.update({a['device_id']:a for a in option['actions']})
    if actions:
        _apply(k,now,{'actions':[]},'escalation_fallback',previous={'actions':list(actions.values())})


def resolve(k, escalation_id, option_id, resolved_by, rationale=None):
    if resolved_by != 'claude':
        raise RuleError('Only Claude resolves escalations; use owner_command or undo for manual control')
    if escalation_id not in k._escalations:
        raise RuleError(f'unknown escalation {escalation_id!r}')
    e = k._escalations[escalation_id]
    option = next((o for o in e['options'] if o['option_id']==option_id),None)
    if option is None:
        raise RuleError(f'unknown option {option_id!r}')
    if e['status'] in ('resolved','obsolete'):
        return Escalation.model_validate(e).model_dump(mode='json')
    now = k._now
    reason = 'after_deadline' if now >= _time(e['deadline_sim_ts']) else None
    if reason is None and hasattr(k, '_escalation_forecast'):
        fresh = k._escalation_forecast()
        index = next((i for i,t in enumerate(fresh['block_starts']) if t==_time(e['block_start'])),None)
        if index is not None:
            target = k._meter_now()['target_kw']
            current = options(k,now,fresh,index,target)
            replacement = next((o for o in current if o['option_id']==option_id),None)
            e['problem'].update(forecast_peak_kw=fresh['total_kw'][index],target_kw=target,
                                excess_kw=max(0.,fresh['total_kw'][index]-target))
            if replacement is None:
                reason = 'outside_authority'
            else:
                option = replacement
                e['options'] = [replacement if o['option_id']==option_id else o for o in e['options']]
                devices = {d['device_id']:d for d in k._planning_devices()}
                for o in e['options']:
                    o['within_authority'] = authorized(o,k.authority)
                    o['harm_score'] = harm(o,k.authority,devices)
                e['options'].sort(key=lambda o:(not o['within_authority'],o['harm_score'],
                    o['projected']['cost_delta_usd'],len(o['actions']),o['option_id']))
                for rank,o in enumerate(e['options'],1):
                    o['rank']=rank
    if reason is None:
        if len([a for a in e['claude_attempts'] if a['reason']!='after_deadline']) >= 2:
            raise RuleError('Claude retry budget exhausted')
        if not authorized(option,k.authority): reason='outside_authority'
        # Check safety again using latest device categories, even if a stored option was altered.
        ds={d['device_id']:d for d in k._planning_devices()}
        for a in option['actions']:
            d=ds.get(a['device_id'])
            if d is None or not _movable(k,d,now) or (a['action']=='reduce' and a['value']<power_floor_pct(d['category'])):
                reason='outside_authority'
    e['claude_attempts'].append({'ts':now,'option_id':option_id,'accepted':reason is None,
                                 'reason':reason,'rationale':rationale})
    e['updated_ts']=now
    if reason=='after_deadline':
        e.update(status='expired_default',resolved_by='default')
    elif reason is None:
        previous=next(o for o in e['options'] if o['option_id']==e['active_option_id'])
        _apply(k,now,option,'escalation_choice',previous,until=_time(e['block_start'])+BLOCK,
               baseline=getattr(k,'_escalation_baselines',{}).get(escalation_id,{}),escalation_id=escalation_id)
        e.update(status='resolved',resolved_by='claude',chosen_option_id=option_id,
                 active_option_id=option_id,rationale=rationale)
    return Escalation.model_validate(e).model_dump(mode='json')
