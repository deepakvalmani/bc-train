#pragma once
#include <array>
#include <cstdint>
namespace map_policies {
// Selector values are persisted in draft bytes 1018-1019.
enum class Map : std::uint8_t { unknown=0, ambush, collision, contest, corners, eight, elkring, expanse, fragment, interlock, lanes, monolith, packs, pilgrimage, rows, rushbait_v2, stampede, swirl };
static_assert(int(Map::swirl)<256);
static_assert(4+2*506<=1016); // group distances cannot overlap the altar plan or selector
struct Facts { int width,height,team_size,groups,walls,holes,altars,bushes; };
inline bool equal(Facts a,Facts b) {
    return a.width==b.width && a.height==b.height && a.team_size==b.team_size && a.groups==b.groups
        && a.walls==b.walls && a.holes==b.holes && a.altars==b.altars && a.bushes==b.bushes;
}
inline Map identify(Facts f) {
    if(equal(f,{100,100,5,12,540,1832,4,132}))return Map::ambush;
    if(equal(f,{41,41,3,20,84,60,2,222}))return Map::collision;
    if(equal(f,{50,50,5,14,40,0,2,26}))return Map::contest;
    if(equal(f,{71,71,5,30,44,84,5,60}))return Map::corners;
    if(equal(f,{41,30,5,8,36,22,1,24}))return Map::eight;
    if(equal(f,{30,30,5,10,0,36,2,36}))return Map::elkring;
    if(equal(f,{80,80,3,24,224,16,10,0}))return Map::expanse;
    if(equal(f,{30,30,3,6,24,320,2,24}))return Map::fragment;
    if(equal(f,{40,40,4,14,76,16,4,38}))return Map::interlock;
    if(equal(f,{90,30,5,42,0,76,18,144}))return Map::lanes;
    if(equal(f,{50,50,5,22,98,0,6,66}))return Map::monolith;
    if(equal(f,{31,31,3,8,0,0,6,62}))return Map::packs;
    if(equal(f,{50,65,5,23,0,654,4,152}))return Map::pilgrimage;
    if(equal(f,{50,50,4,9,214,0,2,142}))return Map::rows;
    if(equal(f,{30,80,4,18,80,142,2,120}))return Map::rushbait_v2;
    if(equal(f,{60,50,5,13,0,610,2,456}))return Map::stampede;
    if(equal(f,{45,30,4,22,30,354,2,14}))return Map::swirl;
    return Map::unknown;
}
struct Policy {
    bool v42_settings=false, explicit_draft=false;
    std::array<int,11> draft{3,4,10,9,0,2,7,6,1,8,5};
    float recall_hp=0.48f, pair_recall_hp=0.50f, burst_frac=0.3f, equal_fight_hp=0.6f, heat_danger=3.0f;
    bool linked_pair=true, cassi_keep_range=true, flee_outnumbered=true;   // Cassi+Issac are over half of our late deaths (linked: one death costs two champions)
    int safe_gems=15, bank_at_danger=10, bank_min=8, bank_max=55, bank_near=5, finish_slack=15;
    double bank_k=5.0, squishy_centre_mult=0.15, tank_centre_mult=1.5;
    double team_soak=0.5, squad_soak=0.6, clear_rate=1.0, gold_only_scale=1.0;
    bool path_distance=false, skip_unreachable=false;
    int force_delivery_remaining=0;
    // Map roles: farm only camps clearly on our side of a symmetric map (no trek to the enemy half or the monolith).
    bool home_only=false; int home_margin=3; double home_proj=0.53;   // home = projection on spawn->spawn line <= home_proj
    // One champion captures (gets the whole reward, fewer bank trips); the rest move straight on to the next camp.
    bool solo_capture=true;   // one champion captures, the rest start the next camp (Nyx spends 2x the time capturing and clears 1.6x the camps)
    // Fuel: score only the K nearest camp groups per decision (0 = all). Falls back to all groups when none is usable.
    int near_k=0;
    // Avoid camps near where this champion recently died (only where measured useful: Contest, 131 repeat deaths vs Mite).
    bool death_memory=false;
    // Alone (<=1 ally in reach) against 3+ foes: leave at any HP. Top teams die almost only when nearly dead; we die at high HP while alone.
    bool lone_flee=false;
    // per-map camp-choice numbers (tools/pm_tune.py); defaults = v45 global values
    double gem_w=1.8, gold_w=0.8, camp_overhead=5.0;
    float join_mult=2.0f, overstaff_mult=0.097f, wait_claimed_mult=0.1f, sticky_mult=1.5f;
    int lone_foes=3;            // foes needed to trigger lone_flee
    bool rally=false;           // a champion hit by 2+ foes calls nearby healthy allies to its cell
    int respawn_gate=0;         // rounds to wait at spawn after a death until an ally is beside us
    int gate_buddies=1;         // allies that must stand beside us before we leave spawn during the gate (Contest: leave as a squad of 3+)
    int spiral_deaths=0;        // death-spiral breaker: after this many own deaths within spiral_window rounds, use a respawn gate even if respawn_gate=0 (0 = off)
    int spiral_gate=60;         // gate length (rounds) while in a death spiral
    int spiral_window=400;      // look-back window (rounds) for the death count
};
inline Policy accepted(){return {};}
// Website loss screen: retain this overlay only on maps that improved.
inline Policy website_race(){auto p=accepted();p.linked_pair=true;p.cassi_keep_range=true;p.flee_outnumbered=true;p.pair_recall_hp=0.50f;p.clear_rate=1.5;p.gold_only_scale=1.0;return p;}
inline Policy measured_v42() {
    Policy p;p.v42_settings=true;p.recall_hp=0.35f;p.pair_recall_hp=0.35f;p.burst_frac=0.25f;
    p.equal_fight_hp=0.65f;p.heat_danger=2.5f;p.linked_pair=true;p.cassi_keep_range=true;
    p.safe_gems=12;p.bank_at_danger=8;p.bank_min=12;p.bank_k=8.5;p.finish_slack=20;
    p.squishy_centre_mult=0.10;p.tank_centre_mult=1.8;return p;
}
// Each named function is an executable policy, not a claim that every field was optimized.
// Winning controls retain their measured settings while weak-map changes are screened together.
inline Policy ambush() {auto p=website_race();p.path_distance=true;p.skip_unreachable=true;p.gold_only_scale=1.0;return p;}
inline Policy collision() {auto p=accepted();p.draft={3,4,10,9,0,2,7,6,1,8,5};p.respawn_gate=25;p.lone_foes=2;p.lone_flee=true;p.spiral_deaths=3;return p;}
// 19 Oct ladder: Contest 83 deaths/game, every death to an enemy squad as we trickled out of spawn one by one (0 gems). Leave spawn as a squad of 3+. (Local test vs v36/v38: gate alone 19.7 deaths, flee alone 19.0, both 44, neither 9.7: weak local bots cannot judge it, so the gate is pinned in pm_train.)
inline Policy contest() {auto p=accepted();p.draft={3,4,10,9,0,2,7,6,1,8,5};p.death_memory=true;p.respawn_gate=80;p.gate_buddies=3;return p;}
inline Policy corners() {auto p=measured_v42();p.explicit_draft=true;p.draft={9,0,4,3,10,2,7,6,1,8,5};return p;}
inline Policy eight() {auto p=accepted();p.draft={3,4,10,9,0,2,7,6,1,8,5};p.lone_flee=true;p.spiral_deaths=3;return p;}
inline Policy elkring() {auto p=website_race();p.draft={3,4,10,9,0,2,7,6,1,8,5};return p;}
inline Policy expanse() {auto p=website_race();p.explicit_draft=true;p.draft={3,9,2,4,10,0,7,6,1,8,5};return p;}
inline Policy fragment() {auto p=website_race();p.draft={3,4,10,9,0,2,7,6,1,8,5};p.lone_flee=true;p.respawn_gate=25;p.lone_foes=2;p.lone_flee=true;p.spiral_deaths=3;return p;}
inline Policy interlock() {auto p=accepted();p.draft={3,4,10,9,0,2,7,6,1,8,5};p.lone_flee=true;p.spiral_deaths=3;return p;}
inline Policy lanes() {auto p=accepted();p.explicit_draft=true;p.draft={3,8,4,10,9,0,2,7,6,1,5};p.near_k=10;return p;}
inline Policy monolith() {auto p=accepted();p.draft={3,4,10,9,0,2,7,6,1,8,5};return p;}
inline Policy packs() {auto p=measured_v42();p.explicit_draft=true;p.draft={3,4,10,9,0,2,7,6,1,8,5};p.lone_flee=true;return p;}
inline Policy pilgrimage() {auto p=accepted();p.draft={3,4,10,9,2,0,7,6,1,8,5};p.lone_flee=true;p.spiral_deaths=3;return p;}
inline Policy rows() {
    // v42 overlay (website_race + custom draft + clear_rate 1.5) made Rows farming fail solo: 1296 rounds vs 705 plain.
    auto p=accepted();p.home_only=true;p.solo_capture=true;p.explicit_draft=true;p.draft={3,9,2,0,4,10,7,6,1,8,5};
    return p;
}
inline Policy rushbait_v2() {auto p=accepted();p.draft={3,4,10,9,0,2,7,6,1,8,5};return p;}
inline Policy stampede() {
    auto p=website_race();p.explicit_draft=true;p.draft={9,0,6,4,10,3,7,2,1,8,5};
    p.team_soak=3.0;p.squad_soak=0.65;p.clear_rate=4.0;p.recall_hp=0.50f;
    p.gold_only_scale=0.03;p.lone_flee=true;p.spiral_deaths=3;return p;
}
inline Policy swirl() {auto p=accepted();p.spiral_deaths=3;return p;}
#include "policy_tuning.h"
inline Policy for_map_untuned(Map id) {
    switch(id) {
    case Map::ambush:return ambush();
    case Map::collision:return collision();
    case Map::contest:return contest();
    case Map::corners:return corners();
    case Map::eight:return eight();
    case Map::elkring:return elkring();
    case Map::expanse:return expanse();
    case Map::fragment:return fragment();
    case Map::interlock:return interlock();
    case Map::lanes:return lanes();
    case Map::monolith:return monolith();
    case Map::packs:return packs();
    case Map::pilgrimage:return pilgrimage();
    case Map::rows:return rows();
    case Map::rushbait_v2:return rushbait_v2();
    case Map::stampede:return stampede();
    case Map::swirl:return swirl();
    default:{auto p=accepted();p.explicit_draft=true;p.draft={3,4,8,9,0,10,2,7,6,1,5};return p;}   // top-team draft: Cassi+Issac, Stellar, Ren, Varg, Ryth
    }
}
inline Policy for_map(Map id) { auto p=for_map_untuned(id); policy_tuning::apply(id,p); return p; }
}
