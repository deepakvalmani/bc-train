"""Run resumable exhaustive offline extraction using independent engine processes."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import zipfile
import random

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'out/replay_corpus'
SOURCE = ROOT / 'game_summaries/replays-2026-10-18-part1'
EXPECTED = set()

def done_count():
    return len(EXPECTED & {p.name.split('.json')[0] for p in (OUT/'games').glob('*.json*') if p.name.endswith(('.json','.json.gz'))})

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    files_by_id = {p.stem:p for p in sorted(SOURCE.rglob('*.repl26a'))}
    records_by_id = {}
    archives = []
    # Hash archive contents in one pass: opening thousands of OneDrive-backed
    # raw files just for inventory is substantially slower.
    for archive in [SOURCE.with_suffix('.zip')]:
        with zipfile.ZipFile(archive) as z:
            infos=[i for i in z.infolist() if i.filename.endswith('.repl26a')]
            archives.append(dict(file=archive.name,replays=len(infos),missing_extracted=[]))
            for info in infos:
                if not info.filename.endswith('.repl26a'):continue
                ident=Path(info.filename).stem
                b=z.read(info)  # zipfile verifies CRC
                current=files_by_id.get(ident)
                if current is None or current.stat().st_size!=info.file_size:
                    current=OUT/'inputs'/f'{ident}.repl26a'
                    current.parent.mkdir(parents=True,exist_ok=True)
                    if not current.exists() or current.stat().st_size!=len(b):current.write_bytes(b)
                    files_by_id[ident]=current
                digest=hashlib.sha256(b).hexdigest()
                if ident in records_by_id and records_by_id[ident]['sha256']!=digest:
                    raise ValueError('Conflicting replay ID across archives: '+ident)
                records_by_id[ident]=dict(path=str(current.relative_to(ROOT)),id=ident,size=len(b),sha256=digest)
    files = sorted(files_by_id.values())
    assets = next(p for p in (Path(os.environ['LOCALAPPDATA']) / 'cambc/assets').glob('*/visualiser/assets')
                  if (p / 'v0_0_3-zaIi77qe.wasm').exists())
    for p in files:
        if p.stem in records_by_id:continue
        b = p.read_bytes()
        records_by_id[p.stem]=dict(path=str(p.relative_to(ROOT)), id=p.stem, size=len(b), sha256=hashlib.sha256(b).hexdigest())
    records=sorted(records_by_id.values(),key=lambda r:r['id'])
    EXPECTED.update(r['id'] for r in records)
    for p in (ROOT / 'game_summaries').glob('*'):
        if p.suffix == '.crdownload':
            archives.append(dict(file=p.name, size=p.stat().st_size, incomplete=True))
    inventory = dict(files=len(files), unique_hashes=len({r['sha256'] for r in records}), records=records, archives=archives)
    (OUT / 'inventory.json').write_text(json.dumps(inventory, indent=2), encoding='utf-8')
    jobs = 6
    bins = [[] for _ in range(jobs)]
    totals = [0]*jobs
    for r in sorted(records, key=lambda r: -r['size']):
        n = totals.index(min(totals))
        bins[n].append(r['path'])
        totals[n] += r['size']
    processes = []
    for n, batch in enumerate(bins):
        random.Random(20261020+n).shuffle(batch)
        manifest = OUT / f'manifest_{n}.json'
        manifest.write_text(json.dumps(batch), encoding='utf-8')
        log = (OUT / f'worker_{n}.log').open('w', encoding='utf-8')
        proc = subprocess.Popen(['node', '--no-warnings', str(ROOT/'tools/corpus_extract.mjs'), str(assets), str(manifest), str(OUT/'games')],
                                cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        processes.append((proc, log))
    started = time.time()
    while any(p.poll() is None for p, _ in processes):
        done = done_count()
        status = dict(done=done,total=len(files),elapsed_seconds=round(time.time()-started),pids=[p.pid for p,_ in processes if p.poll() is None])
        (OUT/'progress.json').write_text(json.dumps(status),encoding='utf-8')
        time.sleep(10)
    for p, log in processes:
        log.close()
    (OUT/'complete.json').write_text(json.dumps(dict(done=done_count(),total=len(files),elapsed_seconds=round(time.time()-started),exitcodes=[p.returncode for p,_ in processes])),encoding='utf-8')

if __name__ == '__main__':
    main()
