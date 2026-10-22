"""Pure farming speed: rounds to 1000 gems with nobody opposing. python tools/solo.py bots/X [--maps a,b]"""
import json, subprocess, sys, pathlib, re
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import rt
ROOT = rt.HOME
MAPS = "collision corners elkring expanse interlock lanes monolith packs rows".split()
bot = sys.argv[1]
maps = MAPS
if "--maps" in sys.argv: maps = sys.argv[sys.argv.index("--maps") + 1].split(",")
rt.prep(bot); rt.prep("bots/idle")
subprocess.run([rt.EXE, "build", bot], cwd=ROOT, capture_output=True)
subprocess.run([rt.EXE, "build", "bots/idle"], cwd=ROOT, capture_output=True)
res = {}
for m in maps:
    out = ROOT / "out" / "solo_tmp"
    for attempt in range(3):
        r = subprocess.run([rt.EXE, "run", bot, "bots/idle", "--map", f"maps/{m}.map26a", "-o", str(out / m),
                            *rt.stats_args(out / f"{m}.json"), *rt.RUN_FLAGS], cwd=ROOT, capture_output=True, text=True)
        p = out / f"{m}.json"
        if p.exists(): break
    s = rt.load_stats(p); p.unlink()
    res[m] = s["round"] if s["teams"][0]["submittedGems"] >= 1000 else 9999
print(bot, "avg %d" % (sum(res.values()) / len(res)), " ".join(f"{k[:4]}{v}" for k, v in res.items()))
