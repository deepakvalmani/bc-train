#pragma once
#include <algorithm>

// First verified horizon: own action sequence plus one target retaliation.
// No hidden state, opponent rollout, or probability estimate is assumed.
namespace pair_model {
enum class Sequence { wait, attack, damage_attack, stun_attack, reset_attack };
struct Observation {
    double health=0, basic=0, spell=0, incoming=0;
    bool attack=false, damage=false, stun=false, reset=false;
};
struct Plan { Sequence sequence=Sequence::wait; double damage=0, score=0; };
inline Plan choose(Observation s) {
    if(s.health<=0)return {};
    const double basic=s.attack?s.basic:0;
    Plan best;
    auto consider=[&](Sequence sequence,double damage,bool stun) {
        damage=std::min(s.health,damage);
        const double score=damage+((stun || damage>=s.health)?s.incoming:0);
        // Ties retain the simpler sequence and preserve a cooldown.
        if(score>best.score+0.0001)best={sequence,damage,score};
    };
    if(s.attack)consider(Sequence::attack,basic,false);
    if(s.damage)consider(Sequence::damage_attack,s.spell+basic,false);
    if(s.stun && s.incoming>0)consider(Sequence::stun_attack,basic,true);
    if(s.reset)consider(Sequence::reset_attack,basic+s.basic,false);
    return best;
}
}

