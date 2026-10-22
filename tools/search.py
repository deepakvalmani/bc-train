"""Deterministic local search proposals and matched-result bookkeeping.

These helpers use observed game outcomes, without treating repeated cached
games as independent evidence. They never run matches or relax promotion gates.
"""
from __future__ import annotations

import copy
import hashlib
import itertools
import json
import math


def profile_key(values):
    """Return a stable identity for a JSON-compatible parameter profile."""
    encoded = json.dumps(values, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def rank_result(rows, baseline, config, complete):
    """Describe a paired result, distinguishing safe leads from promotions.

    ``complete`` must mean that the caller finished the intended full schedule.
    Partial comparisons can provide gains for reporting, but are never safe
    leads. A safe lead passes all map/fault gates; it can still fall short of
    the separate minimum overall win gain needed for deployment.
    """
    layout = lambda rs: [(r["opponent"], r["map"], r["side"]) for r in rs]
    cases = layout(rows)
    if cases != layout(baseline) or len(cases) != len(set(cases)):
        raise ValueError("Search results require unique, matched map/opponent/side cases")
    if not rows:
        return dict(win_gain=0.0, gem_gain=0.0, rate_gain=0.0, faults=0.0,
                    complete=False, safe=False, useful=False, maps={})
    if complete and config.get("all_maps_required"):
        expected = {(op, m, side) for op in {r["opponent"] for r in baseline}
                    for m in config["validation_maps"] for side in (0, 1)}
        if set(cases) != expected:
            raise ValueError("A complete search result must cover every map and both sides")

    def mean(rs, key):
        values = [float(r[key]) for r in rs]
        if any(not math.isfinite(v) for v in values):
            raise ValueError(f"Non-finite search result: {key}")
        return sum(values) / len(values)

    def delta(a, b):
        return dict(win_gain=mean(a, "points") - mean(b, "points"),
                    gem_gain=mean(a, "share") - mean(b, "share"),
                    rate_gain=mean(a, "rate") - mean(b, "rate"),
                    faults=mean(a, "faults"))

    result = delta(rows, baseline)
    safe = bool(complete) and all(r["faults"] == 0 for r in rows)
    per_map = {}
    for name in sorted({r["map"] for r in rows}):
        a = [r for r in rows if r["map"] == name]
        b = [r for r in baseline if r["map"] == name]
        change = delta(a, b)
        per_map[name] = change
        if config.get("strict_per_map") and any(change[k] < -1e-9
                                                for k in ("win_gain", "gem_gain", "rate_gain")):
            safe = False
        if (config.get("promotion_objective") == "wins" and
                change["win_gain"] < -config["max_map_win_regression"] - 1e-9):
            safe = False
        if (change["gem_gain"] < -config["max_map_gem_regression"] or
                mean(a, "faults") > mean(b, "faults")):
            safe = False
    useful = safe and (result["win_gain"] > 1e-9 or
                       (abs(result["win_gain"]) <= 1e-9 and result["gem_gain"] > 1e-9))
    result.update(complete=bool(complete), safe=safe, useful=useful, maps=per_map)
    return result


def _checked(values, space):
    """Copy and validate a complete profile without changing caller data."""
    result = copy.deepcopy(values)
    for name, value in result.items():
        spec = space[name]
        kind = spec[0]
        if kind == "bool":
            valid = type(value) is bool
        elif kind == "permutation":
            valid = (isinstance(value, list) and all(type(v) is int for v in value)
                     and sorted(value) == sorted(spec[1]))
        else:
            valid = (type(value) in (int, float) and math.isfinite(value)
                     and spec[1] <= value <= spec[2]
                     and (kind != "int" or int(value) == value))
        if not valid:
            raise ValueError(f"Invalid search value for {name}: {value}")
        if kind == "int":
            result[name] = int(value)
        elif kind == "float":
            result[name] = float(value)
    return result


def _repair_banking(values, space):
    if "BANK_MIN" in values and "BANK_MAX" in values and values["BANK_MIN"] > values["BANK_MAX"]:
        minimum = max(space["BANK_MIN"][1], min(values["BANK_MAX"], space["BANK_MIN"][2]))
        maximum = max(values["BANK_MAX"], minimum)
        if maximum > space["BANK_MAX"][2]:
            raise ValueError("Search ranges cannot satisfy BANK_MIN <= BANK_MAX")
        values["BANK_MIN"], values["BANK_MAX"] = minimum, maximum
    return values


def _number(value, spec):
    low, high = spec[1:]
    value = max(low, min(high, value))
    if spec[0] == "int":
        return max(math.ceil(low), min(math.floor(high), int(round(value))))
    # Bounds themselves can contain more than four fractional digits.
    return float(max(low, min(high, round(value, 4))))


def local_candidates(base, donor, space, dependencies=None):
    """Refine each changed numeric coordinate around a promising legal donor.

    Other donor fields, including dependency switches, remain intact. The
    dependency argument is accepted for the trainer's shared proposal API; no
    switches are activated here because the donor already supplies its branch.
    Results are ``(profile, changed_names)`` relative to ``base``, capped at 16.
    """
    base, donor = _checked(base, space), _checked(donor, space)
    if base.keys() != donor.keys():
        raise ValueError("Local search requires matching profile fields")
    coordinates = [name for name in sorted(base)
                   if base[name] != donor[name] and space[name][0] in ("int", "float")]
    seen = {profile_key(base), profile_key(donor)}
    proposals = []
    # Round-robin modes give each changed coordinate a refinement before
    # filling the remaining slots with more distant alternatives.
    for mode in ("halfway", "beyond", "neighbor"):
        for name in coordinates:
            spec = space[name]
            difference = donor[name] - base[name]
            if mode == "halfway":
                value = base[name] + difference * 0.5
            elif mode == "beyond":
                value = donor[name] + difference
            else:
                step = max(1 if spec[0] == "int" else 0.0001,
                           min(abs(difference) * 0.25, (spec[2] - spec[1]) * 0.01))
                value = donor[name] + math.copysign(step, difference)
            candidate = copy.deepcopy(donor)
            candidate[name] = _number(value, spec)
            candidate = _checked(_repair_banking(candidate, space), space)
            key = profile_key(candidate)
            if key in seen:
                continue
            seen.add(key)
            proposals.append((candidate, sorted(n for n in base if candidate[n] != base[n])))
            if len(proposals) >= 16:
                return proposals
    return proposals


def combine_candidates(base, donors, space):
    """Combine compatible donor changes in deterministic input order.

    Each donor is a complete profile. A pair can share identical changes, but
    conflicting values for one field make that pair incompatible. The caller
    should supply only evidence-backed donors from the same comparison parent;
    this helper makes no performance claim about their combinations.
    """
    base = _checked(base, space)
    changes = []
    seen = {profile_key(base)}
    for donor in donors:
        donor = _checked(donor, space)
        if donor.keys() != base.keys():
            raise ValueError("Combining search profiles requires matching fields")
        seen.add(profile_key(donor))
        changes.append({name: copy.deepcopy(donor[name]) for name in base if donor[name] != base[name]})
    proposals = []
    for left, right in itertools.combinations(changes, 2):
        if any(left[name] != right[name] for name in left.keys() & right.keys()):
            continue
        candidate = copy.deepcopy(base)
        candidate.update(copy.deepcopy(left))
        candidate.update(copy.deepcopy(right))
        # Incompatible banking edits should be rejected rather than silently
        # manufacturing a third, unevaluated donor change during combination.
        if ("BANK_MIN" in candidate and "BANK_MAX" in candidate
                and candidate["BANK_MIN"] > candidate["BANK_MAX"]):
            continue
        candidate = _checked(candidate, space)
        key = profile_key(candidate)
        if key in seen:
            continue
        seen.add(key)
        changed = sorted(name for name in base if candidate[name] != base[name])
        if changed:
            proposals.append((candidate, changed))
        if len(proposals) >= 12:
            break
    return proposals
