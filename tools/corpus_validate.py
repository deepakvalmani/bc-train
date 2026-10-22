"""Cross-check telemetry against the pre-existing independent replay inspector."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import csv
from corpus_report import OUT, ROOT, evidence_files, evidence_id, load_evidence

IDS=['00000b92-283b-4c7c-9289-85b61f74a2ba','06037290-2822-4588-a952-9689490ca2f5','043fd691-3fb8-426f-9c93-85dec65a526d']

def main():
    assets=next(p for p in (Path(os.environ['LOCALAPPDATA'])/'cambc/assets').glob('*/visualiser/assets') if (p/'v0_0_3-zaIi77qe.wasm').exists())
    inv={r['id']:r for r in json.loads((OUT/'inventory.json').read_text())['records']}
    files={evidence_id(p):p for p in evidence_files()}
    refs=OUT/'validation';refs.mkdir(exist_ok=True)
    expected=list(IDS)
    teams=OUT/'teams.csv'
    if teams.exists():
        with teams.open(encoding='utf-8-sig',newline='') as f:
            seller=next((r['id'] for r in csv.DictReader(f) if int(r.get('sales') or 0)>0),None)
        if seller and seller not in expected:expected.append(seller)
    results=[]
    for ident in expected:
        # Main extraction may not yet have reached a chosen validation replay.
        if ident not in files:continue
        d=load_evidence(files[ident]);ref=refs/(ident+'.json')
        if not ref.exists():subprocess.run(['node','--no-warnings',str(ROOT/'tools/inspect_website_replay.mjs'),str(assets),inv[ident]['path'],str(ref)],check=True,cwd=ROOT,timeout=300)
        r=json.loads(ref.read_text())
        checks=dict(source_hash=d['sha256']==inv[ident]['sha256'],terminal_round=d['rounds']==r['terminal']['round'],
                    terminal_score=d['scores']==r['terminal']['gems'],outcome=d['outcome']==r['terminal']['outcome'],
                    deaths=len(d['deaths'])==len(r['deaths']),banks=len(d['banks'])==len(r['deliveries']),
                    purchases=len(d['purchases'])==len(r['purchases']),clears=len(d['clears'])==len(r['clears']))
        for s in [0,1]:
            checks[f'team{s}_delivered']=sum(b['amount'] for b in r['deliveries'] if b['team']==s)==d['scores'][s]
            checks[f'team{s}_acquired']=sum(b['amount'] for b in r['acquisitions'] if b['team']==s)==d['teams'][s]['gemsAcquired']
            checks[f'team{s}_casts']=sum(n for k,n in r['actions'].items() if k.split(':')[0]==str(s) and k.split(':')[-1]=='6')==d['teams'][s]['actions'].get('6',0)
        key=lambda e:(e['round'],e['team'],e['type'],e.get('amount',e.get('carried')))
        checks['bank_events']=sorted(map(key,d['banks']))==sorted(map(key,r['deliveries']))
        checks['death_events']=sorted((x['round'],x['team'],x['type'],x['bag']) for x in d['deaths'])==sorted((x['round'],x['team'],x['type'],x['carried']) for x in r['deaths'])
        checks['purchase_changes']=[(x['round'],x['team'],x['type'],x['goldDelta'],x['delta']) for x in d['purchases']]==[(x['round'],x['team'],x['type'],x['goldAfter']-x['goldBefore'],[a-b for a,b in zip(x['itemsAfter'],x['itemsBefore'])]) for x in r['purchases']]
        results.append(dict(id=ident,map=d['map'],schema=d['schema'],checks=checks,passed=all(checks.values())))
    result=dict(engine_sha256=hashlib.sha256((assets/'v0_0_3-zaIi77qe.wasm').read_bytes()).hexdigest(),
                decoder='official visualiser 0.0.3, timeline ABI 40152',results=results,passed=len(results)==len(expected) and all(r['passed'] for r in results))
    (OUT/'validation.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
