#include <cambc.h>
#include "draft.h"
#include "params.h"
#include "champion_maps.h"
#include "map_strategy.h"
#include <algorithm>
#include <array>
#include <cstdint>
#include <iterator>
#include <vector>
#include <iostream>

namespace {

// Draft memory layout (read by every champion at the start of the match):
//   [0] 0xB7 magic, [1] version 1, [2..3] group count n (LE),
//   then n x uint16 LE: walking distance from our spawn to each camp group (65535 = unreachable).
void write_plan() {
    const auto walls = cambc::map::walls() | cambc::map::holes() | cambc::map::altars()
        | cambc::map::spawn_region(cambc::team::enemy);
    cambc::distance_field field;
    cambc::bitboard visited;
    field.compute(walls, cambc::map::spawn_region(cambc::team::ally), visited);
    const auto groups = cambc::map::camp_groups();
    const std::size_t n = std::min<std::size_t>(groups.size(), (cambc::constants::draft_memory_bytes - 12) / 2);
    std::array<std::uint8_t, 1024> buf{};
    buf[0] = 0xB7; buf[1] = 1;
    buf[2] = std::uint8_t(n & 0xFF); buf[3] = std::uint8_t(n >> 8);
    for (std::size_t i = 0; i < n; ++i) {
        std::uint16_t best = 65535;
        for (const auto& c : groups[i].camps()) best = std::min(best, field.get(c.spawn_position()));
        buf[4 + 2 * i] = std::uint8_t(best & 0xFF);
        buf[5 + 2 * i] = std::uint8_t(best >> 8);
    }
    // Reuse this completed terrain search at champion startup. A private altar
    // still takes the original pocket-hop planner; ordinary maps skip a BFS.
    bool all_altars_reachable=true;
    for(auto altar:cambc::map::altars().positions()) {
        cambc::bitboard nearby;
        nearby.draw_chebyshev(altar,cambc::constants::submit_gems_range);
        if((nearby & visited).is_empty()){all_altars_reachable=false;break;}
    }
    buf[1016]=0xA9;
    buf[1017]=all_altars_reachable ? 1 : 0;
    // Last four draft bytes identify the measured map; runtime shared memory remains 8 bytes.
    // Only Packs consumes the full map fingerprint. Avoid surveying every
    // tile of large fallback maps during their constrained draft turns.
    const auto signature=(cambc::map::width()==31 && cambc::map::height()==31)
        ? champion_maps::fingerprint() : 0u;
    for(int i=0;i<4;++i)buf[1020+i]=std::uint8_t(signature>>(8*i));
    buf[1018]=static_cast<std::uint8_t>(map_strategy::identify());
    buf[1019]=0xA7; // versioned map selector; group-distance data ends before byte 1016
    cambc::draft_memory = std::span<const std::uint8_t>(buf.data(), buf.size());
}

}  // namespace

// Map-aware preference order (champion_draft ids: ryth0 vesper1 vendetta2 cassi_issac3 stellar4
// prism5 marcella6 willow7 ren8 varg9 tavi10).
std::vector<int> map_order(std::uint32_t size, const std::vector<cambc::champion_draft>& enemy) {
    static const auto profile=map_policies::for_map(map_strategy::identify());
    {   // Nyx (ladder #2) drafts, read from 25 games on all 21 maps: Cassi+Issac, Stellar, Ren, Ryth, Varg; Vendetta carry on eight/big_world/boss_battle
        const int w = cambc::map::width(), h = cambc::map::height();
        const bool carry_map = (w == 41 && h == 30) || (w == 100 && h == 100) || (w == 50 && h == 41);
        (void)carry_map;
        // 22 Oct top-5 study (24 games each): Vesper 4/5 teams, Heart of Ruin 4/5, Marcella 4/5, Ryth 4/5, Vendetta 3/5; only Fish uses Cassi+Issac
        // (our linked pair died 25 times a game in fights). Order: Vesper, Heart of Ruin, Marcella, Ryth, Vendetta, Ren, Stellar, Prism, Tavi, Willow, Varg, Cassi+Issac.
        static const int TOP5[] = {1, 11, 6, 0, 2, 8, 4, 5, 10, 7, 9, 3};
        return std::vector<int>(std::begin(TOP5), std::end(TOP5));
    }
    if(profile.explicit_draft)return std::vector<int>(profile.draft.begin(),profile.draft.end());
    // Winning drafts per official map, from 233 top-13 ladder games (ids: ryth0 vend2 cassi3 stell4 prism5
    // willow7 ren8 varg9 tavi10). Maps are recognised by size and team size; unknown maps fall through.
    if (TOP_DRAFT) {
        const int w = cambc::map::width(), h = cambc::map::height();
        std::vector<int> top;
        // Kept only where it won both sides vs v29 (expanse, rows, lanes); packs/collision lost both.
        if (w == 80 && h == 80) top.assign(std::begin(DRAFT_EXPANSE), std::end(DRAFT_EXPANSE));            // expanse
        else if (w == 50 && h == 50 && size == 4) top.assign(std::begin(DRAFT_ROWS), std::end(DRAFT_ROWS));   // rows
        else if (w == 90 && h == 30) top.assign(std::begin(DRAFT_LANES), std::end(DRAFT_LANES));     // lanes
        else if (w == 71 && h == 71) top.assign(std::begin(DRAFT_CORNERS), std::end(DRAFT_CORNERS)); // corners: Varg+Ryth hold centre
        if (!top.empty()) {
            for (int id : DRAFT_ORDER) if (std::find(top.begin(), top.end(), id) == top.end()) top.push_back(id);
            return top;
        }
    }
    // Cassi+Issac die together: 37 linked deaths in 15 ladder games (both bags lost) -> last pick.
    std::vector<int> order;
    for (int i = 0; i < DRAFT_OPEN_COUNT; ++i)
        if (!NO_CASSI || DRAFT_OPENER[i] != 3) order.push_back(DRAFT_OPENER[i]);
    int groups = 0, multi = 0, monoliths = 0;
    for (const auto& g : cambc::map::camp_groups()) {
        ++groups;
        if (g.camps().size() >= 2) ++multi;
        for (const auto& c : g.camps()) if (c.is_monolith()) { ++monoliths; break; }
    }
    const int area = cambc::map::width() * cambc::map::height();
    const bool splash_map = monoliths > 0 || (groups > 0 && multi >= groups * DRAFT_SPLASH_RATIO);
    if (splash_map) { for (int i = 0; i < DRAFT_MAP_COUNT; ++i) if (std::find(order.begin(), order.end(), DRAFT_SPLASH[i]) == order.end() && (!NO_CASSI || DRAFT_SPLASH[i] != 3)) order.push_back(DRAFT_SPLASH[i]); }        // Varg splash, then Ryth tank
    else if (area <= DRAFT_SMALL_AREA) { for (int i = 0; i < DRAFT_MAP_COUNT; ++i) if (std::find(order.begin(), order.end(), DRAFT_SMALL[i]) == order.end() && (!NO_CASSI || DRAFT_SMALL[i] != 3)) order.push_back(DRAFT_SMALL[i]); } // small + contested: Ryth first
    else { for (int i = 0; i < DRAFT_MAP_COUNT; ++i) if (std::find(order.begin(), order.end(), DRAFT_LARGE[i]) == order.end() && (!NO_CASSI || DRAFT_LARGE[i] != 3)) order.push_back(DRAFT_LARGE[i]); }                   // big maps: Varg, Vendetta
    // Enemy stacking stuns: Marcella is immune, take her with our last pick.
    int stunners = 0;
    for (auto c : enemy) {
        const int id = (int)c;
        if (id == 3 || id == 10 || id == 0 || id == 5 || id == 8) ++stunners;
    }
    if (COUNTER_STUN && stunners >= DRAFT_STUN_COUNT && size >= 4) order.insert(order.begin() + std::min<std::size_t>(order.size(), size - 1), 6);
    for (int id : DRAFT_ORDER) if (id != 3 || !NO_CASSI) if (std::find(order.begin(), order.end(), id) == order.end()) order.push_back(id);
    if (NO_CASSI) order.push_back(3);
    std::vector<int> unique;
    for (int id : order) if (std::find(unique.begin(), unique.end(), id) == unique.end()) unique.push_back(id);
    for (int id : DRAFT_ORDER) if (std::find(unique.begin(), unique.end(), id) == unique.end()) unique.push_back(id);
    return unique;
}

// Pick the first champion in our preference order that we do not own yet.
void play_draft() {
    static bool planned = false;
    if (DRAFT_MEMORY && !planned) {
        planned = true;
        try { write_plan(); } catch (const std::exception&) {}
    }
    const auto chosen = cambc::draft::current_draft(cambc::team::ally);
    std::uint32_t size = 0;
    try { size = cambc::draft::team_size(); } catch (const std::exception&) {}
    std::vector<int> order(std::begin(DRAFT_ORDER), std::end(DRAFT_ORDER));
    if (MAP_DRAFT) {
        try { order = map_order(size, cambc::draft::current_draft(cambc::team::enemy)); } catch (const std::exception&) {}
    } else if (DRAFT_BY_SIZE && size >= DRAFT_LARGE_SIZE) {
        order.assign(std::begin(DRAFT_ORDER5), std::end(DRAFT_ORDER5));
    }
    for (int id : order) {
        const auto c = static_cast<cambc::champion_draft>(id);
        if (std::find(chosen.begin(), chosen.end(), c) == chosen.end()) {
            cambc::draft::pick(c);
            return;
        }
    }
}
