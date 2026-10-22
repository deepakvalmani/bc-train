"""Resumable v43 search against frozen v42 with a v36/v38 regression guard. No uploads."""
import argparse, hashlib, json, math, random, shutil, signal, subprocess, time, zipfile
from pathlib import Path
import train

ROOT=Path(__file__).resolve().parent.parent
MAPS='ambush collision contest corners eight elkring expanse fragment interlock lanes monolith packs pilgrimage rows rushbait-v2 stampede swirl'.split()
SPACE={
 'clear_rate':[1.0,1.25,1.5,2.0,3.0,4.0,5.0], 'bank_k':[6.5,8.0,9.5,11.0,13.0],
 'team_soak':[0.4,0.6,0.8,1.2,2.0], 'squad_soak':[0.4,0.6,0.8],
 'gold_only_scale':[0.03,0.15,0.3,0.6,1.0], 'recall_hp':[0.3,0.38,0.45,0.55],
 'pair_recall_hp':[0.35,0.45,0.55], 'burst_frac':[0.2,0.3,0.4],
 'solo_capture':[False,True], 'near_k':[0,6,10,16],
}

def render(base,genes):
 if not genes:return base
 marker='inline Policy for_map(Map id)'
 if base.count(marker)!=1:raise ValueError('Expected one map-policy dispatcher')
 text=base.replace(marker,'inline Policy base_for_map(Map id)',1)
 cases=[]
 for name,fields in sorted(genes.items()):
  if name not in MAPS:raise ValueError('Unknown map')
  assignments=[]
  for key,value in sorted(fields.items()):
   if key not in SPACE or value not in SPACE[key]:raise ValueError('Out-of-range gene')
   literal=str(value).lower() if isinstance(value,bool) else str(value)
   assignments.append(f'p.{key}={literal};')
  cases.append('case Map::'+name.replace('-','_')+':'+''.join(assignments)+'break;')
 pos=text.rfind('}')
 return text[:pos]+'\ninline Policy for_map(Map id){auto p=base_for_map(id);switch(id){'+''.join(cases)+'default:break;}return p;}\n'+text[pos:]

def policy_defaults(source,folder,deadline):
    """Read effective map values using the pure C++ policy header, not regex guesses."""
    code='#include "map_policies.h"\n#include <iostream>\n#include <iomanip>\nint main(){std::cout<<std::setprecision(9);for(int i=1;i<=17;++i){auto p=map_policies::for_map(static_cast<map_policies::Map>(i));std::cout<<i'
    code+=''.join('<<" "<<p.'+key for key in SPACE)+'<<"\\n";}}\n'
    cpp=folder/'policy_values.cpp';exe=folder/'policy_values.exe';cpp.write_text(code)
    train.command(['g++','-std=c++17','-O2','-I',source/'src',cpp,'-o',exe],deadline,folder/'logs/policy-values-build.log')
    result=subprocess.run([str(exe)],capture_output=True,text=True,check=True,timeout=10)
    lines=result.stdout.splitlines()
    if len(lines)!=len(MAPS):raise ValueError('Incomplete policy defaults')
    values={}
    for index,line in enumerate(lines):
        parts=line.split()
        if int(parts[0])!=index+1 or len(parts)!=len(SPACE)+1:raise ValueError('Invalid defaults row')
        values[MAPS[index]]={key:float(value) for key,value in zip(SPACE,parts[1:])}
    return values

def scores(rows):
 return {'wins':sum(r['won'] for r in rows),'games':len(rows),
         'share':sum(r['share'] for r in rows)/len(rows),
         'faults':sum(r['faults'] for r in rows)}

def completed(path):
 try:
  j=json.loads(path.read_text())
  if j['match']['outcome'] not in ('teamA','teamB','draw'):return False
  if {t['team'] for t in j['teams']}!={'teamA','teamB'}:return False
  with zipfile.ZipFile(path.with_suffix('.repl26a')) as archive:
   if not {'team-a.stdout','team-b.stdout'}.issubset(archive.namelist()):return False
   return archive.testzip() is None
 except (OSError,ValueError,KeyError,zipfile.BadZipFile):return False

def acceptable(candidate,incumbent):
 if len(candidate)!=34 or len(incumbent)!=34:return False
 if {(r['map'],r['side']) for r in candidate}!={(m,s) for m in MAPS for s in (0,1)}:return False
 if scores(candidate)['faults'] or scores(candidate)['wins']<=scores(incumbent)['wins']:return False
 return all(sum(r['won'] for r in candidate if r['map']==m)>=sum(r['won'] for r in incumbent if r['map']==m) for m in MAPS)

def reference_ok(rows, minimum=57):
 expected={(m,side,op) for m in MAPS for side in (0,1) for op in ('v36','v38')}
 return (len(rows)==68 and {(r['map'],r['side'],r.get('opponent')) for r in rows}==expected
         and scores(rows)['faults']==0 and scores(rows)['wins']>=minimum)

class Search:
 def __init__(self,args):
  self.args=args;self.runtime=(ROOT/args.runtime).resolve();self.folder=(ROOT/args.run).resolve();self.folder.mkdir(parents=True,exist_ok=True)
  self.deadline=time.monotonic()+args.minutes*60
  train.ROOT=self.runtime;train.ENGINE=self.runtime/'cambc.exe'
  for x in ['logs','results','snapshots']:(self.folder/x).mkdir(exist_ok=True)
  # Fixed names inside this run, never replace source outside this run.
  tag=hashlib.sha256(str(self.folder).encode()).hexdigest()[:8]
  self.op=self.runtime/'bots'/('g43_'+tag+'_42')
  self.cand=self.runtime/'bots'/('g43_'+tag+'_candidate')
  self.refs={n:self.runtime/'bots'/('g43_'+tag+'_'+n) for n in ('v36','v38')}
  self.seed=self.folder/'seed'
  self.frozen=self.folder/'v42'
  state_path=self.folder/'state.json'
  if state_path.exists():
   self.state=json.loads(state_path.read_text())
   if self.state.get('schema')!=2:raise ValueError('Old unguarded experiment: use --run out/t43guard')
  else:
   if self.op.exists() or self.cand.exists():raise ValueError('Training runtime bot names already exist; resume the original run')
   original=ROOT/'out/t43/seed'
   opponent=ROOT/'out/t43/v42'
   if not original.exists():original=ROOT/'bots/v43'
   if not opponent.exists():opponent=ROOT/'bots/v42'
   shutil.copytree(original/'src',self.seed/'src')
   shutil.copytree(opponent/'src',self.frozen/'src')
   for n in self.refs:shutil.copytree(self.runtime/'bots'/n/'src',self.folder/n/'src')
   runtime_hash=hashlib.sha256(train.ENGINE.read_bytes())
   for f in [self.runtime/'cambc.toml',*sorted((self.runtime/'sdk/cpp').rglob('*')),*[self.runtime/'maps'/(m+'.map26a') for m in MAPS]]:
    if f.is_file():runtime_hash.update(f.read_bytes())
   self.state={'schema':2,'references':{n:train.source_hash(self.folder/n) for n in self.refs},'reference_baseline':None,'reference_incumbent':None,'runtime':runtime_hash.hexdigest(),'seed':train.source_hash(self.seed),'opponent':train.source_hash(self.frozen),'genes':{},'trials':0,'promotions':0,'baseline':None,'incumbent':None,'pending':None,'target':34,'status':'active'}
   train.atomic_json(state_path,self.state)
  if train.source_hash(self.seed)!=self.state['seed'] or train.source_hash(self.frozen)!=self.state['opponent']:raise ValueError('Frozen sources changed')
  runtime_hash=hashlib.sha256(train.ENGINE.read_bytes())
  for f in [self.runtime/'cambc.toml',*sorted((self.runtime/'sdk/cpp').rglob('*')),*[self.runtime/'maps'/(m+'.map26a') for m in MAPS]]:
   if f.is_file():runtime_hash.update(f.read_bytes())
  if runtime_hash.hexdigest()!=self.state['runtime']:raise ValueError('Runtime changed; do not reuse this experiment')
  self.base=(self.seed/'src/map_policies.h').read_text()
  defaults_file=self.folder/'defaults.json'
  if defaults_file.exists():self.defaults=json.loads(defaults_file.read_text())
  else:
   self.defaults=policy_defaults(self.seed,self.folder,self.deadline);train.atomic_json(defaults_file,self.defaults)
  self.built_source=None
  self.sync(self.frozen,self.op)
  for n,dst in self.refs.items():
   if train.source_hash(self.folder/n)!=self.state['references'][n]:raise ValueError('Frozen reference changed')
   self.sync(self.folder/n,dst)
 def save(self):train.atomic_json(self.folder/'state.json',self.state)
 def sync(self,src,dst):
  (dst/'src').mkdir(parents=True,exist_ok=True)
  shutil.copytree(src/'src',dst/'src',dirs_exist_ok=True)
 def command(self,args,name):
  train.command([train.ENGINE,*args],self.deadline,self.folder/'logs'/(name+'.log'))
 def evaluate(self,genes,maps,opponent=None):
  op=self.refs[opponent] if opponent else self.op
  label=opponent or "v42"
  expected=self.state["references"][opponent] if opponent else self.state["opponent"]
  self.sync(self.seed,self.cand)
  (self.cand/'src/map_policies.h').write_text(render(self.base,genes))
  digest=train.source_hash(self.cand)
  snapshot=self.folder/'snapshots'/digest
  if not snapshot.exists():shutil.copytree(self.cand/'src',snapshot/'src')
  if train.source_hash(op)!=expected:raise ValueError('Frozen runtime opponent changed')
  if self.built_source!=digest:
   self.command(['build',self.cand,'--release'],digest+'-build');self.built_source=digest
  lines=[]
  for m in maps:
   for side in (0,1):
    path=self.folder/'results'/f'{digest}-{label}-{m}-{side}.json'
    if completed(path):continue
    path.unlink(missing_ok=True)
    path.with_suffix('.repl26a').unlink(missing_ok=True)
    a,b=self.cand,op
    if side:a,b=b,a
    lines.append(f'"{a}" "{b}" "{self.runtime / "maps" / (m+".map26a")}" "{path.with_suffix(".repl26a")}" --statistics "{path}" --json')
  if lines:
   manifest=self.folder/'batch.txt';manifest.write_text('\n'.join(lines)+'\n')
   self.command(['run-batch',manifest,'--release','--jobs',str(self.args.jobs),'--fuel-quantum','100000'],digest+'-matches')
  rows=[]
  for m in maps:
   for side in (0,1):
    path=self.folder/'results'/f'{digest}-{label}-{m}-{side}.json'
    if not path.exists():raise RuntimeError('Incomplete match: '+str(path))
    j=json.loads(path.read_text());own=int(j['teams'][side]['submittedGems']);enemy=int(j['teams'][1-side]['submittedGems'])
    faults=sum(j['diagnostics']['botFaults'].values())
    replay=path.with_suffix('.repl26a')
    if not replay.exists():raise RuntimeError('Missing replay/log evidence')
    with zipfile.ZipFile(replay) as archive:
     for name in ['team-a.stdout','team-b.stdout']:
      if name not in archive.namelist():raise RuntimeError('Missing team log')
      faults+=archive.read(name).count(b'bot error:')
    rows.append({'map':m,'side':side,'opponent':label,'won':j['match']['outcome']==('teamA' if side==0 else 'teamB'),'share':own/(own+enemy) if own+enemy else .5,'gems':own,'enemy_gems':enemy,'faults':faults,'rounds':j['match']['roundsStarted'],'fuel_events':sum(len(stream['entries']) for stream in j.get('events',[]) if stream['kind']=='fuelExhausted' and stream['owner'].get('team')==('teamA' if side==0 else 'teamB')),'source':digest})
  return rows
 def ready(self):
  digest=self.state['incumbent'][0]['source'];source=self.folder/'snapshots'/digest
  # Package only the incumbent that passed both validation schedules.
  target=self.folder/'best';self.sync(source,target)
  (self.folder/'ready.pending.zip').unlink(missing_ok=True)
  self.command(['bundle',source,'--output',self.folder/'ready.pending.zip'],'bundle')
  with zipfile.ZipFile(self.folder/'ready.pending.zip') as z:
   expected={p.relative_to(source).as_posix():p.read_bytes() for p in (source/'src').rglob('*') if p.is_file()}
   if set(z.namelist())!=set(expected) or any(z.read(k)!=v for k,v in expected.items()):raise ValueError('Bundle differs from evaluated source')
  (self.folder/'ready.pending.zip').replace(self.folder/'ready.zip')
  train.atomic_json(self.folder/'report.json',{'source':digest,'opponent':self.state['opponent'],'runtime':self.state['runtime'],'release':True,'fuel':100000,'summary':scores(self.state['incumbent']),'rows':self.state['incumbent'],'sweep':scores(self.state['incumbent'])['wins']==34,'reference_summary':scores(self.state['reference_incumbent']),'reference_rows':self.state['reference_incumbent'],'references':self.state['references'],'reference_floor':max(57,scores(self.state['reference_baseline'])['wins'],scores(self.state['reference_incumbent'])['wins']),'note':'Frozen v42 search with v36/v38 guard; not evidence of ladder strength.'})
 def run(self):
  self.command(['build',self.op,'--release'],'opponent-build')
  for n,op in self.refs.items():self.command(['build',op,'--release'],n+'-build')
  if self.state['baseline'] is None:
   rows=self.evaluate({},MAPS)
   if scores(rows)['faults']:raise RuntimeError('Baseline has faults; fix before training')
   self.state['baseline']=rows;self.state['incumbent']=rows;self.save();print('BASELINE',scores(rows),flush=True)
  if self.state['reference_baseline'] is None:
   refs=sum((self.evaluate({},MAPS,n) for n in self.refs),[])
   if not reference_ok(refs):raise RuntimeError('Starting reference baseline failed 57/68 zero-fault gate')
   self.state['reference_baseline']=refs;self.state['reference_incumbent']=refs;self.save()
   print('REFERENCE BASELINE',scores(refs),flush=True)
  self.ready()
  while time.monotonic()<self.deadline and scores(self.state['incumbent'])['wins']<34:
   if not self.state['pending']:
    unsolved=[m for m in MAPS if sum(r['won'] for r in self.state['incumbent'] if r['map']==m)<2]
    rng=random.Random(20261017+self.state['trials']);m=unsolved[self.state['trials']%len(unsolved)];field=rng.choice(list(SPACE));genes=json.loads(json.dumps(self.state['genes']));current=genes.get(m,{}).get(field,self.defaults[m][field]);choices=[v for v in SPACE[field] if not math.isclose(float(v),float(current),abs_tol=1e-6)];genes.setdefault(m,{})[field]=rng.choice(choices)
    if self.state['trials']==0:
     m='lanes';field='near_k';genes={'lanes':{'near_k':6}}
    self.state['pending']={'map':m,'field':field,'genes':genes};self.save()
   trial=self.state['pending'];m=trial['map'];screen=self.evaluate(trial['genes'],[m]);old=[r for r in self.state['incumbent'] if r['map']==m]
   accepted=False;refs=None
   if not scores(screen)['faults'] and scores(screen)['wins']>scores(old)['wins']:
    full=self.evaluate(trial['genes'],MAPS)
    if acceptable(full,self.state['incumbent']):
     refs=sum((self.evaluate(trial['genes'],MAPS,n) for n in self.refs),[])
     floor=max(57,scores(self.state['reference_baseline'])['wins'],scores(self.state['reference_incumbent'])['wins'])
     if reference_ok(refs,floor):
      self.state['genes']=trial['genes'];self.state['incumbent']=full;self.state['reference_incumbent']=refs;self.state['promotions']+=1;accepted=True
   self.state['trials']+=1;self.state['pending']=None;self.save()
   with (self.folder/'trials.jsonl').open('a') as history:
    history.write(json.dumps({'trial':self.state['trials'],'genes':trial['genes'],'screen':screen,'accepted':accepted,'reference':scores(refs) if refs else None,'best':scores(self.state['incumbent'])})+'\n')
   print('TRIAL',self.state['trials'],m,trial['field'],scores(screen),'references',scores(refs) if refs else 'not needed','accepted',accepted,'BEST',scores(self.state['incumbent']),flush=True)
   self.ready()
  if scores(self.state['incumbent'])['wins']==34:self.state['status']='sweep';self.save()
  self.ready()

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--minutes',type=float,default=60);p.add_argument('--jobs',type=int,default=2);p.add_argument('--runtime',default='out/current-runtime');p.add_argument('--run',default='out/t43guard');a=p.parse_args()
 if a.minutes<=0 or a.jobs<1:p.error('Positive minutes/jobs required')
 signal.signal(signal.SIGINT,lambda *_:train.STOP.set())
 folder=(ROOT/a.run).resolve();folder.mkdir(parents=True,exist_ok=True)
 with train.run_lock(folder/'trainer.lock'):
  search=Search(a)
  try:search.run()
  except train.BudgetExpired:
   search.save();print('Session budget reached; rerun the same command to resume.',flush=True)
  finally:print('Current',scores(search.state['incumbent']) if search.state['incumbent'] else 'baseline pending',flush=True)
if __name__=='__main__':main()
