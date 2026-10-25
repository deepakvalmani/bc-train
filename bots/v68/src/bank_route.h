#pragma once

// Per-champion observations and route progress; no unseen state is asserted.
namespace bank_route {
struct LockBelief {
    bool was_locked=false;
    int observed=-100000;
    void observe(int round,bool locked){was_locked=locked;observed=round;}
    bool avoid(int round,int memory) const {
        return was_locked && round-observed<=memory;
    }
};
struct Progress {
    int destination=-1,best_distance=100000,last_round=-100000,without_gain=0;
    void reset(){*this=Progress{};}
    int observe(int round,int target,int distance) {
        if(target!=destination || round-last_round>1) {
            destination=target;best_distance=distance;without_gain=0;
        }else if(distance<best_distance) {
            best_distance=distance;without_gain=0;
        }else ++without_gain;
        last_round=round;
        return without_gain;
    }
};
}

