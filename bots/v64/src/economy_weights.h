#pragma once
namespace economy {
inline constexpr bool banking=false, camps=false, survival=false, shopping=false, combat=false, mobility=false;
inline constexpr float BANK_RISK_W=1.0f, ALTAR_TRAVEL_W=1.0f, TRIBUTE_INTERRUPT_RISK=1.0f;
inline constexpr float CAMP_VALUE_W=1.0f, CAMP_CLEAR_TURNS_W=1.0f, CAPTURE_TIME_W=1.0f, CAMP_DAMAGE_RISK_W=1.0f, RESPAWN_VALUE_W=1.0f;
inline constexpr float DEATH_RISK_W=1.0f, RECALL_HP_THRESHOLD=0.4f, CARRIED_GEM_RISK_W=1.0f;
inline constexpr float ALTAR_ROUTE_COST_W=1.0f, DASH_VALUE_W=1.0f, TELEPORT_VALUE_W=1.0f, BUSH_AMBUSH_W=0.2f;
inline constexpr float EXPECTED_DAMAGE_W=1.0f, KILL_CONFIRM_W=1.0f, ABILITY_VALUE_W=1.0f, ENEMY_GEM_CARRY_W=1.0f, ITEM_ROI_W=1.0f;
}
