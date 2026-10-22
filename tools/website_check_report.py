"""Report release-mode comparisons on the isolated current website runtime."""
import argparse,hashlib,json
from pathlib import Path
import train
from decode_camstat import decode,schema

def row(path,side,map_name,opponent):
 data=decode(path);match=data['match'];teams={t['id']:t for t in data['teams']}
 identities={c['id']:c for c in data['roster']['champions']}
 champions=[]
 for c in data['champions']:
  identity=identities[c['id']]
  if identity['team']!=side:continue
  metrics={schema['metrics'][m['id']]:m['value'] for m in c['metrics']}
  champions.append(dict(id=c['id'],type=identity['type'],**metrics))
 own,enemy=teams[side]['submittedGems'],teams[1-side]['submittedGems']
 fuel=sum(len(s['entries']) for s in data['events'] if s['kind']==14 and s['owner'] in identities and identities[s['owner']]['team']==side)
 return dict(map=map_name,side=side,opponent=opponent,points=float(match['outcome']==side+1),share=own/(own+enemy) if own+enemy else .5,
  rate=own/match['roundsStarted'],rounds=match['roundsStarted'],gems=own,enemy_gems=enemy,
  faults=data['diagnostics']['botFaults'][side],enemy_faults=data['diagnostics']['botFaults'][1-side],fuel_exhausted=fuel,
  deaths=sum(c['deaths'] for c in champions),champion_economy=champions,
  economy={key:sum(c[key] for c in champions) for key in ('collectedGems','submittedGems','earnedGold','spentGold','kills')})

def report(runtime,matches,label,opponents,maps):
 pin=json.loads((matches/'pin.json').read_text())
 for name in [label,*opponents]:
  if train.source_hash(runtime/'bots'/name)!=pin['sources'][name]:
   raise ValueError('Source changed during qualification: '+name)
 if not pin.get('release') or pin.get('fuel')!=100000:
  raise ValueError('Expected website release settings')
 rows=[row(matches/f'{label}_{op}_{m}_{side}.camstat',side,m,op) for op in opponents for m in maps for side in (0,1)]
 return dict(source=train.source_hash(runtime/'bots'/label),runtime='toolkit 2.2.5 / engine 0.0.3 / release / 100000 fuel',games=len(rows),
  summary=train.summarize(rows),fault_free=all(r['faults']==0 for r in rows),opponents_fault_free=all(r['enemy_faults']==0 for r in rows),
  fuel_exhausted=sum(r['fuel_exhausted'] for r in rows),opponents={op:train.summarize([r for r in rows if r['opponent']==op]) for op in opponents},
  maps={m:train.summarize([r for r in rows if r['map']==m]) for m in maps},rows=rows)

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--runtime',type=Path,required=True);p.add_argument('--matches',type=Path,required=True);p.add_argument('--label',required=True);p.add_argument('--output',type=Path,required=True)
 a=p.parse_args();maps=json.loads((train.ROOT/'out/v42-map-batch/manifest.json').read_text())['maps']
 result=report(a.runtime,a.matches,a.label,['v36','v38'],maps);a.output.write_text(json.dumps(result,indent=2));print(json.dumps({k:v for k,v in result.items() if k not in ('rows','maps')}))
