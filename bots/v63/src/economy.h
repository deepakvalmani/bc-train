#pragma once
#include <algorithm>
#include <cmath>
#include <cambc.h>
#include "economy_weights.h"
namespace economy {
struct Risk { double damage=0, death=0, interrupt=0; };
// Observable-threat proxy, not a calibrated probability or hidden-state oracle.
inline Risk estimate(double health, double incoming, double cc, double horizon) {
    Risk r;
    r.damage=std::max(0.0,incoming)*std::clamp(horizon,1.0,24.0);
    r.death=r.damage > 0 ? std::clamp(r.damage/std::max(1.0,health)-0.25,0.0,1.0) : 0;
    r.interrupt=std::clamp(cc*std::min(1.0,horizon/8.0),0.0,1.0);
    return r;
}
inline double delivered_value(double gems, double gold, double turns, double death, double interruption) {
    const double survival=std::clamp(1.0-CAMP_DAMAGE_RISK_W*death,0.0,1.0);
    return (CAMP_VALUE_W*gems*survival*(1.0-0.5*interruption)+0.1*gold)/std::max(1.0,turns);
}
}
