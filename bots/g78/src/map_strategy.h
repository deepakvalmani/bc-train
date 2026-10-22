#pragma once
#include "champion_maps.h"
#include "map_policies.h"
namespace map_strategy {
// Draft code identifies directly: newly written draft memory is committed at
// the turn boundary. Champion VMs read the committed selector during gameplay.
inline map_policies::Map identify() {
    return map_policies::Map::unknown;   // general bot: the map pool changes every patch, settings are one global block
    return map_policies::identify({int(cambc::map::width()),int(cambc::map::height()),
        int(cambc::draft::team_size()),int(cambc::map::camp_groups().size()),
        int(cambc::map::walls().count()),int(cambc::map::holes().count()),
        int(cambc::map::altars().count()),int(cambc::map::bushes().count())});
}
inline map_policies::Map current_map() {
    return map_policies::Map::unknown;
    static const auto id=[] {
        const auto raw=std::uint8_t(cambc::draft_memory[1018]);
        if(std::uint8_t(cambc::draft_memory[1019])!=0xA7 || raw>int(map_policies::Map::swirl))
            return map_policies::Map::unknown;
        const auto selected=static_cast<map_policies::Map>(raw);
        if(selected==map_policies::Map::packs && !champion_maps::packs_map())
            return map_policies::Map::unknown;
        return selected;
    }();
    return id;
}
inline const map_policies::Policy& policy() {
    static const auto value=map_policies::for_map(current_map());return value;
}
inline bool use_v42(){return policy().v42_settings;}
}
