"""Frozen, matched Packs-only team experiments; no automatic promotion."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil

import train
from release_check import ReleaseCheck


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError('Unsupported source contract: ' + old)
    return text.replace(old, new)


def configure(source, label):
    path = source / 'src/bot.cpp'
    text = path.read_text(encoding='utf-8')
    if label == 'capture-split':
        text = replace_once(text, 'if (SPLIT_CAPTURE && best >= 0)',
                            'if ((SPLIT_CAPTURE || champion_maps::packs_map()) && best >= 0)')
    elif label == 'observed-finish':
        old = 'carried += (int)(ALLY_BAG_ESTIMATE * unseen * (int)gems);'
        text = replace_once(text, old, 'if (!champion_maps::packs_map()) ' + old)
    elif label == 'early-power':
        text = replace_once(text, 'std::min(3, CUSTOM_EMBLEM_COUNT)',
                            'std::min(champion_maps::packs_map() ? 1 : 3, CUSTOM_EMBLEM_COUNT)')
    elif label in ('pair-safe', 'pair-bold'):
        config = source / 'src/champion_maps.h'
        config.write_text(replace_once(config.read_text(), 'pair_health()<0.45f',
                          'pair_health()<' + ('0.60f' if label == 'pair-safe' else '0.35f')))
    elif label == 'cassi-engage':
        text = replace_once(text, 'if (CASSI_KEEP_RANGE && me.champion_name()',
                            'if (CASSI_KEEP_RANGE && !champion_maps::packs_map() && me.champion_name()')
    elif label == 'supported-engage':
        text = replace_once(text, 'if (exposed && retreat_from_danger(6))',
                            'if (exposed && (!champion_maps::packs_map() || friends <= foes || me.health() < me.max_health()*0.60f) && retreat_from_danger(6))')
    elif label in ('teacher-settings', 'teacher-combat'):
        teacher = train.ROOT / 'bots/v41/src'
        shutil.copy2(teacher / 'sequence_weights.h', source / 'src/sequence_weights.h')
        if label == 'teacher-settings':
            params = (teacher / 'params.h').read_text()
            params += '\nconstexpr int DRAFT_CORNERS[] = {9,0,4,3,10,2,7,6,1,8,5};\n'
            (source / 'src/params.h').write_text(params)
    else:
        raise ValueError('Unknown experiment ' + label)
    path.write_text(text, encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, default=train.ROOT / 'bots/v42')
    parser.add_argument('--opponents-manifest', type=Path, required=True)
    parser.add_argument('--opponents', default='v36-fixed,v38-fixed')
    parser.add_argument('--labels', default='capture-split,observed-finish,early-power')
    parser.add_argument('--jobs', type=int, default=2, choices=[1, 2])
    args = parser.parse_args()
    root = args.out.resolve()
    root.mkdir(parents=True, exist_ok=False)
    opponents = args.opponents.split(',')
    sources = json.loads(args.opponents_manifest.read_text())['sources']
    sources = {name: sources[name] for name in opponents}
    for label in args.labels.split(','):
        target = root / label
        train.copy_source(args.baseline, target)
        configure(target, label)
        sources[label] = str(target)
    manifest = dict(sources=sources, maps=['packs'], parent=train.source_hash(args.baseline))
    train.atomic_json(root / 'manifest.json', manifest)
    check = ReleaseCheck(root / 'evaluation', manifest, args.jobs, keep_artifacts=True)
    # Independent source trees can compile together; each compiler uses one worker.
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        list(pool.map(check.build, sources))
    for label in args.labels.split(','):
        check.evaluate(label, opponents, ['packs'])


if __name__ == '__main__':
    main()
