"""Survey all physical champion designs in fuel-bounded local SDK batches."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import train

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();folder=args.out.resolve();folder.mkdir(parents=True,exist_ok=False)
    batches=[]
    for first in range(0,12,2):
        batch=folder/f'batch-{first}'
        subprocess.run([sys.executable,str(train.ROOT/'tools/study_packs.py'),'--out',str(batch),
                        '--first',str(first),'--last',str(first+2)],cwd=train.ROOT,check=True)
        batches.append(json.loads((batch/'inventory.json').read_text()))
    # Compare geometry/rewards too: never merge observations of different maps.
    for batch in batches:
        if batch['map_sha256']!=batches[0]['map_sha256'] or batch['sdk']!=batches[0]['sdk']:
            raise ValueError('Map/SDK changed during survey')
        for side in (0,1):
            geometry={k:v for k,v in batch['observations'][side].items() if k!='champions'}
            expected={k:v for k,v in batches[0]['observations'][side].items() if k!='champions'}
            if geometry!=expected:raise ValueError('Map observations disagree')
    result=json.loads(json.dumps(batches[0]))
    result['source']='batched SDK design survey';result['sources']=[b['source'] for b in batches]
    for side in (0,1):result['observations'][side]['champions']=[c for b in batches for c in b['observations'][side]['champions']]
    if result['observations'][0]['champions']!=result['observations'][1]['champions']:
        raise ValueError('Champion designs disagree between sides')
    train.atomic_json(folder/'inventory.json',result)
    print('Verified all 12 physical designs and all packs groups from both sides')

if __name__=='__main__':main()
