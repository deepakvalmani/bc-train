"""Read one local map's metadata through the SDK, from immutable survey sources."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time
import train


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--map',default='packs')
    parser.add_argument('--out',type=Path)
    parser.add_argument('--first',type=int,default=0)
    parser.add_argument('--last',type=int,default=2)
    parser.add_argument('--no-rows',action='store_true')
    args=parser.parse_args()
    map_file=train.ROOT/'maps'/(args.map+'.map26a')
    if not map_file.is_file():raise ValueError('Map does not exist: '+str(map_file))
    folder=(args.out or (train.ROOT/'out/map-studies'/args.map)).resolve();folder.mkdir(parents=True,exist_ok=True)
    snapshot=folder/'prepared'
    if snapshot.exists():raise ValueError('Use a fresh survey directory')
    train.copy_source(train.ROOT/'bots/packs-lab',snapshot)
    config=snapshot/'src/lab_config.h'
    config.write_text(config.read_text().replace('SURVEY_FIRST=0',f'SURVEY_FIRST={args.first}').replace('SURVEY_LAST=2',f'SURVEY_LAST={args.last}').replace('SURVEY_ROWS=true',f'SURVEY_ROWS={str(not args.no_rows).lower()}'))
    digest=train.source_hash(snapshot)
    os.environ['CMAKE_BUILD_PARALLEL_LEVEL']='1'
    deadline=time.monotonic()+600
    train.command([train.ENGINE,'build',snapshot],deadline,folder/'build.log')
    observations=[]
    for side in (0,1):
        work=folder/('survey-side-'+str(side));work.mkdir(exist_ok=True)
        bots=[snapshot,train.ROOT/'bots/idle']
        if side:bots.reverse()
        train.command([train.ENGINE,'run',*bots,'--map',map_file,
                       '--fuel','100000','--out-dir',work],deadline,folder/('side-'+str(side)+'.log'))
        output=train.bot_stdout(work,side)
        if output is None or 'LAB_ERROR' in output:raise ValueError('Survey failed: '+str(work))
        heads=[json.loads(line.removeprefix('MAPHEAD ')) for line in output.splitlines() if line.startswith('MAPHEAD ')]
        rows=[json.loads(line.removeprefix('MAPROW ')) for line in output.splitlines() if line.startswith('MAPROW ')]
        groups=[json.loads(line.removeprefix('MAPGROUP ')) for line in output.splitlines() if line.startswith('MAPGROUP ')]
        if len(heads)!=1 or (not args.no_rows and len(rows)!=heads[0]['height']):raise ValueError('Expected one complete SDK map observation')
        champions=[json.loads(line.removeprefix('CHAMPDATA ')) for line in output.splitlines() if line.startswith('CHAMPDATA ')]
        if len(champions)!=args.last-args.first:raise ValueError('Missing requested champion designs')
        observations.append(dict(side=side,champions=champions,rows=[r['value'] for r in sorted(rows,key=lambda r:r['y'])],groups=groups,**heads[0]))
    report=dict(map=args.map,map_sha256=hashlib.sha256(map_file.read_bytes()).hexdigest(),
        source=digest,sdk=(train.ROOT/'cambc.toml').read_text().strip(),observations=observations,
        note='Survey intentionally resigns. These are metadata observations, not competitive results.')
    train.atomic_json(folder/'inventory.json',report)
    print(json.dumps({k:v for k,v in report.items() if k!='observations'},indent=2))
    print('Verified',len(observations[0]['groups']),'groups and',len(observations[0]['champions']),'champion designs from both sides')


if __name__=='__main__':main()
