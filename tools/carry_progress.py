"""python tools/carry_progress.py bots/v48c bots/v50 [--reset contest,eight]
Copies the per-map trained values from one bot's tuning.json into another bot (same tunables), resets the listed maps to the
new bot's seed values, regenerates the generated headers and verifies them. Run it AFTER stopping the old trainer (Ctrl-C)."""
import argparse, json, pathlib, subprocess, sys
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import check_headers, safeio
ap = argparse.ArgumentParser(); ap.add_argument("src"); ap.add_argument("dst"); ap.add_argument("--reset", default="contest")
o = ap.parse_args()
src = json.load(open(ROOT / o.src / "tuning.json")); dst = json.load(open(ROOT / o.dst / "tuning.json"))
reset = set(filter(None, o.reset.split(",")))
for mp, m in src["maps"].items():
    if mp in reset:
        continue
    dst["maps"][mp] = m
for mp in reset:
    dst["maps"][mp] = {"tune": {}, "policy": {}, "draft": None, "score": None, "cscore": None, "tested": [], "accepted": 0, "stalled": 0}
safeio.dump_json(ROOT / o.dst / "tuning.json", dst)
subprocess.run([sys.executable, "tools/pm_train.py", o.dst, "--merge-from", "none"], cwd=ROOT, capture_output=True)
ok, miss, extra = check_headers.check(o.dst)
print(f"carried {len(src['maps']) - len(reset)} maps from {o.src} to {o.dst}, reset {sorted(reset)}; headers {'OK' if ok else 'MISMATCH'}")
sys.exit(0 if ok else 1)
