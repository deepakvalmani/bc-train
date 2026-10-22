"""Explain Packs openings and delivery from independently verified replay events.

Usage: python tools/packs_decisions.py --report RUN/LABEL_report.json --out REPORT.json
The report's sibling matches directory must retain the corresponding replays.
Replay observations are for analysis only and are never supplied to a bot.
"""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re
import subprocess
import zipfile

import train

CHAMPIONS = ['Ryth', 'Vesper Vale', 'Vendetta', 'Cassi', 'Issac', 'Stellar',
             'Prism', 'Marcella', 'Willow', 'Ren', 'Varg', 'Tavi']


def summarize_inspection(data, side):
    rounds = data['rounds']
    heroes = {}
    for row in rounds:
        for c in row['champions']:
            if c['team'] == side:
                heroes.setdefault(c['id'], c)
    result = []
    for ident, first in heroes.items():
        samples = [(r['round'], c) for r in rounds for c in r['champions'] if c['id'] == ident]
        acquired = [e for e in data.get('acquisitions', []) if e['id'] == ident]
        delivered = [e for e in data.get('deliveries', []) if e['id'] == ident]
        deaths = [e for e in data['deaths'] if e['id'] == ident]
        purchases = [e for e in data.get('purchases', []) if e['id'] == ident]
        # Round-end sampling flags a stationary carry streak. It does not infer its cause.
        longest = streak = 0
        previous = None
        for round_no, c in samples:
            if (previous and c['alive'] and previous[1]['alive'] and c['gems'] > 0
                    and c['gems'] == previous[1]['gems']
                    and c['position'] == previous[1]['position'] and round_no == previous[0] + 1):
                streak += 1
            else:
                streak = 1 if c['alive'] and c['gems'] > 0 else 0
            longest = max(longest, streak)
            previous = (round_no, c)
        moved = next((n for n, c in samples if c['position'] != first['position']), None)
        result.append(dict(id=ident, champion=CHAMPIONS[first['type']], first_move=moved,
                           first_acquisition=acquired[0]['round'] if acquired else None,
                           first_delivery=delivered[0]['round'] if delivered else None,
                           observed_gems_acquired=sum(e['amount'] for e in acquired),
                           delivered=sum(e['amount'] for e in delivered), deliveries=len(delivered),
                           deaths=len(deaths),
                           unsubmitted_bag_decreases=sum(e['amount'] for e in data['drops']
                               if e['id'] == ident and not e['scoreGain']),
                           first_item_change=purchases[0]['round'] if purchases else None,
                           longest_stationary_carry=longest))
    return dict(terminal=data['terminal'], champions=result,
                opening_acquisitions=[e for e in data.get('acquisitions', []) if e['team'] == side and e['round'] <= 120],
                opening_clears=[e for e in data['clears'] if e['round'] <= 120],
                first_team_delivery=next((e['round'] for e in data['events'] if e['team'] == side), None))


def inspect_report(report_path, out, assets=None):
    report_path = Path(report_path)
    report = json.loads(report_path.read_text())
    if assets is None:
        assets = next((p for p in (Path(os.environ['LOCALAPPDATA']) / 'cambc/assets').glob('*/visualiser/assets')
                       if (p / 'v0_0_1-ctH8uuEb.wasm').exists()), None)
    if assets is None:
        raise ValueError('Supported installed visualiser assets are required')
    matches = []
    for row in report['rows']:
        if row['map'] != 'packs':
            continue
        pattern = f"{report['source']}_*_packs_{row['side']}"
        candidates = list((report_path.parent / 'matches').glob(pattern))
        # Several opponents may share a side: resolve using the exact statistics.
        work = None
        for candidate in candidates:
            stats = candidate / 'statistics.json'
            if not stats.exists():
                continue
            # Cache filename also pins opponent identity; use its row to disambiguate.
            cache = report_path.parent / 'cache' / (candidate.name + '.json')
            if cache.exists() and json.loads(cache.read_text()).get('opponent') == row['opponent']:
                work = candidate
                break
        if work is None:
            raise ValueError('Missing retained match for ' + str(row))
        output = work / 'decisions-inspection.json'
        if not output.exists() or json.loads(output.read_text()).get('schema') != 2:
            with zipfile.ZipFile(next(work.glob('*.repl26a'))) as archive:
                (work / 'replay.raw').write_bytes(archive.read('replay.repl26a'))
            subprocess.run(['node', '--no-warnings', str(train.ROOT / 'tools/inspect_packs_replay.mjs'),
                            str(assets), str(work / 'replay.raw'), str(output)], check=True, timeout=180)
        data = json.loads(output.read_text())
        terminal = data['terminal']
        if (terminal['round'], terminal['gems'][row['side']], terminal['gems'][1-row['side']]) != (row['rounds'], row['gems'], row['enemy_gems']):
            raise ValueError('Replay terminal does not match statistics')
        match = summarize_inspection(data, row['side'])
        if sum(c['delivered'] for c in match['champions']) != row['gems']:
            raise ValueError('Per-champion deliveries do not reconcile with final score')
        # Optional runtime traces establish actual assignments; absence remains unknown.
        trace = work / f"team-{'a' if row['side'] == 0 else 'b'}.stdout"
        actions = Counter()
        assignments = []
        if trace.exists():
            for line in trace.read_text(encoding='utf-8').splitlines():
                m = re.match(r'A r(\d+) (\S+) (\S+) tgt(-?\d+)', line)
                if m:
                    round_no, champion, action, target = m.groups()
                    actions[action] += 1
                    if int(round_no) <= 120:
                        assignments.append(dict(round=int(round_no), champion=champion, action=action, target=int(target)))
        match.update(side=row['side'], opponent=row['opponent'], source=report['source'],
                     faults=row['faults'], enemy_faults=row['enemy_faults'],
                     action_counts=dict(actions), opening_assignments=assignments)
        matches.append(match)
    result = dict(source=report['source'], matches=matches,
                  note='Exact replay events plus round-end movement samples. Unsubmitted bag decreases are not necessarily simultaneous with the death flag. Item changes can include combining or loss; stationary carry alone does not establish a banking fault.')
    train.atomic_json(Path(out), result)
    lines = ['# Packs decision report', '', f"Source: `{report['source']}`", '',
             '| Opponent / side | Champion | First pickup | First delivery | Gems delivered | Deaths | Unsubmitted bag decreases |',
             '|---|---|---:|---:|---:|---:|---:|']
    for match in matches:
        for c in match['champions']:
            lines.append(f"| {match['opponent']} / {match['side']} | {c['champion']} | {c['first_acquisition']} | {c['first_delivery']} | {c['delivered']} | {c['deaths']} | {c['unsubmitted_bag_decreases']} |")
    lines += ['', result['note'], '']
    Path(out).with_suffix('.md').write_text('\n'.join(lines), encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--assets', type=Path)
    args = parser.parse_args()
    inspect_report(args.report, args.out, args.assets)
