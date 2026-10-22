"""Bounded economic experiments and observational delivery/purchase accounting."""
import collections
import math
import re

GROUPS = {
    'banking': ['BANK_RISK_W','ALTAR_TRAVEL_W','TRIBUTE_INTERRUPT_RISK','ALTAR_ROUTE_COST_W'],
    'camps': ['CAMP_VALUE_W','CAMP_CLEAR_TURNS_W','CAPTURE_TIME_W','CAMP_DAMAGE_RISK_W','RESPAWN_VALUE_W'],
    'survival': ['DEATH_RISK_W','RECALL_HP_THRESHOLD','CARRIED_GEM_RISK_W'],
    'shopping': ['ITEM_ROI_W'],
    'combat': ['EXPECTED_DAMAGE_W','KILL_CONFIRM_W','ABILITY_VALUE_W','ENEMY_GEM_CARRY_W'],
    'mobility': ['DASH_VALUE_W','TELEPORT_VALUE_W','BUSH_AMBUSH_W'],
}
DEFAULTS = {name: (0.4 if name=='RECALL_HP_THRESHOLD' else 0.2 if name=='BUSH_AMBUSH_W' else 1.0)
            for names in GROUPS.values() for name in names}


def read(path):
    text = path.read_text(encoding='utf-8')
    values = {}
    for name in [*GROUPS,*DEFAULTS]:
        match = re.search(r'\b'+name+r'\s*=\s*(true|false|[0-9.eE+-]+)f?\s*[,;]',text)
        if not match:
            raise ValueError('Missing economic setting: '+name)
        values[name] = match[1]=='true' if name in GROUPS else float(match[1])
    return values


def header(values):
    if set(values) != set(GROUPS) | set(DEFAULTS):
        raise ValueError('Economic parameter coverage mismatch')
    lines=['#pragma once','namespace economy {']
    for name in GROUPS:
        if type(values[name]) is not bool:
            raise ValueError('Invalid economic feature flag')
        lines.append(f'inline constexpr bool {name} = {str(values[name]).lower()};')
    for name in DEFAULTS:
        value=values[name]
        limit=0.95 if name=='RECALL_HP_THRESHOLD' else 4.0
        if type(value) not in (int,float) or not math.isfinite(value) or not 0.05<=value<=limit:
            raise ValueError('Economic weight outside bounds: '+name)
        lines.append(f'inline constexpr float {name} = {value:.6f}f;')
    return '\n'.join([*lines,'}',''])


def proposals(values, cycle):
    # One economic system at a time; every group gets an experiment each six cycles.
    group=list(GROUPS)[cycle % len(GROUPS)]
    for factor in (0.8,1.2):
        proposal=dict(values)
        proposal[group]=True
        names=GROUPS[group]
        name=names[(cycle//len(GROUPS)) % len(names)]
        upper=0.95 if name=='RECALL_HP_THRESHOLD' else 4.0
        proposal[name]=round(max(0.05,min(upper,proposal[name]*factor)),6)
        yield proposal


def enrich(text, frames, diagnosis):
    extra={}
    for line in text.splitlines():
        fields=line.split()
        if not fields or fields[0]!='PX':
            continue
        try:
            if len(fields)!=14:
                raise ValueError()
            values=list(map(int,fields[1:]))
            if any(v<0 for v in values) or values[11] not in (0,1):
                raise ValueError()
            r,champion,x,y,gems,spent,strength,focus,maxhp,incoming,cc,cancelled,failed=values
            if (champion,r) in extra:
                raise ValueError()
            extra[champion,r]=dict(spent=spent,cancelled=cancelled,failed=failed,
                                  strength=strength,focus=focus,maxhp=maxhp)
        except ValueError:
            diagnosis['malformed']+=1
    metrics=dict(observed_gems_acquired=0, inferred_personal_gems_tributed=0,
                 observed_shop_spend=0, delivery_gem_rounds=0, aged_gems_delivered=0,
                 recall_turns=0, tribute_turns=0, confirmed_tribute_cancellations=0,
                 explored_action_failures=0, purchase_windows=[])
    for champion,history in frames.items():
        history.sort(key=lambda f:f['round'])
        bag=collections.deque()
        previous=None
        for index,frame in enumerate(history):
            r=frame['round']; record=extra.get((champion,r),{})
            metrics['recall_turns']+=frame['action']=='recalling'
            metrics['tribute_turns']+=frame['action']=='tributing'
            for key,field in [('observed_shop_spend','spent'),('confirmed_tribute_cancellations','cancelled'),
                              ('explored_action_failures','failed')]:
                metrics[key]+=record.get(field,0)
            if previous is None or r!=previous['round']+1:
                bag.clear()  # Never invent collection times across missing observations.
            else:
                gain=frame['gems']-previous['gems']
                if gain>0 and frame['alive']:
                    bag.append([r,gain]); metrics['observed_gems_acquired']+=gain
                loss=max(0,-gain)
                delivered=(loss>0 and frame['alive'] and previous['action'] in ('tributing','tribute_start')
                           and frame['banked']>previous['banked'] and not record.get('cancelled'))
                if delivered:
                    metrics['inferred_personal_gems_tributed']+=loss
                while loss and bag:
                    collected,amount=bag[0]; used=min(loss,amount)
                    if delivered:
                        metrics['delivery_gem_rounds']+=used*(r-collected)
                        metrics['aged_gems_delivered']+=used
                    loss-=used; bag[0][1]-=used
                    if not bag[0][1]: bag.popleft()
            if record.get('spent'):
                future=history[index:]
                after=next((f for f in future if f['round']>=r+24),None)
                if after:
                    metrics['purchase_windows'].append(dict(champion=champion,round=r,gold_spent=record['spent'],
                        subsequent_team_tribute=after['banked']-frame['banked'],
                        survived_window=all(f['alive'] for f in future if f['round']<=after['round'])))
            previous=frame
    metrics['mean_observed_delivery_delay']= (metrics['delivery_gem_rounds']/metrics['aged_gems_delivered']
                                              if metrics['aged_gems_delivered'] else None)
    metrics['accounting_note']='Observed bag changes; personal tribute inferred. Purchase returns are team correlations, not causal ROI.'
    diagnosis.update(metrics)
    return extra
