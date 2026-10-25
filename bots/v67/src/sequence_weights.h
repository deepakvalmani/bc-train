#pragma once
// Offline search chooses orders independently for healthy and injured combat.
// 0 = existing teacher; 1 = attack then spell; 2 = spell then attack; 3 = attack, spell, disengage.
// v42: healthy=1 (attack->spell->attack fires the reset combo faster for all healthy champions).
namespace sequences {
inline constexpr int healthy = 1, injured = 0;
static_assert(healthy >= 0 && healthy <= 3 && injured >= 0 && injured <= 3);
}
