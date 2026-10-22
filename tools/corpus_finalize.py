"""Finish the report after the exhaustive worker batch; all work stays local."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
from corpus_run import ROOT,OUT
from safeio import dump_json

def status(stage,**kwargs):
    dump_json(OUT/'finalize_status.json',dict(stage=stage,**kwargs))

def main():
    status('waiting_for_extraction')
    while True:
        try:
            inventory=json.loads((OUT/'inventory.json').read_text())
            done=json.loads((OUT/'complete.json').read_text())
            if done['total']==inventory['files']:
                if not all(c==0 for c in done['exitcodes']):raise RuntimeError('A corpus worker exited unsuccessfully')
                break
        except (OSError,ValueError,KeyError):pass
        time.sleep(10)
    expected={r['id'] for r in inventory['records']}
    present={p.name[:-8] for p in (OUT/'games').glob('*.json.gz')}
    missing=expected-present
    if missing:raise ValueError(f'{len(missing)} replay files still lack current compressed evidence: '+','.join(sorted(missing)[:20]))
    steps=[('main_report',[sys.executable,'tools/corpus_report.py']),
           ('timing_routes_builds',[sys.executable,'tools/corpus_patterns.py']),
           ('independent_validation',[sys.executable,'tools/corpus_validate.py']),
           ('playbook_package',[sys.executable,'tools/corpus_publish.py'])]
    for label,cmd in steps:
        status(label)
        with (OUT/(label+'.log')).open('w',encoding='utf-8') as log:
            subprocess.run(cmd,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
    status('ready_for_final_review',expected=len(expected))

if __name__=='__main__':
    try:main()
    except Exception:
        status('needs_attention',error=traceback.format_exc())
        raise
