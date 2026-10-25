#pragma once
#include <algorithm>
#include <array>
#include <cmath>
#include <iostream>
#include <string_view>
#include <charconv>
#include <cstring>
#include <cambc.h>
#include "policy_weights.h"

// Bounded linear residuals on existing legal candidate choices. The SDK still
// authorises every action. Logging is a separate, never-submitted build.
namespace policy {
inline constexpr bool active = learned::enabled || learned::telemetry;
inline constexpr int max_scores = 96, reserve = 18000, keep = 4;
using Features = std::array<float, learned::features>;
struct Option { int id = -1; float base = 0, score = 0, scale = 1; Features x{}; };
inline std::array<std::array<Option, keep>, learned::heads> options{};
inline std::array<int, learned::heads> selected{-1,-1,-1,-1};
inline int calls = 0, start_round = -1, rows = 0;
inline bool sample = false;
inline unsigned shop_spent=0, gems_begin=0, failed_actions=0;
inline double incoming=0, cc_risk=0;
inline void begin() {
    if constexpr (!active && !learned::audit) return;
    calls = 0;
    if constexpr (learned::telemetry || learned::audit) {
        shop_spent=0; failed_actions=0; incoming=0; cc_risk=0;
        if constexpr (learned::telemetry) gems_begin=cambc::self().gem_count();
        start_round = (int)cambc::round_number();
        sample = (start_round % 16 == 0) && rows < 768;
        selected.fill(-1);
        for (auto& head : options) for (auto& option : head) option.id = -1;
    }
}
inline double score(int head, int id, double base, Features x, double scale) {
    if constexpr (!active) return base;
    if (++calls > max_scores || cambc::fuel_remaining() < reserve) return base;
    for (float& v : x) v = std::isfinite(v) ? std::clamp(v, -1.0f, 1.0f) : 0.0f;
    double result = base;
    if constexpr (learned::enabled) {
        float residual = 0;
        for (int i = 0; i < learned::features; ++i) residual += learned::weights[head][i] * x[i];
        result += std::clamp((double)residual, -0.5, 0.5) * std::max(0.001, scale);
    }
    if constexpr (learned::telemetry && learned::exploration > 0) {
        unsigned seed = (unsigned)(start_round*747796405u + (head+1)*2891336453u
                                  + (id+1)*277803737u + learned::exploration_seed);
        seed ^= seed >> 16;
        result += ((seed % 2001)/1000.0 - 1.0) * learned::exploration * scale;
    }
    if constexpr (learned::telemetry) if (sample) {
        auto& list = options[head];
        int at = -1;
        for (int i=0; i<keep; ++i) if (list[i].id == id) { at=i; break; }
        if (at < 0) for (int i=0; i<keep; ++i) if (list[i].id < 0) { at=i; break; }
        if (at < 0) {
            at = 0;
            for (int i=1; i<keep; ++i) if (list[i].score < list[at].score) at=i;
            if (result < list[at].score) return result;
        }
        list[at] = {id, (float)base, (float)result, (float)scale, x};
    }
    return result;
}
inline void choose(int head, int id) { if constexpr (learned::telemetry) selected[head] = id; }
struct LogBuffer {
    char data[1536]; int used=0;
    void text(std::string_view value) { std::memcpy(data+used,value.data(),value.size()); used+=(int)value.size(); }
    void number(long long value) { auto result=std::to_chars(data+used,data+sizeof(data),value); used=(int)(result.ptr-data); }
    void field(long long value) { data[used++]=' '; number(value); }
    void line() { data[used++]='\n'; }
    void flush() { std::cout.write(data,used); used=0; }
};
inline void end(const char* action) {
    if constexpr (!learned::telemetry && !learned::audit) return;
    auto& me=cambc::self();
    const int now=(int)cambc::round_number(), champion=(int)me.champion_name();
    LogBuffer log;
    if (cambc::fuel_remaining()<6000) {
        log.text("PF "); log.number(now); log.field(champion); log.line(); log.flush(); return;
    }
    log.text("PT "); log.number(now); log.field(champion); log.text(" "); log.text(action);
    log.field(me.is_alive()); log.field((int)me.health()); log.field(me.gem_count());
    log.field(me.gold_count()); log.field(cambc::global_submitted_gems(cambc::team::ally));
    log.field(cambc::fuel_remaining()); log.field(now!=start_round); log.line();
    if constexpr (learned::telemetry) {
        const auto position=me.is_alive() ? me.position() : cambc::vec2{0,0};
        log.text("PX "); log.number(now); log.field(champion);
        log.field(position.x); log.field(position.y); log.field(gems_begin); log.field(shop_spent);
        log.field((int)me.strength()); log.field((int)me.focus()); log.field((int)me.max_health());
        log.field((int)incoming); log.field((int)(cc_risk*1000));
        log.field(me.state().contains(cambc::champion_state::submit_gems_cancelled));
        log.field(failed_actions); log.line();
    }
    if (sample && cambc::fuel_remaining()>reserve && learned::telemetry) {
        const std::string_view act{action}; int h=0;
        if (act=="pvp_flee" || act=="protect_bag" || act=="cassi_back" || act=="pvp_kite" || act=="retreat" || act=="sequence_retreat") h=2;
        else if (act.starts_with("pvp")) h=1;
        else if (act=="walk_altar" || act=="tribute_start" || act=="break_lock") h=3;
        else if (selected[3]>=0 && start_round%32==0) h=3;
        for (const auto& o:options[h]) if (o.id>=0 && rows<768) {
            log.text("PD "); log.number(start_round); log.field(champion); log.field(h);
            log.field(o.id); log.field(o.id==selected[h]);
            log.field((int)(o.base*1000)); log.field((int)(o.score*1000));
            log.field((int)(std::max(0.001f,o.scale)*1000));
            for (float value:o.x) log.field((int)(value*1000));
            log.line(); ++rows;
        }
    }
    log.flush();
    log.text("PE "); log.number(start_round); log.field(cambc::round_number()); log.field(champion); log.line(); log.flush();
}
static_assert(learned::schema == 1 && learned::heads == 4 && learned::features == 12);
static_assert(learned::telemetry || learned::exploration == 0, "Exploration is training-only");
static_assert(sizeof(learned::weights) == 192, "Policy weights must remain compact");
}
