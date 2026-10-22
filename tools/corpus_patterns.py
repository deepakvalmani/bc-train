"""Second-stage timing, route, build and action-sequence analysis; streamed by game."""
import csv
import json
from collections import Counter,defaultdict
from pathlib import Path
from statistics import median
import zipfile
import math
from corpus_report import evidence_files,load_evidence

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'out/replay_corpus'
NAMES=['Ryth','Vesper Vale','Vendetta','Cassi','Issac','Stellar','Prism','Marcella','Willow','Ren','Varg','Tavi','Heart of Ruin']

def main():
    inv=json.loads((OUT/'inventory.json').read_text())
    geom=json.loads((OUT/'geometry.json').read_text())
    source_hashes={r['id']:r['sha256'] for r in inv['records']}
    productive_ids=None
    # The audited first pass already classifies every unique game. Avoid parsing
    # large idle/failed-game timelines when this pass cannot use them.
    if (OUT/'teams.csv').exists():
        with (OUT/'teams.csv').open(encoding='utf-8-sig',newline='') as f:
            team_rows=list(csv.DictReader(f))
        if len(team_rows)==2*inv['unique_hashes']:
            productive_ids={r['id'] for r in team_rows if r['productive']=='True'}
    seen=set(); execution=defaultdict(Counter);intervals=defaultdict(list);routes=[];economy=[];cases=[];allsteps=0;count=0
    fingerprint=defaultdict(lambda:dict(n=0,wins=0,ids=[]));short_banks=[];combat=[];opening_positions=[]
    for file in evidence_files():
        ident=file.name.split('.json')[0]
        if source_hashes[ident] in seen:continue
        seen.add(source_hashes[ident]);count+=1
        if productive_ids is not None and ident not in productive_ids:continue
        d=load_evidence(file)
        prod=all(t['gemsAcquired']>=100 and t['captures']>=3 and not t['errors'] for t in d['teams'])
        clean=prod and max(d['scores'])>=1000 and all(not t['rollovers'] for t in d['teams'])
        if not prod:continue
        turns=defaultdict(list)
        for a in d.get('turnActions',[]):turns[(a[0],a[1],a[2])].append(a)
        hero_turns=defaultdict(list)
        for (r,s,tp),acts in turns.items():hero_turns[(s,tp)].append(acts)
        hero_casts=defaultdict(list)
        for c in d['casts']:hero_casts[(c['team'],c['type'],c['slot'])].append(c)
        for h in d['heroes']:
            key=(h['name'],int(d['winner']==h['team']),int(clean))
            ec=execution[key];ec['games']+=1;ec['alive_rounds']+=h['aliveRounds'];ec['moves']+=h['moves']
            ec['attacks']+=h['actions'].get('5',0);ec['casts_0']+=h['casts'][0];ec['casts_1']+=h['casts'][1]
            for acts in hero_turns[(h['team'],h['type'])]:
                kinds=[a[3] for a in acts]
                if 4 in kinds and 5 in kinds:ec['move_and_attack_turns']+=1
                if kinds.count(5)>=2:ec['multiple_basic_turns']+=1
                if 5 in kinds and 6 in kinds:ec['attack_and_cast_turns']+=1
                if kinds.count(6)>1:ec['multiple_cast_turns']+=1
                if 16 in kinds and 11 in kinds:ec['cancel_and_restart_recall_turns']+=1
                for j in range(len(acts)-2):
                    if acts[j][3]==5 and acts[j+1][3]==6 and acts[j+2][3]==5:ec['attack_cast_attack_sequences']+=1
            for slot in [0,1]:
                casts=hero_casts[(h['team'],h['type'],slot)]
                rs=[c['round'] for c in casts]
                intervals[(h['name'],key[1],key[2],slot)].extend(b-a for a,b in zip(rs,rs[1:]))
                ec[f'casts_enemy8_{slot}']+=sum(c['enemies8']>0 for c in casts)
        groups=defaultdict(list)
        for c in geom.get(d['map'],{}).get('camps',[]):groups[c['group']].append(c)
        for s,t in enumerate(d['teams']):
            hs=[h for h in d['heroes'] if h['team']==s]
            attacks=[a for a in d['attacks'] if a['team']==s and a['target'] is not None]
            byround=defaultdict(list)
            for a in attacks:byround[a['round']].append(a)
            focused=0
            for acts in byround.values():
                attackers=defaultdict(set)
                for a in acts:
                    if a.get('targetId') is not None:attackers[a['targetId']].add(a['type'])
                focused+=any(len(actors)>=2 for actors in attackers.values())
            comparable=[a for a in attacks if a.get('targetHp') is not None and a.get('lowestHpInBasicRange') is not None]
            combat.append(dict(id=d['id'],map=d['map'],side=s,won=int(d['winner']==s),clean=clean,
                champion_basic_attacks=len(attacks),pvp_basic_rounds=len(byround),multi_body_focus_rounds=focused,
                multi_body_focus_fraction=focused/len(byround) if byround else None,
                mean_distinct_targets_per_pvp_round=sum(len({a.get('targetId') for a in acts if a.get('targetId') is not None}) for acts in byround.values())/len(byround) if byround else None,
                lowest_hp_comparable_attacks=len(comparable),
                lowest_hp_fraction=sum(a['targetHp']<=a['lowestHpInBasicRange']+1e-6 for a in comparable)/len(comparable) if comparable else None,
                target_hp_fraction_median=median([a['targetHp'] for a in attacks if a['targetHp'] is not None]) if attacks else None))
            trajectory={x['round']:x for x in d['trajectory']}
            checkpoints=[('r20',20),('r40',40),('r60',60)]
            if d['firstContact'] is not None and 2<=d['firstContact']<=61:checkpoints.append(('pre_first_contact',d['firstContact']-1))
            for label,r in checkpoints:
                if r not in trajectory:continue
                sample=trajectory[r];ours=[c for c in sample['teams'][s]['positions'] if c[4] and c[1]>=0];foes=[c for c in sample['teams'][1-s]['positions'] if c[4] and c[1]>=0]
                if not ours:continue
                cheb=lambda a,b:max(abs(a[1]-b[1]),abs(a[2]-b[2]))
                allies4=[sum(c is not p and cheb(c,p)<=4 for p in ours) for c in ours]
                allies8=[sum(c is not p and cheb(c,p)<=8 for p in ours) for c in ours]
                front=min(ours,key=lambda c:min(cheb(c,f) for f in foes)) if foes else None
                hpos={h['type']:h['initial'] for h in hs}
                opening_positions.append(dict(id=d['id'],map=d['map'],side=s,won=int(d['winner']==s),clean=clean,checkpoint=label,round=r,
                    living_bodies=len(ours),total_hp=sum(c[3] for c in ours),
                    average_allies4=sum(allies4)/len(ours),average_allies8=sum(allies8)/len(ours),
                    bodies_with_at_most_one_ally8=sum(n<=1 for n in allies8),
                    front_allies4=sum(c is not front and cheb(c,front)<=4 for c in ours) if front is not None else None,front_allies8=sum(c is not front and cheb(c,front)<=8 for c in ours) if front is not None else None,
                    mean_distance_from_initial_tile=sum(max(abs(c[1]-hpos[c[0]]['x']),abs(c[2]-hpos[c[0]]['y'])) for c in ours)/len(ours)))
            caps=[c for c in d['captures'] if c['team']==s]
            cc=Counter(c['group'] for c in caps)
            clears=defaultdict(list)
            for c in d['clears']:clears[c['group']].append(c)
            lag=[];otherclear=0
            for c in caps:
                candidates=[x for x in clears[c['group']] if x['round']<=c['round']]
                if candidates:
                    last=candidates[-1];lag.append(c['round']-last['round'])
                    otherclear+=last['team'] is not None and last['team']!=s
            start={'x':sum(h['initial']['x'] for h in hs)/len(hs),'y':sum(h['initial']['y'] for h in hs)/len(hs)}
            gd={g:min(max(abs(c['x']-start['x']),abs(c['y']-start['y'])) for c in camps) for g,camps in groups.items()}
            ordered=sorted(gd,key=gd.get)
            opening=[]
            for c in caps[:8]:opening.append({'round':c['round'],'group':c['group'],'spawn_cheb_distance':gd.get(c['group']),'static_distance_rank':ordered.index(c['group'])+1 if c['group'] in ordered else None})
            route=dict(id=d['id'],map=d['map'],side=s,won=int(d['winner']==s),clean=clean,first8=json.dumps(opening),
                       clear_to_capture_median=median(lag) if lag else None,clear_to_capture_max=max(lag) if lag else None,
                       captured_after_other_last_hit=otherclear,top_group_capture_share=max(cc.values())/sum(cc.values()) if cc else 0,
                       captures=len(caps),unique_groups=len(cc))
            routes.append(route)
            purch=[p for p in d['purchases'] if p['team']==s]
            eq=[0]*42;by100=[0]*42
            for p in purch:
                for j,n in enumerate(p['delta']):eq[j]+=n;by100[j]+=n*(p['round']<=100)
            costeq=lambda arr,k:sum(arr[f*6+k]+5*arr[f*6+k+1] for f in range(7))
            bagcounts=[b['amount'] for b in d['banks'] if b['team']==s]
            er=dict(id=d['id'],map=d['map'],side=s,won=int(d['winner']==s),clean=clean,
                    strength_eq_100=costeq(by100,0),focus_eq_100=costeq(by100,2),health_eq_100=costeq(by100,4),
                    strength_eq_end=costeq(eq,0),focus_eq_end=costeq(eq,2),health_eq_end=costeq(eq,4),
                    first_shop=min((p['round'] for p in purch),default=None),
                    bank_median=median(bagcounts) if bagcounts else None,bank_max=max(bagcounts) if bagcounts else None,
                    no_bank=int(not bagcounts),acquired=t['gemsAcquired'],banked=d['scores'][s],gems_lost=t['deathBagLost'])
            starts=defaultdict(list)
            for a in d.get('turnActions',[]):
                if a[1]==s and a[3]==12:starts[a[2]].append(a[0])
            durations=[]
            for b in d['banks']:
                if b['team']!=s:continue
                before=[r for r in starts[b['type']] if r<b['round']]
                if before:
                    gap=b['round']-before[-1];durations.append(gap)
                    if gap<math.ceil(b['amount']/10):short_banks.append(dict(id=d['id'],map=d['map'],side=s,champion=NAMES[b['type']],start=before[-1],complete=b['round'],gems=b['amount'],observed_gap=gap,ceil_final_bag_div10=math.ceil(b['amount']/10)))
            er['observed_bank_channel_gap_median']=median(durations) if durations else None
            economy.append(er)
            fp=fingerprint[(d['map'],s,t['openingHash'])];fp['n']+=1;fp['wins']+=d['winner']==s
            if len(fp['ids'])<5:fp['ids'].append(d['id'])
        winner=d['winner'];loser=1-winner
        wm=d['teams'][winner]['milestones'];lm=d['teams'][loser]['milestones']
        cases.append(dict(id=d['id'],map=d['map'],rounds=d['rounds'],winner=winner,clean=clean,loser_gems=d['scores'][loser],
                          winner_deaths=sum(x['team']==winner for x in d['deaths']),loser_deaths=sum(x['team']==loser for x in d['deaths']),
                          comeback100='100' in wm and wm['100']['gems']<lm['100']['gems'],
                          comeback300='300' in wm and wm['300']['gems']<lm['300']['gems'],
                          winner_fewer_captures=d['teams'][winner]['captures']<d['teams'][loser]['captures'],
                          winner_fewer_gold=d['teams'][winner]['goldAcquired']<d['teams'][loser]['goldAcquired']))
    def write(name,rows):
        if not rows:return
        keys=list(dict.fromkeys(k for r in rows for k in r))
        with (OUT/name).open('w',newline='',encoding='utf-8-sig') as f:w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(rows)
    ers=[]
    for (name,won,clean),ec in sorted(execution.items()):
        r=dict(champion=name,won=won,clean=clean,**ec)
        for k in ['moves','attacks','casts_0','casts_1','attack_cast_attack_sequences','multiple_basic_turns']:
            r[k+'_per_100_alive_rounds']=round(100*ec[k]/max(1,ec['alive_rounds']),2)
        for slot in [0,1]:
            iv=intervals[(name,won,clean,slot)]
            r[f'cast_gap_median_{slot}']=median(iv) if iv else None
            r[f'cast_gaps_under8_{slot}']=sum(x<8 for x in iv)
            r[f'cast_gaps_total_{slot}']=len(iv)
        ers.append(r)
    write('execution.csv',ers);write('routes.csv',routes);write('economy.csv',economy);write('short_bank_channels.csv',short_banks)
    write('combat_selection.csv',combat);write('opening_positions.csv',opening_positions)
    opening_summary=[];combat_summary=[]
    for label in ['r20','r40','r60','pre_first_contact']:
        for won in [0,1]:
            selected=[r for r in opening_positions if r['clean'] and r['won']==won and r['checkpoint']==label]
            if selected:opening_summary.append(dict(checkpoint=label,won=won,games=len(selected),**{k:round(median(r[k] for r in selected if r[k] is not None),3) if any(r[k] is not None for r in selected) else None for k in ['living_bodies','total_hp','average_allies4','average_allies8','front_allies4','front_allies8','mean_distance_from_initial_tile']}))
    for won in [0,1]:
        selected=[r for r in combat if r['clean'] and r['won']==won and r['champion_basic_attacks']>=5]
        if selected:combat_summary.append(dict(won=won,games=len(selected),**{k:round(median(r[k] for r in selected if r[k] is not None),4) if any(r[k] is not None for r in selected) else None for k in ['multi_body_focus_fraction','mean_distinct_targets_per_pvp_round','lowest_hp_fraction','target_hp_fraction_median']}))
    write('opening_summary.csv',opening_summary);write('combat_selection_summary.csv',combat_summary)
    if not short_banks:(OUT/'short_bank_channels.csv').write_text('id,map,side,champion,start,complete,gems,observed_gap,ceil_final_bag_div10\n',encoding='utf-8')
    write('opening_clusters.csv',[dict(map=k[0],side=k[1],hash=k[2],games=v['n'],wins=v['wins'],win_pct=round(100*v['wins']/v['n'],1),examples=';'.join(v['ids'])) for k,v in fingerprint.items() if v['n']>=2])
    selected={}
    for m in sorted({c['map'] for c in cases}):
        cs=[c for c in cases if c['map']==m and c['loser_gems']>=250]
        if cs:selected['fastest_competitive_'+m]=min(cs,key=lambda c:c['rounds'])
    for label,pred,key in [('comeback_after300',lambda c:c['comeback300'],lambda c:-c['loser_gems']),
                           ('won_with_fewer_captures',lambda c:c['winner_fewer_captures'],lambda c:c['rounds']),
                           ('death_heavy_loss',lambda c:c['loser_deaths']>=20,lambda c:-c['loser_deaths'])]:
        cs=[c for c in cases if pred(c)]
        selected[label]=sorted(cs,key=key)[:10]
    (OUT/'case_selection.json').write_text(json.dumps(selected,indent=2))
    print(json.dumps(dict(unique_games=count,productive_games=len(cases),execution_rows=len(ers),selected_cases=len(selected)),indent=2))

if __name__=='__main__':main()
