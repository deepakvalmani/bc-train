#pragma once
#include <cstddef>
#include <initializer_list>
#include "params.h"

// Competition invariants are not learned parameters. Invalid generated or
// manually edited genes fail compilation instead of creating invalid actions.
namespace rules {
template<std::size_t N>
constexpr bool legal_draft(const int (&order)[N]) {
    if (N != 11) return false;
    bool seen[11]{};
    for (int id : order) {
        if (id < 0 || id >= 11 || seen[id]) return false;
        seen[id] = true;
    }
    return true;
}
constexpr bool within(std::initializer_list<int> values, int low, int high) {
    for (int v : values) if (v < low || v > high) return false;
    return true;
}
static_assert(legal_draft(DRAFT_ORDER) && legal_draft(DRAFT_ORDER5));
static_assert(legal_draft(DRAFT_EXPANSE) && legal_draft(DRAFT_ROWS) && legal_draft(DRAFT_LANES));
static_assert(legal_draft(DRAFT_CORNERS));
static_assert(legal_draft(DRAFT_OPENER) && legal_draft(DRAFT_SPLASH) && legal_draft(DRAFT_SMALL) && legal_draft(DRAFT_LARGE));
} // namespace rules
