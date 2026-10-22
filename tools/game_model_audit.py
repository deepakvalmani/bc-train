"""Audit the installed map snapshot using existing terrain and decoded replays.

Does not build bots, run matches, authenticate, or fetch platform data.
Reward totals use the saved week-two patch values, not a live engine query.
"""

import argparse
from collections import Counter, defaultdict, deque
import gzip
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CAMPS = [
    ("Wolf", 1350, 20, 3, 40, 4),
    ("Elk", 2400, 60, 4, 90, 15),
    ("Gem cluster", 120, 0, 0, 0, 7),
    ("Gold cluster", 120, 0, 0, 20, 0),
    ("Monolith", 20000, 200, 5, 300, 200),
    ("Golem", 5000, 120, 4, 160, 36),
]
HEROES = [
    "Ryth", "Vesper Vale", "Vendetta", "Cassi", "Issac", "Stellar",
    "Prism", "Marcella", "Willow", "Ren", "Varg", "Tavi", "Heart of Ruin",
]


def digest(file):
    return hashlib.sha256(file.read_bytes()).hexdigest()


def walking_distances(rows, side):
    starts = [(x, y) for y, row in enumerate(rows)
              for x, tile in enumerate(row) if tile == side]
    blocked = {"#", "~", "A", "e" if side == "s" else "s"}
    distance = dict.fromkeys(starts, 0)
    queue = deque(starts)
    width, height = len(rows[0]), len(rows)
    while queue:
        x, y = queue.popleft()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                nx, ny = x + dx, y + dy
                if not (0 <= nx < width and 0 <= ny < height):
                    continue
                if (nx, ny) in distance or rows[ny][nx] in blocked:
                    continue
                distance[nx, ny] = distance[x, y] + 1
                queue.append((nx, ny))
    return distance


def describe_map(name, terrain, camps):
    rows = terrain["rows"]
    assert len(rows) == terrain["h"]
    assert all(len(row) == terrain["w"] for row in rows)
    distances = [walking_distances(rows, side) for side in ("s", "e")]
    groups = defaultdict(list)
    for x, y, group, kind in camps:
        assert rows[y][x] == "c", (name, x, y, rows[y][x])
        groups[group].append((x, y, kind))
    result = []
    for group, members in sorted(groups.items()):
        kinds = Counter(kind for _, _, kind in members)
        values = [CAMPS[kind] for _, _, kind in members]
        ds = [min((field.get((x, y), 65535) for x, y, _ in members),
                  default=65535) for field in distances]
        if ds[0] == ds[1] == 65535:
            zone = "unreachable_by_walking"
        elif ds[0] + 6 < ds[1]:
            zone = "a_nearer"
        elif ds[1] + 6 < ds[0]:
            zone = "b_nearer"
        else:
            zone = "similar_distance"
        result.append({
            "id": group, "tiles": [[x, y] for x, y, _ in members],
            "types": {CAMPS[k][0]: v for k, v in kinds.items()},
            "hp": sum(c[1] for c in values),
            "summed_strength": sum(c[2] for c in values),
            "gold": sum(c[4] for c in values),
            "gems": sum(c[5] for c in values),
            "spawn_walk_distance": ds, "zone": zone,
        })
    altars = [(x, y) for y, row in enumerate(rows)
              for x, tile in enumerate(row) if tile == "A"]
    altar_distances = []
    for field in distances:
        altar_distances.append(min((
            field.get((x + dx, y + dy), 65535)
            for x, y in altars for dx in (-1, 0, 1) for dy in (-1, 0, 1)
            if dx or dy), default=65535))
    return {
        "width": terrain["w"], "height": terrain["h"],
        "altars": [list(p) for p in altars],
        "spawn_to_altar_walk_lower_bound": altar_distances,
        "groups": result, "group_count": len(result),
        "gem_groups": sum(g["gems"] > 0 for g in result),
        "single_sweep_gems": sum(g["gems"] for g in result),
        "single_sweep_gold": sum(g["gold"] for g in result),
        "walking_unreachable_gem_groups": sum(
            g["gems"] > 0 and g["zone"] == "unreachable_by_walking"
            for g in result),
        "gems_by_zone": {zone: sum(g["gems"] for g in result if g["zone"] == zone)
                         for zone in ("a_nearer", "similar_distance", "b_nearer",
                                      "unreachable_by_walking")},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", default="rt_v5")
    parser.add_argument("--replays", default="out/fish4")
    parser.add_argument("--probes", default="out/game_model_20261022/probes")
    parser.add_argument("--out", default="out/game_model_20261022/audit.json")
    args = parser.parse_args()
    runtime = ROOT / args.runtime
    pool_file = runtime / ".cambc/map-pool.json"
    pool = json.loads(pool_file.read_text(encoding="utf-8"))["maps"]
    wanted = {Path(row["file"]).stem: row for row in pool}
    mismatches = [row["file"] for row in pool
                  if digest(runtime / "maps" / row["file"]) != row["sha256"]]
    if mismatches:
        raise ValueError(f"Installed maps differ from their manifest: {mismatches}")
    maps, bases = {}, {}
    for file in sorted((ROOT / args.probes).glob("*.json")):
        name = file.stem
        if name not in wanted:
            continue
        data = json.loads(file.read_text(encoding="utf-8"))
        if data["map_sha256"] != wanted[name]["sha256"]:
            raise ValueError(f"Probe map hash mismatch: {name}")
        replay = ROOT / data["probe_replay"]
        if digest(replay) != data["probe_replay_sha256"]:
            raise ValueError(f"Probe replay hash mismatch: {name}")
        maps[name] = describe_map(name, data["terrain"], data["campInfo"])
        maps[name].update(map_sha256=data["map_sha256"],
                          source=data["source"], probe_file=str(file.relative_to(ROOT)),
                          sdk_group_rewards_verified=True)
    scanned = 0
    for file in sorted((ROOT / args.replays).glob("*.json.gz")):
        with gzip.open(file, "rt", encoding="utf-8") as handle:
            data = json.load(handle)
        scanned += 1
        name = data["map"]
        if name in wanted and name not in maps and data.get("campInfo"):
            source = Path(data["source"].replace("\\", "/"))
            source = source if source.is_absolute() else ROOT / source
            raw = source.read_bytes()
            if hashlib.sha256(raw).hexdigest() != data["sha256"]:
                raise ValueError(f"Replay source hash mismatch: {source}")
            if (runtime / "maps" / wanted[name]["file"]).read_bytes() not in raw:
                raise ValueError(f"Map bytes not found in replay: {name}, {source}")
            terrain = json.loads((ROOT / "out/terrain" / (name + ".json"))
                                 .read_text(encoding="utf-8"))
            maps[name] = describe_map(name, terrain, data["campInfo"])
            maps[name].update({"map_sha256": wanted[name]["sha256"],
                               "representative_replay": data["id"],
                               "replay_sha256": data["sha256"]})
        initial = next((s[1] for s in data.get("stats", [])
                        if s[0] == 0 and s[1]), [])
        first_snapshot = next((s[1] for s in data.get("snaps", []) if s[1]), [])
        identities = {h["id"]: h["type"] for h in data["heroes"]}
        hp = {h[0]: h[6] for h in first_snapshot}
        for ident, _, _, focus, strength, attack_range in initial:
            kind = identities[ident]
            if kind not in bases and ident in hp:
                bases[kind] = {"name": HEROES[kind], "max_hp_observed": hp[ident],
                               "focus_observed": focus, "strength_observed": strength,
                               "attack_range": attack_range,
                               "replay": data["id"]}
        if len(maps) == len(wanted) and len(bases) == len(HEROES):
            break
    result = {
        "baseline": "Local SDK/CLI 3.0.4; saved engine-1.0.2 replay extraction",
        "live_platform_verified": False,
        "manifest_sha256": digest(pool_file),
        "reward_basis": "Current camp table; new-map group totals independently checked with the installed SDK probe",
        "path_basis": "Optimistic eight-neighbor walking, camps treated as cleared; no live occupancy or SDK edge validation",
        "scanned_cached_replays": scanned,
        "missing_maps": sorted(set(wanted) - maps.keys()),
        "missing_champion_types": [HEROES[i] for i in range(len(HEROES)) if i not in bases],
        "maps": dict(sorted(maps.items())),
        "initial_champion_observations": [bases[i] for i in sorted(bases)],
    }
    target = ROOT / args.out
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Maps: {len(maps)}/{len(wanted)}; initial champion types: {len(bases)}/{len(HEROES)}; scanned: {scanned}")
    print("map | size | groups/gem groups | sweep gems | A/B altar walk lower bound | unreachable gem groups")
    for name, m in sorted(maps.items()):
        print(f"{name} | {m['width']}x{m['height']} | {m['group_count']}/{m['gem_groups']} | {m['single_sweep_gems']} | {m['spawn_to_altar_walk_lower_bound']} | {m['walking_unreachable_gem_groups']}")
    print("Initial champion observations:")
    for b in result["initial_champion_observations"]:
        print(b["name"], b["max_hp_observed"], b["strength_observed"], b["focus_observed"])
    print("Saved", target)
    if result["missing_maps"] or result["missing_champion_types"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
