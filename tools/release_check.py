"""Pinned, resumable release comparisons without changing an active trainer."""
import argparse
import concurrent.futures as futures
import hashlib
import json
import os
from pathlib import Path
import time
import train


def runtime_signature(config):
    digest=hashlib.sha256(train.ENGINE.read_bytes())
    for path in [train.ROOT/'cambc.toml',*sorted((train.ROOT/'sdk/cpp').rglob('*'))]:
        if path.is_file(): digest.update(path.read_bytes())
    for name in dict.fromkeys(config['train_maps']+config['validation_maps']):
        digest.update((train.ROOT/'maps'/(name+'.map26a')).read_bytes())
    return digest.hexdigest()


class ReleaseCheck:
    def __init__(self, folder, manifest, jobs=2, keep_artifacts=False):
        self.folder=Path(folder).resolve(); self.folder.mkdir(parents=True,exist_ok=True)
        self.manifest=manifest; self.jobs=jobs; self.built=set(); self.keep_artifacts=keep_artifacts
        self.deadline=time.monotonic()+4*3600
        self.config=json.loads((train.ROOT/'tools/train_handbook_config.json').read_text())
        self.runtime=runtime_signature(self.config)
        self.sources={name:Path(path).resolve() for name,path in manifest['sources'].items()}
        self.hashes={name:train.source_hash(path) for name,path in self.sources.items()}
        pin=dict(runtime=self.runtime,sources=self.hashes,maps=manifest['maps'])
        record=self.folder/'pin.json'
        if record.exists() and json.loads(record.read_text())!=pin:
            raise ValueError('Release inputs changed; use a separate comparison directory')
        train.atomic_json(record,pin)
        for name in ('cache','logs','matches'): (self.folder/name).mkdir(exist_ok=True)

    def build(self,label):
        if label in self.built: return
        if train.source_hash(self.sources[label])!=self.hashes[label]: raise ValueError('Source changed: '+label)
        # Compile one file at a time while another training process may be active.
        os.environ['CMAKE_BUILD_PARALLEL_LEVEL']='1'
        train.command([train.ENGINE,'build',self.sources[label]],self.deadline,self.folder/'logs'/(label+'_build.log'))
        self.built.add(label)

    def cache_path(self,label,opponent,map_name,side):
        return self.folder/'cache'/f'{self.hashes[label]}_{self.hashes[opponent]}_{map_name}_{side}.json'

    def import_cache(self,label,opponent,run):
        run=Path(run); state=json.loads((run/'state.json').read_text())
        if state['runtime']!=self.runtime: raise ValueError('Old results use a different runtime')
        for name in self.manifest['maps']:
            for side in (0,1):
                source=run/'cache'/self.cache_path(label,opponent,name,side).name
                if source.exists():
                    row=json.loads(source.read_text())
                    row.update(opponent=opponent,source='accepted-run cache')
                    train.atomic_json(self.cache_path(label,opponent,name,side),row)

    def play(self,label,opponent,map_name,side):
        cache=self.cache_path(label,opponent,map_name,side)
        if cache.exists(): return json.loads(cache.read_text())
        key=cache.stem; work=self.folder/'matches'/key; work.mkdir(parents=True,exist_ok=True)
        a,b=self.sources[label],self.sources[opponent]
        if side: a,b=b,a
        stats=work/'statistics.json'
        log=self.folder/'logs'/(key+'.log')
        for attempt in range(3):
            stats.unlink(missing_ok=True)
            try:
                train.command([train.ENGINE,'run',a,b,'--map',train.ROOT/'maps'/(map_name+'.map26a'),
                               '--fuel','100000','--statistics',stats,'--out-dir',work],
                              self.deadline,log)
                break
            except RuntimeError:
                if attempt==2 or 'Access is denied' not in log.read_text(encoding='utf-8'):
                    raise
        row=train.parse_stats(json.loads(stats.read_text()),side,self.config['competition_rules'])
        for team,field in [(side,'faults'),(1-side,'enemy_faults')]:
            output=train.bot_stdout(work,team)
            if output is None:
                row[field]+=1
            else:
                row[field]+=output.count('bot error:')
                if 'bot error:' in output:
                    (self.folder/'logs'/f'{key}_side{team}.stdout').write_text(output,encoding='utf-8')
        row.update(map=map_name,side=side,opponent=opponent)
        train.atomic_json(cache,row)
        if self.keep_artifacts:
            for side in (0,1):
                output=train.bot_stdout(work,side)
                if output is not None:(work/f'team-{"a" if side==0 else "b"}.stdout').write_text(output,encoding='utf-8')
        else:
            for path in work.iterdir():
                if path.is_file() and path.name!='statistics.json': path.unlink()
        return row

    def evaluate(self,label,opponents,maps):
        for name in dict.fromkeys([label,*opponents]): self.build(name)
        cases=[(label,op,m,side) for op in opponents for m in maps for side in (0,1)]
        print(f'Checking {label}: {len(cases)} games, {len(maps)} maps, both sides',flush=True)
        rows=[]; last=time.monotonic()
        with futures.ThreadPoolExecutor(max_workers=self.jobs) as pool:
            pending=[pool.submit(self.play,*case) for case in cases]
            for future in futures.as_completed(pending):
                rows.append(future.result()); now=time.monotonic()
                if now-last>=10 or len(rows)==len(cases):
                    print(f'  {len(rows)}/{len(cases)} complete',flush=True);last=now
        rows.sort(key=lambda r:(r['opponent'],r['map'],r['side']))
        report=dict(source=self.hashes[label],games=len(rows),summary=train.summarize(rows),
                    fault_free=not any(r['faults'] for r in rows),
                    opponents_fault_free=not any(r['enemy_faults'] for r in rows),
                    opponents={op:train.summarize([r for r in rows if r['opponent']==op]) for op in opponents},
                    maps={m:train.summarize([r for r in rows if r['map']==m]) for m in maps},rows=rows)
        train.atomic_json(self.folder/(label+'_report.json'),report)
        print(label,json.dumps({k:v for k,v in report.items() if k not in ('rows','maps')}),flush=True)
        return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--folder',type=Path,required=True)
    parser.add_argument('--labels',required=True)
    parser.add_argument('--opponents',default='v36-fixed,v38-fixed')
    parser.add_argument('--maps',default='')
    parser.add_argument('--jobs',type=int,default=2)
    parser.add_argument('--keep-artifacts',action='store_true',help='Retain replays and stdout for diagnosis')
    parser.add_argument('--import-baseline',type=Path)
    args=parser.parse_args()
    manifest=json.loads(args.manifest.read_text());check=ReleaseCheck(args.folder,manifest,args.jobs,args.keep_artifacts)
    opponents=args.opponents.split(',')
    if args.import_baseline:
        for opponent in opponents: check.import_cache('accepted',opponent,args.import_baseline)
    maps=args.maps.split(',') if args.maps else manifest['maps']
    for label in args.labels.split(','): check.evaluate(label,opponents,maps)


if __name__=='__main__': main()
