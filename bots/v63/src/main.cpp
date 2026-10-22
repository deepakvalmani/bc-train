// Dispatch draft and gameplay; a failed turn is logged and still yields.
#include <cambc.h>
#include <iostream>
#include "bot.h"
#include "draft.h"
#include "rules.h"
#include "champion_maps_config.h"
extern const char* g_stage;

int main() {
    if (cambc::constants::max_rounds != 2000 || cambc::constants::winning_gems != 1000
        || cambc::constants::shared_memory_bytes != 8 || cambc::constants::draft_memory_bytes != 1024) {
        std::cerr << "Unsupported competition settings: expected 2000 rounds, 1000 gems, 8/1024 memory bytes\n";
        return 1;
    }
    Bot bot;
    while (true) {
        try {
            if (cambc::is_draft())
                play_draft();
            else {
                if constexpr(CHAMPION_MAPS_SINGLE_GROUP>=0) {
                    if(cambc::global_submitted_gems(cambc::team::ally)>=CHAMPION_MAPS_DELIVERY_GEMS) {
                        std::cout << "CM_COMPLETE " << cambc::round_number() << std::endl;
                        cambc::resign();
                    }
                    const auto who=cambc::self().champion_name();
                    const bool selected=CHAMPION_MAPS_LAB_ACTOR<0
                        ?(who==cambc::champion_type::cassi || who==cambc::champion_type::issac)
                        :int(who)==CHAMPION_MAPS_LAB_ACTOR;
                    if(!selected && int(who)!=CHAMPION_MAPS_LAB_COMPANION) {
                        cambc::end_turn();continue;
                    }
                    const bool alive=cambc::self().is_alive();
                    std::cout << "CM_STATE " << cambc::round_number() << ' ' << cambc::to_string(who) << ' '
                              << alive << ' ' << (alive?cambc::self().health():0) << ' '
                              << (alive?cambc::self().gem_count():0) << ' '
                              << cambc::global_submitted_gems(cambc::team::ally) << std::endl;
                }
                bot.play_turn();
            }
        } catch (const std::exception& error) {
            std::cout << "bot error: " << error.what() << " at " << g_stage << std::endl;
        } catch (...) {
            std::cout << "bot error: unknown exception" << std::endl;
        }

        cambc::end_turn();
    }
}
