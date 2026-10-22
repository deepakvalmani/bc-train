"""Stable action-name decoding for compact training logs."""
NAMES = ('approach_goals', 'bank_choose', 'bank_fighting', 'bank_giveup', 'break_lock', 'busy', 'capturing', 'cassi_back', 'cg_pre_loop', 'cg_vis', 'contest', 'contest_hold', 'dead', 'fight', 'fight_cast', 'fight_stray', 'fight_tgt', 'finish', 'full', 'hunt', 'hunt_hit', 'idle', 'join', 'join_fight', 'leave_dead', 'leave_to_collector', 'lock_snipe', 'lowhp_fire', 'nav_pre', 'no_target', 'post_choose', 'post_move', 'post_move_atk', 'pre_approach', 'pre_bank', 'pre_choose', 'pre_contest', 'pre_hunt', 'pre_lowhp', 'pre_mtc', 'pre_observe', 'pre_snipe', 'protect_bag', 'pvp', 'pvp_chase', 'pvp_flee', 'pvp_kite', 'recall_hp', 'recall_private', 'recall_shop', 'recalling', 'regroup', 'retreat', 'sequence_retreat', 'shop', 'spawn_heal', 'start', 'stuck', 'stuck_altar', 'stuck_camp', 'support', 'teleport', 'tribute_private', 'tribute_start', 'tributing', 'wait_respawn', 'wait_squad', 'walk_altar', 'walk_camp', 'walk_home', 'walk_launch', 'walk_private')

def code(name):
    value=5381
    for letter in name: value=(value*33+ord(letter)) & 65535
    return value

CODES={str(code(name)):name for name in NAMES}
if len(CODES)!=len(NAMES): raise ValueError("Telemetry action-code collision")

def decode(value):
    if value.startswith("@"):
        if value[1:] not in CODES: raise ValueError("Unknown telemetry action code")
        return CODES[value[1:]]
    return value
