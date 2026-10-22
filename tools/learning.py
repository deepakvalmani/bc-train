"""Persistent feedback for evolutionary proposals; match results remain authoritative.

Effects are associations from controlled matchups, not proof that an individual
parameter caused a result when several parameters changed together.
"""
import hashlib
import json
import math


def mean(rows, name):
    return sum(r.get(name, 0) for r in rows) / len(rows)


def reward(candidate, baseline):
    win = mean(candidate, "points") - mean(baseline, "points")
    gems = mean(candidate, "share") - mean(baseline, "share")
    speed = (mean(candidate, "rate") - mean(baseline, "rate")) / max(0.1, mean(baseline, "rate"))
    value = 2 * win + 0.5 * gems + 0.05 * max(-1, min(1, speed))
    if any(r.get("faults", 0) for r in candidate):
        value = min(value, -1.0)
    return max(-1, min(1, value))


def observe(memory, parent, candidate, old, new, rows, baseline, stage, coverage=1.0):
    memory.setdefault("version", 1)
    if not rows or len(rows) != len(baseline):
        return None
    layout = lambda rs: [(r["opponent"], r["map"], r["side"]) for r in rs]
    if layout(rows) != layout(baseline):
        raise ValueError("Feedback requires exactly matched map/opponent/side cases")
    identity = [parent, candidate, stage, sorted(layout(rows))]
    key = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
    seen = memory.setdefault("seen_comparisons", {})
    if key in seen:
        return None  # Reusing deterministic cached games is not new evidence.
    changed = [n for n in old.keys() & new.keys() if old[n] != new[n]]
    if not changed:
        return None
    value = reward(rows, baseline)
    strength = 1.0 if stage == "validation" else 0.25
    if stage.endswith("_partial"):
        strength *= max(0, min(1, coverage))
    alpha = 0.2 * strength / math.sqrt(len(changed))
    effects = memory.setdefault("parameters", {})
    maps = {}
    for name in sorted({r["map"] for r in rows}):
        a, b = [r for r in rows if r["map"] == name], [r for r in baseline if r["map"] == name]
        maps[name] = dict(signal=reward(a, b), win_delta=mean(a, "points") - mean(b, "points"),
                          gem_share_delta=mean(a, "share") - mean(b, "share"),
                          gem_rate_delta=mean(a, "rate") - mean(b, "rate"),
                          deaths_delta=(mean(a, "deaths") - mean(b, "deaths")) if stage == "validation" else None)
        if stage == "validation":
            memory.setdefault("map_baselines", {})[name] = dict(
                parent=parent, points=mean(b, "points"), share=mean(b, "share"))
    for name in changed:
        item = effects.setdefault(name, dict(observations=0, effect=0.0, direction=0.0, maps={}))
        item["observations"] += 1
        if stage == "validation" and all(a[metric] == b[metric] for a, b in zip(rows, baseline)
                                          for metric in ("points", "share", "rate")):
            item["neutral_observations"] = item.get("neutral_observations", 0) + 1
        item["effect"] = (1 - alpha) * item["effect"] + alpha * value
        item["last_parent"] = parent
        item["last_candidate"] = candidate
        if type(old[name]) in (int, float) and type(new[name]) in (int, float):
            sign = 1 if new[name] > old[name] else -1
            item["direction"] = (1 - alpha) * item["direction"] + alpha * sign * value
        for map_name, result in maps.items():
            prev = item["maps"].get(map_name, 0.0)
            item["maps"][map_name] = (1 - alpha) * prev + alpha * result["signal"]
    profile = memory.setdefault("candidate_scores", {})
    previous = profile.get(candidate)
    if previous is None or stage == "validation" or previous["stage"] != "validation":
        profile[candidate] = dict(score=value * (strength if stage.endswith("_partial") else 1),
                                  stage=stage, parent=parent, cases=len(rows), coverage=coverage)
    memory.setdefault("completed_profiles", {})[parent + ":" + candidate] = True
    seen[key] = True
    memory["observations"] = memory.get("observations", 0) + 1
    worst = min(maps, key=lambda m: maps[m]["signal"])
    return dict(parent=parent, candidate=candidate, stage=stage, signal=value,
                cases=len(rows), coverage=coverage,
                changed=sorted(changed), maps=maps, worst_map=worst,
                attribution="associated changes; multi-parameter effects are not isolated causes")


def parameter_weight(memory, name, target_map=None):
    stats = memory.get("parameters", {}).get(name, {})
    uncertainty = 1 / math.sqrt(1 + stats.get("observations", 0))
    effect = stats.get("effect", 0)
    weak_map_potential = 0.0
    for map_name, impact in stats.get("maps", {}).items():
        weakness = 1 - memory.get("map_baselines", {}).get(map_name, {}).get("points", 0.5)
        weak_map_potential += weakness * max(0, impact)
    # Nonzero floor plus the once-per-cycle queue preserves exploration.
    targeted = max(0, stats.get("maps", {}).get(target_map, 0)) if target_map else 0
    neutral_discount = 1 + 0.5 * stats.get("neutral_observations", 0)
    return max(0.25, (1 + uncertainty + 3 * effect + weak_map_potential + 6 * targeted) / neutral_discount)


def numeric_proposal(memory, name, current, low, high, rng, scale=0.08):
    stats = memory.get("parameters", {}).get(name, {})
    direction = stats.get("direction", 0)
    evidence = stats.get("observations", 0)
    # Keep substantial random exploration; observational direction can be wrong.
    if evidence >= 3 and abs(direction) > 0.01 and rng.random() < 0.65:
        step = abs(rng.gauss(0, (high - low) * scale))
        return current + (step if direction > 0 else -step)
    return None


def parent_weights(memory, parents, incumbent):
    scores = memory.get("candidate_scores", {})
    result = []
    for parent in parents:
        entry = scores.get(parent, {})
        score = entry.get("score", 0)
        if entry.get("parent") != incumbent:
            score *= 0.25  # Older comparisons become weaker advice after a promotion.
        result.append(math.exp(max(-3, min(3, score * 4))))
    return result
