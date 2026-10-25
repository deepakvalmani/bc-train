#pragma once
// Track consecutive travel attempts, excluding fights, captures and respawn waits.
struct CampTravelProgress {
    int group=-1, last_round=-100, best_distance=1000000, improved_round=0;
    bool stalled(int selected,int round,int distance) {
        if(selected!=group || round!=last_round+1) {
            group=selected;best_distance=distance;improved_round=round;
        } else if(distance<best_distance) {
            best_distance=distance;improved_round=round;
        }
        last_round=round;
        return round-improved_round>=40;
    }
};
