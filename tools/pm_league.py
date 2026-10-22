"""Self-play league for one or more maps (runs as one CI job per map, or locally).

    python tools/pm_league.py bots/v46 --maps lanes --hours 5.3

Loop: train the map(s) with tools/pm_train.py until every map is converged/saturated or time runs out; then freeze a
snapshot of the current bot (tools/snapshot.py), add it to the training opponents (newest snapshots + the fixed older
bots), reset the map's search state (tested list, scores) and train again against the stronger pool. Repeats until --hours.
The confirmation opponents stay fixed so the bot cannot drift into beating only its own copies.
"""
import argparse, json, os, pathlib, subprocess, sys, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import safeio
ROOT = pathlib.Path(__file__).resolve().parent.parent
os.chdir(ROOT)
ap = argparse.ArgumentParser()
ap.add_argument("base")
ap.add_argument("--maps", required=True)
ap.add_argument("--hours", type=float, default=5.3)
ap.add_argument("--opps", default="v44,v43,v36,v38")
ap.add_argument("--confirm", default="v42,v40,rep_v36,rep_v38")
ap.add_argument("--jobs", type=int, default=2)
ap.add_argument("--batch", type=int, default=2)
ap.add_argument("--patience", type=int, default=40)
ap.add_argument("--keep-snapshots", type=int, default=2)
o = ap.parse_args()
base = pathlib.Path(o.base)
tag = o.maps.replace(",", "_").replace("-", "_")
t_end = time.time() + o.hours * 3600
fixed = o.opps.split(",")
snaps = []
rnd = 0
tj = ROOT / base / "tuning.json"
while True:
    left = (t_end - time.time()) / 3600
    if left < 0.15:
        break
    pool = snaps[:o.keep_snapshots] + [f for f in fixed if f not in snaps]
    pool = pool[:max(4, len(fixed))]
    print(f"=== league round {rnd}: {left:.2f} h left, opponents {pool}", flush=True)
    cmd = [sys.executable, "tools/pm_train.py", str(base), "--maps", o.maps, "--hours", f"{left:.3f}", "--opps", ",".join(pool),
           "--confirm", o.confirm, "--jobs", str(o.jobs), "--batch", str(o.batch), "--patience", str(o.patience),
           "--per-map-minutes", "100000", "--log", f"league_{tag}.log", "--tag", f"lg{tag}_"]
    rc = subprocess.run(cmd).returncode
    if rc != 0:
        print(f"pm_train exited with code {rc}; stopping league", flush=True)
        break
    if (t_end - time.time()) / 3600 < 0.3:
        break
    name = f"lg_{tag}_{rnd}"
    if subprocess.run([sys.executable, "tools/snapshot.py", str(base), name]).returncode != 0:
        break
    snaps.insert(0, name)
    st = json.load(open(tj))
    for mp in o.maps.split(","):
        m = st["maps"].get(mp)
        if m:
            m.update({"stalled": 0, "sat_logged": False, "score": None, "cscore": None, "tested": []})
    safeio.dump_json(tj, st)
    rnd += 1
print("=== league finished", flush=True)
