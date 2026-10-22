"""Evidence tables and per-game reviews for the exhaustive local replay corpus.

Re-run while extracting for a provisional report; only completion audit permits
calling the report exhaustive. No web/team metadata is inferred from replay IDs.
"""
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median, mean
import math
import zipfile
import gzip
import os
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'out/replay_corpus'
NAMES = ['Ryth','Vesper Vale','Vendetta','Cassi','Issac','Stellar','Prism','Marcella','Willow','Ren','Varg','Tavi','Heart of Ruin']
ACTIONS = 'Phase.Respawn.Capture.Tick.Move.Attack.Cast ability.Input.End turn.Set priority..Recall.Submit gems.Shop.Place ward.Consumable.Cancel channel.Sandbox.Gems submitted.Draft champion.Place altar lock.Teleport channel.Teleport complete.Movement blocked.Resign.Sell item.Turn rollover.Bot error'.split('.')
FAMILIES = ['Monster','Power','Durability','Treasure','Jungle','Home','Bruiser']

def evidence_files():
    expected={r['id'] for r in json.loads((OUT/'inventory.json').read_text(encoding='utf-8'))['records']}
    files={p.stem:p for p in (OUT/'games').glob('*.json')}
    files.update({p.name[:-8]:p for p in (OUT/'games').glob('*.json.gz')})
    return sorted(p for ident,p in files.items() if ident in expected)

def load_evidence(p):
    with (gzip.open(p,'rt',encoding='utf-8') if p.suffix=='.gz' else p.open(encoding='utf-8')) as f:d=json.load(f)
    d['trajectory']=[r for r in d['trajectory'] if any(t['positions'] for t in r['teams'])]
    return d

def evidence_id(p):return p.name.split('.json')[0]

def med(xs):
    ys = [x for x in xs if x is not None]
    return round(median(ys), 2) if ys else None

def pct(n, d):
    return round(100*n/d, 1) if d else None

def wilson(w,n):
    if not n: return [0,100]
    p=w/n; z=1.96; den=1+z*z/n
    mid=(p+z*z/(2*n))/den
    half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return [round((mid-half)*100,1),round((mid+half)*100,1)]

def write_csv(name, rows):
    if not rows: return
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with (OUT/name).open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(rows)

def table(rows, columns):
    return '\n'.join(['| '+' | '.join(c[0] for c in columns)+' |','| '+' | '.join('---' for _ in columns)+' |']+
        ['| '+' | '.join(str(r.get(k,'—')) if r.get(k) is not None else '—' for _,k in columns)+' |' for r in rows])

def main():
    inventory=json.loads((OUT/'inventory.json').read_text(encoding='utf-8'))
    games=[]; seen={}; duplicates=[]
    filelist=evidence_files()
    inventory_by_id={r['id']:r for r in inventory['records']}
    for f in filelist:
        ident=evidence_id(f)
        digest=inventory_by_id[ident]['sha256']
        if digest in seen:
            duplicates.append(dict(id=ident,same_as=seen[digest]))
        else:
            seen[digest]=ident;games.append(f)
    expected={r['id'] for r in inventory['records']}
    processed={evidence_id(p) for p in filelist}
    errors=[]
    for f in (OUT/'games').glob('errors-*.jsonl'):
        errors.extend(json.loads(s) for s in f.read_text().splitlines() if s)
    unresolved=[e for e in errors if Path(e['file']).stem in expected and Path(e['file']).stem not in processed]
    coverage=dict(expected=len(expected),processed=len(processed),unique_analyzed=len(games),duplicates=len(duplicates),
                  missing=sorted(expected-processed),unexpected=sorted(processed-expected),errors=unresolved,historical_error_count=len(errors),integrity_failures=[],schemas={},
                  complete=expected==processed and not unresolved,
                  snapshots=0,rounds=0,archives=inventory['archives'])
    (OUT/'duplicates.json').write_text(json.dumps(duplicates,indent=2),encoding='utf-8')
    occurrences=Counter(x['same_as'] for x in duplicates)
    rows=[]; heroes=[]; reviews=[]; draftpairs=defaultdict(list);game_meta=[]
    review_zip=zipfile.ZipFile(OUT/'game_reviews.zip','w',compression=zipfile.ZIP_DEFLATED,compresslevel=3)
    for file in games:
        d=load_evidence(file)
        if any(t['actions'].get('25',0) for t in d['teams']) and d.get('itemCacheVersion',0)<2:
            assets=next(p for p in (Path(os.environ['LOCALAPPDATA'])/'cambc/assets').glob('*/visualiser/assets') if (p/'v0_0_3-zaIi77qe.wasm').exists())
            manifest=OUT/'inventory_sale_repair.json'
            manifest.write_text(json.dumps([d['source']]),encoding='utf-8')
            subprocess.run(['node','--no-warnings',str(ROOT/'tools/corpus_extract.mjs'),str(assets),str(manifest),str(OUT/'games')],cwd=ROOT,env={**os.environ,'CORPUS_FORCE':'1'},check=True)
            d=load_evidence(OUT/'games'/(d['id']+'.json.gz'))
            if d.get('itemCacheVersion',0)<2:raise RuntimeError('Equipment-sale replay repair failed: '+d['id'])
        coverage['schemas'][str(d['schema'])]=coverage['schemas'].get(str(d['schema']),0)+1
        failures=[]
        if d['sha256']!=inventory_by_id[d['id']]['sha256']:failures.append('source checksum mismatch')
        if d['schema']<3:failures.append('missing full turn-action evidence')
        for s in [0,1]:
            if sum(b['amount'] for b in d['banks'] if b['team']==s)!=d['scores'][s]:failures.append(f'team {s} bank reconciliation')
        for h in d['heroes']:
            if sum(h['budget'].values())!=d['rounds']:failures.append(f'hero {h["id"]} activity coverage')
        if failures:coverage['integrity_failures'].append(dict(id=d['id'],failures=failures))
        coverage['snapshots']+=d['steps'];coverage['rounds']+=d['rounds']
        productive=all(t['gemsAcquired']>=100 and t['captures']>=3 and not t['errors'] for t in d['teams'])
        competitive=productive and min(d['scores'])>=250 and max(d['scores'])>=1000
        clean=productive and max(d['scores'])>=1000 and all(not t['rollovers'] for t in d['teams'])
        mirrored=clean and d['teams'][0]['draft']==d['teams'][1]['draft']
        dd=[]
        for s,t in enumerate(d['teams']):
            hs=[h for h in d['heroes'] if h['team']==s]
            deaths=[x for x in d['deaths'] if x['team']==s]
            banks=[b for b in d['banks'] if b['team']==s]
            cap=[c for c in d['captures'] if c['team']==s]
            clear=[c for c in d['clears'] if c['team']==s]
            prevbank={};gaps=[]
            for b in banks:
                if b['type'] in prevbank:gaps.append(b['round']-prevbank[b['type']])
                prevbank[b['type']]=b['round']
            episodes={(x['round'],'pair' if x['type'] in [3,4] else x['id']) for x in deaths}
            bygroup=defaultdict(list)
            for c in cap:bygroup[c['group']].append(c['round'])
            intervals=[b-a for rs in bygroup.values() for a,b in zip(rs,rs[1:])]
            budgets=t['budget']; denom=sum(budgets.values())
            row=dict(id=d['id'],content_occurrences=1+occurrences[d['id']],map=d['map'],side=s,won=int(d['winner']==s),rounds=d['rounds'],gems=d['scores'][s],enemy_gems=d['scores'][1-s],
                     productive=productive,competitive=competitive,clean=clean,competitive_clean=clean and competitive,mirrored=mirrored,draft='/'.join(NAMES[n] for n in t['draft']),
                     deaths_bodies=len(deaths),death_episodes=len(episodes),first_death=min((x['round'] for x in deaths),default=None),
                     early_deaths=sum(x['round']<=100 for x in deaths),alone_deaths=sum(x['allies8']<=1 for x in deaths),high_hp_deaths=sum(x['hpFraction']>.75 for x in deaths),
                     carried_on_death=sum(x['bag'] for x in deaths),death_bag_lost=t['deathBagLost'],captures=t['captures'],unique_camps=len(bygroup),
                     first_capture=min((c['round'] for c in cap),default=None),first_bank=min((b['round'] for b in banks),default=None),
                     bank_count=len(banks),bank_size=med([b['amount'] for b in banks]),bank_gap=med(gaps),camp_repeat_gap=med(intervals),
                     gold=t['goldAcquired'],gold_spent=t['goldSpent'],gems_acquired=t['gemsAcquired'],
                     camp_damage=round(t['campDamage']),nonlethal_pvp_damage=round(t['pvpDamage']),
                     moves=t['actions'].get('4',0),positional_displacements=t['moves'],attacks=t['actions'].get('5',0),casts=t['actions'].get('6',0),recall_starts=t['recalls'],wards=t['wards'],
                     blocked=t['actions'].get('23',0),locks=t.get('altarLocks',0),teleport_channel_starts=t['actions'].get('21',0),generic_consumable_events=t.get('consumables',0),sales=t['actions'].get('25',0),
                     errors=t['errors'],rollovers=t['rollovers'],early_rollovers=sum(a[1]==s and a[3]==26 and a[0]<=10 for a in d.get('turnActions',[])),first_contact=d['firstContact'],first_pvp_damage=d['firstPvpDamage'],
                     opening_hash=t['openingHash'],max_bag=t['maxBag'],end_bag=t['gemsAcquired']-sum(b['amount'] for b in banks)-sum(x['bag'] for x in deaths))
            row['max_hero_gold_share']=round(max((h['goldAcquired'] for h in hs),default=0)/max(1,t['goldAcquired']),4)
            row['top3_hero_gold_share']=round(sum(sorted((h['goldAcquired'] for h in hs),reverse=True)[:3])/max(1,t['goldAcquired']),4)
            for key in ['move','camp','pvp','capture','dead','stationary']:
                row[key+'_pct']=pct(budgets.get(key,0),denom)
            for r in [50,100,150,200,300,400,500]:
                m=t['milestones'].get(str(r),{})
                for key in ['gems','gold','captures','deaths','carried']:row[f'{key}_{r}']=m.get(key)
            for fam in range(7):row[FAMILIES[fam].lower()+'_shard_eq']=sum(h['items'][fam*6+k]+5*h['items'][fam*6+k+1] for h in hs for k in [0,2,4])
            for stat,k in [('strength',0),('focus',2),('health',4)]:row[stat+'_shard_eq']=sum(h['items'][f*6+k]+5*h['items'][f*6+k+1] for h in hs for f in range(7))
            rows.append(row);dd.append(row)
            for h in hs:
                ccasts=[c for c in d['casts'] if c['team']==s and c['type']==h['type']]
                deaths_h=[x for x in deaths if x['id']==h['id']]
                hr=dict(id=d['id'],map=d['map'],side=s,won=row['won'],productive=productive,clean=clean,mirrored=mirrored,champion=h['name'],
                        alive_rounds=h['aliveRounds'],deaths=len(deaths_h),gems_acquired=h['gemsAcquired'],delivered=h['delivered'],
                        camp_damage=round(h['campDamage']),pvp_damage=round(h['pvpDamage']),gold=h['goldAcquired'],spent=h['goldSpent'],
                        first_move=h.get('firstMove'),first_acquisition=h.get('firstAcquisition'),first_bank=h.get('firstBank'),
                        avg_bag=round(h['bagRounds']/max(1,h['aliveRounds']),2),allies8=round(h['ally8Sum']/max(1,h['aliveRounds']),2),
                        avg_hp_pct=round(100*h['hpFractionSum']/max(1,h['aliveRounds']),1),stationary_carry=h['stationaryCarry'])
                for slot in [0,1]:
                    hr[f'casts_{slot}']=h['casts'][slot]
                    hr[f'ready_round_samples_{slot}']=h['readyObservations'][slot]
                    hr[f'ready_near_enemy8_samples_{slot}']=h['readyWithEnemy8'][slot]
                    hr[f'casts_near_enemy8_{slot}']=sum(c['slot']==slot and c['enemies8']>0 for c in ccasts)
                    rs=[c['round'] for c in ccasts if c['slot']==slot]
                    hr[f'cast_gap_{slot}']=med([b-a for a,b in zip(rs,rs[1:])])
                for rr,st in h.get('stats',{}).items():
                    for k in ['focus','strength','maxHp','hp','gold']:hr[k+'_'+rr]=round(st[k],2)
                heroes.append(hr)
        win=dd[d['winner']] if d['winner'] in [0,1] else dd[0]
        lose=dd[1-d['winner']] if d['winner'] in [0,1] else dd[1]
        reasons=[]
        for field,label,thr in [('captures','more completed camps',2),('gold','higher gold income',300),('camp_damage','more camp damage',2000),('unique_camps','broader camp rotation',2)]:
            if win[field]-lose[field]>=thr:reasons.append(f'{label}: {win[field]} vs {lose[field]}')
        if lose['death_episodes']-win['death_episodes']>=2:reasons.append(f'fewer death episodes: {win["death_episodes"]} vs {lose["death_episodes"]}')
        if win.get('gems_100') is not None and lose.get('gems_100') is not None:reasons.append(f'banked at r100: {win["gems_100"]} vs {lose["gems_100"]}')
        if min(d['scores'])==0:reasons.append('zero-score side: weak/failed banking or idle behaviour; inspect before copying winner')
        if win['errors'] or lose['errors']:reasons.append(f'bot errors A/B: {dd[0]["errors"]}/{dd[1]["errors"]}')
        reviews.append(dict(id=d['id'],map=d['map'],winner='AB'[d['winner']] if d['winner'] in [0,1] else '?',rounds=d['rounds'],
                            score_a=d['scores'][0],score_b=d['scores'][1],productive=productive,competitive=competitive,
                            observed_differences='; '.join(reasons) or 'No single large measured difference; examine banking timing and event evidence.',
                            first_contact=d['firstContact'],first_pvp=d['firstPvpDamage'],draft_a=dd[0]['draft'],draft_b=dd[1]['draft'],
                            deaths_a=dd[0]['death_episodes'],deaths_b=dd[1]['death_episodes'],captures_a=dd[0]['captures'],captures_b=dd[1]['captures'],
                            gold_a=dd[0]['gold'],gold_b=dd[1]['gold'],evidence=f'games/{d["id"]}.json.gz'))
        draftpairs[(d['map'],*sorted([dd[0]['draft'],dd[1]['draft']]))].append(dd)
        review_zip.writestr(d['id']+'.md',game_card(d,dd,reasons))
        game_meta.append({**{k:d[k] for k in ['id','map','rounds','scores','steps']},
                          'teams':[{**{k:t.get(k,0) for k in ['errors','rollovers','altarLocks','consumables','resigned']},'teleport_channel_starts':t['actions'].get('21',0),'sales':t['actions'].get('25',0)} for t in d['teams']],
                          'heroes':[{'type':h['type']} for h in d['heroes']],
                          'deaths':[{k:x[k] for k in ['type','hpFraction','allies8']} for x in d['deaths']]})
    by_id={evidence_id(p):p for p in filelist}
    coverage['duplicate_files_verified']=0
    for canonical,aliases in _groups(duplicates,lambda r:r['same_as']).items():
        canonical_path=OUT/'games'/(canonical+'.json.gz')
        if not canonical_path.exists():canonical_path=by_id[canonical]
        original=load_evidence(canonical_path)
        for dup in aliases:
            alias=load_evidence(by_id[dup['id']])
            if alias['sha256']!=inventory_by_id[dup['id']]['sha256'] or alias['id']!=dup['id']:
                coverage['integrity_failures'].append(dict(id=dup['id'],failures=['duplicate source checksum or identity mismatch']))
            else:
                coverage['duplicate_files_verified']+=1
                if original.get('itemCacheVersion',0)>=2 and any(t['actions'].get('25',0) for t in original['teams']):
                    alias={**original,'id':dup['id'],'source':inventory_by_id[dup['id']]['path'],'evidence_reused_from':canonical}
                    dest=OUT/'games'/(dup['id']+'.json.gz');tmp=dest.with_name(dest.name+'.clone.tmp')
                    with gzip.open(tmp,'wt',encoding='utf-8',compresslevel=1) as f:json.dump(alias,f,separators=(',',':'))
                    os.replace(tmp,dest)
            review_zip.writestr(dup['id']+'.md',f'# {dup["id"]}\n\nByte-identical replay: see {dup["same_as"]}.md. Excluded from statistical counts.\n')
    review_zip.close()
    games=game_meta
    coverage['complete']=coverage['complete'] and not coverage['integrity_failures']
    (OUT/'coverage.json').write_text(json.dumps(coverage,indent=2),encoding='utf-8')
    write_csv('teams.csv',rows);write_csv('champion_games.csv',heroes);write_csv('game_reviews.csv',reviews)
    # Winner-vs-loser comparisons are paired within the same replay, never unmatched map means.
    comparisons=[]; predictive=[]
    fields=['deaths_bodies','death_episodes','early_deaths','captures','unique_camps','gold','gold_spent','camp_damage',
            'casts','attacks','recall_starts','wards','blocked','bank_count','bank_size','first_bank','first_capture','death_bag_lost',
            'move_pct','camp_pct','pvp_pct','capture_pct','dead_pct','stationary_pct','strength_shard_eq','focus_shard_eq','health_shard_eq','max_hero_gold_share','top3_hero_gold_share']
    subsets={'all':rows,**{k:[r for r in rows if r[k]] for k in ['productive','competitive','clean','competitive_clean','mirrored']}}
    paired={}
    for r in rows:paired.setdefault(r['id'],[]).append(r)
    for subset,rrs in subsets.items():
        wins=[r for r in rrs if r['won']];losses=[r for r in rrs if not r['won']]
        for field in fields:
            pairs=[(pair[0],pair[1]) for pair in paired.values() if len(pair)==2 and (subset=='all' or pair[0][subset])]
            wt=[];lt=[];diffs=[];higherwins=0;non_ties=0
            for a,b in pairs:
                w,l=(a,b) if a['won'] else (b,a)
                if w.get(field) is None or l.get(field) is None:continue
                wt.append(w[field]);lt.append(l[field]);diffs.append(w[field]-l[field])
                if w[field]!=l[field]:non_ties+=1;higherwins+=w[field]>l[field]
            comparisons.append(dict(subset=subset,metric=field,pairs=len(diffs),winner_median=med(wt),loser_median=med(lt),paired_difference_median=med(diffs),higher_value_wins_pct=pct(higherwins,non_ties),non_tied_pairs=non_ties))
        for r in [50,100,150,200,300]:
            for field in ['gems','gold','captures','deaths']:
                key=f'{field}_{r}'; ahead=[]
                for pair in paired.values():
                    a,b=pair
                    if subset!='all' and not a[subset]:continue
                    if a.get(key) is None or b.get(key) is None or a[key]==b[key]:continue
                    leader=a if a[key]>b[key] else b
                    ahead.append(leader['won'])
                predictive.append(dict(subset=subset,round=r,feature=field,non_tied_games=len(ahead),higher_value_win_pct=pct(sum(ahead),len(ahead)),ci95=wilson(sum(ahead),len(ahead))))
    write_csv('winner_loser.csv',comparisons);write_csv('early_leads.csv',predictive)
    maprows=[]
    for m in sorted({r['map'] for r in rows}):
        rs=[r for r in rows if r['map']==m];pr=[r for r in rs if r['clean']];ww=[r for r in pr if r['won']];ll=[r for r in pr if not r['won']]
        maprows.append(dict(map=m,games=len(rs)//2,productive_games=sum(r['productive'] for r in rs)//2,clean_games=len(pr)//2,side_a_win_pct=pct(sum(r['won'] for r in rs if r['side']==0),len(rs)//2),side_a_clean_win_pct=pct(sum(r['won'] for r in pr if r['side']==0),len(pr)//2),
            median_rounds=med([r['rounds'] for r in rs]),first_contact=med([r['first_contact'] for r in pr]),
            winner_deaths=med([r['death_episodes'] for r in ww]),loser_deaths=med([r['death_episodes'] for r in ll]),
            winner_camps=med([r['captures'] for r in ww]),loser_camps=med([r['captures'] for r in ll]),
            winner_gems_100=med([r['gems_100'] for r in ww]),loser_gems_100=med([r['gems_100'] for r in ll]),
            winner_gems_300=med([r['gems_300'] for r in ww]),loser_gems_300=med([r['gems_300'] for r in ll]),
            winner_move_pct=med([r['move_pct'] for r in ww]),loser_move_pct=med([r['move_pct'] for r in ll])))
    write_csv('maps.csv',maprows)
    champ_all=[]
    for subset in ['productive','clean']:
        champ=[]
        for name in NAMES:
            hs=[h for h in heroes if h['champion']==name and h[subset]];n=len(hs);w=sum(h['won'] for h in hs)
            # Drafts containing the hero on only one side: removes automatic 50% mirror contribution.
            exclusive=[]
            for pair in paired.values():
                a,b=pair
                if not a[subset]:continue
                included=[name in r['draft'].split('/') for r in pair]
                if sum(included)==1:exclusive.append(pair[included.index(True)]['won'])
            champ.append(dict(champion=name,appearances=n,wins=w,win_pct=pct(w,n),exclusive_games=len(exclusive),exclusive_win_pct=pct(sum(exclusive),len(exclusive)),exclusive_ci95=wilson(sum(exclusive),len(exclusive)),
                gems=med([h['delivered'] for h in hs]),deaths=med([h['deaths'] for h in hs]),camp_damage=med([h['camp_damage'] for h in hs]),
                slot0_casts=med([h['casts_0'] for h in hs]),slot1_casts=med([h['casts_1'] for h in hs]),slot0_gap=med([h['cast_gap_0'] for h in hs]),slot1_gap=med([h['cast_gap_1'] for h in hs]),
                allies8=med([h['allies8'] for h in hs]),focus_100=med([h.get('focus_100') for h in hs]),strength_100=med([h.get('strength_100') for h in hs])))
        champ_all.extend(dict(subset=subset,**r) for r in champ)
    write_csv('champions.csv',champ_all)
    champ=[r for r in champ_all if r['subset']=='clean']
    champion_maps=[]
    for m in sorted({r['map'] for r in rows}):
        mp=[p for p in paired.values() if p[0]['map']==m and p[0]['clean']]
        for name in NAMES:
            exclusive=[]
            for pair in mp:
                included=[name in r['draft'].split('/') for r in pair]
                if sum(included)==1:exclusive.append(pair[included.index(True)]['won'])
            champion_maps.append(dict(map=m,champion=name,exclusive_games=len(exclusive),wins=sum(exclusive),win_pct=pct(sum(exclusive),len(exclusive)),ci95=wilson(sum(exclusive),len(exclusive))))
    write_csv('champion_maps.csv',champion_maps)
    drafts=[]
    for subset in ['productive','clean']:
        for (m,draft),rs in _groups([r for r in rows if r[subset]],lambda r:(r['map'],r['draft'])).items():
            n=len(rs);w=sum(r['won'] for r in rs)
            ex=[r for r in rs if paired[r['id']][1-r['side']]['draft']!=draft]
            drafts.append(dict(subset=subset,map=m,draft=draft,games=n,wins=w,win_pct=pct(w,n),ci95=wilson(w,n),nonmirror_games=len(ex),nonmirror_wins=sum(r['won'] for r in ex),nonmirror_win_pct=pct(sum(r['won'] for r in ex),len(ex)),nonmirror_ci95=wilson(sum(r['won'] for r in ex),len(ex)),median_rounds=med([r['rounds'] for r in rs]),median_deaths=med([r['death_episodes'] for r in rs])))
    write_csv('drafts.csv',sorted(drafts,key=lambda r:(r['map'],-r['games'])))
    all_deaths=[x for d in games for x in d['deaths']]
    prod_ids={r['id'] for r in rows if r['productive']}
    pd=[x for d in games if d['id'] in prod_ids for x in d['deaths']]
    anomalies=dict(zero_zero=sum(d['scores']==[0,0] for d in games),zero_side=sum(min(d['scores'])==0 for d in games),
        under_1000=sum(max(d['scores'])<1000 for d in games),unknown_maps=sum(d['map']=='unknown' for d in games),
        errors=sum(t['errors'] for d in games for t in d['teams']),rollovers=sum(t['rollovers'] for d in games for t in d['teams']),
        locks=sum(t.get('altarLocks',0) for d in games for t in d['teams']),teleport_channel_starts=sum(t['teleport_channel_starts'] for d in games for t in d['teams']),
        generic_consumable_events=sum(t.get('consumables',0) for d in games for t in d['teams']),sales=sum(t['sales'] for d in games for t in d['teams']),resignations=sum(bool(t.get('resigned')) for d in games for t in d['teams']),
        heart_of_ruin_games=sum(any(h['type']==12 for h in d['heroes']) for d in games),
        productive_deaths=len(pd),productive_linked_body_deaths=sum(x['type'] in [3,4] for x in pd),
        productive_high_hp_deaths=sum(x['hpFraction']>.75 for x in pd),productive_alone_deaths=sum(x['allies8']<=1 for x in pd))
    summary=dict(coverage={k:v for k,v in coverage.items() if k not in ['missing','errors']},subsets={k:len(v)//2 for k,v in subsets.items()},anomalies=anomalies)
    (OUT/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    report=['# Replay corpus analysis','',f'Coverage: **{len(processed):,}/{len(expected):,} files**, {len(games):,} unique replay contents. '+('Complete.' if coverage['complete'] else '**PROVISIONAL — extraction is not complete.**'),'',
    f"Decoded {coverage['snapshots']:,} engine timeline states across {coverage['rounds']:,} game rounds. {len(duplicates)} byte-identical duplicates are excluded from statistical tables; every file retains evidence.",
    '', '## How to use this evidence','',
    'The game reviews cover both sides of each unique replay. These are descriptive observations, not controlled tests of a strategy. Replays do not identify team names, ratings, bot versions, private memory, intended targets or reasoning. Do not interpret champion win rates as intrinsic champion strength.',
    'Confidence intervals are nominal binomial intervals. Repeated anonymous policies and matchups can be correlated, so real uncertainty can be larger; team-level clustering cannot be reconstructed from these files.',
    '',f"All games: {len(games):,}. Productive games: {len(prod_ids):,} (both sides acquired at least 100 gems, captured at least three camps, and have no recorded bot-error events). Clean productive games: {len(subsets['clean'])//2:,}. Identical-draft clean games: {len(subsets['mirrored'])//2:,}. Competitive sensitivity set: {sum(r['competitive'] for r in rows)//2:,} (productive, loser banked at least 250 and winner banked at least 1000). Filtering by achieved resources can bias comparisons; compare all subsets in the CSVs.",
    '',f"Zero/zero games: {anomalies['zero_zero']:,}; games with a zero-score side: {anomalies['zero_side']:,}; games ending below 1000 on both sides: {anomalies['under_1000']:,}. A tiebreak winner in an idle game supplies no evidence for a winning farming strategy.",
    '', '## Winners versus losers','',
    'Paired comparisons from the same productive game. Medians are per team; the median paired difference can differ from the difference between marginal medians. Higher-value win percentages omit ties. The clean subset additionally requires a 1000-gem finish and excludes either side having a fuel rollover. Thus zero-score gold-tiebreak games cannot drive the primary strategy comparison. competitive_clean further requires the losing team to have banked at least 250. The mirrored subset requires clean play and identical physical champion lineups; it still does not control bot skill or starting side.', '',
    '### Clean productive games (primary strategy comparison)','',
    table([r for r in comparisons if r['subset']=='clean'],[('Metric','metric'),('Games','pairs'),('Winner median','winner_median'),('Loser median','loser_median'),('Median paired difference','paired_difference_median'),('Higher value wins %','higher_value_wins_pct')]),
    '', '### All productive games (including fuel rollovers)','',
    table([r for r in comparisons if r['subset']=='productive'],[('Metric','metric'),('Games','pairs'),('Winner median','winner_median'),('Loser median','loser_median'),('Median paired difference','paired_difference_median'),('Higher value wins %','higher_value_wins_pct')]),
    '', '## Early timing','',
    'For each checkpoint, compare sides still present in that replay. Earlier-ending games are absent; later checkpoints therefore describe a different subset. A lead predicts the recorded winner but does not prove how to create that lead.', '',
    table([r for r in predictive if r['subset']=='clean'],[('Round','round'),('Higher metric','feature'),('Non-tied games','non_tied_games'),('Win %','higher_value_win_pct'),('95% interval','ci95')]),
    '', '## Map-specific observations','', 'Performance columns below use the clean subset. All-game side rates can be distorted by gold-tiebreak and inactive games; clean side rates are also supplied in maps.csv.', '',table(maprows,[('Map','map'),('All games','games'),('Productive','productive_games'),('Clean','clean_games'),('A wins % clean','side_a_clean_win_pct'),('First contact r','first_contact'),('W deaths','winner_deaths'),('L deaths','loser_deaths'),('W captures','winner_camps'),('L captures','loser_camps'),('W gems r300','winner_gems_300'),('L gems r300','loser_gems_300')]),
    '', '## Champion selection and execution','',
    'Exclusive means a champion was present on exactly one side. Team skill, draft partners, map, game duration and bot quality remain confounders. Cassi and Issac are physical bodies from one draft selection; their deaths must not be treated as two independent fights. Heart of Ruin is retained separately if present.', '',
    table(champ,[('Champion','champion'),('Appearances','appearances'),('Exclusive games','exclusive_games'),('Exclusive win %','exclusive_win_pct'),('95% interval','exclusive_ci95'),('Median delivered','gems'),('Median deaths','deaths'),('Slot 0 gap','slot0_gap'),('Slot 1 gap','slot1_gap')]),
    '', 'See `drafts.csv` for complete map/draft results and uncertainty, and `champion_games.csv` for per-champion purchases, stats, ability timing, first movement, acquisition and banking.',
    '', '## Rare mechanics and technical events','', '```json',json.dumps(anomalies,indent=2),'```',
    '', '## Measurement definitions and limits','',
    '- Every replay is advanced through the official offline visualiser engine to a terminal outcome. Input/scheduler frames with unchanged measured state are skipped for allocation only; engine transitions still execute. The source SHA-256 pins the evidence.',
    '- Recorded actions require an initial substep and unique event key. They represent successful replay-visible actions, not attempted API calls. Failed/blocked movement is separately recorded. Positional movement includes displacement effects, so action moves and position changes can differ.',
    '- Recall counts are channel starts, not completed healing trips. Some bots cancel a previous recall, act, then start another in the same turn; thousands of starts can correspond to few completed recalls. Teleport counts are channel starts too; completion cannot be inferred from that counter. Altar-lock and teleport actions are consumable uses even when the generic consumable event count is zero.',
    '- First contact means opposing living bodies are within Chebyshev distance 8 using omniscient positions. Walls and bushes may block actual vision. Nearby allies/enemies are distance counts, not visibility or guaranteed attack support.',
    '- A cast near an enemy does not prove it targeted or hit that enemy. Round-start readiness samples are not legal-cast opportunities, and casts/readiness is not a valid cooldown-utilisation percentage. Ability gaps include travel, death and target absence.',
    '- Cast/turn-action from/to coordinates are raw engine step payloads. Some cast types populate the target but leave the source as (0,0); that source is not a verified caster position. Proximity counters use the actual champion snapshot position. Move and basic-attack coordinate payloads are useful for their respective paths/targets. Empty-body trajectory entries originate in draft transitions and should be omitted from gameplay movement analysis.',
    '- Round activity uses priority: dead, observed nonlethal PvP damage participation, camp damage dealt, standing on an available reward spawn tile, displacement, stationary. A round can contain multiple activities; it is classified once. Stationary is not necessarily idle (channeling, waiting, healing and buying can be useful).',
    '- Camp captures are completed group rewards. Clear last hits can be unowned (e.g. spells whose owner is no longer recoverable); use capture ownership for farming comparisons. Gold is reconstructed from positive bag changes, excluding explicit sale-refund events; gold spent counts shop-step decreases. Sale-containing replays are re-extracted with inventory updates at both buys and sales. This remains a reconstructed income measure rather than a direct read of the official lifetime-gold tiebreak field.',
    '- The purchase-event list records changes to the 42 equipment slots, including combinations and sales. Consumable-only purchases do not alter that list; their spending is included in shop gold decreases and their uses appear as altar locks or teleport channels. It is not a complete record of unspent consumable stock.',
    '- Nonlethal PvP damage is a conservative actor-attributed measure; lethal transitions are omitted to avoid counting linked-death HP removal as damage. Damage-over-time attribution and spell-owner expiry can leave unassigned damage. Do not use it as exact total combat damage.',
    '- Camp damage also uses the visible event actor or recovered spell owner. Retaliation and indirect effects may be unassigned or associated with the triggering event. It is not an exact intrinsic-DPS measurement for comparing kits. Carried-bag averages and maxima use round-end samples and can miss brief intra-round peaks.',
    '- Death HP is the immediately preceding engine state, not HP at engagement start. High-HP linked deaths can occur when the partner dies. Death bag at risk and measured bag loss differ; both are supplied. Physical deaths and deduplicated same-round pair death episodes are separate.',
    '- Banking events are observed bag decreases coinciding with team score increases. Multiple recipients are attributed individually. Bag increases include capture rewards and theft; they are not purely camp production. End inventories use five-shard purchase equivalents per emblem; Power emblems grant six shards of stats.',
    '- Only the first folder (replays-2026-10-18-part1) and its completed CRC-checked archive are included. The second folder is excluded by user instruction.',
    '', '## Evidence files','',
    '- `game_reviews.csv`: one review per unique replay, winning side, drafts, economy, deaths and observed differences.',
    '- `game_reviews.zip`: a Markdown review for every match ID, with complete captures, deliveries, deaths, purchases and position/economy checkpoints; identical contents cross-reference their original review.',
    '- `games/<match-id>.json.gz`: compressed JSON evidence with purchases, casts, attacks, deaths, bank/capture events, all useful turn actions, opening actions and position samples.',
    '- `teams.csv`, `champion_games.csv`: all per-game measurements; `maps.csv`, `champions.csv`, `drafts.csv`, `winner_loser.csv`, `early_leads.csv`: comparison tables.',
    '- `coverage.json`, `inventory.json`, `duplicates.json`: completeness, source hashes, failures and duplicate accounting.', '']
    (OUT/'REPORT.md').write_text('\n'.join(report),encoding='utf-8')
    print(json.dumps(summary,indent=2))

def _groups(rows, key):
    d=defaultdict(list)
    for r in rows:d[key(r)].append(r)
    return d

def game_card(d,rows,reasons):
    lines=[f'# {d["id"]}', '',f'Map: {d["map"]}; winner: {"AB"[d["winner"]]}; end round: {d["rounds"]}; A/B score: {d["scores"]}.',
           f'Source SHA-256: `{d["sha256"]}`.', '', '## Observable outcome differences','']
    lines += ['- '+s for s in reasons] or ['No single large measured difference; inspect the timeline below.']
    lines += ['', '## Draft, opening and individual roles','']
    for side in [0,1]:
        lines += [f'### Team {"AB"[side]}','',rows[side]['draft'],'',
                  f'Captures {rows[side]["captures"]}, distinct groups {rows[side]["unique_camps"]}, gold acquired {rows[side]["gold"]}, shop spend {rows[side]["gold_spent"]}; physical deaths {rows[side]["deaths_bodies"]}, death episodes {rows[side]["death_episodes"]}.','']
        for h in [h for h in d['heroes'] if h['team']==side]:
            lines.append(f'- {h["name"]}: first move r{h.get("firstMove")}, first acquisition r{h.get("firstAcquisition")}, first bank r{h.get("firstBank")}; delivered {h["delivered"]}, acquired {h["gemsAcquired"]}; casts slot 0/1 {h["casts"]}; camp damage {round(h["campDamage"])}; activity {h["budget"]}.')
            first=[a for a in d['opening'][side] if a[1]==h['type'] and a[2] in [4,5,6,11,12,13]][:18]
            lines.append('  Opening actions: '+', '.join(f'r{a[0]} {ACTIONS[a[2]]}'+(f' slot {a[3]}' if a[2]==6 else '')+(f'→({a[4]},{a[5]})' if a[2] in [4,5,6] else '') for a in first)+'.')
        lines.append('')
    lines += ['## Economy and position checkpoints','',table(d['trajectory'],[('Round','round'),('Banked A/B','scores'),('Positions, bags, captures and gold A/B','teams')]),'',
              '## Complete capture order','']
    for s in [0,1]:lines.append(f'Team {"AB"[s]}: '+', '.join(f'r{x["round"]}:g{x["group"]}' for x in d['captures'] if x['team']==s))
    lines += ['', '## Complete bank events','',table(d['banks'],[('Round','round'),('Side','team'),('Champion type','type'),('Gems','amount'),('x','x'),('y','y')]),'',
              '## Every death and immediate context','',table(d['deaths'],[('Round','round'),('Side','team'),('Champion type','type'),('HP fraction before','hpFraction'),('Bag','bag'),('Allies within 8','allies8'),('Enemies within 8','enemies8'),('Actor type','actorType'),('Actor kind','actorKind')]),'',
              '## Observed equipment inventory changes','',
              'Index mapping: seven families Monster/Power/Durability/Treasure/Jungle/Home/Bruiser, each six indices = Strength shard/emblem, Focus shard/emblem, Health shard/emblem. Negative shard changes can be automatic combination into an emblem.','',
              table(d['purchases'],[('Round','round'),('Side','team'),('Champion type','type'),('Gold change','goldDelta'),('Inventory delta (42 items)','delta')]),'',
              '## Interpretation limits','',
              'Differences above are observations, not proof of the winner’s intent or a causal test. Nearby counts use omniscient distance and ignore line of sight. Death HP is the preceding state and linked deaths can remove a healthy partner. Read REPORT.md for definitions. Full cast and attack sequences are in the corresponding games JSON.','']
    return '\n'.join(lines)

if __name__=='__main__':main()
