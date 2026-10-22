#pragma once
#include "champion_maps.h"
#include "camp_sequences.h"

namespace packs_actions {
inline bool enabled() {
    if constexpr(!CHAMPION_MAPS_EXTENDED)return false;
    const auto who=cambc::self().champion_name();
    return (CHAMPION_MAPS_PROFILE<0 || int(who)==CHAMPION_MAPS_PROFILE || int(who)==CHAMPION_MAPS_PROFILE2)
        && champion_maps::packs_map()
        && who!=cambc::champion_type::cassi && who!=cambc::champion_type::issac
        // These one-turn camp overrides lost to identical-draft legacy controls
        // in full games. Keep the measured stronger fallbacks on packs.
        && who!=cambc::champion_type::prism && who!=cambc::champion_type::ren;
}
inline void support() {
    using namespace cambc;
    if(!enabled() || self().champion_name()!=champion_type::willow || !champion_maps::current())return;
    auto& me=self();const auto heal=me.abilities()[0];
    if(!heal.is_heal() || !champion_maps::ready(heal))return;
    const auto valid=heal.valid_tiles();const double amount=heal.heal_amount();
    std::optional<champion> best;double best_score=0;
    for(const auto& ally:vision::champions(team::ally)) {
        if(!champion_maps::current())break;
        if(!ally.is_visible() || !ally.is_alive() || ally.position()==me.position() || !valid.is_set(ally.position()))continue;
        const double hp=ally.health(),max_hp=ally.max_health();
        const double useful=std::min(amount,max_hp-hp);
        // Save casts on scratches; urgent allies have a lower healing threshold.
        if(useful<amount*(hp<max_hp*0.4?0.25:0.75))continue;
        double urgency=1+(1-hp/max_hp);
        if(ally.champion_name()==champion_type::cassi || ally.champion_name()==champion_type::issac)urgency+=0.5;
        const double score=useful*urgency;
        if(score>best_score){best=ally;best_score=score;}
    }
    if(best && champion_maps::ready(heal)) {
        const int round=round_number();const double hp=best->health(),predicted=heal.heal_amount(*best);
        if(heal.use(*best) && round==(int)round_number() && best->is_visible())
            if constexpr(CHAMPION_MAPS_TRACE)std::cout<<"CM_HEAL "<<round<<' '<<predicted<<' '<<best->health()-hp<<std::endl;
    }
}
inline bool harmless_dash(const cambc::camp& target) {
    using namespace cambc;
    auto& me=self();
    if(!champion_maps::current() || !me.can_attack() || champion_maps::in_range(target)
       || me.health()<me.max_health()*0.75f || !vision::champions(team::enemy).empty())return false;
    const auto group=target.camp_group();
    for(const auto& c:group.camps())if(c.base_stats().base_strength>0)return false;
    const auto abilities=me.abilities();
    for(const auto& a:abilities)if(a.is_dash() && champion_maps::ready(a)) {
        const auto blocked=map::walls()|map::holes()|map::altars()|map::spawn_region(team::enemy)
            |vision::camp_tiles()|vision::champion_tiles()|vision::teleport_tiles();
        const auto target_pos=target.position();const auto range=me.attack_range();
        for(const auto tile:(a.valid_tiles()&~blocked).positions()) {
            if(tile.chebyshev_distance(target_pos)>range)continue;
            if(!champion_maps::current())return false;
            if(a.use(tile)) {
                if constexpr(CHAMPION_MAPS_TRACE)std::cout<<"CM_DASH "<<round_number()<<' '<<tile.x<<' '<<tile.y<<std::endl;
                return true;
            }
        }
    }
    return false;
}
inline bool fight(const cambc::camp& target) {
    using namespace cambc;
    if(!enabled() || !champion_maps::current())return false;
    try {
        auto& me=self();const auto who=me.champion_name();
        if(!target.is_visible() || target.health()<=0)return false;
        struct Seen {camp handle;vec2 position;};std::vector<Seen> seen;
        camp_sequences::State state;
        const auto origin=me.position();const auto attack_tiles=me.attack_tiles();
        state.attack=me.can_attack();
        const auto items=me.item_count();
        const bool monster=items[item_type::monster_emblem_of_strength]+items[item_type::monster_emblem_of_focus]+items[item_type::monster_emblem_of_health]>0;
        state.basic=me.strength()*(monster?1.1:1.0); // strength already includes Ryth passive/items
        double before=0;
        const auto group=target.camp_group();
    for(const auto& c:group.camps())if(c.is_visible() && c.health()>0 && seen.size()<8) {
            const auto p=c.position();const double hp=c.health();
            const double incoming=!c.buffs().has_stun() && origin.chebyshev_distance(p)<=c.attack_range()?c.strength():0;
            state.targets.push_back({hp,incoming,attack_tiles.is_set(p),0});seen.push_back({c,p});before+=hp;
        }
        if(seen.empty())return false;
        for(unsigned i=0;i<seen.size();++i)for(unsigned j=0;j<seen.size();++j)
            if(i==j || (who==champion_type::varg && seen[i].position.chebyshev_distance(seen[j].position)<=1))
                state.targets[i].splash|=1u<<j;
        camp_sequences::Action best;camp_sequences::Value best_value;
        vec2 best_centre{};
        auto consider=[&](camp_sequences::Action a,vec2 centre=vec2{}) {
            const auto value=camp_sequences::evaluate(state,a);
            if(value.score>best_value.score+0.001){best=a;best_value=value;best_centre=centre;}
        };
        // Ties preserve basic-only before any spell, across all visible targets.
        for(unsigned i=0;i<seen.size();++i)consider({int(i)});
        const auto abilities=me.abilities();
        for(int slot=0;slot<int(abilities.size());++slot) {
            const auto& a=abilities[slot];
            if(!champion_maps::ready(a))continue;
            // Prism and Ren can reach camps with a no-walk spell one tile before
            // their basic attack. Repeatedly taking that cast delays the approach
            // and was worse than their same-draft controls in full packs games.
            // Once in attack position, retain the spell + basic sequence model.
            if(a.is_attack_reset()) {
                const bool enhanced=a.get<ability_attack_reset>().enhanced_attack;
                for(unsigned i=0;i<seen.size();++i)if(state.targets[i].attackable) {
                    int follow=i;
                    // A basic lethal hit can redirect the reset attack to a second camp.
                    if(state.attack && state.targets[i].hp<=state.basic)
                        for(unsigned j=0;j<seen.size();++j)if(j!=i && state.targets[j].attackable){follow=j;break;}
                    consider({int(i),follow,slot,2,0,enhanced?(1u<<follow):0});
                }
            }else if(a.is_damage() || a.is_cc()) {
                const auto valid=a.valid_tiles();const double spell=a.damage_amount();
                for(unsigned t=0;t<seen.size();++t)if(valid.is_set(seen[t].position))
                    for(unsigned i=0;i<seen.size();++i)
                        consider({int(i),int(t),slot,1,1u<<t,a.is_cc()?(1u<<t):0,spell});
            }else if(a.is_aoe_damage()) {
                const auto info=a.get<ability_aoe_damage>();const double spell=a.damage_amount();
                std::array<bool,256> evaluated{};
                const auto valid=a.valid_tiles().export_linear_buffer();
                const int width=map::width(),height=map::height();
                std::vector<vec2> centres;
                // Camp positions first: every packs cluster fits in radius one
                // around any of its members. Further centres cover edge cases.
                for(const auto& c:seen)centres.push_back(c.position);
                for(const auto& c:seen)for(int dy=-int(info.radius);dy<=int(info.radius);++dy)
                    for(int dx=-int(info.radius);dx<=int(info.radius);++dx) {
                        const vec2 tile{c.position.x+dx,c.position.y+dy};
                        if(std::find(centres.begin(),centres.end(),tile)==centres.end())centres.push_back(tile);
                    }
                for(const auto tile:centres) {
                    if(fuel_remaining()<40000 || !champion_maps::current())break;
                    if(tile.x<0 || tile.y<0 || tile.x>=width || tile.y>=height)continue;
                    const int index=tile.y*width+tile.x;
                    if(!((valid[index>>3]>>(index&7))&1))continue;
                    unsigned mask=0;for(unsigned j=0;j<seen.size();++j)
                        if(tile.chebyshev_distance(seen[j].position)<=info.radius)mask|=1u<<j;
                    if(!mask || evaluated[mask])continue;
                    evaluated[mask]=true;
                    for(unsigned i=0;i<seen.size();++i)consider({int(i),-1,slot,1,mask,info.duration>0?mask:0,spell},tile);
                }
            }else if(a.is_shield()) {
                const double protection=a.shield_amount();
                for(unsigned i=0;i<seen.size();++i)consider({int(i),-1,slot,3,0,0,0,protection});
            }
        }
        if(!champion_maps::current())return false;
        const int round=round_number();int attacks=0,casts=0;
        auto attack=[&](int i) {
            if(champion_maps::current() && me.is_alive() && me.can_attack() && champion_maps::in_range(seen[i].handle)) {
                me.attack(seen[i].handle);++attacks;
            }
        };
        if(best.slot>=0 && best.kind!=2) {
            const auto& a=abilities[best.slot];
            if(champion_maps::ready(a)) {
                if(a.is_aoe_damage())casts+=a.use(best_centre);
                else if(a.is_shield())casts+=a.use();
                else casts+=a.use(seen[best.follow].handle);
            }
        }
        attack(best.primary);
        if(best.kind==2 && champion_maps::current() && !me.can_attack() && champion_maps::ready(abilities[best.slot])
           && champion_maps::in_range(seen[best.follow].handle)) {
            if(abilities[best.slot].use())++casts;
            attack(best.follow);
        }
        if constexpr(CHAMPION_MAPS_TRACE)if(attacks || casts) {
            if(round==(int)round_number()) {
                double after=0;for(const auto& c:seen)if(c.handle.is_visible())after+=c.handle.health();
                std::cout<<"CM "<<round<<' '<<to_string(who)<<' '<<(best.kind==2?4:best.kind==1?2:best.kind==3?5:1)
                         <<' '<<best_value.damage<<' '<<before-after<<' '<<attacks<<' '<<casts<<' '<<fuel_remaining()<<std::endl;
            }else std::cout<<"CM_DISCONTINUITY "<<round<<std::endl;
        }
        if(!attacks && !casts)return harmless_dash(target);
        return true;
    }catch(const error& e){if(e.code()!=error_code::api_not_in_vision)throw;return false;}
}
}

