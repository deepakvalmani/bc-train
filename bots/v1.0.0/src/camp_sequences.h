#pragma once
#include <algorithm>
#include <vector>
#include <array>

// Small, observable one-turn model. Incoming is a threat estimate, not a rollout.
namespace camp_sequences {
struct Target { double hp=0, incoming=0; bool attackable=false; unsigned splash=0; };
struct State { std::vector<Target> targets; double basic=0; bool attack=false; };
struct Action {
    int primary=0, follow=-1, slot=-1, kind=0; // 0 basic, 1 direct/area, 2 reset, 3 shield
    unsigned hit=0, stun=0; double spell=0, protection=0;
};
struct Value { double damage=0, score=0; };
inline Value evaluate(const State& state,const Action& action) {
    std::array<double,8> hp{};
    const unsigned count=std::min<unsigned>(state.targets.size(),hp.size());
    for(unsigned i=0;i<count;++i)hp[i]=state.targets[i].hp;
    unsigned stunned=action.stun;
    auto hit=[&](unsigned mask,double damage) {
        for(unsigned i=0;i<count;++i)if(mask&(1u<<i))hp[i]=std::max(0.0,hp[i]-damage);
    };
    auto attack=[&](int target) {
        if(target<0 || target>=int(count) || hp[target]<=0 || !state.targets[target].attackable)return;
        hit(state.targets[target].splash,state.basic);
    };
    if(action.kind==1)hit(action.hit,action.spell);
    if(state.attack)attack(action.primary);
    if(action.kind==2)attack(action.follow>=0?action.follow:action.primary);
    Value value;
    double incoming=0;
    for(unsigned i=0;i<count;++i) {
        value.damage+=state.targets[i].hp-hp[i];
        if(hp[i]<=0 || (stunned&(1u<<i)))value.score+=state.targets[i].incoming;
        else incoming+=state.targets[i].incoming;
    }
    value.score+=value.damage+std::min(incoming,action.protection);
    return value;
}
}

