"""Freeze a copy of a bot as a fixed training opponent (self-play / league training).
python tools/snapshot.py bots/v46 v47     # copies bots/v46 -> bots/v47 (sources + trained values at this moment)
Then train the original against the frozen copy:  python tools/pm_parallel.py bots/v46 --opps v47,v44,v43,v36 ...
Never train the snapshot: it must stay frozen. Keep older snapshots in the pool so the bot does not only learn to beat its last self."""
import shutil, sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
src, name = pathlib.Path(sys.argv[1]), sys.argv[2]
dst = ROOT / "bots" / name
if dst.exists():
    sys.exit(f"{dst} already exists: pick a new name (snapshots must never be overwritten)")
shutil.copytree(ROOT / src, dst, ignore=shutil.ignore_patterns(".cambc", "tuning.json"))
print("frozen", dst)
