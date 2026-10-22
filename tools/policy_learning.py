"""Bounded decision logs, return-weighted imitation, and source-only export.

This is a small linear residual policy, not PPO or counterfactual replay.
Observed returns are noisy team credit; complete matches decide deployment.
"""
import bisect
import collections
import json
import math
import random
import re
import time
import economy_learning
import telemetry_actions

SCHEMA, HEADS, FEATURES = 1, 4, 12
NAMES = ("camp", "combat", "retreat", "bank")


def check_weights(weights):
    if len(weights) != HEADS or any(len(row) != FEATURES for row in weights):
        raise ValueError("Expected a 4 by 12 policy")
    for row in weights:
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in row):
            raise ValueError("Non-finite policy weight")
        if sum(abs(v) for v in row) > 0.50001:
            raise ValueError("Policy row exceeds its bounded residual budget")
    return [[float(v) for v in row] for row in weights]


def header(weights, enabled=True, telemetry=False, audit=False, exploration=0.0, exploration_seed=0):
    weights = check_weights(weights)
    if not math.isfinite(exploration) or not 0 <= exploration <= 0.15 or (exploration and not telemetry):
        raise ValueError("Exploration is bounded and restricted to data collection")
    if type(exploration_seed) is not int or not 0 <= exploration_seed < 2**32:
        raise ValueError("Invalid collection seed")
    literal = ",\n".join("    {" + ", ".join(format(v, ".8f") + "f" for v in row) + "}" for row in weights)
    flag = lambda v: "true" if v else "false"
    return ("#pragma once\n// Offline-trained bounded residual policy. No runtime Python or file access.\n"
            "namespace learned {\ninline constexpr int schema = 1, heads = 4, features = 12;\n"
            f"inline constexpr bool enabled = {flag(enabled)}, telemetry = {flag(telemetry)}, audit = {flag(audit)};\n"
            f"inline constexpr float exploration = {exploration:.6f}f;\n"
            f"inline constexpr unsigned exploration_seed = {exploration_seed};\n"
            f"inline constexpr float weights[heads][features] = {{\n{literal}\n}};\n}}\n")


def read_header(bot):
    path = bot / "src" / "policy_weights.h"
    if not path.exists():
        return [[0.0] * FEATURES for _ in range(HEADS)], False
    text = path.read_text(encoding="utf-8")
    enabled = re.search(r"\benabled\s*=\s*(true|false)", text)
    match = re.search(r"\bweights\[heads\]\[features\]\s*=\s*(\{.*?\});", text, re.S)
    if not enabled or not match:
        raise ValueError("Unrecognised policy header")
    values = re.findall(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?", match[1])
    if not values:
        weights = [[0.0] * FEATURES for _ in range(HEADS)]
    elif len(values) == HEADS * FEATURES:
        numbers = [float(v) for v in values]
        weights = [numbers[h*FEATURES:(h+1)*FEATURES] for h in range(HEADS)]
    else:
        raise ValueError("Incorrect exported weight count")
    return check_weights(weights), enabled[1] == "true"


def parse(text, result):
    frames, groups = collections.defaultdict(list), collections.defaultdict(list)
    bad_rounds = set()
    bad_by_champion=collections.defaultdict(set)
    last_champion=None
    diagnosis = dict(turns=0, fuel_failures=0, audit_ends=0, malformed=0,
                     deaths=0, estimated_gems_lost=0, travel_turns=0, capture_turns=0,
                     stuck_turns=0, suspected_tribute_interruptions=0, suspected_abandoned_captures=0,
                     sampled_shared_camp_targets=0, minimum_fuel=1000000)
    for line in text.splitlines():
        fields = line.split()
        if not fields or fields[0] not in ("PT", "PD", "PE", "PF"):
            continue
        try:
            if fields[0] == "PF":
                diagnosis["fuel_failures"] += 1
                if len(fields)==3:
                    bad_by_champion[int(fields[2])].add(int(fields[1]))
                else:
                    bad_rounds.add(int(fields[1]))
            elif fields[0] == "PE":
                if len(fields) not in (3,4):
                    raise ValueError()
                diagnosis["audit_ends"] += 1
                diagnosis["fuel_failures"] += int(int(fields[1]) != int(fields[2]))
                if int(fields[1]) != int(fields[2]):
                    champion=int(fields[3]) if len(fields)==4 else last_champion
                    bad=bad_by_champion[champion] if champion is not None else bad_rounds
                    bad.update((int(fields[1]),int(fields[2])))
                    bad.update(range(max(0,int(fields[1])), min(2001,int(fields[2])+1)))
            elif fields[0] == "PT":
                if len(fields) != 11:
                    raise ValueError()
                r, champion = int(fields[1]), int(fields[2])
                last_champion=champion
                frame = dict(round=r, action=telemetry_actions.decode(fields[3]), alive=int(fields[4]), health=float(fields[5]),
                             gems=int(fields[6]), gold=int(fields[7]), banked=int(fields[8]), fuel=int(fields[9]))
                if r < 0 or r > 2000 or frame["alive"] not in (0, 1) or not math.isfinite(frame["health"]):
                    raise ValueError()
                if any(frame[k] < 0 for k in ("health", "gems", "gold", "banked", "fuel")) or fields[10] not in ("0", "1"):
                    raise ValueError()
                diagnosis["fuel_failures"] += int(fields[10])
                if int(fields[10]):
                    bad_by_champion[champion].add(r)
                frames[champion].append(frame)
            else:
                if len(fields) != 21:
                    raise ValueError()
                r, champion, head, action, chosen = map(int, fields[1:6])
                base, score, scale = [float(v)/1000 for v in fields[6:9]]
                x = [float(v)/1000 for v in fields[9:]]
                if not 0 <= head < HEADS or chosen not in (0, 1) or scale <= 0:
                    raise ValueError()
                if not 0 <= r <= 2000 or champion < 0 or action < 0:
                    raise ValueError()
                if not all(math.isfinite(v) for v in [base, score, scale, *x]) or any(abs(v) > 1.00001 for v in x):
                    raise ValueError()
                groups[(champion, r, head)].append(dict(id=action, chosen=chosen, base=base, score=score, scale=scale, x=x))
        except (ValueError, IndexError):
            diagnosis["malformed"] += 1
    # Frame parsing is intentionally isolated so malformed SDK/log data never
    # turns into a guessed training label.
    economic_records=economy_learning.enrich(text, frames, diagnosis)
    economic_required=result.get('require_economic_telemetry')
    sparse=result.get('sparse_economic_telemetry')
    if economic_required and ((not sparse and len(economic_records)!=sum(map(len,frames.values())))
                              or (sparse and not economic_records)):
        diagnosis['malformed']+=1
    decisions = []
    for champion, history in frames.items():
        ordered = sorted(f["round"] for f in history)
        for a,b in zip(ordered,ordered[1:]):
            if b > a+1:
                bad_by_champion[champion].update(range(a,b+1))
    for champion, history in frames.items():
        history.sort(key=lambda f: f["round"])
        rounds = [f["round"] for f in history]
        for previous, current in zip(history, history[1:]):
            if current["round"] != previous["round"] + 1:
                diagnosis["fuel_failures"] += 1
            if previous["alive"] and not current["alive"]:
                diagnosis["deaths"] += 1
                diagnosis["estimated_gems_lost"] += previous["gems"]
            if previous["action"] == "tributing" and current["action"] != "tributing" and current["gems"] >= previous["gems"]:
                diagnosis["suspected_tribute_interruptions"] += 1
            if (previous["action"] == "capturing" and current["action"] != "capturing"
                    and current["gems"] <= previous["gems"] and current["gold"] <= previous["gold"]):
                diagnosis["suspected_abandoned_captures"] += 1
        for frame_index, frame in enumerate(history):
            diagnosis["turns"] += 1
            diagnosis["minimum_fuel"] = min(diagnosis["minimum_fuel"], frame["fuel"])
            diagnosis["travel_turns"] += frame["action"].startswith("walk")
            diagnosis["capture_turns"] += frame["action"] == "capturing"
            diagnosis["stuck_turns"] += frame["action"].startswith("stuck") or frame["action"] == "no_target"
            future_index = min(len(history)-1, bisect.bisect_left(rounds, frame["round"] + 24))
            future = history[future_index]
            clean_window = not any(r in bad_rounds or r in bad_by_champion[champion]
                                   for r in range(frame["round"],future["round"]+1))
            local = ((future["banked"]-frame["banked"])/100
                     + 0.2*(future["gems"]-frame["gems"])/100
                     - (frame["gems"]/100 if frame["alive"] and not future["alive"] else 0))
            weights=result.get('reward_weights')
            if weights:
                window=history[frame_index:future_index+1]
                death_loss=sum(a['gems'] for a,b in zip(window,window[1:]) if a['alive'] and not b['alive'])
                spent=sum(economic_records.get((champion,f['round']),{}).get('spent',0) for f in window)
                failures=sum(economic_records.get((champion,f['round']),{}).get('failed',0) for f in window)
                local=(weights['tribute']*(future['banked']-frame['banked'])/100
                       -weights['death']*death_loss/100
                       -weights['time']*(future['round']-frame['round'])/24
                       +weights['gold']*max(0,future['gold']-frame['gold']+spent)/100
                       +weights['kills']*result.get('economy',{}).get('kills',0)/max(1,len(history))
                       -weights['failure']*failures)
            quality = max(0.1, min(2.0, 0.5 + result["points"] + 0.25*local))
            for head in range(HEADS):
                choices = groups.get((champion, frame["round"], head), [])
                if len({c["id"] for c in choices}) != len(choices):
                    diagnosis["malformed"] += 1
                    continue
                chosen = [i for i, c in enumerate(choices) if c["chosen"]]
                if len(choices) < 2 or len(chosen) != 1 or not clean_window:
                    continue
                if head == 0 and choices[chosen[0]]["x"][9] > 0:
                    diagnosis["sampled_shared_camp_targets"] += 1
                # Assign returns only when the resulting turn used that class
                # of decision; the other choices can still teach the baseline.
                action = frame["action"]
                used = ((head == 0 and action in ("walk_camp", "fight", "fight_stray", "capturing", "wait_squad", "wait_respawn"))
                        or (head == 1 and action.startswith("pvp"))
                        or (head == 2 and action in ("retreat", "pvp_flee", "protect_bag", "cassi_back", "pvp_kite", "sequence_retreat"))
                        or (head == 3 and action in ("walk_altar", "tribute_start", "walk_camp", "fight", "capturing")))
                decisions.append(dict(head=head, choices=choices, selected=chosen[0], quality=quality if used else 0.25,
                                      teacher=max(range(len(choices)), key=lambda i: choices[i]["base"]),
                                      round=frame["round"], champion=champion))
    if diagnosis["audit_ends"] < diagnosis["turns"]:
        diagnosis["fuel_failures"] += diagnosis["turns"] - diagnosis["audit_ends"]
    audit_passed = diagnosis["turns"] > 0 and not (diagnosis["fuel_failures"] or diagnosis["malformed"] or result["faults"])
    usable = (bool(decisions) and diagnosis["audit_ends"] == diagnosis["turns"]
              and not (diagnosis["malformed"] or result["faults"]))
    return dict(schema=SCHEMA, usable=usable, audit_passed=audit_passed,
                diagnostics=diagnosis, decisions=decisions if usable else [])


def fit(initial, decisions, seed, deadline):
    """Teacher-anchored return-weighted pairwise imitation, with bounded weights."""
    anchor = check_weights(initial)
    weights = [row[:] for row in anchor]
    rng = random.Random(seed)
    counts = collections.Counter(d["map"] for d in decisions)
    order = list(decisions)
    rng.shuffle(order)
    updates = 0
    for epoch in range(3):
        for d in order:
            if time.monotonic() >= deadline:
                return weights, dict(updates=updates, complete=False)
            choices, head = d["choices"], d["head"]
            selected = d["teacher"] if epoch == 0 else d["selected"]
            chosen = choices[selected]
            for i, other in enumerate(choices):
                if i == selected:
                    continue
                normalizer = max(chosen["scale"], other["scale"], 0.001)
                z1 = sum(w*x for w, x in zip(weights[head], chosen["x"]))
                z2 = sum(w*x for w, x in zip(weights[head], other["x"]))
                margin = (chosen["base"] + chosen["scale"]*z1 - other["base"] - other["scale"]*z2) / normalizer
                error = 1/(1+math.exp(max(-30, min(30, margin))))
                balance = min(3.0, len(order)/max(1, len(counts)*counts[d["map"]]))
                strength = 0.25 if epoch == 0 else d["quality"]
                for j in range(FEATURES):
                    gradient = (chosen["scale"]*chosen["x"][j] - other["scale"]*other["x"][j])/normalizer
                    weights[head][j] += 0.004*balance*strength*error*gradient - 0.0002*(weights[head][j]-anchor[head][j])
                norm = sum(abs(v) for v in weights[head])
                if norm > 0.5:
                    weights[head] = [v*0.5/norm for v in weights[head]]
                updates += 1
    return check_weights(weights), dict(updates=updates, complete=True)
