"""Compare two-opponent map policies and verify explicit drafts were executed."""
import argparse
import json
from pathlib import Path
import re

import train


def function_body(text, name):
    match = re.search(r'inline Policy ' + re.escape(name) + r'\(\)\s*\{', text)
    if match is None:
        raise ValueError('Missing map function: ' + name)
    start = match.end()
    depth = 1
    for end in range(start, len(text)):
        if text[end] == '{':
            depth += 1
        elif text[end] == '}':
            depth -= 1
            if depth == 0:
                return text[start:end]
    raise ValueError('Unclosed map policy: ' + name)


def make_report(source, report_path, baseline_path, output):
    report = json.loads(report_path.read_text())
    baseline = json.loads(baseline_path.read_text())
    pin = json.loads((report_path.parent / 'pin.json').read_text())
    inventory = json.loads((train.ROOT / 'docs/maps/policy-inventory.json').read_text())
    if set(report['opponents']) != {'v36-fixed', 'v38-fixed'}:
        raise ValueError('Only the selected v36/v38 comparison is permitted')
    if train.source_hash(source) != report['source']:
        raise ValueError('Report source mismatch')
    text = (source / 'src/map_policies.h').read_text()
    rows = []
    for name, facts in inventory.items():
        body = function_body(text, name.replace('-', '_'))
        explicit = 'p.explicit_draft=true' in body
        expected = None
        if explicit:
            match = re.search(r'p\.draft=\{([^}]+)\}', body)
            expected = [int(x) for x in match[1].split(',')][:facts['team_size']]
        cases = [r for r in report['rows'] if r['map'] == name]
        actual_cases = {(r['opponent'], r['side']) for r in cases}
        if len(cases) != 4 or actual_cases != {(op, side) for op in report['opponents'] for side in (0, 1)}:
            raise ValueError('Incomplete or duplicated schedule: ' + name)
        for case in cases:
            if case['faults'] or case['enemy_faults']:
                raise ValueError('Faulted case: ' + name)
            key = f"{report['source']}_{pin['sources'][case['opponent']]}_{name}_{case['side']}"
            stats = json.loads((report_path.parent / 'matches' / key / 'statistics.json').read_text())
            if expected is not None and stats['teams'][case['side']]['draftPicks'] != expected:
                raise ValueError('Explicit draft was not executed: ' + key)
        before, after = baseline['maps'][name], report['maps'][name]
        rows.append(dict(map=name, previous_wins=before['points']*4,
                         wins=after['points']*4, share=after['share'], rate=after['rate'],
                         deaths=after['deaths'], verified_explicit_draft=expected))
    result = dict(source=report['source'], games=report['games'],
                  wins=report['summary']['points']*report['games'],
                  previous_wins=baseline['summary']['points']*baseline['games'], maps=rows,
                  opponents=report['opponents'], fault_free=True)
    train.atomic_json(output, result)
    lines = ['# v42 map policy comparison', '',
             '| Map | Previous wins / 4 | New wins / 4 | Gem share | Deaths |',
             '|---|---:|---:|---:|---:|']
    for row in rows:
        lines.append(f"| {row['map']} | {row['previous_wins']:g} | {row['wins']:g} | {row['share']:.2%} | {row['deaths']:.2f} |")
    output.with_suffix('.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    make_report(args.source, args.report, args.baseline, args.out)
