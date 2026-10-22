"""Controlled champion packs test. Resignation is not a competitive loss/win."""
import argparse
import collections
import json
import os
import re
from pathlib import Path
import time
import train


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=train.ROOT/'bots/champion-maps')
    parser.add_argument('--out',type=Path,default=train.ROOT/'out/champion-studies/cassi-issac-packs')
    parser.add_argument('--champion',choices=['pair','ryth','vesper_vale','vendetta','stellar','prism','marcella','willow','ren','varg','tavi'],default='pair')
    parser.add_argument('--companion',choices=['ren','ryth'],help='Optional active ally for healing studies')
    parser.add_argument('--control',action='store_true',help='Disable the new pair profile, retain identical lab restrictions')
    parser.add_argument('--trace',action='store_true',help='Extra legacy decision trace; diagnostic runs are separate from timing comparisons')
    parser.add_argument('--group',type=int,default=2,choices=range(8))
    parser.add_argument('--rounds',type=int,default=300)
    args=parser.parse_args()
    folder=args.out.resolve();folder.mkdir(parents=True,exist_ok=True)
    source=folder/'prepared'
    if source.exists():raise ValueError('Use a new output directory; measurements are immutable')
    train.copy_source(args.source.resolve(),source)
    config=source/'src/champion_maps_config.h'
    inventory=json.loads((train.ROOT/'docs/maps/packs.inventory.json').read_text())
    group=inventory['observations'][0]['groups'][args.group]
    map_hash=__import__('hashlib').sha256((train.ROOT/'maps/packs.map26a').read_bytes()).hexdigest()
    if map_hash!=inventory['map_sha256']:raise ValueError('Packs changed; refresh and review the inventory before testing')
    text=config.read_text().replace('CHAMPION_MAPS_SINGLE_GROUP=-1',f'CHAMPION_MAPS_SINGLE_GROUP={args.group}')
    text=text.replace('CHAMPION_MAPS_DELIVERY_GEMS=48',f'CHAMPION_MAPS_DELIVERY_GEMS={group["gems"]}')
    physical=dict(ryth=0,vesper_vale=1,vendetta=2,stellar=5,prism=6,marcella=7,willow=8,ren=9,varg=10,tavi=11)
    if args.champion!='pair':text=text.replace('CHAMPION_MAPS_LAB_ACTOR=-1',f'CHAMPION_MAPS_LAB_ACTOR={physical[args.champion]}')
    if args.companion:text=text.replace('CHAMPION_MAPS_LAB_COMPANION=-1',f'CHAMPION_MAPS_LAB_COMPANION={physical[args.companion]}')
    text=text.replace('CHAMPION_MAPS_EXTENDED=false','CHAMPION_MAPS_EXTENDED=true')
    text=re.sub(r'CHAMPION_MAPS_PROFILE=-?\d+','CHAMPION_MAPS_PROFILE=-1',text)
    text=re.sub(r'CHAMPION_MAPS_PROFILE2=-?\d+','CHAMPION_MAPS_PROFILE2=-1',text)
    if args.control:text=text.replace('CHAMPION_MAPS_ENABLED=true','CHAMPION_MAPS_ENABLED=false')
    config.write_text(text)
    # Both experiments start with the pair, buy no initial equipment, and
    # bank immediately after this one reward rather than waiting for respawn.
    selected=3 if args.champion=='pair' else dict(ryth=0,vesper_vale=1,vendetta=2,stellar=4,prism=5,marcella=6,willow=7,ren=8,varg=9,tavi=10)[args.champion]
    order=[selected]+[i for i in range(11) if i!=selected]
    if args.companion:
        second={'ren':8,'ryth':0}[args.companion]
        order=[selected,second]+[i for i in range(11) if i not in (selected,second)]
    train.write_params(source,dict(ADAPTIVE_BANK=False,BANK_AT=1,BANK_NEAR=1,SHOP_GOLD=0,
        DRAFT_ORDER=order,DRAFT_OPENER=order,MAP_DRAFT=False,DRAFT_BY_SIZE=False,NO_CASSI=False))
    if args.trace:
        # The training parameter writer deliberately forces TRACE off. This
        # explicit lab-only override never touches training or release sources.
        params=source/'src/params.h'
        params.write_text(re.sub(train.param_pattern('TRACE'),lambda m:m[1]+'true'+m[3],params.read_text()))
    digest=train.source_hash(source)
    pin=dict(companion=args.companion,champion=args.champion,source=digest,map_sha256=map_hash,group=args.group,delivery_gems=group['gems'])
    train.atomic_json(folder/'pin.json',pin)
    os.environ['CMAKE_BUILD_PARALLEL_LEVEL']='1'
    deadline=time.monotonic()+900
    train.command([train.ENGINE,'build',source],deadline,folder/'build.log')
    results=[]
    for side in (0,1):
        work=folder/('side-'+str(side));work.mkdir()
        bots=[source,train.ROOT/'bots/idle']
        if side:bots.reverse()
        command=[train.ENGINE,'run',*bots,'--map',train.ROOT/'maps/packs.map26a',
                 '--fuel','100000','--rounds',str(args.rounds),'--statistics',work/'statistics.json','--out-dir',work]
        for attempt in range(3):
            try:
                train.command(command,deadline,folder/('side-'+str(side)+'.log'))
                break
            except RuntimeError as error:
                if 'Access is denied' in str(error) and attempt<2:continue
                if 'Statistics require a game outcome' in str(error):break
                raise
        stdout=train.bot_stdout(work,side)
        if stdout is None:raise ValueError('Missing lab stdout')
        (work/'measurements.stdout').write_text(stdout)
        completions=[int(line.split()[1]) for line in stdout.splitlines() if line.startswith('CM_COMPLETE ')]
        measurements=[];sequences=collections.Counter()
        for line in stdout.splitlines():
            if not line.startswith('CM '):continue
            _,round_no,champion,sequence,predicted,observed,attacks,casts,fuel=line.split()
            sequences[champion+':'+sequence]+=1
            measurements.append(dict(round=int(round_no),champion=champion,sequence=int(sequence),
                predicted=float(predicted),observed=float(observed),attacks=int(attacks),casts=int(casts),fuel=int(fuel)))
        stats=json.loads((work/'statistics.json').read_text()) if (work/'statistics.json').exists() else None
        result=dict(engine_faults=int(stats['botFaults'][side]) if stats else None,enemy_faults=int(stats['botFaults'][1-side]) if stats else None,side=side,completed=bool(completions),delivery_round=min(completions) if completions else None,
            errors=stdout.count('bot error:'),discontinuities=stdout.count('CM_DISCONTINUITY'),
            sequences=dict(sequences),measurements=measurements,
            max_prediction_error=max((abs(r['predicted']-r['observed']) for r in measurements),default=None),
            max_casts=max((r['casts'] for r in measurements),default=0))
        states=[line.split() for line in stdout.splitlines() if line.startswith('CM_STATE ')]
        previous={};deaths=0
        for row in states:
            alive=int(row[3]);champion=row[2]
            if previous.get(champion)==1 and not alive:deaths+=1
            previous[champion]=alive
        result.update(deaths=deaths,minimum_live_health=min((float(row[4]) for row in states if row[3]=='1'),default=None),
            dashes=stdout.count('CM_DASH '),capture_steps=stdout.count('CM_CAPTURE_STEP '),heals=stdout.count('CM_HEAL '),
            max_heal_error=max((abs(float(line.split()[2])-float(line.split()[3])) for line in stdout.splitlines() if line.startswith('CM_HEAL ')),default=0))
        results.append(result)
        print(json.dumps({k:v for k,v in result.items() if k!='measurements'}),flush=True)
    report=dict(**pin,control=args.control,diagnostic_trace=args.trace,results=results,
        note='Controlled single group, other allies idle, enemy-response decisions disabled only in lab. No competitive win rate is implied.')
    train.atomic_json(folder/'report.json',report)
    if not all(r['completed'] and r['errors']==0 and r['engine_faults']==0 and r['enemy_faults']==0 and r['deaths']==0 for r in results):raise ValueError('Controlled delivery test failed; inspect logs')
    if args.companion and args.champion=='willow' and not args.control and not all(r['heals']>0 and r['max_heal_error']<=0.2 for r in results):
        raise ValueError('Expected correctly predicted healing on both sides')
    if not args.control and not all(r['measurements'] and r['max_prediction_error']<=0.2 and r['max_casts']<=1 and r['discontinuities']==0 for r in results):
        raise ValueError('Action predictions/legality did not meet the test criteria')


if __name__=='__main__':main()
