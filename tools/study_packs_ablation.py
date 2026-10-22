"""Matched packs profile/route comparisons with retained offline replay evidence."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import zipfile
import train
from release_check import ReleaseCheck


def inspect(folder,report,assets):
    for row in report['rows']:
        work=next((folder/'matches').glob(f'{report["source"]}_*_packs_{row["side"]}'))
        output=work/'inspection.json'
        if not output.exists():
            with zipfile.ZipFile(next(work.glob('*.repl26a'))) as archive:
                (work/'replay.raw').write_bytes(archive.read('replay.repl26a'))
            subprocess.run(['node','--no-warnings',str(train.ROOT/'tools/inspect_packs_replay.mjs'),
                            str(assets),str(work/'replay.raw'),str(output)],check=True,timeout=120)
        terminal=json.loads(output.read_text())['terminal'];side=row['side']
        if (terminal['round'],terminal['gems'][side],terminal['gems'][1-side])!=(row['rounds'],row['gems'],row['enemy_gems']):
            raise ValueError('Decoded replay disagrees with final statistics')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--routes',action='store_true')
    parser.add_argument('--jobs',type=int,default=2,choices=[1,2])
    parser.add_argument('--assets',type=Path)
    args=parser.parse_args();root=args.out.resolve();root.mkdir(parents=True,exist_ok=False)
    assets=args.assets
    if assets is None:
        candidates=list((Path(os.environ['LOCALAPPDATA'])/'cambc/assets').glob('*/visualiser/assets'))
        assets=next((p for p in candidates if (p/'v0_0_1-ctH8uuEb.wasm').exists()),None)
    if assets is None:raise ValueError('Supported local visualiser assets not found; pass --assets')
    sources={}
    for label,profile in [('baseline',None),('stellar',5),('tavi',11),('combined',-1)]:
        source=root/label;train.copy_source(train.ROOT/'bots/champion-maps',source)
        config=source/'src/champion_maps_config.h';text=config.read_text()
        text=re.sub(r'CHAMPION_MAPS_EXTENDED=(true|false)',f'CHAMPION_MAPS_EXTENDED={"true" if profile is not None else "false"}',text)
        text=re.sub(r'CHAMPION_MAPS_PROFILE=-?\d+',f'CHAMPION_MAPS_PROFILE={profile if profile is not None else -1}',text)
        text=re.sub(r'CHAMPION_MAPS_BANK_ROUTE=(true|false)',f'CHAMPION_MAPS_BANK_ROUTE={"true" if args.routes else "false"}',text)
        config.write_text(text);sources[label]=str(source)
    sources['v36']=str(train.ROOT/'bots/v36')
    manifest=dict(sources=sources,maps=['packs']);train.atomic_json(root/'manifest.json',manifest)
    check=ReleaseCheck(root/'results',manifest,args.jobs,keep_artifacts=True)
    for label in ('baseline','stellar','tavi','combined'):
        report=check.evaluate(label,['v36'],['packs']);inspect(root/'results',report,assets)

if __name__=='__main__':main()
