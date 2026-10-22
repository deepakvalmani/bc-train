#pragma once
inline constexpr bool CHAMPION_MAPS_ENABLED=true;
inline constexpr bool CHAMPION_MAPS_TRACE=false;
// Test harness only: -1 is normal play. Controlled tests resign after delivery.
inline constexpr int CHAMPION_MAPS_SINGLE_GROUP=-1;
inline constexpr int CHAMPION_MAPS_DELIVERY_GEMS=48;
// Physical champion for a controlled lab; pair members are both allowed for Cassi.
inline constexpr int CHAMPION_MAPS_LAB_ACTOR=-1;

inline constexpr int CHAMPION_MAPS_LAB_COMPANION=-1;

// New profiles need full-map qualification before becoming the default.
inline constexpr bool CHAMPION_MAPS_EXTENDED=true;

// Physical champion filter for controlled profile ablations; -1 enables all.
inline constexpr int CHAMPION_MAPS_PROFILE=11;
// Optional second physical profile for matched lineup studies.
inline constexpr int CHAMPION_MAPS_PROFILE2=-1;

// Packs-only route experiment; retain last observed enemy locks while routing.
inline constexpr bool CHAMPION_MAPS_BANK_ROUTE=true;
inline constexpr int CHAMPION_MAPS_LOCK_MEMORY=75;

