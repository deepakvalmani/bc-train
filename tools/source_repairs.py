"""Versioned, narrow repairs applied to new copies, never archived checkpoints."""
from pathlib import Path


def repair_movement(bot):
    path = Path(bot) / 'src' / 'bot.cpp'
    data = path.read_bytes()
    text = data.decode('utf-8').replace('\r\n', '\n')
    if '// Navigation liveness v2' in text:
        return
    marker = 'bool move_towards_closest(cambc::bitboard goals) {'
    if text.count(marker) != 1:
        raise ValueError('Unknown movement source; refusing automatic repair')
    start = text.index(marker)
    end = text.index('// Static navigation:', start)
    if 'if constexpr (economy::mobility)' in text[start:end]:
        repair_navigation_liveness(path)
        return  # Current learner already contains movement and dash exploration.
    replacement = '''bool move_towards_closest(cambc::bitboard goals) {
    auto& me = cambc::self();
    if (!me.can_move() || goals.is_set(me.position())) return false;
    const auto blocked = blocked_tiles();
    goals &= ~blocked | cambc::vision::camp_tiles();
    if (goals.is_empty()) return false;
    cambc::distance_field field;
    cambc::bitboard visited;
    field.compute_to(blocked & ~goals, goals, tiles_around(me.position(), 0), visited);
    const auto origin = me.position();
    std::array<std::pair<int, vec2>, 8> choices;
    int n = 0;
    for (auto tile : blocked.reachable_tiles(origin, 1).positions())
        if (field.get(tile) < field.get(origin)) choices[n++] = {field.get(tile), tile};
    std::sort(choices.begin(), choices.begin()+n,
              [](const auto& a, const auto& b) { return a.first < b.first; });
    for (int i=0; i<n && me.can_move(); ++i) {
        if (blocked_tiles().is_set(choices[i].second)) continue;
        try { if (me.move_absolute(choices[i].second)) return true; }
        catch (const cambc::error&) {}
    }
    return false;
}

'''
    text = text[:start] + replacement + text[end:]
    path.write_bytes(text.replace('\n', '\r\n').encode('utf-8') if b'\r\n' in data else text.encode('utf-8'))
    repair_navigation_liveness(path)


def repair_navigation_liveness(path):
    """Fuel suspension can resume a route after death or displacement."""
    data = Path(path).read_bytes()
    text = data.decode('utf-8').replace('\r\n', '\n')
    if '// Navigation liveness v2' in text:
        return
    replacements = [
        ('b.set(cambc::self().position(), false);',
         '// Navigation liveness v2: a suspended calculation may resume after death.\n    const auto position = cambc::self().position();\n    if (position.x >= 0 && position.y >= 0 && position.x < b.width() && position.y < b.height())\n        b.set(position, false);'),
        ('if (!me.can_move() || goals.is_set(me.position())) return false;',
         'if (!me.is_alive() || !me.can_move()) return false;\n    const auto origin = me.position();\n    if (origin.x < 0 || origin.y < 0 || origin.x >= goals.width() || origin.y >= goals.height()) return false;\n    if (goals.is_set(origin)) return false;\n    const auto planning_round = cambc::round_number();'),
        ('field.compute_to(blocked & ~goals, goals, tiles_around(me.position(), 0), visited);\n    const auto origin = me.position();',
         'field.compute_to(blocked & ~goals, goals, tiles_around(origin, 0), visited);\n    // The saved field and occupancy belong to the turn and position that started this search.\n    if (cambc::round_number() != planning_round || !me.is_alive() || me.position() != origin) return false;'),
        ('for (int i=0; i<n && me.can_move(); ++i) {',
         'for (int i=0; i<n && me.can_move(); ++i) {\n        if (cambc::round_number() != planning_round || !me.is_alive() || me.position() != origin) return false;'),
    ]
    for before, after in replacements:
        if text.count(before) != 1:
            raise ValueError('Unknown navigation liveness source; refusing automatic repair')
        text = text.replace(before, after)
    Path(path).write_bytes(text.replace('\n','\r\n').encode() if b'\r\n' in data else text.encode())
