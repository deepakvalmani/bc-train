#pragma once
#include <cambc.h>
#include <algorithm>
#include <cstdint>
#include <iostream>
#include "pair_model.h"
#include "champion_maps_config.h"

namespace champion_maps {
// Geometry/reward fingerprint of the SDK-observed packs map. The source file's
// independent SHA-256 is recorded in docs/maps/packs.md and inventory.json.
inline constexpr std::uint32_t packs_fingerprint=2066395605u;
// Stampede is a 60x50 open, high-pressure camp map. Its geometry fingerprint is
// pinned from the local published map pool so the draft experiment cannot bleed
// into other maps.
inline constexpr std::uint32_t stampede_fingerprint=1950295051u;
inline std::uint32_t fingerprint() {
    using namespace cambc;
    std::uint32_t hash=2166136261u;
    auto mix=[&](std::uint32_t v){hash=(hash^v)*16777619u;};
    mix(map::width());mix(map::height());
    const auto walls=map::walls(),holes=map::holes(),altars=map::altars(),bushes=map::bushes();
    const auto spawns=map::spawn_region(team::ally)|map::spawn_region(team::enemy);
    for(int y=0;y<map::height();++y)for(int x=0;x<map::width();++x) {
        const vec2 p{x,y};mix(walls.is_set(p)?1:holes.is_set(p)?2:altars.is_set(p)?4:bushes.is_set(p)?8:spawns.is_set(p)?16:0);
    }
    for(const auto& g:map::camp_groups()) {
        mix(g.gem_value());mix(g.gold_value());mix(g.max_respawn_timer());
        for(const auto& c:g.camps()){mix(c.spawn_position().x);mix(c.spawn_position().y);}
    }
    return hash;
}
inline int started=-1;
inline cambc::vec2 origin{};
inline void begin() {
    started=cambc::round_number();
    if(cambc::self().is_alive())origin=cambc::self().position();
}
inline bool current() {return started==(int)cambc::round_number() && cambc::fuel_remaining()>22000;}
inline bool packs_map() {
    if constexpr(!CHAMPION_MAPS_ENABLED)return false;
    static const bool packs=[] {
        std::uint32_t hash=0;
        for(int i=0;i<4;++i)hash|=std::uint32_t(std::uint8_t(cambc::draft_memory[1020+i]))<<(i*8);
        return hash==packs_fingerprint;
    }();
    return packs;
}
inline bool stampede_map() {
    if constexpr(!CHAMPION_MAPS_ENABLED)return false;
    static const bool stampede=[] {
        std::uint32_t hash=0;
        for(int i=0;i<4;++i)hash|=std::uint32_t(std::uint8_t(cambc::draft_memory[1020+i]))<<(i*8);
        return hash==stampede_fingerprint;
    }();
    return stampede;
}
inline bool ambush_map() {
    // The current published Ambush is the only 100x100 map in the pinned pool.
    // This dimension gate is intentionally narrow until its full fingerprint is
    // recorded by the large-map inventory tool.
    return CHAMPION_MAPS_ENABLED && cambc::map::width()==100 && cambc::map::height()==100;
}
inline bool enabled() {
    const auto who=cambc::self().champion_name();
    return packs_map() && (who==cambc::champion_type::cassi || who==cambc::champion_type::issac);
}
inline float pair_health() {
    using namespace cambc;
    auto& me=self();float health=me.health()/me.max_health();
    const auto other=me.champion_name()==champion_type::cassi?champion_type::issac:champion_type::cassi;
    for(const auto& ally:vision::champions(team::ally))try {
        if(ally.champion_name()==other && ally.is_visible() && ally.is_alive())
            health=std::min(health,ally.health()/ally.max_health());
    }catch(const error& e){if(e.code()!=error_code::api_not_in_vision)throw;}
    return health; // Unseen partner health is unknown; never invented.
}
inline bool retreat_pair() {return enabled() && current() && pair_health()<0.45f;}
inline bool in_range(const cambc::camp& target) {
    return target.is_visible() && target.health()>0 && cambc::self().attack_tiles().is_set(target.position());
}
inline bool ready(const cambc::ability& a) {
    if(!current() || !cambc::self().is_alive() || !a.is_ready())return false;
    const bool exclusive=std::visit([](const auto& v){return v.exclusive_with_movement;},*a.info());
    return !exclusive || cambc::self().position()==origin;
}
inline void enter_capture(const cambc::camp& target) {
    using namespace cambc;
    auto& me=self();
    if(!current() || !me.is_alive() || !me.can_move())return;
    const auto group=target.camp_group();
    if(!std::holds_alternative<map::camp_group_reward_available>(group.state()))return;
    auto blocked=map::walls()|map::holes()|map::altars()|map::spawn_region(team::enemy)
        |vision::camp_tiles()|vision::champion_tiles()|vision::teleport_tiles();
    blocked.set(me.position(),false);
    const auto options=blocked.reachable_tiles(me.position(),me.base_stats().base_move_speed)&group.spawn_tiles();
    if(group.spawn_tiles().is_set(me.position()))return;
    for(auto tile:options.positions())if(current() && me.move_absolute(tile)) {
        if constexpr(CHAMPION_MAPS_TRACE)std::cout << "CM_CAPTURE_STEP " << round_number() << ' ' << to_string(me.champion_name()) << std::endl;
        return;
    }
}
// First dash policy is deliberately restricted to harmless groups. Dangerous
// engagement and escape dashes need their own measured survival tests.
inline bool dash_to_harmless(const cambc::camp& target) {
    using namespace cambc;
    auto& me=self();
    if(!enabled() || !current() || me.champion_name()!=champion_type::issac || !me.can_attack()
       || !target.is_visible() || target.health()<=0 || in_range(target) || pair_health()<0.65f)return false;
    bool partner=false;
    for(const auto& ally:vision::champions(team::ally))
        if(ally.is_visible() && ally.is_alive() && ally.champion_name()==champion_type::cassi)partner=true;
    if(!partner || !vision::champions(team::enemy).empty())return false;
    const auto group=target.camp_group();
    for(const auto& c:group.camps())if(c.base_stats().base_strength>0)return false;
    const auto ability=me.abilities()[1];
    if(!ready(ability))return false;
    const auto blocked=map::walls()|map::holes()|map::altars()|map::spawn_region(team::enemy)
        |vision::camp_tiles()|vision::champion_tiles()|vision::teleport_tiles();
    const auto options=ability.valid_tiles()&~blocked;
    for(auto tile:options.positions()) {
        if(tile.chebyshev_distance(target.position())>1)continue;
        if(!current())return false;
        if(ability.use(tile)) {
            if constexpr(CHAMPION_MAPS_TRACE)std::cout << "CM_DASH " << round_number() << ' ' << tile.x << ' ' << tile.y << std::endl;
            return true;
        }
    }
    return false;
}
inline bool fight(const cambc::camp& target) {
    using namespace cambc;
    if(!enabled() || !current())return false;
    auto& me=self();
    try {
        if(!target.is_visible() || target.health()<=0)return false;
        auto abilities=me.abilities();
        const bool cassi=me.champion_name()==champion_type::cassi;
        const auto tiles=target.position();
        pair_model::Observation observation;
        observation.health=target.health();
        const auto items=me.item_count();
        const bool monster=items[item_type::monster_emblem_of_strength]+items[item_type::monster_emblem_of_focus]+items[item_type::monster_emblem_of_health]>0;
        observation.basic=me.strength()*(monster?1.1:1.0);
        observation.attack=me.can_attack() && in_range(target);
        observation.incoming=me.position().chebyshev_distance(tiles)<=target.attack_range()?target.strength():0;
        if(cassi) {
            observation.damage=ready(abilities[0]) && abilities[0].valid_tiles().is_set(tiles);
            if(observation.damage)observation.spell=abilities[0].damage_amount();
            observation.stun=ready(abilities[1]) && abilities[1].valid_tiles().is_set(tiles) && !target.buffs().has_stun();
        }else observation.reset=ready(abilities[0]) && in_range(target);
        const auto plan=pair_model::choose(observation);
        const int round=round_number();
        const double before=target.health();
        int attacks=0,casts=0;
        auto attack=[&] {
            if(current() && me.is_alive() && me.can_attack() && in_range(target)){me.attack(target);++attacks;}
        };
        switch(plan.sequence) {
        case pair_model::Sequence::damage_attack:
            if(ready(abilities[0]) && target.is_visible() && target.health()>0 && abilities[0].use(target))++casts;
            attack();break;
        case pair_model::Sequence::stun_attack:
            if(ready(abilities[1]) && target.is_visible() && target.health()>0 && abilities[1].use(target))++casts;
            attack();break;
        case pair_model::Sequence::reset_attack:
            attack();
            if(current() && me.is_alive() && target.is_visible() && target.health()>0 && in_range(target)
               && !me.can_attack() && ready(abilities[0]) && abilities[0].use())++casts;
            attack();break;
        case pair_model::Sequence::attack:attack();break;
        default:break;
        }
        if(attacks || casts)enter_capture(target);
        if constexpr(CHAMPION_MAPS_TRACE) if(attacks || casts) {
            // Immediate measurements only: other turns must not contaminate damage.
            if(round==(int)round_number()) {
                double after=0;
                if(target.is_visible())after=target.health();
                std::cout << "CM " << round << ' ' << to_string(me.champion_name()) << ' '
                          << int(plan.sequence) << ' ' << plan.damage << ' ' << before-after << ' '
                          << attacks << ' ' << casts << ' ' << fuel_remaining() << std::endl;
            }else std::cout << "CM_DISCONTINUITY " << round << std::endl;
        }
        if(!attacks && !casts)return dash_to_harmless(target);
        return true;
    }catch(const error& e){if(e.code()!=error_code::api_not_in_vision)throw;return false;}
}
// Ranged approach goals for Cassi; only live, observed camps justify standoff.
inline cambc::bitboard standoff(const cambc::camp& camp) {
    cambc::bitboard result;
    if(enabled() && cambc::self().champion_name()==cambc::champion_type::cassi && current()
       && camp.is_visible() && camp.health()>0 && camp.strength()>0) {
        result.draw_chebyshev(camp.position(),3);
        cambc::bitboard inner;inner.draw_chebyshev(camp.position(),2);result&=~inner;
    }
    return result;
}
}

