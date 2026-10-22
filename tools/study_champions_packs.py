"""Run bounded per-champion packs studies against idle, with immutable sources."""
import argparse
import concurrent.futures
import json
from pathlib import Path
import subprocess
import sys
import train

CHAMPIONS=['pair','ryth','vesper_vale','vendetta','stellar','prism','marcella','willow','ren','varg','tavi']

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--champions',default=','.join(CHAMPIONS))
    parser.add_argument('--groups',default='2')
    parser.add_argument('--jobs',type=int,default=2,choices=[1,2])
    parser.add_argument('--rounds',type=int,default=600)
    parser.add_argument('--controls',action='store_true')
    args=parser.parse_args()
    champions=args.champions.split(',');groups=[int(x) for x in args.groups.split(',')]
    if any(c not in CHAMPIONS for c in champions) or any(g not in range(8) for g in groups):
        parser.error('Unknown champion or group')
    folder=args.out.resolve();folder.mkdir(parents=True,exist_ok=False)
    source=folder/'source';train.copy_source(train.ROOT/'bots/champion-maps',source)
    train.atomic_json(folder/'pin.json',dict(source=train.source_hash(source),champions=champions,groups=groups))
    tasks=[(c,g,control) for c in champions for g in groups for control in ([False,True] if args.controls else [False])]
    def run(task):
        champion,group,control=task
        label=f'{champion}-group{group}'+('-control' if control else '')
        work=folder/label
        command=[sys.executable,str(train.ROOT/'tools/study_pair_packs.py'),'--source',str(source),
                 '--champion',champion,'--group',str(group),'--out',str(work),'--rounds',str(args.rounds)]
        if control:command+=['--control']
        with (folder/(label+'.log')).open('w',encoding='utf-8') as log:
            result=subprocess.run(command,cwd=train.ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=1000)
        report=work/'report.json'
        row=dict(champion=champion,group=group,control=control,passed=result.returncode==0,
                 report=json.loads(report.read_text()) if report.exists() else None)
        print(label,'PASS' if row['passed'] else 'FAIL',flush=True)
        return row
    rows=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        for result in pool.map(run,tasks):
            rows.append(result);train.atomic_json(folder/'report.json',rows)
    if not all(row['passed'] for row in rows):raise SystemExit('Some studies failed; inspect report.json and logs')

if __name__=='__main__':main()
