"""Narrow, reversible migration of unqualified handbook vision checkpoints."""
import json
import tempfile
from pathlib import Path
import train


TARGET_CATCH = '''} catch (const cambc::error& failure) {
    // Movement or a fuel suspension can invalidate a previously visible target.
    // Abandon this observation only; other API failures remain visible to the runner.
    if (failure.code() != cambc::error_code::api_not_in_vision) throw;
    target_killable = false;
    return nullptr;
}'''
FIRE_CATCH = '''} catch (const cambc::error& failure) {
    if (failure.code() != cambc::error_code::api_not_in_vision) throw;
    return false;
}'''


def vision_source(text, reverse=False):
    changes = [
        ('Bot::pick_target(int range) {', 'Bot::pick_target(int range) try {'),
        ('    return tgt;\n}', '    return tgt;\n' + TARGET_CATCH),
        ('Bot::fire_at(const cambc::champion& tgt) {',
         'Bot::fire_at(const cambc::champion& tgt) try {'),
        ('    return acted;\n}', '    return acted;\n' + FIRE_CATCH),
    ]
    if reverse:
        changes = [(after, before) for before, after in changes]
    for before, after in changes:
        if text.count(before) != 1:
            raise ValueError('Unknown handbook vision source; use a new --run directory')
        text = text.replace(before, after, 1)
    return text


def migrate(trainer, seed, upgrade_from=None):
    state_path = trainer.folder / 'state.json'
    if not state_path.exists():
        return False
    previous = json.loads(state_path.read_text())
    source = train.ROOT / trainer.config['start']
    contract = train.source_hash(source)
    if previous.get('policy_contract') == contract:
        return False
    if (previous.get('incumbent_validation') or previous.get('policy_cycle')
            or previous.get('pending') or previous.get('trials', 0)
            or previous.get('promotions', 0) or previous.get('policy_cycles', 0)
            or previous['config'] != trainer.config):
        raise ValueError('Vision migration requires an unchanged, unqualified run with no learning trials; use a new --run')
    # Prove this is exactly the known source fix, not a general contract bypass.
    with tempfile.TemporaryDirectory(prefix='vision_contract_', dir=trainer.folder) as directory:
        path = Path(directory)
        train.copy_source(source, path)
        bot = path / 'src/bot.cpp'
        bot.write_text(vision_source(bot.read_text(), reverse=True))
        if train.source_hash(path) != previous.get('policy_contract'):
            raise ValueError('Other handbook source changes detected; use a new --run directory')
    # Check runtime, configuration and checkpoint identities before changing state.
    trainer.load(seed, upgrade_from)
    roles = ('teacher', 'incumbent', 'anchors', 'holdouts', 'champions', 'exploiters')
    digests = set()
    for role in roles:
        value = trainer.state.get(role, [])
        digests.update([value] if isinstance(value, str) else value)
    mapping = {}
    for digest in sorted(digests):
        original = trainer.checkpoints / digest
        if train.source_hash(original) != digest:
            raise ValueError('Changed checkpoint: ' + digest)
        if not (original / 'src/handbook.h').exists():
            continue
        with tempfile.TemporaryDirectory(prefix='vision_checkpoint_', dir=trainer.folder) as directory:
            path = Path(directory)
            train.copy_source(original, path)
            bot = path / 'src/bot.cpp'
            bot.write_text(vision_source(bot.read_text()))
            mapping[digest] = trainer.snapshot(path)
    if not mapping:
        raise ValueError('No matching handbook checkpoint to repair')
    backup = trainer.folder / ('state.before-vision-' + previous['policy_contract'] + '.json')
    if not backup.exists():
        train.atomic_json(backup, previous)
    for role in roles:
        if role in trainer.state:
            value = trainer.state[role]
            trainer.state[role] = (mapping.get(value, value) if isinstance(value, str)
                                  else list(dict.fromkeys(mapping.get(d, d) for d in value)))
    trainer.state['policy_contract'] = contract
    trainer.state.setdefault('source_migrations', []).append(dict(
        repair='handbook_vision_v1', old_contract=previous['policy_contract'],
        new_contract=contract, checkpoints=mapping,
        reason='Drop observations invalidated by movement/fuel suspension; preserve other API failures'))
    trainer.save()
    print('[REPAIR] Replaced stale handbook vision checkpoint. Existing checkpoints and cached games preserved; changed sources will be retested.', flush=True)
    return True
