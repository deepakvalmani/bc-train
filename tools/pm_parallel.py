"""Run several per-map trainers at the same time, each in its own isolated runtime folder, then merge the results.

    python tools/pm_parallel.py bots/v46 --workers 2 --hours 10          # start (maps are split between the workers)
    python tools/pm_parallel.py bots/v46 --merge                         # merge worker results into bots/v46 (also done at the end)

Why isolated: trainers must not share one runtime folder (they overwrite each other's compiled bots and results).
Each worker i gets:  out/runtime_wi/   (lean copy of out/current-runtime: cambc.exe, maps, sdk, cmake, opponents v36/v38)
                     bots/<base>_wi/    (copy of the bot with its own tuning.json)
                     out/pm/train_wi.log
Workers train disjoint sets of maps, so merging is just copying each worker's map entries into <base>/tuning.json.
Choose --workers by CPU cores: 2 for 8 cores (default), 3 for 12+ cores. Each worker runs --batch candidates at once,
each candidate plays --jobs games at once.
"""
import argparse, os, pathlib, shutil, subprocess, sys, time

ROOT = pathlib.Path(__file__).resolve().parent.parent
os.chdir(ROOT)
ap = argparse.ArgumentParser()
ap.add_argument("base")
ap.add_argument("--workers", type=int, default=2)
ap.add_argument("--hours", type=float, default=10.0)
ap.add_argument("--maps", default="all")
ap.add_argument("--batch", type=int, default=2)
ap.add_argument("--jobs", type=int, default=2)
ap.add_argument("--patience", type=int, default=45)
ap.add_argument("--per-map-minutes", type=float, default=25.0)
ap.add_argument("--opps", default="v44,v43,v36,v38")
ap.add_argument("--confirm", default="v42,v40,rep_v36,rep_v38")
ap.add_argument("--merge", action="store_true", help="only merge worker results into the base bot and exit")
o = ap.parse_args()
base = pathlib.Path(o.base)
name = base.name
ALL = ("ambush collision contest corners eight elkring expanse fragment interlock lanes monolith packs "
       "pilgrimage rows rushbait_v2 stampede swirl").split()
maps = ALL if o.maps == "all" else o.maps.split(",")
workers = [f"bots/{name}_w{i}" for i in range(o.workers)]
groups = [maps[i::o.workers] for i in range(o.workers)]


def merge():
    subprocess.run([sys.executable, "tools/pm_train.py", o.base, "--merge-from", ",".join(workers)], check=False)


if o.merge:
    merge()
    sys.exit(0)

src_rt = ROOT / "out" / "current-runtime"
procs = []
for i, (wdir, grp) in enumerate(zip(workers, groups)):
    rt_dir = ROOT / "out" / f"runtime_w{i}"
    if not (rt_dir / "cambc.exe").exists():
        print(f"creating isolated runtime {rt_dir} ...", flush=True)
        rt_dir.mkdir(parents=True, exist_ok=True)
        for item in src_rt.iterdir():
            if item.name in ("out", "bots") or item.suffix == ".txt":
                continue
            dst = rt_dir / item.name
            if item.is_dir():
                shutil.copytree(item, dst, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".cambc"))
            else:
                shutil.copy2(item, dst)
        (rt_dir / "bots").mkdir(exist_ok=True)
        for b in ("v36", "v38", "idle"):
            if (src_rt / "bots" / b).exists() and not (rt_dir / "bots" / b).exists():
                shutil.copytree(src_rt / "bots" / b, rt_dir / "bots" / b, ignore=shutil.ignore_patterns(".cambc"))
    if not (ROOT / wdir).exists():
        shutil.copytree(ROOT / base, ROOT / wdir, ignore=shutil.ignore_patterns(".cambc"))
    env = dict(os.environ, CAMBC_HOME=str(pathlib.Path("out") / f"runtime_w{i}"))
    cmd = [sys.executable, "tools/pm_train.py", wdir, "--maps", ",".join(grp), "--hours", str(o.hours), "--batch", str(o.batch),
           "--jobs", str(o.jobs), "--patience", str(o.patience), "--per-map-minutes", str(o.per_map_minutes),
           "--opps", o.opps, "--confirm", o.confirm, "--tag", f"pmw{i}_", "--log", f"train_w{i}.log"]
    print(f"worker {i}: maps {grp}", flush=True)
    procs.append(subprocess.Popen(cmd, env=env))
    time.sleep(5)
print("all workers started. Watch: Get-Content out/pm/train_w0.log -Wait -Tail 20  (and train_w1.log). Ctrl-C stops everything.", flush=True)
try:
    while any(p.poll() is None for p in procs):
        time.sleep(30)
except KeyboardInterrupt:
    print("stopping workers ...", flush=True)
    for p in procs:
        p.terminate()
    time.sleep(3)
print("merging worker results into", o.base, flush=True)
merge()
