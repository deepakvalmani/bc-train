#pragma once
// Offline-trained bounded residual policy. No runtime Python or file access.
namespace learned {
inline constexpr int schema = 1, heads = 4, features = 12;
inline constexpr bool enabled = false, telemetry = false, audit = false;
inline constexpr float exploration = 0.000000f;
inline constexpr unsigned exploration_seed = 0;
inline constexpr float weights[heads][features] = {
    {0.00000000f, 0.00000000f, 0.00000000f, 0.00000000f, 0.00000000f, 0.00000000f, 0.00000000f, 0.00000000f, 0.00000000f, 0.00000000f, 0.00000000f, 0.00000000f},
    {0.00000000f, 0.00000000f, 0.00000000f, 0.00000000f, 0.00000000f, 0.00000000f, 0.00000000f, 0.00000000f, 0.00000000f, 0.00000000f, 0.00000000f, 0.00000000f},
    {0.00000000f, 0.00000000f, 0.00000000f, 0.00000000f, 0.00000000f, 0.00000000f, 0.00000000f, 0.00000000f, 0.00000000f, 0.00000000f, 0.00000000f, 0.00000000f},
    {0.00000000f, 0.00000000f, 0.00000000f, 0.00000000f, 0.00000000f, 0.00000000f, 0.00000000f, 0.00000000f, 0.00000000f, 0.00000000f, 0.00000000f, 0.00000000f}
};
}
