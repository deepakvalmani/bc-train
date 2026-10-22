#include <cmath>
#include <limits>
// v12: squads sized to each camp's danger, full ability use, persistent camp HP, altar locks
// (break theirs, drop ours), plus: gem hunting, lock-sniping enemy tributes, contesting
// captures, private (walled-in) altars via teleport crystal, walking-distance targeting
// with a draft-memory plan, and wards on our target.
#include <cambc.h>
#include "bot.h"
#include "params.h"
#include "policy.h"
#include "sequence_weights.h"
#include "economy.h"
#include "champion_maps.h"
#include "packs_actions.h"
#include "map_strategy.h"
#include <algorithm>
#include <array>
#include <cstdint>
#include <iostream>
#include <span>
#include <variant>
#include <type_traits>

using cambc::vec2;
using cambc::team;

const char* g_stage = "";   // last checkpoint reached this turn (printed on errors)
namespace {

int dist(vec2 a, vec2 b) { return (int)a.chebyshev_distance(b); }

std::vector<vec2> g_altars;      // altars we can walk next to
std::vector<int> g_tile_group;   // map tile -> camp group index (or -1)
int g_w = 0, g_range = 1;
cambc::bitboard g_danger; bool g_have_danger = false;   // tiles around boss-strength camps (never path or fight there)
bool g_replay_repairs=false;
std::unique_ptr<cambc::bitboard> g_enemy_spawn; // cached: never waste a PvP turn on spawn recovery
cambc::bitboard g_static_walls;  // terrain we can never stand on

int group_at(vec2 p) {
    if (p.x < 0 || p.y < 0 || p.x >= g_w || p.y * g_w + p.x >= (int)g_tile_group.size()) return -1;
    return g_tile_group[p.y * g_w + p.x];
}

cambc::bitboard tiles_around(vec2 p, int r) {
    cambc::bitboard t; t.clear(); t.draw_chebyshev(p, r); return t;
}

cambc::bitboard g_camp_spawns; bool g_block_camps = false;   // every camp position; blocked on bank walks
cambc::bitboard blocked_tiles() {
    auto b = cambc::map::walls() | cambc::map::holes() | cambc::map::altars()
        | cambc::map::spawn_region(team::enemy) | cambc::vision::champion_tiles()
        | cambc::vision::camp_tiles() | cambc::vision::teleport_tiles();
    if (g_block_camps) b |= g_camp_spawns;
    if (DANGER_BLOCK && g_have_danger && !g_danger.is_set(cambc::self().position())) b |= g_danger;   // inside the zone: walk out freely
    // Navigation liveness v2: a suspended calculation may resume after death.
    const auto position = cambc::self().position();
    if (position.x >= 0 && position.y >= 0 && position.x < b.width() && position.y < b.height())
        b.set(position, false);
    return b;
}

int g_mtc_dist = -1;   // walking distance to the goals measured by the last move_towards_closest (-1: none)
bool move_towards_closest(cambc::bitboard goals) {
    auto& me = cambc::self();
    if (!me.is_alive() || !me.can_move()) return false;
    const auto origin = me.position();
    if (origin.x < 0 || origin.y < 0 || origin.x >= goals.width() || origin.y >= goals.height()) return false;
    if (goals.is_set(origin)) return false;
    const auto planning_round = cambc::round_number();
    const auto blocked = blocked_tiles();
    goals &= ~blocked | cambc::vision::camp_tiles();
    if (goals.is_empty()) return false;
    cambc::distance_field field;
    cambc::bitboard visited;
    field.compute_to(blocked & ~goals, goals, tiles_around(origin, 0), visited);
    g_mtc_dist = field.get(origin);
    // The saved field and occupancy belong to the turn and position that started this search.
    if (cambc::round_number() != planning_round || !me.is_alive() || me.position() != origin) return false;
    if constexpr (economy::mobility) if (me.can_cast() && cambc::fuel_remaining()>35000) {
        for (auto& ability : me.abilities()) {
            if (!ability.is_dash() || !ability.is_ready()) continue;
            vec2 destination=origin; double gain=1.0/economy::DASH_VALUE_W;
            for (auto tile : ability.valid_tiles().positions()) {
                if (tile.chebyshev_distance(origin)>2 || blocked_tiles().is_set(tile)) continue;
                const double saving=(double)field.get(origin)-field.get(tile)-1;
                if (saving>gain) { gain=saving; destination=tile; }
            }
            if (destination!=origin) {
                try { if (ability.use(destination)) return true; }
                catch (const cambc::error&) {}
                if constexpr (learned::telemetry) ++policy::failed_actions;
            }
        }
    }
    std::array<std::pair<int, vec2>, 8> choices;
    int n = 0;
    for (auto tile : blocked.reachable_tiles(origin, 1).positions())
        if (field.get(tile) < field.get(origin)) choices[n++] = {field.get(tile), tile};
    std::sort(choices.begin(), choices.begin()+n,
              [](const auto& a, const auto& b) { return a.first < b.first; });
    for (int i=0; i<n && me.can_move(); ++i) {
        if (cambc::round_number() != planning_round || !me.is_alive() || me.position() != origin) return false;
        if (blocked_tiles().is_set(choices[i].second)) continue;
        try { if (me.move_absolute(choices[i].second)) return true; }
        catch (const cambc::error&) { if constexpr (learned::telemetry) ++policy::failed_actions; }
    }
    return false;
}

// Static navigation: one full distance field per destination over fixed terrain, built once
// (at most one per round) and exported, so each later step is 8 local lookups, not a fresh search.
std::unordered_map<int, std::vector<std::uint16_t>> g_nav;
// Cached fields everywhere (STATIC_NAV) or only on big maps, where a fresh search per step blows the fuel budget.
bool nav_on() {
    static const bool big = cambc::map::width() * cambc::map::height() >= NAV_BIG_AREA;
    return STATIC_NAV || (NAV_BIG && big);
}
const std::vector<std::uint16_t>* nav_get(int key) {
    auto it = g_nav.find(key);
    return it == g_nav.end() ? nullptr : &it->second;
}
const std::vector<std::uint16_t>* nav_build(int key, const cambc::bitboard& goals) {
    static int built_round = -1;
    const int r = (int)cambc::round_number();
    if (built_round == r || cambc::fuel_remaining() < NAV_BUILD_FUEL) return nullptr;
    built_round = r;
    try {
        cambc::distance_field f;
        cambc::bitboard visited;
        f.compute(g_static_walls & ~goals, goals, visited);
        std::vector<std::uint16_t> v((size_t)goals.width() * goals.height());
        f.export_linear_buffer(std::span<std::uint16_t>{v});
        return &(g_nav[key] = std::move(v));
    } catch (const std::exception&) { return nullptr; }
}
int nav_at(const std::vector<std::uint16_t>& f, vec2 p) {
    if (p.x < 0 || p.y < 0 || p.x >= g_w || p.y * g_w + p.x >= (int)f.size()) return 65535;
    return f[p.y * g_w + p.x];
}
// Step to the best neighbour that is strictly closer; units in the way -> try the next one.
bool step_by_field(const std::vector<std::uint16_t>& f) {
    auto& me = cambc::self();
    if (!me.can_move()) return false;
    const vec2 pos = me.position();
    const int here = nav_at(f, pos);
    if (here == 0 || here == 65535) return false;
    std::array<std::pair<int, vec2>, 8> c;
    int n = 0;
    for (int dy = -1; dy <= 1; ++dy)
        for (int dx = -1; dx <= 1; ++dx) {
            if (!dx && !dy) continue;
            const vec2 q{pos.x + dx, pos.y + dy};
            const int v = nav_at(f, q);
            if (v < here) c[n++] = {v, q};
        }
    std::sort(c.begin(), c.begin() + n, [](const auto& a, const auto& b) { return a.first < b.first; });
    for (int k = 0; k < n; ++k) {
        try { if (me.move_absolute(c[k].second)) return true; } catch (const std::exception&) {}
    }
    return false;
}

// One engine read per visible camp per turn (repeated host queries were blowing the fuel budget).
struct CampView {
    cambc::camp c;
    vec2 pos, spawn;
    float hp, max_hp, str;
    int group;
};
std::vector<CampView> g_cv;
std::vector<cambc::champion> g_enemies, g_allies;   // visible champions, read once per turn
std::vector<cambc::map::camp_group> g_groups;   // cached once; identities are static

// Bitboard tests are engine calls: export once, then test bits locally (row-major, LSB first).
struct LinBits {
    std::vector<std::uint8_t> b;
    int w = 0, h = 0;
    void load(const cambc::bitboard& bb) { b = bb.export_linear_buffer(); w = bb.width(); h = bb.height(); }
    bool test(vec2 p) const {
        if (p.x < 0 || p.y < 0 || p.x >= w || p.y >= h) return false;
        const int i = p.y * w + p.x;
        return (b[i >> 3] >> (i & 7)) & 1;
    }
};
LinBits g_vis;   // this champion's visible tiles, this turn

int group_at(vec2 p);
// Moving our ward drops whatever only the old ward could see; any later query on those units
// throws "Unit is not in vision" and ended the turn. Drop them from this turn's snapshot.
void refresh_vision() {
    auto gone = [](const auto& u) { try { if (!u.is_visible()) return true; (void)u.position(); return false; } catch (const std::exception&) { return true; } };
    std::erase_if(g_allies, gone);
    std::erase_if(g_enemies, gone);
    std::erase_if(g_cv, [&](const CampView& v) { return gone(v.c); });
    if (LOCAL_BITS) g_vis.load(cambc::vision::visible_tiles());
}
void snapshot_camps() {
    if (LOCAL_BITS) g_vis.load(cambc::vision::visible_tiles());
    g_enemies = cambc::vision::champions(team::enemy);
    g_allies = cambc::vision::champions(team::ally);
    // Dead allies stay in the list but any query on them throws ("Unit is not in vision") and
    // ended the whole turn (~10 lost turns per game, 86 in 10 ladder games): keep only live, visible ones.
    std::erase_if(g_allies, [](const cambc::champion& a) {
        try { if (!a.is_visible() || !a.is_alive()) return true; (void)a.position(); (void)a.health(); return false; }
        catch (const std::exception&) { return true; }
    });
    g_cv.clear();
    for (const auto& c : cambc::vision::camps()) {
        try {
            if (!c.is_visible()) continue;
            const vec2 sp = c.spawn_position();
            g_cv.push_back(CampView{c, c.position(), sp, c.health(), c.max_health(), c.strength(), group_at(sp)});
        } catch (const std::exception&) {}
    }
    g_have_danger = false;
    if (DANGER_STR > 0)
        for (const auto& v : g_cv)
            if (v.str >= DANGER_STR && v.hp > 0 && dist(cambc::self().position(), v.pos) <= 12) {
                if (!g_have_danger) { g_danger.clear(); g_have_danger = true; }
                g_danger.draw_chebyshev(v.pos, DANGER_R);
            }
}
// TRACE profiling: fuel left at named checkpoints of a turn.
std::array<std::pair<const char*, int>, 16> g_prof; int g_np = 0;
inline void PROF(const char* n) { g_stage = n; if (TRACE && g_np < 16) g_prof[g_np++] = {n, (int)cambc::fuel_remaining()}; }
// Chebyshev distance to our nearest spawn tile (spawn heals; recall lands there).
int home_dist(vec2 p) {
    static std::vector<vec2> tiles;
    if (tiles.empty())
        for (auto t : cambc::map::spawn_region(team::ally).positions()) tiles.push_back(t);
    int d = 1 << 20;
    for (auto t : tiles) d = std::min(d, dist(p, t));
    return d;
}

// Cheap spawn test (spawn tiles are near our start; recomputed lazily once).
bool at_spawn_hint(vec2 p) {
    static LinBits sp; static bool ready = false;
    if (!ready) { sp.load(cambc::map::spawn_region(team::ally)); ready = true; }
    return sp.test(p);
}


// Lanchester square law: (our hp x our dps) / (their hp x their dps). Above 1 we win the exchange.
// Counts only visible units (allies do not share vision), so it errs on the cautious side.
double g_lanch = 99.0;   // last ratio computed this turn
int g_lanch_foes = 0;
double champ_dps(const cambc::champion& c) {
    try { return std::max(1.0, (double)c.strength() + LANCH_FOCUS_W * (double)c.focus()); }
    catch (const std::exception&) { return 1.0; }
}
double lanchester(vec2 centre, int foe_r, int ally_r, int& foes_out) {
    auto& me = cambc::self();
    const vec2 pos = me.position();
    double a_hp = me.health(), a_dps = std::max(1.0, (double)me.strength() + LANCH_FOCUS_W * (double)me.focus());
    double f_hp = 0, f_dps = 0;
    foes_out = 0;
    for (const auto& e : g_enemies) {
        try {
            if (!e.is_visible() || !e.is_alive() || dist(centre, e.position()) > foe_r) continue;
            f_hp += e.health(); f_dps += champ_dps(e); ++foes_out;
        } catch (const std::exception&) {}
    }
    if (foes_out == 0) return 99.0;
    for (const auto& a : g_allies) {
        try {
            if (a.position() == pos || dist(centre, a.position()) > ally_r) continue;
            a_hp += a.health(); a_dps += champ_dps(a);
        } catch (const std::exception&) {}
    }
    return (a_hp * a_dps) / std::max(1.0, f_hp * f_dps);
}

bool cv_in_reach(const CampView& v) {
    return v.hp > 0 && dist(cambc::self().position(), v.pos) <= g_range;
}

template<class T>
bool in_reach(const T& u) {
    return u.is_visible() && u.health() > 0 && dist(cambc::self().position(), u.position()) <= g_range;
}

unsigned gems_of(const cambc::champion& c) {
    try { return c.gem_count(); } catch (const std::exception&) { return 0; }
}

bool enemy_locked(vec2 altar) {
    if (!cambc::vision::has_altar_lock(altar)) return false;
    try { return cambc::vision::altar_lock_at(altar).is_enemy(); } catch (const std::exception&) { return true; }
}

}  // namespace

// Start-up spread over several turns. On a 92-camp map camp_groups() costs ~60k fuel and building the group list ~70k more,
// more than one turn (~97k) allows; a turn cut off mid-init left team_dps/team_n unset and the bot idled all game
// (week-2 maps big-world / islands). Each stage runs only with enough fuel left and the stage counter persists.
void Bot::init_static() {
    auto& me_init = cambc::self();
    (void)me_init;
    if (init_stage == 0) {
    // Camps are scored by WALKING distance on maps up to 80x80 (week-2 solo scans: corridors 329->578 gems, fracture 305->513,
    // gold-rush 452->706, eight 568->863, elk-arena 216->1008); on 100x100 maps the path searches cost too much fuel.
    map_path_distance=map_strategy::policy().path_distance || (int)cambc::map::width() * (int)cambc::map::height() <= 6400;
    const auto selected_map=map_strategy::current_map();
    g_replay_repairs=selected_map==map_policies::Map::ambush || selected_map==map_policies::Map::rushbait_v2;
    if(g_replay_repairs)g_enemy_spawn=std::make_unique<cambc::bitboard>(cambc::map::spawn_region(team::enemy));
    auto& me = cambc::self();
    g_range = me.attack_range();
    g_w = cambc::map::width();
    g_static_walls = cambc::map::walls() | cambc::map::holes() | cambc::map::altars()
        | cambc::map::spawn_region(team::enemy);

    // Corners retains its measured opening; its startup never exhausted fuel.
    const bool open_altars=selected_map!=map_policies::Map::corners
        && std::uint8_t(cambc::draft_memory[1016])==0xA9
        && std::uint8_t(cambc::draft_memory[1017])==1;
    if(open_altars) {
        g_altars=cambc::map::altars().positions();
    } else {
    // Walkable area from our spawn. Altars outside it are walled in (teleport only).
    cambc::distance_field home;
    cambc::bitboard reach;
    home.compute(g_static_walls, cambc::map::spawn_region(team::ally), reach);
    LinBits reachable_tiles;
    std::vector<std::uint16_t> home_distances;
    for (auto a : cambc::map::altars().positions()) {
        const auto near = tiles_around(a, cambc::constants::submit_gems_range) & reach;
        if (!near.is_empty()) { g_altars.push_back(a); continue; }
        if (!TELEPORT) continue;
        // Plan a crystal hop: launch from a walkable tile, land within 3 tiles inside the pocket.
        PrivateAltar pa;
        pa.altar = a;
        cambc::distance_field pocket;
        const auto roots = tiles_around(a, cambc::constants::submit_gems_range) & ~g_static_walls;
        if (roots.is_empty()) continue;
        pocket.compute(g_static_walls, roots, pa.inside);
        // Pocket-hop planning repeatedly queried the same immutable boards.
        // Export lazily: ordinary maps with no private altar pay no export cost.
        if(reachable_tiles.w==0) {
            reachable_tiles.load(reach);
            home_distances.resize((size_t)g_w*cambc::map::height());
            home.export_linear_buffer(std::span<std::uint16_t>{home_distances});
        }
        int best = 1 << 30;
        for (auto t : pa.inside.positions()) {
            const int dt = pocket.get(t);
            if (dt > 6) continue;
            for (int dx = -3; dx <= 3; ++dx) for (int dy = -3; dy <= 3; ++dy) {
                const vec2 l{t.x + dx, t.y + dy};
                if (!reachable_tiles.test(l)) continue;
                const int cost = home_distances[l.y*g_w+l.x] + 4 * dt;
                if (cost < best) { best = cost; pa.launch = l; pa.land = t; }
            }
        }
        if (best < (1 << 30)) privates.push_back(pa);
    }
    if (g_altars.empty()) g_altars = cambc::map::altars().positions();

    }

    g_tile_group.assign((size_t)g_w * cambc::map::height(), -1);
    g_camp_spawns.clear();
    init_stage = 1;
    }   // end of stage 0
    if (init_stage == 1) {
        if (cambc::fuel_remaining() < 85000) return;   // camp_groups() needs ~60k on a big map: wait for a fresh turn
        g_groups = cambc::map::camp_groups();
        info.clear(); info_next = 0; init_stage = 2;
        if (cambc::fuel_remaining() < 120000) return;   // big maps (camp_groups ~60k, then the group loop): continue next turn. Small maps carry on in the same turn.
    }
    if (init_stage == 2) {
        for (; info_next < g_groups.size(); ++info_next) {
            if (cambc::fuel_remaining() < 18000) return;   // continue next turn
            const auto& g = g_groups[info_next];
        GroupInfo gi;
        gi.gems = g.gem_value();
        gi.gold = g.gold_value();
        for (const auto& c : g.camps()) {
            const auto bs = c.base_stats();
            gi.hp += bs.base_health; gi.dmg += bs.base_strength;
            gi.member_hp.push_back(bs.base_health);
            const vec2 p = c.spawn_position();
            gi.tiles.push_back(p);
            g_tile_group[p.y * g_w + p.x] = (int)info.size();
        }
            info.push_back(std::move(gi));
        }
    ready_round.assign(info.size(), 0);
    if(g_replay_repairs)camp_avoid_until.assign(info.size(), 0);
    hp_left.resize(info.size());
    member_left.resize(info.size());
    gfield.resize(info.size());
    for (size_t i = 0; i < info.size(); ++i) { hp_left[i] = info[i].hp; member_left[i] = info[i].member_hp; }
        // Camp groups with no walking route from our spawn (islands, fracture, big-world: the bot used to pick the straight-line
        // nearest camp across water and stand "stuck_camp" at spawn all game). One BFS from spawn marks them; they are never chosen.
        {
            cambc::distance_field hf; cambc::bitboard rch;
            hf.compute(g_static_walls, cambc::map::spawn_region(team::ally), rch);
            unreach_grp.assign(info.size(), 0);
            for (size_t gi = 0; gi < info.size(); ++gi) {
                bool any = false;
                for (auto tp : info[gi].tiles) {
                    for (int dx = -1; dx <= 1 && !any; ++dx) for (int dy = -1; dy <= 1 && !any; ++dy) {
                        const vec2 q{tp.x + dx, tp.y + dy};
                        if (q.x < 0 || q.y < 0 || q.x >= cambc::map::width() || q.y >= cambc::map::height()) continue;
                        if (hf.get(q) != 65535) any = true;
                    }
                    if (any) break;
                }
                unreach_grp[gi] = any ? 0 : 1;
            }
        }
        init_stage = 3;
        if (cambc::fuel_remaining() < 15000) return;
    }
    auto& me = cambc::self();
    team_dps = 0; team_hp = 0;

    // Draft memory: walking distance from spawn to every group, computed with draft fuel.
    if (DRAFT_MEMORY) {
        try {
            const auto& mem = cambc::draft_memory;
            if (mem.size() >= 4 && std::to_integer<int>(mem[0]) == 0xB7 && std::to_integer<int>(mem[1]) == 1) {
                const std::size_t n = std::to_integer<std::size_t>(mem[2]) | (std::to_integer<std::size_t>(mem[3]) << 8);
                if (n == info.size() && mem.size() >= 4 + 2 * n) {
                    spawn_dist.resize(n);
                    for (std::size_t i = 0; i < n; ++i)
                        spawn_dist[i] = std::uint16_t(std::to_integer<int>(mem[4 + 2 * i]) | (std::to_integer<int>(mem[5 + 2 * i]) << 8));
                }
            }
        } catch (const std::exception&) {}
    }

    // Slot = rank of our champion type among allies: identical on every ally, no collisions.
    std::vector<int> types;
    for (const auto& c : cambc::champions(team::ally)) {
        types.push_back((int)c.champion_name());
        try {
            const auto bs = c.base_stats();
            team_dps += bs.base_strength; team_hp += bs.base_health;
        } catch (...) {}
    }
    std::sort(types.begin(), types.end());
    slot = (int)(std::find(types.begin(), types.end(), (int)me.champion_name()) - types.begin()) % 6;
    team_n = std::max<int>(1, (int)types.size());
    team_has_tank = false;
    for (int t : types) if (t == (int)cambc::champion_type::ryth || t == (int)cambc::champion_type::varg || t == (int)cambc::champion_type::marcella) team_has_tank = true;
    team_dps = std::max<double>(team_dps, me.strength());
    team_hp = std::max<double>(team_hp, me.max_health());
    if (TEAMFIGHT) {
        bool stunner = false;
        for (auto& a : me.abilities()) if (a.is_cc()) stunner = true;
        try { me.set_priority(stunner ? 2 : 1); } catch (const std::exception&) {}
    }
    initialised = true;
}

// Walking distance from `from` to a group (cached per group; a few new fields per turn at most).
int Bot::walk_dist(int i, vec2 from) {
    int cheb = 1 << 20;
    for (auto p : info[i].tiles) cheb = std::min(cheb, dist(from, p));
    if (!PATH_DIST && !map_path_distance) return cheb;
    if (!gfield[i]) {
        static int built_round = -1, built = 0;
        const int r = (int)cambc::round_number();
        if (r != built_round) { built_round = r; built = 0; }
        if (built >= 1 || cambc::fuel_remaining() < PATH_BUILD_FUEL) {
            // Not cached yet: at spawn the draft plan already knows the answer.
            if (!spawn_dist.empty() && cambc::map::spawn_region(team::ally).is_set(from) && spawn_dist[i] != 65535)
                return std::max<int>(cheb, spawn_dist[i]);
            return cheb;
        }
        ++built;
        cambc::bitboard roots; roots.clear();
        for (auto p : info[i].tiles) roots.set(p);
        cambc::bitboard visited;
        gfield[i] = std::make_unique<cambc::distance_field>();
        gfield[i]->compute(g_static_walls & ~roots, roots, visited);
    }
    const int d = gfield[i]->get(from);
    return d == 65535 ? -1 : std::max(cheb, d);   // -1: unreachable on foot
}

void Bot::buy_items() {
    auto& me = cambc::self();
    auto purchase = [&](auto item, unsigned count=1) {
        const unsigned before = me.gold_count();
        if constexpr (std::is_same_v<decltype(item), cambc::consumable_type>) me.buy(item);
        else me.buy(item,count);
        if constexpr (learned::telemetry) policy::shop_spent += before-me.gold_count();
    };
    try {
        if (OWN_LOCKS || LOCK_SNIPE) {
            const auto lock = cambc::consumable_type::altar_lock;
            if (me.consumables()[lock].count() == 0 && me.gold_count() >= lock.cost() && me.can_buy(lock))
                purchase(lock);
        }
        if (TELEPORT && !privates.empty()) {
            const auto tp = cambc::consumable_type::tp_crystal;
            if (me.consumables()[tp].count() == 0 && me.gold_count() >= tp.cost() && me.can_buy(tp))
                purchase(tp);
        }
    } catch (const std::exception&) {}
    using it = cambc::item_type;
    using ct = cambc::champion_type;
    const auto who = me.champion_name();
    if (!SMART_SHOP) {
        // Willow heals off Focus; everyone else wins on Strength (basic attacks dominate DPS).
        auto item = who == ct::willow ? it::power_shard_of_focus : it::power_shard_of_strength;
        unsigned n = me.gold_count() / item.cost();
        if (n && me.can_buy(item, n)) purchase(item, n);
        return;
    }
    if (MIMIC_SHOP) {   // Nyx build order (25 games): Treasure emblem FIRST (+20% gold, bought round ~50), then Jungle/Bruiser/Durability emblems, then every coin into Power shards
        try {
            const bool focus_main = who == ct::stellar || who == ct::cassi || who == ct::ren || who == ct::prism || who == ct::tavi || who == ct::willow;
            std::vector<std::pair<it, it>> plan;
            if (who == ct::stellar || who == ct::cassi || who == ct::prism || who == ct::tavi)
                plan = {{it::treasure_shard_of_focus, it::treasure_emblem_of_focus}, {it::jungle_shard_of_focus, it::jungle_emblem_of_focus},
                        {it::durability_shard_of_focus, it::durability_emblem_of_focus}, {it::bruiser_shard_of_health, it::bruiser_emblem_of_health}};
            else if (who == ct::issac)
                plan = {{it::treasure_shard_of_strength, it::treasure_emblem_of_strength}, {it::durability_shard_of_health, it::durability_emblem_of_health}};
            else if (who == ct::ren || who == ct::ryth)
                plan = {{it::treasure_shard_of_health, it::treasure_emblem_of_health}, {it::bruiser_shard_of_health, it::bruiser_emblem_of_health},
                        {it::durability_shard_of_health, it::durability_emblem_of_health}};
            else if (who == ct::varg)
                plan = {{it::treasure_shard_of_health, it::treasure_emblem_of_health}, {it::jungle_shard_of_health, it::jungle_emblem_of_health},
                        {it::durability_shard_of_health, it::durability_emblem_of_health}};
            else if (who == ct::vendetta)
                plan = {{it::jungle_shard_of_strength, it::jungle_emblem_of_strength}, {it::treasure_shard_of_strength, it::treasure_emblem_of_strength},
                        {it::durability_shard_of_strength, it::durability_emblem_of_strength}, {it::bruiser_shard_of_health, it::bruiser_emblem_of_health}};
            else
                plan = {{it::treasure_shard_of_strength, it::treasure_emblem_of_strength}, {it::monster_shard_of_strength, it::monster_emblem_of_strength}};
            // Intercontinental Fish build (50 replays, 21 Oct): emblems in this order, then every coin into Power shards.
            bool fish = true;
            if (who == ct::stellar || who == ct::heart_of_ruin || who == ct::prism)
                plan = {{it::treasure_shard_of_focus, it::treasure_emblem_of_focus}, {it::home_shard_of_health, it::home_emblem_of_health},
                        {it::durability_shard_of_health, it::durability_emblem_of_health}};
            else if (who == ct::ren)
                plan = {{it::bruiser_shard_of_health, it::bruiser_emblem_of_health}, {it::durability_shard_of_health, it::durability_emblem_of_health}};
            else if (who == ct::ryth)
                plan = {{it::bruiser_shard_of_health, it::bruiser_emblem_of_health}, {it::durability_shard_of_health, it::durability_emblem_of_health}};
            else if (who == ct::issac)
                plan = {{it::treasure_shard_of_strength, it::treasure_emblem_of_strength}, {it::home_shard_of_health, it::home_emblem_of_health},
                        {it::durability_shard_of_health, it::durability_emblem_of_health}};
            else if (who == ct::cassi)
                plan = {{it::durability_shard_of_focus, it::durability_emblem_of_focus}, {it::bruiser_shard_of_health, it::bruiser_emblem_of_health}};
            else fish = false;
            const bool fish_focus = who == ct::stellar || who == ct::heart_of_ruin || who == ct::prism || who == ct::ren || who == ct::cassi;
            if (!fish && HOME_FIRST_MIMIC) {   // recall 3 turns instead of 5: at under 20% HP we died 79% of the time (top teams 39-52%)
                const it hs = focus_main ? it::home_shard_of_focus : (who == ct::ren || who == ct::ryth || who == ct::varg) ? it::home_shard_of_health : it::home_shard_of_strength;
                const it he = focus_main ? it::home_emblem_of_focus : (who == ct::ren || who == ct::ryth || who == ct::varg) ? it::home_emblem_of_health : it::home_emblem_of_strength;
                plan.insert(plan.begin(), {hs, he});
            }
            for (const auto& [shard, emblem] : plan) {
                if (me.item_count()[emblem] > 0) continue;
                const unsigned have = me.item_count()[shard];
                const unsigned n = std::min<unsigned>(have < 5 ? 5 - have : 0, me.gold_count() / shard.cost());
                if (n && me.can_buy(shard, n)) purchase(shard, n);
                if (me.item_count()[emblem] == 0) return;   // save up for it
            }
            const it main = (fish ? fish_focus : focus_main) ? it::power_shard_of_focus : it::power_shard_of_strength;
            const unsigned n = me.gold_count() / main.cost();
            if (n && me.can_buy(main, n)) purchase(main, n);
        } catch (const std::exception&) {}
        return;
    }
    const bool caster = who == ct::stellar || who == ct::tavi || who == ct::cassi || who == ct::prism;
    const bool tank = who == ct::ryth || who == ct::varg || who == ct::marcella;
    if constexpr (economy::shopping) {
        // Compare all 21 shard families/stat choices, one bounded purchase per
        // turn. Partial emblems retain progress; the fifth shard grants passive.
        if (me.gold_count() >= 30 && cambc::fuel_remaining() > 30000) {
            const auto stats = me.base_stats();
            double best_roi=-1; int selected=0;
            for (int family=0; family<7; ++family) for (int stat=0; stat<3; ++stat) {
                const int index=family*6+stat*2;
                const it shard{static_cast<it::enum_type>(index)};
                const unsigned have=me.item_count()[shard];
                const double gain=stat==0 ? stats.strength_growth/std::max(1.0f,me.strength())
                    : stat==1 ? stats.focus_growth/std::max(1.0f,me.focus())*(caster ? 1.0 : 0.35)
                    : stats.health_growth/std::max(1.0f,me.max_health())*(1.0+observed_incoming/100);
                const double passive=family==0 ? 0.10 : family==1 ? gain : family==2 ? 0.11
                    : family==3 ? 0.20*std::max(0.0,1.0-cambc::round_number()/2000.0)
                    : family==4 ? 0.20 : family==5 ? 2.0/std::max(10,home_dist(me.position())+5) : gain*0.5;
                const double roi=(gain+economy::ITEM_ROI_W*passive/std::max(1u,5-std::min(4u,have)))/30;
                if (roi>best_roi && me.can_buy(shard)) { best_roi=roi; selected=index; }
            }
            if (best_roi>=0) purchase(it{static_cast<it::enum_type>(selected)});
        }
        return;
    }
    try {
        // Home emblem first: recall drops from 5 turns to 3 (we recall a lot), stats still count.
        // Univardisty's build (from their ladder stats): Durability(Health) emblem first, Tavi adds
        // Treasure(Focus), then every coin into Power shards of the main stat. No Home emblem.
        if (CUSTOM_SHOP) {
            const bool focus_role = caster || who == ct::willow || who == ct::ren;
            const int families[3] = {
                tank ? TANK_ITEM_FAMILY1 : focus_role ? CASTER_ITEM_FAMILY1 : MELEE_ITEM_FAMILY1,
                tank ? TANK_ITEM_FAMILY2 : focus_role ? CASTER_ITEM_FAMILY2 : MELEE_ITEM_FAMILY2,
                tank ? TANK_ITEM_FAMILY3 : focus_role ? CASTER_ITEM_FAMILY3 : MELEE_ITEM_FAMILY3};
            const int stats[3] = {
                tank ? TANK_ITEM_STAT1 : focus_role ? CASTER_ITEM_STAT1 : MELEE_ITEM_STAT1,
                tank ? TANK_ITEM_STAT2 : focus_role ? CASTER_ITEM_STAT2 : MELEE_ITEM_STAT2,
                tank ? TANK_ITEM_STAT3 : focus_role ? CASTER_ITEM_STAT3 : MELEE_ITEM_STAT3};
            for (int i = 0; i < std::min(3, CUSTOM_EMBLEM_COUNT); ++i) {
                const int index = families[i] * 6 + stats[i] * 2;
                const it shard{static_cast<it::enum_type>(index)};
                const it emblem{static_cast<it::enum_type>(index + 1)};
                if (me.item_count()[emblem] > 0) continue;
                const unsigned have = me.item_count()[shard];
                const unsigned n = std::min<unsigned>(have < 5 ? 5 - have : 0, me.gold_count() / shard.cost());
                if (n && me.can_buy(shard, n)) purchase(shard, n);
                if (me.item_count()[emblem] == 0) return;
            }
            const int stat = tank ? TANK_POWER_STAT : focus_role ? CASTER_POWER_STAT : MELEE_POWER_STAT;
            const it power{static_cast<it::enum_type>(6 + stat * 2)};
            const unsigned n = me.gold_count() / power.cost();
            if (n && me.can_buy(power, n)) purchase(power, n);
            return;
        }
        if (UNIV_SHOP) {
            const bool focus_main = who == ct::stellar || who == ct::tavi || who == ct::ren || who == ct::cassi
                                    || who == ct::prism || who == ct::willow;
            std::vector<std::pair<it, it>> plan;
            if (SHOP_STYLE == 3) {   // procless: Durability + Jungle in the main stat, Bruiser(Health), then Power Str
                if (focus_main) plan = {{it::durability_shard_of_focus, it::durability_emblem_of_focus},
                                        {it::jungle_shard_of_focus, it::jungle_emblem_of_focus}};
                else plan = {{it::durability_shard_of_strength, it::durability_emblem_of_strength},
                             {it::jungle_shard_of_strength, it::jungle_emblem_of_strength}};
                plan.push_back({it::bruiser_shard_of_health, it::bruiser_emblem_of_health});
            } else if (SHOP_STYLE == 2) {   // Quantom: Monster(Str) -> Durability(Health) -> Power Str/Health
                plan = {{it::monster_shard_of_strength, it::monster_emblem_of_strength},
                        {it::durability_shard_of_health, it::durability_emblem_of_health}};
            } else {
                plan = {{it::durability_shard_of_health, it::durability_emblem_of_health}};
                if (who == ct::tavi) plan.push_back({it::treasure_shard_of_focus, it::treasure_emblem_of_focus});
            }
            for (const auto& [shard, emblem] : plan) {
                if (me.item_count()[emblem] > 0) continue;
                const unsigned have = me.item_count()[shard];
                const unsigned n = std::min<unsigned>(have < 5 ? 5 - have : 0, me.gold_count() / shard.cost());
                if (n && me.can_buy(shard, n)) purchase(shard, n);
                if (me.item_count()[emblem] == 0) return;   // save up for it
            }
            if (SHOP_STYLE == 2) {   // two Strength shards per Health shard
                while (me.gold_count() >= it(it::power_shard_of_strength).cost()) {
                    const it pick = (bought_str >= 2 * (bought_hp + 1)) ? it::power_shard_of_health : it::power_shard_of_strength;
                    if (!me.can_buy(pick, 1)) break;
                    purchase(pick, 1);
                    if (pick == it::power_shard_of_health) ++bought_hp; else ++bought_str;
                }
                return;
            }
            const it main = (focus_main && (SHOP_STYLE != 3 || COLLECTOR_FOCUS)) ? it::power_shard_of_focus : it::power_shard_of_strength;
            const unsigned n = me.gold_count() / main.cost();
            if (n && me.can_buy(main, n)) purchase(main, n);
            return;
        }
        if (HOME_FIRST) {
            const auto counts = me.item_count();
            const bool have_home = counts[it::home_emblem_of_strength] + counts[it::home_emblem_of_focus]
                                 + counts[it::home_emblem_of_health] > 0;
            if (!have_home) {
                const it shard = who == ct::willow ? it::home_shard_of_focus : it::home_shard_of_strength;
                const unsigned have = counts[shard];
                const unsigned n = std::min<unsigned>(have < 5 ? 5 - have : 0, me.gold_count() / shard.cost());
                if (n && me.can_buy(shard, n)) { purchase(shard, n); }
                if (me.item_count()[it::home_emblem_of_strength] + me.item_count()[it::home_emblem_of_focus] == 0) return;
            }
        }
        // Then role emblems: Durability (-10% damage taken) for everyone, then a second passive
        // (Jungle for tanks soaking camps, Treasure for Vesper's gold, Monster for the rest).
        if (EMBLEM_PLAN) {
            const bool melee = who == ct::vendetta || who == ct::vesper_vale || who == ct::issac;
            std::vector<std::pair<it, it>> plan;   // (shard, emblem)
            if (tank) {
                plan = {{it::durability_shard_of_health, it::durability_emblem_of_health},
                        {it::jungle_shard_of_health, it::jungle_emblem_of_health}};
            } else if (melee) {
                plan = {{it::durability_shard_of_strength, it::durability_emblem_of_strength}};
                if (who == ct::vesper_vale) plan.push_back({it::treasure_shard_of_strength, it::treasure_emblem_of_strength});
                else plan.push_back({it::monster_shard_of_strength, it::monster_emblem_of_strength});
            } else {   // casters, Willow, Ren: abilities scale with Focus
                plan = {{it::durability_shard_of_focus, it::durability_emblem_of_focus},
                        {it::monster_shard_of_focus, it::monster_emblem_of_focus}};
            }
            const int want = std::min<int>((int)plan.size(), EMBLEM_COUNT);
            for (int i = 0; i < want; ++i) {
                const auto [shard, emblem] = plan[i];
                if (me.item_count()[emblem] > 0) continue;
                const unsigned have = me.item_count()[shard];
                unsigned need = have < 5 ? 5 - have : 0;
                // Tavi can sell at full value: turn loose Power shards into a finished emblem passive.
                if (TAVI_SELL && who == ct::tavi && cambc::map::spawn_region(team::ally).is_set(me.position())
                    && me.gold_count() < need * shard.cost()) {
                    for (it p : {it::power_shard_of_strength, it::power_shard_of_focus, it::power_shard_of_health}) {
                        unsigned own = me.item_count()[p];
                        while (own > 0 && me.gold_count() < need * shard.cost()) { me.sell(p, 1); --own; }
                    }
                }
                const unsigned n = std::min<unsigned>(need, me.gold_count() / shard.cost());
                if (n && me.can_buy(shard, n)) {
                    purchase(shard, n);
                    if (shard == it::durability_shard_of_focus || shard == it::monster_shard_of_focus) bought_foc += n;
                    else if (shard == it::durability_shard_of_health || shard == it::jungle_shard_of_health) bought_hp += n;
                    else bought_str += n;
                }
                if (me.item_count()[emblem] == 0) return;   // save up for this emblem first
            }
        }
        // Then Power shards, one at a time, keeping each role's stat mix.
        while (true) {
            it item = it::power_shard_of_strength;
            const unsigned total = bought_str + bought_foc + bought_hp + 1;
            if (who == ct::willow) item = it::power_shard_of_focus;
            else if (caster && bought_foc < CASTER_FOCUS_SHARE * total) item = it::power_shard_of_focus;
            else if (tank && bought_hp < TANK_HEALTH_SHARE * total) item = it::power_shard_of_health;
            if (me.gold_count() < item.cost() || !me.can_buy(item, 1)) break;
            purchase(item, 1);
            if (item == it::power_shard_of_focus) ++bought_foc;
            else if (item == it::power_shard_of_health) ++bought_hp;
            else ++bought_str;
        }
    } catch (const std::exception&) {}
}

// Cast the best ready spell on (or around) a camp. Spell range is 4, one more than attacks.
bool Bot::cast_on_camp(const cambc::camp& camp) {
    if (champion_maps::enabled()) return champion_maps::fight(camp);
    if (packs_actions::enabled()) return packs_actions::fight(camp);
    auto& me = cambc::self();
    if (!me.can_cast() || !camp.is_visible() || dist(me.position(), camp.position()) > 4) return false;
    // Heavy hitters: stun first (a stunned camp skips its attack). Otherwise damage first.
    const bool stun_first = camp.strength() >= STUN_FIRST_STR;
    // Fish: Heart of Ruin and Ren cast their shield and landing-damage dash on camps all game (HoR ~75 dashes per game).
    if (FISH_CAMP_SPELLS) for (auto& a : me.abilities()) {
        if (!a.is_ready() || !me.can_cast()) continue;
        try {
            if (a.is_shield() && a.can_target_self() && camp.strength() > 0 && me.health() < me.max_health() * FISH_SHIELD_HP) {
                if (a.use()) return true;
            } else if (a.is_dash()) {
                const auto d = a.get<cambc::ability_dash>();
                if (d.modifier <= 0) continue;
                const vec2 c = camp.position(), p = me.position();
                const int reach = (int)d.range, rad = std::max(1, (int)d.radius);
                vec2 best{-1, -1}; int bd = 1 << 20;
                for (int dy = -rad; dy <= rad; ++dy) for (int dx = -rad; dx <= rad; ++dx) {
                    const vec2 t{c.x + dx, c.y + dy};
                    if (t == p || t == c || t.x < 0 || t.y < 0 || t.x >= cambc::map::width() || t.y >= cambc::map::height()) continue;
                    if (dist(p, t) > reach || g_static_walls.is_set(t)) continue;
                    const int score = dist(p, t);
                    if (score < bd) { bd = score; best = t; }
                }
                if (best.x >= 0 && a.use(best)) return true;
            }
        } catch (const std::exception&) {}
    }
    for (int pass = 0; pass < 2; ++pass) {
        const bool want_cc = (pass == 0) == stun_first;
        for (auto& a : me.abilities()) {
            if (!a.is_ready()) continue;
            try {
                if (want_cc) {
                    if (!USE_CC || !a.is_cc() || !a.can_target_camps()) continue;
                    // "Damage and stun" spells are cc with a damage modifier: fine on any camp.
                    const bool deals_damage = a.get<cambc::ability_cc>().modifier > 0;
                    if ((deals_damage || camp.strength() > 0) && a.use(camp)) return true;
                } else if (a.is_damage() && a.can_target_camps()) {
                    if (a.use(camp)) return true;
                } else if (USE_AOE && a.is_aoe_damage() && a.can_target_ground()) {
                    if (a.use(camp.position())) return true;
                }
            } catch (const std::exception&) {}
        }
    }
    return false;
}

// Camp roughly equidistant from both spawns (computed once).
// Home camp: clearly nearer our spawn than theirs and not a monolith group (computed once per game).
bool Bot::is_home_group(int i) {
    static std::vector<signed char> home;
    if (home.size() != info.size()) {
        home.assign(info.size(), 0);
        auto centre = [](const cambc::bitboard& b) {
            long sx = 0, sy = 0, n = 0;
            for (auto t : b.positions()) { sx += t.x; sy += t.y; ++n; }
            return n ? vec2{(int)(sx / n), (int)(sy / n)} : vec2{0, 0};
        };
        const vec2 ours = centre(cambc::map::spawn_region(team::ally)), theirs = centre(cambc::map::spawn_region(team::enemy));
        const double proj_max = map_strategy::policy().home_proj;
        const double ax = theirs.x - ours.x, ay = theirs.y - ours.y, len2 = std::max(1.0, ax * ax + ay * ay);
        for (size_t q = 0; q < info.size(); ++q) {
            if (info[q].tiles.empty() || info[q].dmg >= MONO_DAMAGE_MIN) continue;
            // Projection of the camp onto the spawn->spawn line: 0 = our spawn, 1 = theirs (Chebyshev ties fooled the old test).
            const double t = ((info[q].tiles[0].x - ours.x) * ax + (info[q].tiles[0].y - ours.y) * ay) / len2;
            home[q] = t <= proj_max;
        }
    }
    return i >= 0 && i < (int)home.size() && home[i];
}

bool Bot::is_mid(int i) {
    static std::vector<signed char> mid;
    if (mid.size() != info.size()) {
        mid.assign(info.size(), 0);
        auto centre = [](const cambc::bitboard& b) {
            long sx = 0, sy = 0, n = 0;
            for (auto t : b.positions()) { sx += t.x; sy += t.y; ++n; }
            return n ? vec2{(int)(sx / n), (int)(sy / n)} : vec2{0, 0};
        };
        const vec2 a = centre(cambc::map::spawn_region(team::ally)), b = centre(cambc::map::spawn_region(team::enemy));
        for (size_t q = 0; q < info.size(); ++q)
            if (!info[q].tiles.empty())
                mid[q] = std::abs(dist(info[q].tiles[0], a) - dist(info[q].tiles[0], b)) <= CENTRE_MARGIN;
    }
    return i >= 0 && i < (int)mid.size() && mid[i];
}

int Bot::choose_group() {
    const auto& strategy=map_strategy::policy();
    if constexpr(CHAMPION_MAPS_SINGLE_GROUP>=0) {
        need_here=1;
        return CHAMPION_MAPS_SINGLE_GROUP;
    }
    auto& me = cambc::self();
    PROF("cg0");
    const auto visible = cambc::vision::visible_tiles();
    PROF("cg_vis");
    std::array<std::uint8_t, 8> claims{};
    cambc::shared_memory.read(0, std::span<std::uint8_t>{claims});
    std::vector<int> claim_count(info.size(), 0);
    for (int s = 0; s < 6; ++s)   // bytes 6-7: engage stamp + marked enemy
        if (s != slot && claims[s] > 0 && claims[s] <= info.size()) ++claim_count[claims[s] - 1];

    const vec2 pos = me.position();
    // Scale design stats by our own shard growth (allies shop the same way).
    const auto bs_self = me.base_stats();
    const double str_growth = GROWTH_SCALE ? std::max(1.0, (double)me.strength() / std::max(1.0f, bs_self.base_strength)) : 1.0;
    const double hp_growth = GROWTH_SCALE ? std::max(1.0, (double)me.max_health() / std::max(1.0f, bs_self.base_health)) : 1.0;
    const double t_dps = team_dps * str_growth * strategy.clear_rate, t_hp = team_hp * hp_growth;
    const double avg_dps = t_dps / team_n, avg_hp = t_hp / team_n;
    const int now = (int)cambc::round_number();
    std::vector<cambc::map::camp_group> groups;   // fetched lazily, only if something is visible

    // Fuel: recent sightings filtered once, not per camp (16 x camps distance checks).
    std::array<vec2, 16> recent;
    int n_recent = 0;
    if (DANGER_SQUADS)
        for (const auto& sgt : sightings)
            if (sgt.second >= 0 && now - sgt.second <= DANGER_MEMORY) recent[n_recent++] = sgt.first;
    PROF("cg_pre_loop");
    std::vector<char> alive_grp(info.size(), 0);   // groups with a live monster in this turn's snapshot
    for (const auto& v : g_cv) if (v.group >= 0 && v.group < (int)info.size()) alive_grp[v.group] = 1;
    double best_score = -1;
    int best = -1, best_need = 1;
    // Fuel (Lanes: 40-70 suspended turns per game): consider only the K nearest groups first.
    std::vector<char> near_ok;
    if (strategy.near_k > 0 && (int)info.size() > strategy.near_k + 2) {
        std::vector<std::pair<int,int>> dd; dd.reserve(info.size());
        for (size_t q = 0; q < info.size(); ++q) {
            int cmin = 1 << 20;
            for (auto tp : info[q].tiles) cmin = std::min(cmin, dist(pos, tp));
            dd.push_back({cmin, (int)q});
        }
        std::nth_element(dd.begin(), dd.begin() + strategy.near_k, dd.end());
        near_ok.assign(info.size(), 0);
        for (int q = 0; q < strategy.near_k; ++q) near_ok[dd[q].second] = 1;
        if (target_group >= 0 && target_group < (int)info.size()) near_ok[target_group] = 1;
    }
    // Death memory: skip camps near where this champion recently died (it walked into the same ball 131 times on Contest).
    std::vector<char> deadly;
    if (DEATH_MEMORY_ON && strategy.death_memory) {
        for (const auto& ds : death_sites) {
            if (ds.second <= 0 || now - ds.second > DEATH_TTL) continue;
            if (deadly.empty()) deadly.assign(info.size(), 0);
            for (size_t q = 0; q < info.size(); ++q)
                if (!info[q].tiles.empty() && dist(info[q].tiles[0], ds.first) <= DEATH_RADIUS) deadly[q] = 1;
        }
    }
    for (int pass = 0; pass < 2; ++pass) {
    // Current target first: its score sets a high bar early, so pruning skips more camps.
    for (size_t k = 0; k <= info.size(); ++k) {
        if (!near_ok.empty() && k > 0 && !near_ok[k - 1]) continue;
        if (!deadly.empty() && k > 0 && deadly[k - 1]) continue;
        if (!deadly.empty() && k == 0 && target_group >= 0 && target_group < (int)deadly.size() && deadly[target_group]) continue;
        if (k == 0 && (target_group < 0 || target_group >= (int)info.size())) continue;
        const size_t i = k == 0 ? (size_t)target_group : k - 1;
        if (k > 0 && (int)i == target_group) continue;
        // Fuel guard: running low -> keep the best found so far rather than lose the whole turn.
        if (FUEL_GUARD && (k & 3) == 3 && best >= 0 && cambc::fuel_remaining() < FUEL_RESERVE) break;
        const auto& g = info[i];
        if (g.tiles.empty() || (g_replay_repairs && now<camp_avoid_until[i])) continue;
        if ((SPLIT_CAPTURE || DEAD_CAMP_LEAVE || COLLECTORS) && (int)i == skip_group && now < skip_until) continue;   // an ally is capturing it
        if (strategy.skip_unreachable && i<spawn_dist.size() && spawn_dist[i]==65535) continue;
        if (i < unreach_grp.size() && unreach_grp[i]) continue;   // no walking route to the camp from our spawn (tested: counting shots across holes made fracture/islands/big-world worse)
        double reward = g.gems * GEM_W + g.gold * GOLD_W;
        if(g.gems==0)reward*=strategy.gold_only_scale;

        if (reward <= 0) continue;
        if (strategy.home_only && !is_home_group((int)i)) continue;   // map role: stay on our side
        double centre_mult = 1.0;
        if (AVOID_ENEMY_CAMPS) {   // Mite never fights near us; we lose every fight near their casters (burst range 4)
            bool hot = false;
            for (const auto& e : g_enemies)
                if (e.is_visible() && e.is_alive() && dist(e.position(), g.tiles[0]) <= ENEMY_CAMP_RADIUS) { hot = true; break; }
            if (hot) continue;
        }
        // Fuel: the best this camp could score (1 champion, no fight, every bonus) can't win -> skip.
        // Bound: distance >= straight line (and the respawn wait), kill time >= HP / whole-team DPS,
        // only JOIN can multiply (STICKY is the current target, scored first).
        if (PRUNE_CAMPS && !economy::camps && best_score > 0) {
            int cheb = 1 << 20;
            for (auto p : g.tiles) cheb = std::min(cheb, dist(pos, p));
            const double d_lb = std::max(cheb, ready_round[i] - now);
            const double t_lb = std::max(0.0, hp_left[i]) / t_dps;
            double upper = reward * std::max(1.0f, JOIN_MULT) / (d_lb + t_lb + CAMP_OVERHEAD);
            if constexpr (policy::active)
                upper = 1.5 * upper * std::max({1.0, (double)TANK_CENTRE_MULT, (double)SQUISHY_CENTRE_MULT}) + 0.0005;
            if (upper <= best_score) continue;
        }
        // Cheap prefilter on straight-line distance before paying for a walking distance.
        bool vis = false;
        for (auto p : g.tiles) if (LOCAL_BITS ? g_vis.test(p) : visible.is_set(p)) { vis = true; break; }
        bool reward_ready = false;
        if (vis && STATE_FROM_SNAPSHOT && alive_grp[i]) {
            ready_round[i] = now;   // live monsters in view: up, no reward yet (no engine call)
        } else if (vis) {
            const auto st = g_groups[i].state();
            if (auto r = std::get_if<cambc::map::camp_group_respawning>(&st)) ready_round[i] = now + r->timer;
            else ready_round[i] = now;
            reward_ready = std::holds_alternative<cambc::map::camp_group_reward_available>(st);
        }
        int d = walk_dist((int)i, pos);
        if (d < 0) continue;                         // cannot walk there
        d = std::max(d, ready_round[i] - now);      // waiting for a respawn costs time too

        // Smallest squad whose front-liner survives the fight.
        const double hp = std::max(1.0, hp_left[i]);
        int need = 1;
        while (need < team_n && g.dmg * hp / (need * avg_dps) > SQUAD_SOAK * avg_hp) ++need;
        if (reward_ready) need = 1;
        // Monoliths: a whole-team siege late in the game, once upgrades have doubled our strength.
        const bool siege = MONOLITH && g.dmg >= MONO_DAMAGE_MIN && now >= MONO_MIN_ROUND && str_growth >= MONO_MIN_GROWTH;
        if (siege) need = team_n;
        if (!reward_ready && g.dmg * hp / t_dps > (siege ? TEAM_SOAK_MONO : TEAM_SOAK) * t_hp) continue;   // too strong even together
        // Camps near recent enemy sightings: never go alone, and value them a little lower.
        if (DANGER_SQUADS && team_n >= 2) {
            for (int k = 0; k < n_recent; ++k)
                if (dist(recent[k], g.tiles[0]) <= DANGER_CAMP_RADIUS) { need = std::max(need, 2); break; }
            // Long-term: enemies keep walking through here.
            if (HEATMAP && heat_at(g.tiles[0]) >= HEAT_DANGER) need = std::max(need, 2);
        }
        // Centre (equidistant from both spawns, e.g. the corners gem clusters + altar): only as a squad.
        if (CENTRE_REGROUP && team_n >= 3 && is_mid((int)i)) need = std::max(need, std::min(team_n, REGROUP_SIZE));
        // Fish ball: the whole team (up to FISH_BALL_N) takes every camp together.
        if (FISH_BALL && !reward_ready) need = std::max(need, std::min(team_n, FISH_BALL_N));
        // Tanks hold the contested middle, squishies farm home camps (Mite, corners r20: Varg+Ryth+Stellar arrive
        // together at the centre; our Stellar/Issac/Tavi arrived alone with no tank and lost 3v3 by round 30).
        if (TANK_CENTRE && !FISH_BALL && team_has_tank && is_mid((int)i)) {   // no tank drafted (collision): no restriction
            auto is_tank = [](cambc::champion_type t) { return t == cambc::champion_type::ryth || t == cambc::champion_type::varg || t == cambc::champion_type::marcella; };
            const bool tank = is_tank(me.champion_name());
            bool escorted = false;
            if (!tank) {
                int tanks_near = 0;
                for (const auto& a : g_allies) {
                    try { if (a.is_alive() && is_tank(a.champion_name()) && dist(a.position(), g.tiles[0]) <= ESCORT_RADIUS) ++tanks_near; } catch (const std::exception&) {}
                }
                escorted = tanks_near >= 1;
            }
            if (!tank && !escorted) centre_mult = SQUISHY_CENTRE_MULT;   // alone and squishy: stay home
            else if (tank) centre_mult = TANK_CENTRE_MULT;
        }
        const double turns = reward_ready ? 0 : hp / (need * avg_dps);
        // Zone farming: every gem must later be carried to an altar; a bag of ~30 costs 2 x (camp->altar)
        // walking turns, so camps near altars are worth more (champions settle into altar zones).
        double bank_trip = 0;
        if (ZONE_FARM && !g_altars.empty()) {
            if (camp_alt_d.size() != info.size()) {
                camp_alt_d.assign(info.size(), 0);
                for (size_t q = 0; q < info.size(); ++q) {
                    int ad = 1 << 20;
                    if (!info[q].tiles.empty()) for (auto a : g_altars) ad = std::min(ad, dist(info[q].tiles[0], a));
                    camp_alt_d[q] = ad;
                }
            }
            bank_trip = ZONE_W * g.gems * 2.0 * camp_alt_d[i] / ZONE_BAG;
        }
        double score = reward / ((d + turns + CAMP_OVERHEAD + bank_trip) * need);    // value per champion-turn
        if constexpr (economy::camps) {
            int altar_distance=100;
            for (auto altar : g_altars) altar_distance=std::min(altar_distance,dist(g.tiles[0],altar));
            const double horizon=std::ceil(g.gems/std::max(1,need)/10.0);
            const auto risk=economy::estimate(me.health(), observed_incoming+g.dmg/std::max(1,need),observed_cc,turns+horizon);
            const double elapsed=d+economy::CAMP_CLEAR_TURNS_W*turns+economy::CAPTURE_TIME_W*5
                +economy::ALTAR_TRAVEL_W*altar_distance+horizon
                +economy::RESPAWN_VALUE_W*std::max(0,ready_round[i]-now);
            score=economy::delivered_value(g.gems,g.gold,elapsed*need,risk.death,risk.interrupt);
        }
        score *= centre_mult;
        const int have = claim_count[i];
        const bool respawning = ready_round[i] > now;
        if (respawning && have > 0) score *= WAIT_CLAIMED_MULT;          // someone already waits there
        else if (have >= need && (int)i != target_group && !FISH_BALL) score *= OVERSTAFF_MULT;
        else if (have > 0 && !respawning) score *= FISH_BALL ? FISH_BALL_JOIN : JOIN_MULT;
        if ((int)i == target_group && !respawning) score *= STICKY_MULT;
        if constexpr (policy::active) {
            policy::Features x{1, (float)d/100, (float)turns/100, (float)g.gems/200,
                (float)g.gold/300, (float)(g.dmg*hp/std::max(1.0,t_dps*t_hp)),
                me.health()/std::max(1.0f,me.max_health()), (float)me.gem_count()/100,
                (float)((int)i == target_group), (float)have/5, (float)now/2000,
                (float)(score/(1+score))};
            score = policy::score(0, (int)i, score, x, score);
        }
        if (score > best_score) { best_score = score; best = (int)i; best_need = need; }
    }
    if (best >= 0 || (near_ok.empty() && deadly.empty())) break;   // found one, or already searched everything
    near_ok.clear(); deadly.clear();                                // nothing usable: search all groups
    }
    need_here = best_need;
    policy::choose(0, best);
    return best;
}

// Remember the live health of every visible camp (sleeping camps do not regenerate).
void Bot::observe_camps() {
    const auto visible = cambc::vision::visible_tiles();
    for (size_t i = 0; i < info.size(); ++i) {
        const auto& g = info[i];
        bool any_vis = false;
        for (auto p : g.tiles) if (LOCAL_BITS ? g_vis.test(p) : visible.is_set(p)) { any_vis = true; break; }
        if (!any_vis) continue;
        std::vector<double> cur = member_left[i];
        int present = 0;
        for (size_t k = 0; k < g.tiles.size(); ++k) {
            if (!(LOCAL_BITS ? g_vis.test(g.tiles[k]) : visible.is_set(g.tiles[k]))) continue;
            double h = 0;
            for (const auto& v : g_cv)
                if (v.spawn == g.tiles[k]) { h = v.hp; ++present; break; }
            cur[k] = h;
        }
        if (present == 0) cur = g.member_hp;
        member_left[i] = cur;
        double sum = 0;
        for (double h : cur) sum += h;
        hp_left[i] = sum;
    }
}

// Step away from hitting camps and enemies (damage cancels recall).
bool Bot::retreat_from_danger(int radius) {
    auto& me = cambc::self();
    const vec2 pos = me.position();
    std::vector<vec2> threats;
    for (const auto& v : g_cv)
        if (v.str > 0 && dist(pos, v.pos) <= 4) threats.push_back(v.pos);
    for (const auto& e : g_enemies)
        if (e.is_visible() && dist(pos, e.position()) <= radius) threats.push_back(e.position());
    if (threats.empty() || !me.can_move()) return false;
    const auto blocked = blocked_tiles();
    bool ryth_near = false;
    if (CHAMP_AWARE)
        for (const auto& e : g_enemies)
            if (e.is_visible() && e.champion_name() == cambc::champion_type::ryth && dist(pos, e.position()) <= 4) ryth_near = true;
    // Escape dash: Issac, Ren and Vendetta have a free 2-tile dash. Near death use it to get out of reach in one turn.
    if (DASH_ESCAPE && me.can_cast() && me.health() < me.max_health() * DASH_ESCAPE_HP) {
        for (auto& ability : me.abilities()) {
            if (!ability.is_dash() || !ability.is_ready()) continue;
            vec2 dest = pos; int best_dm = 0;
            for (int q = 0; q < 1; ++q) { int d0 = 1 << 20; for (auto th : threats) d0 = std::min(d0, dist(pos, th)); best_dm = d0; }
            for (auto tile : ability.valid_tiles().positions()) {
                if (tile.chebyshev_distance(pos) > 2 || blocked.is_set(tile)) continue;
                int dmin = 1 << 20;
                for (auto th : threats) dmin = std::min(dmin, dist(tile, th));
                if (dmin > best_dm || (dmin == best_dm && dest != pos && home_dist(tile) < home_dist(dest))) { best_dm = dmin; dest = tile; }
            }
            if (dest != pos) { try { if (ability.use(dest)) return true; } catch (const cambc::error&) {} }
        }
    }
    vec2 best = pos;
    double best_d = std::numeric_limits<int>::min();   // scores can be negative (home bias)
    for (auto t : blocked.reachable_tiles(pos, 1).positions()) {
        int dmin = 1 << 20;
        for (auto th : threats) dmin = std::min(dmin, dist(t, th));
        int sc = dmin * RETREAT_DISTANCE_W;
        if (RETREAT_HOME) sc -= RETREAT_HOME_W * home_dist(t);   // run towards spawn (heal, allies) not into corners
        if (BUSH_AMBUSH && cambc::map::bushes().is_set(t)) sc += RETREAT_BUSH_BONUS + (economy::mobility ? economy::BUSH_AMBUSH_W*20 : 0);   // break line of sight
        if (ryth_near)   // Ryth's stun hits radius 1: do not stand next to allies
            for (const auto& a : g_allies)
                if (a.position() != pos && dist(t, a.position()) <= 1) { sc -= RETREAT_SPREAD_PENALTY; break; }
        double ranked = sc;
        if constexpr (policy::active) {
            policy::Features x{1, (float)dmin/8, (float)home_dist(t)/100, (float)sc/100,
                me.health()/std::max(1.0f,me.max_health()), (float)me.gem_count()/100,
                (float)ryth_near, (float)threats.size()/8, (float)t.x/100, (float)t.y/100,
                (float)cambc::round_number()/2000, last_dmg/std::max(1.0f,me.max_health())};
            ranked = policy::score(2, t.y*g_w+t.x, sc, x, std::max(10.0,std::abs((double)sc)));
        }
        if (ranked > best_d) { best_d = ranked; best = t; }
    }
    if (best != pos) { try {
        if (me.move_absolute(best)) { policy::choose(2, best.y*g_w+best.x); return true; }
    } catch (const cambc::error&) {} }
    return false;
}

// Weakest visible enemy within range (fat bags and the team's marked target first).
const cambc::champion* Bot::pick_target(int range) {
    const vec2 pos = cambc::self().position();
    const int raw6 = (int)std::uint8_t(cambc::shared_memory[6]);
    const int focus_id = (raw6 >> 4) - 1;
    const int stamp_now = (int)cambc::round_number() % 15 + 1;
    const int stamp = raw6 & 15;
    const bool engage_fresh = TEAMFIGHT && stamp > 0 && (stamp_now - stamp + 15) % 15 <= ENGAGE_TTL;
    const cambc::champion* tgt = nullptr;
    double best = 1e18;
    auto& me = cambc::self();
    using ct = cambc::champion_type;
    // Damage we can put out this turn: a basic attack (twice with a ready reset) plus the best spell.
    double burst = me.strength();
    double spell = 0;
    for (auto& a : me.abilities()) {
        if (!a.is_ready()) continue;
        if (a.is_attack_reset()) burst += me.strength();
        else if (a.is_damage() || a.is_cc()) spell = std::max<double>(spell, BURST_FOCUS_MULT * me.focus());
    }
    burst += spell;
    for (const auto& e : g_enemies) {
        if (!e.is_visible() || !e.is_alive() || e.health() <= 0 || dist(pos, e.position()) > range) continue;
        if (g_replay_repairs && g_enemy_spawn->is_set(e.position())) continue;
        double hp = e.health();
        double bag = gems_of(e);
        if (CHAMP_AWARE && (e.champion_name() == ct::cassi || e.champion_name() == ct::issac)) {
            // Linked fate: killing either kills both and hands over both bags; hit the weaker body.
            for (const auto& o : g_enemies)
                if (&o != &e && o.is_visible() && o.is_alive() && (o.champion_name() == ct::cassi || o.champion_name() == ct::issac)) {
                    bag += gems_of(o);
                    if (o.is_visible()) hp = std::min<double>(hp, o.health());
                }
        }
        double sc = TARGET_HP_W * hp - (GEM_HUNT ? TARGET_GEM_W * bag : 0.0);
        if constexpr (economy::combat) {
            sc-=economy::EXPECTED_DAMAGE_W*std::min(hp,burst)
                +economy::KILL_CONFIRM_W*(hp<=burst ? 50+bag : 0)
                +economy::ENEMY_GEM_CARRY_W*bag;
            sc+=economy::ABILITY_VALUE_W*std::max(0,dist(pos,e.position())-g_range)*me.strength();
        }
        if constexpr (policy::active) {
            policy::Features x{1, (float)dist(pos,e.position())/8, (float)hp/std::max(1.0f,e.max_health()),
                (float)bag/100, (float)(burst/std::max(1.0,hp)),
                me.health()/std::max(1.0f,me.max_health()), (float)me.gem_count()/100,
                (float)(e.health() <= burst), (float)engage_fresh, (float)pvp_foes/5,
                (float)cambc::round_number()/2000, (float)sc/2000};
            sc = -policy::score(1, (int)e.champion_name(), -sc, x, std::max(50.0,hp));
        }
        if (engage_fresh && (int)e.champion_name() == focus_id) sc -= MARK_PRIORITY;
        const bool can_kill = SECURE_KILLS && e.health() <= burst;
        if (can_kill) sc -= KILL_PRIORITY;   // a kill now beats everything (Vendetta: resets)
        // Ren reflects 0.2 x Focus per hit: leave him for healthy champions.
        if (CHAMP_AWARE && e.champion_name() == ct::ren && me.health() < me.max_health() * REN_AVOID_HP) sc += REN_TARGET_PENALTY;
        if (sc < best) { best = sc; tgt = &e; target_killable = can_kill; }
    }
    if (!tgt) target_killable = false;
    policy::choose(1, tgt ? (int)tgt->champion_name() : -1);
    return tgt;
}

// Area-damage spells (Stellar slot 1: 1.4 x Focus, radius 1; Prism) are placed on a tile, not a unit, so the unit-target
// spell code below never cast them in fights: 0 casts in 575 ready-with-enemy-in-range rounds on the ladder (top teams ~14%).
// Cast on the tile that hits the most visible enemy champions (never a tile with one of our champions in the blast).
static bool aoe_cast(int min_hits) {
    auto& me = cambc::self();
    if (!AOE_PVP || !me.can_cast()) return false;
    try {
        for (auto& a : me.abilities()) {
            if (!a.is_ready() || !a.is_aoe_damage()) continue;
            const auto info = a.get<cambc::ability_aoe_damage>();
            const auto valid = a.valid_tiles();
            std::vector<cambc::vec2> centres;
            for (const auto& e : g_enemies) {
                if (!e.is_visible() || !e.is_alive() || e.health() <= 0) continue;
                for (int dy = -(int)info.radius; dy <= (int)info.radius; ++dy)
                    for (int dx = -(int)info.radius; dx <= (int)info.radius; ++dx) {
                        const cambc::vec2 t{e.position().x + dx, e.position().y + dy};
                        if (std::find(centres.begin(), centres.end(), t) == centres.end()) centres.push_back(t);
                    }
                if (centres.size() > 60) break;
            }
            int best_hits = 0; cambc::vec2 best_c{};
            for (const auto& c : centres) {
                if (cambc::fuel_remaining() < 30000) break;
                if (!valid.is_set(c)) continue;
                int hits = 0; bool friendly = false;
                for (const auto& e : g_enemies)
                    if (e.is_visible() && e.is_alive() && e.health() > 0 && e.position().chebyshev_distance(c) <= (int)info.radius) ++hits;
                for (const auto& al : g_allies)
                    if (al.is_alive() && al.position().chebyshev_distance(c) <= (int)info.radius) { friendly = true; break; }
                if (me.position().chebyshev_distance(c) <= (int)info.radius) friendly = true;
                if (!friendly && hits > best_hits) { best_hits = hits; best_c = c; }
            }
            if (best_hits >= min_hits && a.use(best_c)) return true;
        }
    } catch (const std::exception&) {}
    return false;
}

// Spend this turn's spells and attack on an enemy (stuns first). Does not use the move.
bool Bot::fire_at(const cambc::champion& tgt) {
    if (g_replay_repairs && g_enemy_spawn->is_set(tgt.position())) return false;
    auto& me = cambc::self();
    bool acted = false;
    if constexpr (sequences::healthy != 0 || sequences::injured != 0) if (map_strategy::use_v42()) {
        const int order = me.health() * 2 < me.max_health() ? sequences::injured : sequences::healthy;
        if (order != 0 && cambc::fuel_remaining() > 24000) {
            // Recheck SDK allowances and target life after every successful step.
            // Failed/hidden-target actions fall back without inventing state.
            auto attack = [&]() {
                try {
                    if (tgt.is_alive() && tgt.health() > 0 && me.can_attack() && in_reach(tgt)) {
                        me.attack(tgt); acted = true;
                    }
                } catch (const std::exception&) {}
            };
            auto spell = [&]() {
                if (!me.can_cast() || !tgt.is_alive() || tgt.health() <= 0) return;
                for (auto& a : me.abilities()) {
                    if (!a.is_ready()) continue;
                    try {
                        if (a.is_attack_reset() && !me.can_attack()) {
                            if (a.use()) { acted = true; return; }
                        } else if (a.can_target_enemies() && (a.is_damage() || a.is_cc())) {
                            if (a.use(tgt)) { acted = true; return; }
                        }
                    } catch (const std::exception&) {}
                }
                if (!acted && aoe_cast(1)) acted = true;
            };
            if (order == 1 || order == 3) { attack(); spell(); attack(); }
            else { spell(); attack(); }
            if (acted && order == 3) disengage_round=(int)cambc::round_number()+1;
            if (acted) return true;
        }
    }
    // Attack reset in fights: hit, reset, hit again (double Strength) unless a stun is ready.
    if (PVP_RESET && me.can_cast() && me.can_attack() && in_reach(tgt)) {
        bool stun_ready = false, reset_ready = false;
        for (auto& a : me.abilities()) {
            if (!a.is_ready()) continue;
            if (a.is_cc() && a.can_target_enemies()) stun_ready = true;
            if (a.is_attack_reset()) reset_ready = true;
        }
        if (reset_ready && !stun_ready) {
            try {
                me.attack(tgt);
                for (auto& a : me.abilities())
                    if (a.is_attack_reset() && a.is_ready() && me.can_cast() && !me.can_attack()) {
                        if (a.use() && me.can_attack() && tgt.is_alive() && tgt.health() > 0) me.attack(tgt);
                        break;
                    }
                return true;
            } catch (const std::exception&) { return true; }
        }
    }
    if (aoe_cast(2)) acted = true;   // 2+ enemies in one blast beats the single-target spell (2 x 1.4 F > 2 F)
    if (me.can_cast() && !acted)
        for (int pass = 0; pass < 2 && !acted; ++pass)
            for (auto& a : me.abilities()) {
                if (!a.is_ready() || !a.can_target_enemies()) continue;
                if (TEAMFIGHT ? (pass == 0 ? !a.is_cc() : !a.is_damage()) : (pass == 1 || !(a.is_damage() || a.is_cc()))) continue;
                try { if (a.use(tgt)) { acted = true; break; } } catch (const std::exception&) {}
            }
    if (!acted && aoe_cast(1)) acted = true;   // single-target spell unavailable: the area spell still deals 1.4 x Focus
    try { if (me.can_attack() && in_reach(tgt)) { me.attack(tgt); acted = true; } } catch (const std::exception&) {}
    return acted;
}

// Walled-in altar: nobody can walk there to lock or contest it. Hop in with a crystal,
// tribute, then recall out (recall also heals and lets us shop).
bool Bot::private_altar_turn(const char*& act) {
    if (!TELEPORT || privates.empty()) return false;
    auto& me = cambc::self();
    const vec2 pos = me.position();
    for (const auto& pa : privates) {
        if (!pa.inside.is_set(pos)) continue;
        if (me.gem_count() > 0) {
            if (dist(pos, pa.altar) <= cambc::constants::submit_gems_range && !enemy_locked(pa.altar)) {
                act = "tribute_private"; me.submit_gems(pa.altar); return true;
            }
            cambc::bitboard goals = tiles_around(pa.altar, cambc::constants::submit_gems_range) & pa.inside;
            if (move_towards_closest(goals)) { act = "walk_private"; return true; }
        }
        act = "recall_private"; me.recall(); return true;
    }
    return false;
}

// An enemy channelling a tribute next to an altar: our lock cancels the channel outright.
bool Bot::lock_snipe(const char*& act) {
    if (!LOCK_SNIPE) return false;
    auto& me = cambc::self();
    const vec2 pos = me.position();
    try {
        auto& lockc = me.consumables()[cambc::consumable_type::altar_lock];
        if (lockc.count() == 0) return false;
        for (const auto& e : g_enemies) {
            if (!e.is_visible() || !e.is_submitting_gems()) continue;
            for (auto altar : cambc::map::altars().positions()) {
                if (dist(e.position(), altar) > cambc::constants::submit_gems_range) continue;
                if (cambc::vision::has_altar_lock(altar) || dist(pos, altar) > 2) continue;
                if (lockc.use(altar)) { act = "lock_snipe"; return true; }
            }
        }
    } catch (const std::exception&) {}
    return false;
}

// Gem stealing: chase a visible enemy carrying a fat bag when the fight is not against us.
bool Bot::hunt_carrier(const char*& act) {
    if (!GEM_HUNT) return false;
    auto& me = cambc::self();
    const vec2 pos = me.position();
    if (me.health() < me.max_health() * HUNT_HP || me.gem_count() >= (unsigned)BANK_AT) return false;
    const auto enemies = g_enemies;
    int foes = 0, friends = 1;
    for (const auto& e : enemies) if (e.is_visible() && e.is_alive() && dist(pos, e.position()) <= 6) ++foes;
    for (const auto& a : g_allies)
        if (a.position() != pos && dist(pos, a.position()) <= 6) ++friends;
    if (foes > friends) return false;
    const cambc::champion* prey = nullptr;
    unsigned prey_gems = 0;
    for (const auto& e : enemies) {
        if (!e.is_visible() || !e.is_alive() || dist(pos, e.position()) > HUNT_RANGE) continue;
        if (cambc::map::spawn_region(team::enemy).is_set(e.position())) continue;   // safe at home
        const unsigned g = gems_of(e);
        if (g >= (unsigned)HUNT_MIN_GEMS && g > prey_gems) { prey = &e; prey_gems = g; }
    }
    if (!prey) return false;
    if (me.can_attack() && in_reach(*prey)) { act = "hunt_hit"; me.attack(*prey); return true; }
    if (move_towards_closest(tiles_around(prey->position(), g_range))) { act = "hunt"; return true; }
    return false;
}

// Contest: an enemy standing on a cleared camp region is capturing it. Stepping onto the
// region resets their 5-round timer (and lets us take it if they leave).
bool Bot::contest_capture(const char*& act) {
    if (!CONTEST) return false;
    auto& me = cambc::self();
    const vec2 pos = me.position();
    if (me.health() < me.max_health() * CONTEST_HP) return false;
    if (CAREFUL_PVP && pvp_foes > pvp_friends) return false;   // do not walk into a losing fight
    for (const auto& e : g_enemies) {
        if (!e.is_visible() || !e.is_alive()) continue;
        const int gi = group_at(e.position());
        if (gi < 0 || dist(pos, e.position()) > 8) continue;
        // Only regions whose camps are all dead (a capture is in progress).
        bool alive = false;
        for (const auto& v : g_cv) if (v.group == gi) { alive = true; break; }
        if (alive) continue;
        const auto& tiles = info[gi].tiles;
        if (std::find(tiles.begin(), tiles.end(), pos) != tiles.end()) { act = "contest_hold"; return true; }
        cambc::bitboard goals; goals.clear();
        for (auto p : tiles) goals.set(p);
        if (move_towards_closest(goals)) { act = "contest"; return true; }
    }
    return false;
}

// Wards: free vision. Park one towards where we are going.
void Bot::place_ward_towards(vec2 target) {
    if (!WARDS) return;
    auto& me = cambc::self();
    try {
        if (me.ward_cooldown() > 0) return;
        vec2 best = me.position();
        int best_d = dist(best, target);
        for (auto t : me.ward_placement_tiles().positions())
            if (dist(t, target) < best_d) { best_d = dist(t, target); best = t; }
        const auto wards = me.ward_positions();
        if (!wards.empty() && dist(wards.back(), target) <= best_d) return;   // already watching it
        me.place_ward(best);
    } catch (const std::exception&) {}
}

namespace {
// TRACE: one line per champion turn saying what it ended up doing.
struct TurnLog {
    const char* act = "idle";
    int tgt = -1;
    ~TurnLog() {
        policy::end(act);
        if (!TRACE) return;
        auto& me = cambc::self();
        std::cout << "A r" << cambc::round_number() << " " << cambc::to_string(me.champion_name())
                  << " " << act << " tgt" << tgt << " pos" << cambc::to_string(me.position())
                  << " hp" << (int)me.health() << " gems" << me.gem_count() << " gold" << me.gold_count()
                  << " fuel" << cambc::fuel_remaining();
        for (int i = 0; i < g_np; ++i) std::cout << " " << g_prof[i].first << "=" << g_prof[i].second;
        std::cout << '\n';
        g_np = 0;
    }
};
}  // namespace

void Bot::play_turn() {
    tune::init();
    const auto& strategy=map_strategy::policy();
    const auto LONE_FLEE=strategy.lone_flee;
    const auto LONE_FOES=strategy.lone_foes;
    const auto RALLY=strategy.rally;
    const auto RESPAWN_GATE_BASE=strategy.respawn_gate;
    champion_maps::begin();
    policy::begin();
    TurnLog log;
    auto& me = cambc::self();
    if (!initialised) {
        if (!me.is_alive()) { log.act = "dead"; buy_items(); return; }
        init_static();
        if (!initialised) return;   // staged init: finish it next turn
    }

    if (!me.is_alive()) {            // dead champions can still shop
        if (was_alive) {             // first dead turn: remember where we last stood (the place that killed us)
            death_sites[death_next] = {last_alive_pos, (int)cambc::round_number() + 1};
            death_next = (death_next + 1) % (int)death_sites.size();
            death_rounds[death_hist % (int)death_rounds.size()] = (int)cambc::round_number();
            ++death_hist;
            was_alive = false;
        }
        log.act = "dead";
        cambc::shared_memory[slot] = std::uint8_t(0);
        buy_items();
        return;
    }
    // Death spiral: this champion keeps dying (enemy squad hunting us as we trickle out of spawn): wait for a squad.
    int RESPAWN_GATE = RESPAWN_GATE_BASE;
    if (strategy.spiral_deaths > 0 && RESPAWN_GATE == 0) {
        int recent = 0;
        const int now_r = (int)cambc::round_number();
        for (int k = 0; k < std::min(death_hist, (int)death_rounds.size()); ++k)
            if (now_r - death_rounds[k] <= strategy.spiral_window) ++recent;
        if (recent >= strategy.spiral_deaths) RESPAWN_GATE = strategy.spiral_gate;
    }
    if (!was_alive) respawn_until = (int)cambc::round_number() + RESPAWN_GATE;   // just respawned
    was_alive = true;
    if (!at_spawn_hint(me.position())) last_alive_pos = me.position();   // not our spawn: that is where we would die
    if (me.is_recalling() || me.is_submitting_gems() || me.is_teleporting()
        || (!me.can_move() && !me.can_attack() && !me.can_cast())) {   // a spell may still be usable
        log.act = me.is_recalling() ? "recalling" : me.is_submitting_gems() ? "tributing" : "busy";
        return;
    }

    PROF("start");
    if (!chased_last) chase_streak = 0;   // streak only counts consecutive chase turns
    chased_last = false;
    // Big maps: build the distance field for our current target at the START of the turn, when the
    // whole fuel budget is still available (mid-turn builds pushed turns over the limit).
    if (nav_on() && target_group >= 0 && target_group < (int)info.size() && !nav_get(target_group)
        && !info[target_group].tiles.empty()) {
        cambc::bitboard goals; goals.clear();
        for (auto p : info[target_group].tiles) goals.set(p);
        nav_build(target_group, goals);
    }
    PROF("nav_pre");
    snapshot_camps();
    if constexpr(CHAMPION_MAPS_SINGLE_GROUP>=0) g_enemies.clear();
    if (HEATMAP && (int)cambc::round_number() - heat_decayed >= HEAT_DECAY_TURNS) {
        heat_decayed = (int)cambc::round_number();
        for (auto& h : heat) h *= HEAT_DECAY;
    }
    const vec2 pos = me.position();
    static LinBits own_spawn;   // static terrain: export once instead of a host bitboard per turn
    if (own_spawn.w == 0) own_spawn.load(cambc::map::spawn_region(team::ally));
    const bool at_spawn = own_spawn.test(pos);
    g_lanch = 99.0; g_lanch_foes = 0;
    if ((LANCH_ON || LANCH_GATE || LANCH_RECALL_HP > 0) && !g_enemies.empty() && cambc::fuel_remaining() > 30000)
        g_lanch = lanchester(pos, PVP_FOE_RADIUS, PVP_ALLY_RADIUS + 1, g_lanch_foes);
    observed_incoming=0; observed_cc=0;
    if constexpr (economy::banking || economy::survival || economy::camps || economy::shopping || learned::telemetry) {
        int examined=0;
        for (const auto& enemy : g_enemies) {
            if (++examined>8 || cambc::fuel_remaining()<22000) break;
            try {
                if (!enemy.is_alive() || !enemy.is_visible()) continue;
                const int distance=dist(pos,enemy.position());
                if (distance<=enemy.attack_range()+2) observed_incoming+=enemy.strength();
                for (const auto& ability : enemy.abilities())
                    if (ability.is_cc() && distance<=ability.get<cambc::ability_cc>().range+2) observed_cc+=0.5;
            } catch (const cambc::error&) {}
        }
    }
    if constexpr (learned::telemetry) {
        policy::incoming=observed_incoming; policy::cc_risk=observed_cc;
    }
    if (disengage_round==(int)cambc::round_number() && !at_spawn && retreat_from_danger()) {
        log.act="sequence_retreat"; return;
    }
    // Tavi's passive: shards can be bought anywhere, so spend gold the moment it arrives.
    if (at_spawn || (TAVI_FIELD_SHOP && me.champion_name() == cambc::champion_type::tavi)) buy_items();
    // Recall resolves at turn start; spawn recovery happens at turn END.
    // Leaving immediately would prevent that recovery and repeat low-HP trips.
    if (at_spawn && me.health() < me.max_health() * SPAWN_HEAL_HP) {
        cambc::shared_memory[slot] = std::uint8_t(0);
        log.act = "spawn_heal";
        return;
    }
    // Respawn gate: leave spawn together. Trickling out one by one fed the enemy (Contest: 63-118 deaths a game).
    if (RESPAWN_GATE > 0 && at_spawn && (int)cambc::round_number() < respawn_until) {
        bool foe = false;
        int buddies = 0;
        for (const auto& e : g_enemies) if (e.is_visible() && e.is_alive()) { foe = true; break; }
        for (const auto& a : g_allies) if (a.position() != pos && dist(a.position(), pos) <= 6) ++buddies;
        if (!foe && buddies < strategy.gate_buddies) { log.act = "respawn_wait"; return; }
    }
    PROF("pre_lowhp");
    if (private_altar_turn(log.act)) return;

    // Enemy champions burst ~200-400 in a turn or two: leave earlier when they are around.
    // Took damage since our last turn: a recall started now would be cancelled by the next hit.
    const bool took_dmg = prev_hp > 0 && me.health() < prev_hp - 0.5f;
    last_dmg = prev_hp > 0 ? std::max(0.0f, prev_hp - me.health()) : 0.0f;
    prev_hp = me.health();
    double recall_at = std::max((double)RECALL_HP, FISH_RECALL_HP);   // Fish recalls at median 47% HP
    if constexpr (economy::survival) {
        const auto risk=economy::estimate(me.health(),observed_incoming,observed_cc,5);
        recall_at=std::clamp((double)economy::RECALL_HP_THRESHOLD
            +0.15*economy::DEATH_RISK_W*risk.death
            +0.10*economy::CARRIED_GEM_RISK_W*std::min(1.0,me.gem_count()/100.0),0.05,0.95);
    }
    if (LANCH_RECALL_HP > 0 && g_lanch < LANCH_MIN) recall_at = std::max(recall_at, (double)LANCH_RECALL_HP);
    // Cassi and Issac die together: losing Cassi costs two champions and both bags.
    if (LINKED_CARE && me.champion_name() == cambc::champion_type::cassi) recall_at = std::max(recall_at, CASSI_RECALL_HP);
    if (RECALL_HP_DANGER > RECALL_HP)
        for (const auto& e : g_enemies)
            if (e.is_visible() && e.is_alive() && dist(pos, e.position()) <= 8) { recall_at = RECALL_HP_DANGER; break; }
    // Cassi and Issac share one fate: the pair is only as healthy as its weaker half, so both go home together.
    bool linked_low = false;
    if (champion_maps::retreat_pair()) linked_low=true;
    if (LINKED_PAIR) {
        const auto who_l = me.champion_name();
        if (who_l == cambc::champion_type::cassi || who_l == cambc::champion_type::issac) {
            const auto other = who_l == cambc::champion_type::cassi ? cambc::champion_type::issac : cambc::champion_type::cassi;
            float worst = me.health() / me.max_health();
            for (const auto& a : g_allies) {
                try {
                    if (a.champion_name() == other && a.is_alive() && a.max_health() > 0) worst = std::min(worst, a.health() / a.max_health());
                } catch (const std::exception&) {}
            }
            linked_low = linked_low || worst < PAIR_RECALL_HP;
        }
    }
    if (!at_spawn && (linked_low || me.health() < me.max_health() * recall_at)) {
        cambc::shared_memory[slot] = std::uint8_t(0);
        // Move FIRST: ranged attacks and "excludes walking" spells use up the turn's step.
        const char* moved = nullptr;
        // Walking home is as fast as a recall when spawn is close, and damage cannot cancel it.
        if (WALK_HOME) {
            using it = cambc::item_type;
            const auto ic = me.item_count();
            const bool home = ic[it::home_emblem_of_strength] + ic[it::home_emblem_of_focus] + ic[it::home_emblem_of_health] > 0;
            if (home_dist(pos) <= (home ? 3 : 5)
                && move_towards_closest(cambc::map::spawn_region(team::ally))) moved = "walk_home";
        }
        if (!moved && RETREAT && retreat_from_danger()) moved = "retreat";
        // Something can still hit us: a recall would be cancelled next turn, so walk home instead.
        if (!moved && SAFE_RECALL) {
            bool hit_risk = took_dmg;
            for (const auto& v : g_cv) if (v.str > 0 && v.hp < v.max_hp && dist(pos, v.pos) <= 3) { hit_risk = true; break; }
            for (const auto& e : g_enemies) if (e.is_visible() && e.is_alive() && dist(pos, e.position()) <= 4) { hit_risk = true; break; }
            if (hit_risk && move_towards_closest(cambc::map::spawn_region(team::ally))) moved = "walk_home";
        }
        PROF("lowhp_fire");
    if (KITE) if (const auto* t = pick_target(4)) fire_at(*t);   // whatever the step left us
        if (moved) { log.act = moved; return; }
        log.act = "recall_hp";
        me.recall();
        return;
    }

    PROF("shop");
    // Shopping trip: unspent gold is wasted power. Recall when rich and not mid-fight.
    const bool field_shopper = TAVI_FIELD_SHOP && me.champion_name() == cambc::champion_type::tavi;
    // Fish also recalls to bank: carrying a bag far from home with nothing hitting us (~13 recalls per champion per game).
    static int altar_home = -1;   // an altar next to spawn: a recall is a free trip to the bank
    if (altar_home < 0 && !g_altars.empty()) { altar_home = 1 << 20; for (auto a : g_altars) altar_home = std::min(altar_home, home_dist(a)); }
    const bool fish_bank = FISH_BANK_GEMS > 0 && altar_home >= 0 && altar_home <= FISH_ALTAR_HOME && me.gem_count() >= (unsigned)FISH_BANK_GEMS && home_dist(pos) > FISH_BANK_DIST;
    if ((fish_bank || (SHOP_GOLD > 0 && me.gold_count() >= (unsigned)SHOP_GOLD && me.gem_count() < SHOP_MAX_GEMS)) && !field_shopper && !at_spawn) {
        bool threat = false;
        for (const auto& v : g_cv)
            if (v.hp < v.max_hp && dist(pos, v.pos) <= 4) { threat = true; break; }
        for (const auto& e : g_enemies)
            if (e.is_visible() && dist(pos, e.position()) <= SHOP_THREAT_RADIUS) { threat = true; break; }
        if (!threat) {
            cambc::shared_memory[slot] = std::uint8_t(0);
            log.act = "recall_shop";
            me.recall();
            return;
        }
    }

    PROF("pre_snipe");
    lock_snipe(log.act);   // free action: does not use our move or attack

    PROF("pvp");
    // ---- PvP: fight unless outnumbered and hurt; the whole team hits one marked target ----
    // Shared memory: byte 6 = engage stamp (round), byte 7 = marked enemy (champion type + 1).
    const auto enemies = g_enemies;
    const int now_pvp = (int)cambc::round_number();
    const int stamp_now = now_pvp % 15 + 1;
    const int raw6 = (int)std::uint8_t(cambc::shared_memory[6]);
    const int focus_id = (raw6 >> 4) - 1;
    const int stamp = raw6 & 15;
    const bool engage_fresh = TEAMFIGHT && stamp > 0 && (stamp_now - stamp + 15) % 15 <= ENGAGE_TTL;
    pvp_foes = 0; pvp_friends = 1;
    if (!enemies.empty()) {
        int foes = 0, friends = 1;
        const int foe_r = CAREFUL_PVP ? PVP_FOE_RADIUS : PVP_NORMAL_RADIUS;   // enemies just out of 5 arrive next turn with their burst
        for (const auto& e : enemies) if (e.is_visible() && e.is_alive() && dist(pos, e.position()) <= foe_r) ++foes;
        for (const auto& a : g_allies)
            if (a.position() != pos && dist(pos, a.position()) <= PVP_ALLY_RADIUS) ++friends;
        pvp_foes = foes; pvp_friends = friends;
        if (RALLY && foes >= RALLY_FOES && !at_spawn) {   // outnumbered / heavily engaged: call allies to this cell
            const int cs = std::max(1, (g_w + 15) / 16);
            const int cx = std::min(15, pos.x / cs), cy = std::min(15, pos.y / cs);
            cambc::shared_memory[7] = std::uint8_t((cy << 4) | cx);
            cambc::shared_memory[6] = std::uint8_t((raw6 & 0xF0) | stamp_now);
        }
        if (CASSI_KEEP_RANGE && me.champion_name() == cambc::champion_type::cassi && me.can_move()) {
            int nearest = 99;
            for (const auto& e : enemies)
                if (e.is_visible() && e.is_alive()) nearest = std::min(nearest, dist(pos, e.position()));
            const bool exposed = nearest <= CASSI_DANGER_NEAR || (nearest <= CASSI_DANGER_FAR && friends <= 1);
            if (exposed && retreat_from_danger(6)) { log.act = "cassi_back"; return; }
        }
        for (const auto& e : enemies) {
            if (!e.is_visible() || !e.is_alive()) continue;
            if (dist(pos, e.position()) <= 8) last_enemy_round = now_pvp;
            if (DANGER_SQUADS) {   // remember where enemies roam (ring buffer of 16 sightings)
                sightings[sight_next] = {e.position(), now_pvp};
                sight_next = (sight_next + 1) % 16;
                if (HEATMAP) heat[heat_cell(e.position())] += HEAT_ADD;
            }
        }
        const cambc::champion* tgt = pick_target(4);   // kills, marked target, fat bags, weakest
        // Outnumbered: leave before the stuns land (a stunned champion cannot run).
        const bool finish = tgt && target_killable && in_reach(*tgt);   // a kill in hand: take it
        const bool burst = BURST_EXIT && last_dmg >= BURST_FRAC * me.max_health();   // being focused: leave now
        const bool lone = LONE_FLEE && foes >= LONE_FOES && friends <= 1;
        const bool losing = !finish && (burst || lone || (LANCH_ON && g_lanch_foes > 0 && g_lanch < LANCH_MIN) || (FLEE_OUTNUMBERED
            ? (foes > friends || (foes == friends && me.health() < me.max_health() * EQUAL_FIGHT_HP))
            : (foes > friends && me.health() < me.max_health() * EQUAL_FIGHT_HP)));
        const bool lanch_bad = LANCH_ON && !finish && g_lanch_foes > 0 && g_lanch < LANCH_MIN;
        const bool unsafe_bag = !finish && GEM_SAFETY && me.gem_count() >= (unsigned)SAFE_GEMS && foes >= friends;
        if (tgt && !losing && !unsafe_bag) {
            if (TEAMFIGHT) {
                cambc::shared_memory[6] = std::uint8_t((((int)tgt->champion_name() + 1) << 4) | stamp_now);
            }
            bool acted = fire_at(*tgt);
            // Out of reach: close in rather than drift back to camps while being shot.
            bool tgt_ok = false;   // our hits may have just killed it (dead units throw)
            try { tgt_ok = tgt->is_visible() && tgt->is_alive(); } catch (const std::exception&) {}
            // Careful: only tanks chase, or anyone for a kill this turn; never into more enemies than allies.
            const bool may_chase = !CAREFUL_PVP || ((target_killable || me.max_health() >= CHASE_TANK_HP) && foes <= friends);
            // Same-speed chases rarely connect (Ryth: 233 chase turns, 15 hits): give up after CHASE_MAX turns.
            if (CHASE && may_chase && tgt_ok && chase_streak < CHASE_MAX && me.can_move() && !in_reach(*tgt) && me.health() >= me.max_health() * CHASE_HP
                && move_towards_closest(tiles_around(tgt->position(), g_range))) { ++chase_streak; chased_last = true; log.act = "pvp_chase"; return; }
            // Still have our move after shooting: a ranged champion steps away from melee range.
            if (acted && KITE_STEP && me.can_move() && me.attack_range() >= 3) {
                bool close = false;
                for (const auto& e : g_enemies)
                    if (e.is_visible() && e.is_alive() && dist(pos, e.position()) <= 2) { close = true; break; }
                if (close && retreat_from_danger(2)) { log.act = "pvp_kite"; return; }
            }
            if (acted) { log.act = "pvp"; return; }
        } else if ((losing || unsafe_bag) && foes > 0) {
            // Step first (ranged attacks and some spells forbid walking), then hit back with what is left.
            PROF("pvp_flee");
            const bool fled = retreat_from_danger(unsafe_bag ? 7 : 4);
            bool alive_t = false;
            try { alive_t = tgt && tgt->is_visible() && tgt->is_alive(); } catch (const std::exception&) {}
            if (KITE && alive_t) fire_at(*tgt);
            if (fled) { log.act = unsafe_bag ? "protect_bag" : "pvp_flee"; return; }
        }
    }
    PROF("join");
    // Rally: an ally in trouble wrote its cell; walk there when we are fit, calm and close enough to arrive in time.
    if (RALLY && pvp_foes == 0 && engage_fresh && !at_spawn && me.health() >= me.max_health() * RALLY_HP
        && me.gem_count() < (unsigned)SAFE_GEMS) {
        const int cell = (int)std::uint8_t(cambc::shared_memory[7]);
        if (cell != 0 && me.can_move()) {
            const int cs = std::max(1, (g_w + 15) / 16);
            const vec2 c{(cell & 15) * cs + cs / 2, (cell >> 4) * cs + cs / 2};
            const int dd = dist(pos, c);
            if (dd > cs && dd <= RALLY_RANGE && move_towards_closest(tiles_around(c, 2))) { log.act = "rally"; return; }
        }
    }
    // Answer the engage call: walk to the marked enemy if we can see it and are fit to fight.
    if (JOIN_FIGHT && engage_fresh && me.health() >= me.max_health() * JOIN_HP && me.gem_count() < (unsigned)SAFE_GEMS
        && (!CAREFUL_PVP || pvp_foes <= pvp_friends)) {
        for (const auto& e : enemies) {
            if (!e.is_visible() || !e.is_alive() || (int)e.champion_name() != focus_id) continue;
            if (g_replay_repairs && g_enemy_spawn->is_set(e.position())) continue;
            if (dist(pos, e.position()) > JOIN_RANGE) break;
            if (move_towards_closest(tiles_around(e.position(), g_range))) { log.act = "join_fight"; return; }
            break;
        }
    }
    PROF("pre_hunt");
    if (hunt_carrier(log.act)) return;
    PROF("pre_contest");
    if (contest_capture(log.act)) return;

    PROF("support");
    // Support spells: heal a hurt ally; shield ourselves when taking hits.
    if (packs_actions::enabled()) packs_actions::support();
    for (auto& a : me.abilities()) {
        if (packs_actions::enabled()) break;
        if (!a.is_ready() || !me.can_cast()) continue;
        try {
            if (a.is_heal()) {
                for (const auto& ally : g_allies)
                    if (ally.position() != pos && ally.health() < ally.max_health() * ALLY_HEAL_HP
                        && dist(pos, ally.position()) <= 4 && a.use(ally)) break;
            } else if (USE_SHIELD && a.is_shield() && a.can_target_self()
                       && me.health() < me.max_health() * SELF_SHIELD_HP) {
                a.use();
            }
        } catch (const cambc::error&) {}
    }

    PROF("pre_observe");
    observe_camps();
    // Fuel: while walking to a far camp with no enemies around, keep the choice for a few rounds
    // instead of re-scoring every camp on the map (lanes lost ~14% of turns to fuel).
    PROF("pre_choose");
    int best = -1;
    {
        const int now_c = (int)cambc::round_number();
        bool calm = target_group >= 0 && now_c - choice_round < CHOICE_TTL
                    && ready_round[target_group] <= now_c
                    && dist(pos, info[target_group].tiles[0]) > CHOICE_FAR_DISTANCE
                    && !(target_group == skip_group && now_c < skip_until);
        for (const auto& e : g_enemies) if (calm && e.is_visible()) calm = false;
        if (CHOICE_CACHE && calm) best = target_group;
        else { best = choose_group(); choice_round = now_c; }
    }
    PROF("post_choose");
    // Split capture: capture needs one champion (extra ones do not speed it up). If the camp is dead
    // and an ally already stands on it, move on to the next camp instead of waiting 5 turns.
    if (SPLIT_CAPTURE && best >= 0) {
        const auto& g = info[best];
        const int now_s = (int)cambc::round_number();
        bool on_tile = false, ally_on = false, alive = false, seen = false;
        for (auto p : g.tiles) {
            if (p == pos) on_tile = true;
            if (LOCAL_BITS ? g_vis.test(p) : cambc::vision::visible_tiles().is_set(p)) seen = true;
            for (const auto& a : g_allies) if (a.position() == p && a.position() != pos) ally_on = true;
        }
        for (const auto& v : g_cv) if (v.group == best) { alive = true; break; }
        if (seen && !alive && !on_tile && ally_on && ready_round[best] <= now_s) {
            skip_group = best; skip_until = now_s + 6;
            best = choose_group();
        }
    }
    target_group = best;
    log.tgt = best;
    cambc::shared_memory[slot] = std::uint8_t(best >= 0 ? best + 1 : 0);
    if (best >= 0) {
        // Already watching the camp ourselves: scout the enemies' usual approach instead.
        vec2 ward_to = info[best].tiles[0];
        if (WARD_SCOUT && dist(pos, ward_to) <= 3) {
            int recent = -1;
            for (const auto& sgt : sightings)
                if (sgt.second > recent && dist(sgt.first, pos) <= 12) { recent = sgt.second; ward_to = sgt.first; }
            if (recent < 0 && HEATMAP) {   // no fresh sighting: hottest cell nearby
                float hot = 0;
                for (int dy = -2; dy <= 2; ++dy)
                    for (int dx = -2; dx <= 2; ++dx) {
                        vec2 c{pos.x + dx * 4, pos.y + dy * 4};
                        if (c.x < 0 || c.y < 0 || c.x >= 128 || c.y >= 128) continue;
                        if (heat_at(c) > hot) { hot = heat_at(c); ward_to = c; }
                    }
            }
        }
        place_ward_towards(ward_to);
        refresh_vision();
    }

    PROF("pre_bank");
    // ---- bank gems ----
    int altar_d = 1 << 20;
    for (auto a : g_altars) altar_d = std::min(altar_d, dist(pos, a));
    PROF("bank_fighting");
    bool fighting = false;
    for (const auto& v : g_cv) if (cv_in_reach(v) && v.hp < v.max_hp) { fighting = true; break; }
    const unsigned gems = me.gem_count();
    // Walls can double the real route: budget 2x the straight line plus tribute time.
    const bool endgame = cambc::round_number() + ENDGAME_ROUTE_MULT * altar_d + ENDGAME_SLACK >= cambc::constants::max_rounds;
    const int now_r = (int)cambc::round_number();
    const bool may_bank = now_r >= no_bank_until || endgame;
    // Gem safety: enemies seen recently -> bank smaller bags (a death hands them our gems).
    // Bag size: a trip costs ~2d walking turns, a bag risks g gems -> best bag ~ sqrt(2d/risk) = 9.5 sqrt(d)
    // (equals the old fixed 30 at d = 10; small bags near altars, big bags far away).
    int calm_bank_at = BANK_AT;
    if (ADAPTIVE_BANK) calm_bank_at = std::clamp((int)std::lround(BANK_K * std::sqrt((double)std::max(1, altar_d))), BANK_MIN, BANK_MAX);
    int bank_at = (GEM_SAFETY && now_r - last_enemy_round < DANGER_MEMORY) ? BANK_AT_DANGER : calm_bank_at;
    if constexpr (economy::banking) {
        const auto risk=economy::estimate(me.health(),observed_incoming,observed_cc,std::ceil(gems/10.0)+altar_d);
        bank_at=std::max(1,(int)((bank_at+(economy::ALTAR_TRAVEL_W-1)*altar_d)
            /(1+economy::BANK_RISK_W*risk.death)));
        // Avoid starting a long channel under an observable stun threat.
        if (altar_d<=1 && risk.interrupt*economy::TRIBUTE_INTERRUPT_RISK>0.75 && !endgame)
            bank_at=std::max(bank_at,(int)gems+1);
    }
    // Finish mode: the match is a race to winning_gems TRIBUTED. Gems sitting in five half-full bags do not
    // count (rows: 19 clears = 1254 gems, only 968 banked at the end). When banked + the team's carried
    // gems reach the target, everyone banks now instead of waiting for a "full" bag.
    bool finish_now = false;
    if (FINISH_MODE && gems > 0) {
        const int banked = (int)cambc::global_submitted_gems(team::ally);
        int carried = (int)gems, seen_allies = 0;
        for (const auto& a : g_allies) { try { carried += (int)a.gem_count(); ++seen_allies; } catch (const std::exception&) {} }
        const int unseen = std::max(0, team_n - 1 - seen_allies);
        if (!champion_maps::packs_map()) carried += (int)(ALLY_BAG_ESTIMATE * unseen * (int)gems);   // allies we cannot see are assumed to carry about as much as we do
        finish_now = banked + carried >= (int)cambc::constants::winning_gems - FINISH_SLACK;
        const int remaining=strategy.force_delivery_remaining;
        if(remaining>0 && banked>=(int)cambc::constants::winning_gems-remaining)finish_now=true;
    }
    if (finish_now && may_bank) log.act = "finish";
    bool bank_choice = finish_now || gems >= (unsigned)bank_at || (gems > 0 && (best < 0 || endgame))
        || (gems > 0 && !fighting && altar_d <= BANK_NEAR);
    // Hard finish/endgame and channel/legal gates remain outside the model.
    if constexpr (policy::active) if (may_bank && gems > 0 && !finish_now && !endgame && !fighting && best >= 0) {
        double ranking[2]{};
        for (int b=0; b<2; ++b) {
            policy::Features x{1, (float)b, (float)altar_d/100, (float)gems/100, (float)bank_at/100,
                me.health()/std::max(1.0f,me.max_health()), (float)pvp_foes/5, (float)now_r/2000,
                (float)b*gems/100, (float)b*altar_d/100, (float)bank_choice,
                1.0f-std::clamp((float)(now_r-last_enemy_round)/std::max(1,DANGER_MEMORY),0.0f,1.0f)};
            ranking[b] = policy::score(3, b, b == (int)bank_choice ? 0.6 : 0.4, x, 1.0);
        }
        bank_choice = ranking[1] > ranking[0];
        policy::choose(3, (int)bank_choice);
    }
    // Sticky bank trip: the threshold moves with straight-line altar distance, so a path that first leads away
    // from the altar flipped bank/farm every turn (shortcut: 700 rounds pacing between two tiles).
    if (STICKY_BANK && !bank_choice && !fighting && gems > 0 && now_r - last_bank_round <= 3) bank_choice = true;
    if (may_bank && bank_choice) {
    PROF("bank_choose");
        if (now_r - last_bank_round > 1) { last_altar_dist = 1 << 20; bank_no_gain = 0; bank_stuck = 0; }
        last_bank_round = now_r;
        const bool stable_bank=CHAMPION_MAPS_BANK_ROUTE && champion_maps::packs_map();
        if(stable_bank && bank_lock_beliefs.size()!=g_altars.size())bank_lock_beliefs.resize(g_altars.size());
        int free_d = 1 << 20, locked_d = 1 << 20;
        std::vector<char> lockf(g_altars.size(), 0);
        if (altar_avoid.size() != g_altars.size()) altar_avoid.assign(g_altars.size(), 0);
        for (size_t k = 0; k < g_altars.size(); ++k) {
            // Locks are only visible within vision; skip the engine query for far altars.
            if(stable_bank) {
                const bool visible=LOCAL_BITS?g_vis.test(g_altars[k]):cambc::vision::visible_tiles().is_set(g_altars[k]);
                if(visible)bank_lock_beliefs[k].observe(now_r,enemy_locked(g_altars[k]));
                lockf[k]=bank_lock_beliefs[k].avoid(now_r,CHAMPION_MAPS_LOCK_MEMORY);
            }else lockf[k] = dist(pos, g_altars[k]) <= 9 && enemy_locked(g_altars[k]);
            if (lockf[k]) locked_d = std::min(locked_d, dist(pos, g_altars[k]));
            else free_d = std::min(free_d, dist(pos, g_altars[k]));
        }
        // Private altar: worth the crystal hop when it is not much further than a free altar.
        if (TELEPORT && gems >= (unsigned)bank_at) {
            try {
                auto& tp = me.consumables()[cambc::consumable_type::tp_crystal];
                for (const auto& pa : privates) {
                    const int hop = dist(pos, pa.launch) + 3 + dist(pa.land, pa.altar);
                    const double travel_value=economy::mobility ? economy::TELEPORT_VALUE_W : 1.0;
                    if (tp.count() == 0 || hop/travel_value > std::min(free_d, locked_d + 6) + PRIVATE_SLACK) continue;
                    if (pos == pa.launch) {
                        if (tp.use(pa.land)) { log.act = "teleport"; return; }
                    } else {
                        cambc::bitboard goal; goal.clear(); goal.set(pa.launch);
                        if (move_towards_closest(goal)) { log.act = "walk_launch"; return; }
                    }
                }
            } catch (const std::exception&) {}
        }
        const bool use_locked = free_d > locked_d + LOCKED_DETOUR;
        cambc::bitboard goals; goals.clear();
        for (size_t k = 0; k < g_altars.size(); ++k) {
            const vec2 altar = g_altars[k];
            const bool locked = lockf[k];
            if (locked && !use_locked) continue;
            if (locked) {
                // Break the lock: any champion in attack range can hit it (3 hits clears it).
                try {
                    const auto lk = cambc::vision::altar_lock_at(altar);
                    if (me.can_attack() && dist(pos, lk.position()) <= g_range) {
                        log.act = "break_lock"; me.attack(lk); return;
                    }
                } catch (const std::exception&) {}
            } else if (dist(pos, altar) <= cambc::constants::submit_gems_range) {
                // Drop our own lock first: it blocks enemy tributes but not ours.
                if (OWN_LOCKS && !cambc::vision::has_altar_lock(altar)) {
                    try {
                        auto& lockc = me.consumables()[cambc::consumable_type::altar_lock];
                        if (lockc.count() > 0) lockc.use(altar);
                    } catch (const std::exception&) {}
                }
                bank_stuck = 0; bank_no_gain = 0; last_altar_dist = 1 << 20;
                log.act = "tribute_start"; me.submit_gems(altar); return;
            }
            if (PER_ALTAR_RETRY && now_r < altar_avoid[k]) continue;   // got stuck there recently
            goals |= tiles_around(altar, locked ? std::max(1, g_range) : cambc::constants::submit_gems_range);
        }
        // Real walking distance: head for the altar that is truly closest, via its cached field.
        bool moved = false;
        int path_d = -1;   // walking distance to the altar when known
        if (PER_ALTAR_RETRY && !nav_on()) {   // remember which altar we are heading for
            int bk = -1; double bv = 1 << 20;
            for (size_t k = 0; k < g_altars.size(); ++k) {
                if ((lockf[k] && !use_locked) || now_r < altar_avoid[k]) continue;
                const int v = dist(pos, g_altars[k]);
                if (v < bv) { bv = v; bk = (int)k; }
            }
            bank_altar = bk;
        }
        if (nav_on()) {
            int bk = -1; double bv = 1 << 20;
            for (size_t k = 0; k < g_altars.size(); ++k) {
                if ((lockf[k] && !use_locked) || now_r < altar_avoid[k]) continue;
                const int key = 100000 + 2 * (int)k + (lockf[k] ? 1 : 0);
                const auto* f = nav_get(key);
                if (!f) f = nav_build(key, tiles_around(g_altars[k], lockf[k] ? std::max(1, g_range) : cambc::constants::submit_gems_range));
                double v = f ? nav_at(*f, pos) : dist(pos, g_altars[k]) + 2;   // unbuilt: straight line
                if constexpr (economy::banking) {
                    const auto risk=economy::estimate(me.health(),observed_incoming,observed_cc,std::ceil(gems/10.0));
                    v=economy::ALTAR_ROUTE_COST_W*v+economy::TRIBUTE_INTERRUPT_RISK*risk.interrupt*20;
                    if (HEATMAP) v+=economy::BANK_RISK_W*heat_at(g_altars[k])*4;
                }
                if (v < bv) { bv = v; bk = (int)k; }
            }
            if (bk >= 0) {
                bank_altar = bk;
                if (bv < (1 << 19)) path_d = (int)bv;
                if (const auto* f = nav_get(100000 + 2 * bk + (lockf[bk] ? 1 : 0))) moved = step_by_field(*f);
            }
        }
        // Camp tiles next to an altar are goals for approaching camps, but we cannot stand on them: a camp
        // beside the altar (shortcut) left the nearest goal unenterable and froze the bank walk 2 tiles away.
        if (!moved) { g_mtc_dist = -1; if (BANK_BLOCK_CAMPS) {   // block camps we believe alive (seen or not); hooks lost when every camp position was blocked
                g_camp_spawns.clear();
                for (size_t q = 0; q < info.size(); ++q)
                    if (hp_left[q] > 0 && ready_round[q] <= now_r) for (auto t : info[q].tiles) g_camp_spawns.set(t);
                g_block_camps = true; moved = move_towards_closest(goals & ~cambc::vision::camp_tiles() & ~g_camp_spawns); g_block_camps = false;
            }
            if (!moved) moved = move_towards_closest(goals & ~cambc::vision::camp_tiles()); if (g_mtc_dist >= 0 && g_mtc_dist < 65535) path_d = g_mtc_dist; }
        // Never freeze: if banking makes no progress, go farm for a while and retry later.
        // Progress by walking distance: around walls the path first leads away from the altar, and the
        // straight-line test gave up and turned back every few turns (shortcut: 800 rounds stuck in a loop).
        const int d_now = path_d >= 0 ? path_d : std::min(free_d, locked_d);
        if(stable_bank && bank_altar>=0) {
            const int distance=dist(me.position(),g_altars[bank_altar]);
            bank_no_gain=bank_route_progress.observe(now_r,bank_altar,distance);
        }else if (d_now < last_altar_dist) { last_altar_dist = d_now; bank_no_gain = 0; } else ++bank_no_gain;
        if (!moved) ++bank_stuck; else bank_stuck = 0;
        if (PER_ALTAR_RETRY && bank_altar >= 0 && (bank_stuck >= BANK_STUCK_TURNS || bank_no_gain >= BANK_NO_GAIN)) {
            // Only that altar is the problem: avoid it for a while and try the next one right away.
            if(stable_bank)bank_route_progress.reset();
            altar_avoid[bank_altar] = now_r + BANK_RETRY_WAIT;
            bank_altar = -1;
            bank_stuck = 0; bank_no_gain = 0; last_altar_dist = 1 << 20;
            bool any_left = false;
            for (size_t k = 0; k < g_altars.size(); ++k) if (now_r >= altar_avoid[k]) any_left = true;
            if (!any_left) no_bank_until = now_r + BANK_RETRY_WAIT;   // every altar failed: farm for a while
        } else if (bank_stuck >= BANK_STUCK_TURNS || bank_no_gain >= BANK_NO_GAIN) {
            bank_no_gain = 0;
            no_bank_until = now_r + BANK_RETRY_WAIT;
            bank_stuck = 0; last_altar_dist = 1 << 20;
        }
        if (moved) { log.act = "walk_altar"; return; }
        if (now_r < no_bank_until) { log.act = "bank_giveup"; }
        else { log.act = "stuck_altar"; return; }
    }
    if (best < 0) { log.act = "no_target"; return; }

    PROF("fight");
    // ---- fight ----
    int allies_near = 0;
    if (need_here > 1)
        for (const auto& a : g_allies)
            if (a.position() != pos && dist(a.position(), pos) <= SQUAD_READY_RADIUS) ++allies_near;
    PROF("fight_tgt");
    const bool squad_ready = allies_near + 1 >= need_here;
    if (squad_ready) regroup_wait = 0;

    const CampView* tgt = nullptr;
    for (const auto& v : g_cv) {
        if constexpr(CHAMPION_MAPS_SINGLE_GROUP>=0) {
            if(v.group!=CHAMPION_MAPS_SINGLE_GROUP)continue;
        }
        if (!cv_in_reach(v)) continue;
        if (DANGER_STR > 0 && v.str >= DANGER_STR && v.group != best) continue;   // never pick a fight with a boss camp by accident
        if (!tgt || v.hp < tgt->hp) tgt = &v;
    }
    if (tgt) {
        log.act = tgt->group == best ? "fight" : "fight_stray";
    PROF("fight_cast");
        if (champion_maps::enabled()) { champion_maps::fight(tgt->c); return; }
        if (packs_actions::enabled()) { packs_actions::fight(tgt->c); return; }
        cast_on_camp(tgt->c);
        try {
            if (me.can_attack()) me.attack(tgt->c);
            for (auto& a : me.abilities()) {
                if (a.is_attack_reset() && a.is_ready() && me.can_cast() && !me.can_attack()) {
                    if (a.use() && me.can_attack() && tgt->c.health() > 0) me.attack(tgt->c);
                }
            }
        } catch (const std::exception&) {}
        return;
    }
    PROF("spells4");
    // Spells outrange attacks: open on our target from range 4 once the squad is in place.
    if (squad_ready && me.can_cast())
        for (const auto& v : g_cv)
            if ((v.group == best || v.hp < v.max_hp) && dist(pos, v.pos) <= 4)
                if (cast_on_camp(v.c)) break;

    PROF("pre_approach");
    // Collectors: casters stand on the capture tile (reward and gold split among those present, so gold
    // concentrates into Focus on the champions that kill); melee champions kill the camp and move on.
    if (COLLECTORS && me.attack_range() <= 1 && best >= 0 && ready_round[best] <= (int)cambc::round_number()) {
        bool alive = false;
        for (const auto& v : g_cv) if (v.group == best) { alive = true; break; }
        if (!alive) {
            bool ranged_near = false;
            for (const auto& a : g_allies) {
                try {
                    if (a.is_alive() && a.attack_range() >= 3 && dist(a.position(), info[best].tiles[0]) <= COLLECTOR_RADIUS) { ranged_near = true; break; }
                } catch (const std::exception&) {}
            }
            if (ranged_near) {
                skip_group = best; skip_until = (int)cambc::round_number() + CAPTURE_SKIP_TURNS;
                log.act = "leave_to_collector";
                return;
            }
        }
    }
    // Do not walk into a camp hurt: 55-60% of our deaths before round 300 were camp monsters with no enemy champion near,
    // and a recall started inside the fight is cancelled by the next hit. Heal first (recall heals fully at spawn).
    if (CAMP_ENTER_HP > 0 && !at_spawn && !took_dmg && !me.is_recalling() && best >= 0 && ready_round[best] <= (int)cambc::round_number()
        && hp_left[best] > 0 && me.health() < me.max_health() * CAMP_ENTER_HP && dist(pos, info[best].tiles[0]) > 4) {
        bool foe_near = false;
        for (const auto& e : g_enemies) if (e.is_visible() && e.is_alive() && dist(pos, e.position()) <= 6) { foe_near = true; break; }
        if (!foe_near) {
            cambc::shared_memory[slot] = std::uint8_t(0);
            log.act = "recall_before_camp";
            me.recall();
            return;
        }
    }
    // ---- approach ----
    // Centre: never walk in alone (we got picked off one by one); wait outside until the squad is here.
    if (CENTRE_REGROUP && !squad_ready && is_mid(best) && walk_dist(best, pos) <= REGROUP_DIST
        && regroup_wait < REGROUP_MAX) {
        ++regroup_wait;
        log.act = "regroup";
        if (const auto* t = pick_target(4)) fire_at(*t);   // still shoot whatever comes close
        return;
    }
    PROF("approach_goals");
    const auto& g = info[best];
    cambc::bitboard goals; goals.clear();
    if (ready_round[best] > (int)cambc::round_number()) {
        // Respawning: wait next to it, never on a spawn tile (that would delay the respawn).
        for (auto p : g.tiles) goals |= tiles_around(p, 2);
        for (auto p : g.tiles) goals.set(p, false);
        // Ambush: wait hidden in a bush (enemies outside cannot see or target us).
        if (BUSH_AMBUSH) {
            const cambc::bitboard hide = goals & cambc::map::bushes();
            if (!hide.is_empty()) goals = hide;
        }
        const bool on_tile = std::find(g.tiles.begin(), g.tiles.end(), pos) != g.tiles.end();
        if (!on_tile && goals.is_set(pos)) { log.act = "wait_respawn"; return; }
    } else {
        for (auto p : g.tiles) goals.set(p);
    }
    if (champion_maps::enabled()) {
        cambc::bitboard stand;
        for (const auto& v:g_cv) if(v.group==best && v.hp>0)stand|=champion_maps::standoff(v.c);
        if (!stand.is_empty())goals=stand;
    }
    const bool on_capture = std::find(g.tiles.begin(), g.tiles.end(), pos) != g.tiles.end();
    // Solo capture (map role): among champions on site, only the lowest champion id captures; the others leave at once
    // and start the next camp while the capturer stands its 5 rounds. The capturer receives the whole reward.
    if (strategy.solo_capture && !on_capture && ready_round[best] <= (int)cambc::round_number()) {
        bool alive = false;
        for (const auto& v : g_cv) if (v.group == best) { alive = true; break; }
        if (!alive && (LOCAL_BITS ? g_vis.test(g.tiles[0]) : true)) {
            const int mine = (int)me.champion_name();
            bool other_captures = false;
            for (const auto& a : g_allies) {
                try {
                    if (a.is_alive() && (int)a.champion_name() < mine && dist(a.position(), g.tiles[0]) <= 4) { other_captures = true; break; }
                } catch (const std::exception&) {}
            }
            if (other_captures) {
                skip_group = best;
                skip_until = (int)cambc::round_number() + DEAD_SKIP_TURNS;
                log.act = "leave_to_capturer";
                return;
            }
        }
    }
    // Dead camp whose capture tiles are all taken by allies: we cannot help (extra champions do not
    // speed a capture) -> leave it for a few rounds. Was 145 "stuck" turns in 4 test games.
    if (DEAD_CAMP_LEAVE && !on_capture && ready_round[best] <= (int)cambc::round_number()) {
        bool alive = false, free_tile = false;
        for (const auto& v : g_cv) if (v.group == best) { alive = true; break; }
        if (!alive)
            for (auto p : g.tiles) {
                if (!(LOCAL_BITS ? g_vis.test(p) : cambc::vision::visible_tiles().is_set(p))) { free_tile = true; break; }   // cannot see it: assume free
                bool taken = false;
                for (const auto& a : g_allies) if (a.position() == p) { taken = true; break; }
                if (!taken) { free_tile = true; break; }
            }
        if (!alive && !free_tile) {
            skip_group = best;
            skip_until = (int)cambc::round_number() + DEAD_SKIP_TURNS;
            log.act = "leave_dead";
            return;
        }
    }
    // A successful move can still oscillate around an unreachable objective.
    // Only consecutive approach turns count, so combat/capture time is excluded.
    if (g_replay_repairs && !on_capture) {
        const int travel_round=(int)cambc::round_number();
        int remaining=1000000;
        for(auto tile:g.tiles)remaining=std::min(remaining,dist(pos,tile));
        if(ready_round[best]<=travel_round && camp_travel.stalled(best,travel_round,remaining)) {
            camp_avoid_until[best]=travel_round+50;
            target_group=-1;choice_round=-100;
            cambc::shared_memory[slot]=std::uint8_t(0);
            log.act="change_stalled_camp";return;
        }
    }
    // Camp-start gate: enemies near a live camp that out-power us (Lanchester) -> pick another camp for a while.
    if (LANCH_GATE && !on_capture && ready_round[best] <= (int)cambc::round_number() && dist(pos, g.tiles[0]) > 2
        && !g_enemies.empty() && cambc::fuel_remaining() > 25000) {
        int nf = 0;
        const double r = lanchester(g.tiles[0], LANCH_CAMP_R, LANCH_CAMP_R, nf);
        if (nf > 0 && r < LANCH_MIN) {
            skip_group = best; skip_until = (int)cambc::round_number() + LANCH_SKIP;
            target_group = -1; choice_round = -100;
            cambc::shared_memory[slot] = std::uint8_t(0);
            log.act = "camp_gate";
            return;
        }
    }
    bool moved = false;
    // Far from a live camp: follow its cached field (cheap); close in, keep the exact search.
    if (nav_on() && ready_round[best] <= (int)cambc::round_number() && walk_dist(best, pos) > 4) {
        const auto* f = nav_get(best);
        if (!f) f = nav_build(best, goals);
        if (f) moved = step_by_field(*f);
    }
    PROF("pre_mtc");
    if (!moved) moved = move_towards_closest(goals);
    PROF("post_move");
    log.act = moved ? "walk_camp" : on_capture ? "capturing" : squad_ready ? "stuck_camp" : "wait_squad";
    PROF("post_move_atk");
    if (moved && squad_ready && me.can_attack()) {
        for (const auto& v : g_cv)
            if (v.group == best && cv_in_reach(v)) { try { me.attack(v.c); } catch (const std::exception&) {} break; }
    }
}
