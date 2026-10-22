"""Merge per-map tuning results from CI artifacts into the base bot.
python tools/pm_merge.py bots/v46 art      # art/tuning-<map>/tuning.json -> takes <map> from each, writes tuning.json + headers
"""
import json, os, pathlib, subprocess, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import safeio
ROOT = pathlib.Path(__file__).resolve().parent.parent
os.chdir(ROOT)
base, art = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
tj = base / "tuning.json"
st = json.load(open(tj)) if tj.exists() else {"maps": {}}
n = 0
for d in sorted(art.glob("tuning-*")):
    mp = d.name[len("tuning-"):]
    cand = sorted(d.rglob("tuning.json"))   # artifact keeps the bots/<name>/ prefix (common-ancestor path)
    if not cand:
        print(f"{mp}: no tuning.json in artifact")
        continue
    f = cand[0]
    cur = json.load(open(f))["maps"].get(mp)
    if cur:
        st["maps"][mp] = cur
        n += 1
        print(f"{mp}: accepted {cur['accepted']}, tested {len(cur['tested'])}, score {cur['score']}")
ALL = "ambush collision contest corners eight elkring expanse fragment interlock lanes monolith packs pilgrimage rows rushbait_v2 stampede swirl".split()
missing = [m for m in ALL if not any(art.glob(f"tuning-{m}"))]
if missing:
    print("WARNING: no artifact for", ", ".join(missing), "(kept the old values)")
if n == 0:
    sys.exit("ERROR: merged 0 maps - artifact layout not recognised or all train jobs failed; nothing written")
with open(tj, "w", newline="\n") as fh:
    json.dump(st, fh, indent=1)
subprocess.run([sys.executable, "tools/pm_train.py", str(base), "--merge-from", "none"])   # rewrites map_tuning.h / policy_tuning.h
import check_headers
ok, miss, extra = check_headers.check(base)
if not ok:
    sys.exit(f"ERROR: headers do not match tuning.json after merge ({len(miss)} missing): do not bundle")
print("merged", n, "maps; headers verified against tuning.json")
