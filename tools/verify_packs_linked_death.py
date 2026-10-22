"""Controlled linked-death check: Cassi fights wolves while Issac stays at spawn.

The fixture intentionally resigns and is not a competitive evaluation.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import zipfile

import train


def verify(data):
    deaths = [d for d in data['deaths'] if d['team'] == 0]
    if len(deaths) != 2 or {d['type'] for d in deaths} != {3, 4}:
        raise ValueError('Expected exactly one linked pair death')
    if deaths[0]['round'] != deaths[1]['round'] or deaths[0]['input'] != deaths[1]['input']:
        raise ValueError('Pair did not die at the same engine input')
    issac = next(d for d in deaths if d['type'] == 4)
    if issac['healthBefore'] != 900 or issac['position'] != dict(x=1, y=0):
        raise ValueError('Partner was not at full health in the controlled spawn position')
    return dict(passed=True, deaths=deaths,
                note='Cassi exposed to wolves; Issac at full health at spawn. Intentional resignation is not a competitive result.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    root = args.out.resolve()
    (root / 'src').mkdir(parents=True, exist_ok=False)
    shutil.copy2(train.ROOT / 'tools/fixtures/packs_linked_death.cpp', root / 'src/main.cpp')
    deadline = time.monotonic() + 600
    train.command([train.ENGINE, 'build', root], deadline, root / 'build.log')
    work = root / 'match'
    work.mkdir()
    train.command([train.ENGINE, 'run', root, train.ROOT / 'bots/idle', '--map',
                   train.ROOT / 'maps/packs.map26a', '--fuel', '100000', '--statistics',
                   root / 'statistics.json', '--out-dir', work], deadline, root / 'match.log')
    output = train.bot_stdout(work, 0)
    if output is None or 'LAB_ERROR' in output:
        raise ValueError('Fixture failed or log is missing')
    stats = train.parse_stats(json.loads((root / 'statistics.json').read_text()), 0,
                            json.loads((train.ROOT / 'tools/train_handbook_config.json').read_text())['competition_rules'])
    if stats['faults'] or stats['enemy_faults']:
        raise ValueError('Engine fault invalidates the fixture')
    with zipfile.ZipFile(next(work.glob('*.repl26a'))) as archive:
        (work / 'replay.raw').write_bytes(archive.read('replay.repl26a'))
    assets = next(p for p in (Path(os.environ['LOCALAPPDATA']) / 'cambc/assets').glob('*/visualiser/assets')
                  if (p / 'v0_0_1-ctH8uuEb.wasm').exists())
    subprocess.run(['node', '--no-warnings', str(train.ROOT / 'tools/inspect_packs_replay.mjs'),
                    str(assets), str(work / 'replay.raw'), str(work / 'inspection.json')], check=True, timeout=180)
    train.atomic_json(root / 'result.json', verify(json.loads((work / 'inspection.json').read_text())))


if __name__ == '__main__':
    main()
