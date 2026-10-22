"""Bundle exact validated v42 source and verify every archived byte.

Requires a full-pool, two-sided ReleaseCheck report for this exact source.
Creates a source ZIP for manual competition upload; it never submits online.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import time
import zipfile

import train
from release_check import runtime_signature


def qualification(source, report_path):
    source = Path(source).resolve()
    report_path = Path(report_path).resolve()
    report = json.loads(report_path.read_text())
    pin = json.loads((report_path.parent / 'pin.json').read_text())
    digest = train.source_hash(source)
    config = json.loads((train.ROOT / 'tools/train_handbook_config.json').read_text())
    maps = set(config['train_maps'] + config['validation_maps'])
    if digest != report['source'] or digest not in pin['sources'].values():
        raise ValueError('Qualification source does not match the archive source')
    if pin['runtime'] != runtime_signature(config) or set(pin['maps']) != maps:
        raise ValueError('Qualification runtime or full map pool differs')
    opponents = set(report['opponents'])
    if len(opponents) < 2:
        raise ValueError('Require at least two qualification opponents')
    expected = {(op, m, side) for op in opponents for m in maps for side in (0, 1)}
    actual = [(r['opponent'], r['map'], r['side']) for r in report['rows']]
    if len(actual) != len(expected) or set(actual) != expected or report['games'] != len(expected):
        raise ValueError('Incomplete or duplicated map/side/opponent schedule')
    if any(r['faults'] or r['enemy_faults'] for r in report['rows']):
        raise ValueError('Faulted qualification games cannot qualify an archive')
    if not report['fault_free'] or not report['opponents_fault_free']:
        raise ValueError('Qualification report contains faults')
    # Check the actual build configuration, not prose or release notes.
    flags = (source / 'src/champion_maps_config.h').read_text()
    policy = (source / 'src/policy_weights.h').read_text()
    params = (source / 'src/params.h').read_text()
    requirements = [(flags, r'CHAMPION_MAPS_TRACE\s*=\s*false'),
                    (flags, r'CHAMPION_MAPS_SINGLE_GROUP\s*=\s*-1\s*;'),
                    (flags, r'CHAMPION_MAPS_LAB_ACTOR\s*=\s*-1\s*;'),
                    (flags, r'CHAMPION_MAPS_LAB_COMPANION\s*=\s*-1\s*;'),
                    (params, r'\bTRACE\s*=\s*false'),
                    (policy, r'\benabled\s*=\s*false'),
                    (policy, r'\btelemetry\s*=\s*false'),
                    (policy, r'\baudit\s*=\s*false'),
                    (policy, r'\bexploration\s*=\s*0(?:\.0*)?f\s*;')]
    if not all(re.search(pattern, text) for text, pattern in requirements):
        raise ValueError('Submission source still enables experimental execution or diagnostics')
    return report, pin, digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=train.ROOT / 'bots/v42')
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--runtime-root', type=Path, help='Isolated SDK/map workspace used for qualification')
    parser.add_argument('--engine', type=Path, help='Exact toolkit executable used for qualification')
    args = parser.parse_args()
    if bool(args.runtime_root) != bool(args.engine):
        parser.error('--runtime-root and --engine must be supplied together')
    if args.runtime_root:
        train.ROOT = args.runtime_root.resolve()
        train.ENGINE = args.engine.resolve()
    report, pin, digest = qualification(args.source, args.report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(args.output.stem + '.pending.zip')
    train.command([train.ENGINE, 'bundle', args.source.resolve(), '--output', temporary.resolve()],
                  time.monotonic() + 300, args.output.with_suffix('.bundle.log'))
    files = {p.relative_to(args.source).as_posix(): p.read_bytes()
             for p in (args.source / 'src').rglob('*') if p.is_file()}
    with zipfile.ZipFile(temporary) as archive:
        if archive.testzip() or set(archive.namelist()) != set(files):
            raise ValueError('Archive contents differ from the validated source')
        if any(archive.read(name) != data for name, data in files.items()):
            raise ValueError('Archive source bytes differ')
    if temporary.stat().st_size >= 4_000_000:
        raise ValueError('Archive exceeds the stated 4,000,000-byte upload cap')
    if train.source_hash(args.source) != digest:
        raise ValueError('Source changed while bundling')
    temporary.replace(args.output)
    manifest = dict(version='v42', source=digest, source_path=str(args.source.resolve()),
                    archive=str(args.output.resolve()), archive_bytes=args.output.stat().st_size,
                    archive_sha256=hashlib.sha256(args.output.read_bytes()).hexdigest(),
                    expanded_source_bytes=sum(map(len, files.values())), files=len(files),
                    runtime=pin['runtime'], qualification_report=str(args.report.resolve()),
                    games=report['games'], summary=report['summary'], opponents=report['opponents'],
                    maps=report['maps'], fuel=100000, shared_memory_bytes=8, draft_memory_bytes=1024,
                    note='Local full-pool qualification; legal fuel suspensions are not asserted absent. No online submission performed.')
    train.atomic_json(args.output.with_suffix('.json'), manifest)
    print(json.dumps({k: manifest[k] for k in ['archive', 'archive_bytes', 'archive_sha256', 'source', 'games']}, indent=2))


if __name__ == '__main__':
    main()
