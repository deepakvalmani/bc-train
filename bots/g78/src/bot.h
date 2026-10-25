#pragma once
#include <cambc.h>
#include "bank_route.h"
#include "travel_progress.h"
#include <array>
#include <memory>
#include <utility>
#include <vector>

// Static facts about a camp group, computed once (engine queries cost fuel).
struct GroupInfo {
    std::vector<cambc::vec2> tiles;   // original spawn tiles
    std::vector<double> member_hp;    // design health per member (same order as tiles)
    double hp = 0, dmg = 0;           // summed design health / strength
    double gems = 0, gold = 0;
};

// A walled-in altar reachable only with a teleport crystal: walk to `launch`, crystal to `land`.
struct PrivateAltar {
    cambc::vec2 altar, launch, land;
    cambc::bitboard inside;           // tiles walkable from the altar but not from our spawn
};

inline std::array<std::pair<cambc::vec2, int>, 16> make_empty_sightings() {
    std::array<std::pair<cambc::vec2, int>, 16> a{};
    for (auto& x : a) x.second = -1000;
    return a;
}

class Bot {
    bool initialised = false;
    std::vector<char> unreach_grp, unreach_rng;   // camp groups with no walking route from our spawn
    int init_stage = 0; std::size_t info_next = 0;   // staged start-up (see init_static)
    CampTravelProgress camp_travel;
    std::vector<int> camp_avoid_until;
    bool map_path_distance = false; // static per-map setting, cached outside camp scoring
    std::vector<GroupInfo> info;
    std::vector<int> ready_round;     // per group: first round it is believed alive again
    std::vector<double> hp_left;      // per group: remaining health (damage persists while asleep)
    std::vector<std::vector<double>> member_left;   // per group, per member
    std::vector<std::unique_ptr<cambc::distance_field>> gfield;   // per group: walking distance, lazy
    std::vector<std::uint16_t> spawn_dist;          // per group: walking distance from our spawn (draft memory)
    std::vector<PrivateAltar> privates;
    double team_dps = 0, team_hp = 0;
    int team_n = 1;
    int slot = 0;                     // this champion's byte in shared memory
    int target_group = -1;            // sticky camp-group choice (index into info)
    int need_here = 1;                // squad size wanted for the current target
    int bank_stuck = 0;               // consecutive turns banking made no progress
    int no_bank_until = -1;           // farm instead of banking until this round
    int last_altar_dist = 1 << 20;
    int bank_no_gain = 0;             // turns without getting closer to an altar
    int last_bank_round = -10;
    int spawn_hold_until = -1;
    int last_enemy_round = -1000;
    std::array<std::pair<cambc::vec2, int>, 16> sightings = make_empty_sightings();   // recent enemy positions (pos, round)
    int sight_next = 0;
    // Long-term enemy heat map: 4x4-tile cells, decays 10% every 10 rounds.
    std::array<float, 32 * 32> heat{};
    int heat_decayed = 0;
    bool target_killable = false;   // set by pick_target
    int chase_streak = 0; bool chased_last = false;
    int disengage_round = -1;  // One-turn continuation of an explored combat plan.
    double observed_incoming = 0, observed_cc = 0;
    bool team_has_tank = false;     // drafted Ryth, Varg or Marcella
    int regroup_wait = 0;           // turns waiting outside the centre for the squad
    bool is_mid(int i);
    bool is_home_group(int i);
    float prev_hp = -1;             // health at our previous acting turn
    // Death memory: where this champion died recently (a ring of 6 sites) and where it last stood while alive.
    std::array<std::pair<cambc::vec2, int>, 6> death_sites{};
    int death_next = 0; bool was_alive = true; cambc::vec2 last_alive_pos{0, 0};
    int respawn_until = 0;          // respawn gate: wait at spawn for a buddy until this round
    std::array<int, 8> death_rounds{}; int death_hist = 0;   // rounds of our last deaths (death-spiral breaker)
    float last_dmg = 0;             // health lost since our previous acting turn
    int pvp_foes = 0, pvp_friends = 1;   // this turn's local PvP count (0 when no enemy seen)
    int choice_round = -100;        // round choose_group last ran
    std::vector<int> altar_avoid;   // per altar: round until which banking there is avoided
    std::vector<bank_route::LockBelief> bank_lock_beliefs;
    bank_route::Progress bank_route_progress;
    int bank_altar = -1;            // altar we are walking to
    std::vector<int> camp_alt_d;    // per group: straight-line distance to the nearest altar
    int skip_group = -1, skip_until = 0;   // camp an ally is capturing
    static int heat_cell(cambc::vec2 p) { return std::min(31, std::max(0, (int)p.y / 4)) * 32 + std::min(31, std::max(0, (int)p.x / 4)); }
    float heat_at(cambc::vec2 p) const { return heat[heat_cell(p)]; }     // last round an enemy champion was within 8 tiles
    unsigned bought_str = 0, bought_foc = 0, bought_hp = 0;   // power shards bought by stat

    void init_static();
    void buy_items();
    bool cast_on_camp(const cambc::camp& camp);
    int choose_group();
    void observe_camps();
    bool retreat_from_danger(int radius = 4);
    bool fire_at(const cambc::champion& tgt);
    const cambc::champion* pick_target(int range);
    int walk_dist(int group, cambc::vec2 from);
    bool private_altar_turn(const char*& act);
    bool lock_snipe(const char*& act);
    bool hunt_carrier(const char*& act);
    bool contest_capture(const char*& act);
    void place_ward_towards(cambc::vec2 target);

public:
    void play_turn();
};
