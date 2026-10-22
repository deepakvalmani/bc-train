"""Inspect maps using a stationary SDK probe; no platform authentication or matches.

These are bounded local diagnostic runs, not competitive evaluations.
"""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile
import zlib

from game_model_audit import CAMPS, ROOT, describe_map


def parse_probe(text):
    records = [json.loads(line.removeprefix("MODEL "))
               for line in text.splitlines() if line.startswith("MODEL ")]
    settings, = [r for r in records if r["kind"] == "settings"]
    assert sum(r["kind"] == "complete" for r in records) == 1, "Incomplete probe"
    by_row = {r["y"]: r["cells"] for r in records if r["kind"] == "row"}
    assert len(by_row) == settings["h"], "Missing terrain rows"
    groups = [r for r in records if r["kind"] == "group"]
    assert sorted(r["id"] for r in groups) == list(range(settings["groups"]))
    rows = [list(by_row[y]) for y in range(settings["h"])]
    camps = []
    for g in groups:
        for x, y, kind, hp, strength in g["camps"]:
            assert hp == CAMPS[kind][1] and strength == CAMPS[kind][2]
            rows[y][x] = "c"
            camps.append([x, y, g["id"], kind])
        assert g["gems"] == sum(CAMPS[c[2]][5] for c in g["camps"])
        assert g["gold"] == sum(CAMPS[c[2]][4] for c in g["camps"])
    terrain = {"w": settings["w"], "h": settings["h"], "rows": ["".join(r) for r in rows]}
    return settings, terrain, camps, groups


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--maps", required=True, help="Comma-separated installed map stems")
    parser.add_argument("--out", default="out/game_model_20261022/probes")
    args = parser.parse_args()
    runtime = ROOT / "rt_v5"
    exe = runtime / "cambc.exe"
    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    bot = str(ROOT / "bots/model_probe")
    subprocess.run([str(exe), "build", bot], cwd=runtime, check=True)
    manifest = json.loads((runtime / ".cambc/map-pool.json").read_text())["maps"]
    known = {Path(r["file"]).stem: r for r in manifest}
    for name in args.maps.split(","):
        assert name in known, name
        map_file = runtime / "maps" / known[name]["file"]
        sha = hashlib.sha256(map_file.read_bytes()).hexdigest()
        assert sha == known[name]["sha256"], name
        destination = out / name
        if not list(destination.glob("*.repl26a")):
            run = subprocess.run([str(exe), "run", bot, bot, "--map", str(map_file),
                                  "--rounds", "220", "--release", "--fuel", "100000",
                                  "-o", str(destination)], cwd=runtime,
                                 capture_output=True, text=True, timeout=180)
            (out / (name + ".log")).write_text(run.stdout + run.stderr, encoding="utf-8")
            run.check_returncode()
        replay, = destination.glob("*.repl26a")
        with zipfile.ZipFile(replay) as bundle:
            data = bundle.read("team-a.stdout")
        try:
            data = zlib.decompress(data)
        except zlib.error:
            pass
        text = data.decode("utf-8", errors="strict").replace("\0", "")
        settings, terrain, camps, groups = parse_probe(text)
        result = describe_map(name, terrain, camps)
        result.update(map_sha256=sha, source="live SDK stationary local probe",
                      settings=settings, sdk_groups=groups, campInfo=camps, terrain=terrain,
                      probe_replay=str(replay.relative_to(ROOT)),
                      probe_replay_sha256=hashlib.sha256(replay.read_bytes()).hexdigest())
        (out / (name + ".json")).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(name, result["width"], result["height"], "groups", result["group_count"],
              "gems", result["single_sweep_gems"], "bank", result["spawn_to_altar_walk_lower_bound"],
              "isolated", result["walking_unreachable_gem_groups"], flush=True)


if __name__ == "__main__":
    main()
