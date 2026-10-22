"""Per-map parameter tuner. Each map gets its own policy overrides, chosen by head-to-head results vs several opponents.
python tools/pm_tune.py bots/v46 --maps lanes,corners --opps v44,v43,v36,v38 --jobs 4 --rounds 2 [--work pmA]
Accepted overrides are written into bots/<work>/src/map_policies.h; log in out/pm/<work>.log."""
import argparse, json, os, re, shutil, subprocess, sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent; os.chdir(ROOT)
ap = argparse.ArgumentParser(); ap.add_argument("base"); ap.add_argument("--maps", default="all")
ap.add_argument("--opps", default="v44,v43,v36,v38"); ap.add_argument("--jobs", type=int, default=4)
ap.add_argument("--rounds", type=int, default=2); ap.add_argument("--work", default="pmA")
o = ap.parse_args()
ALL = "ambush collision contest corners eight elkring expanse fragment interlock lanes monolith packs pilgrimage rows rushbait_v2 stampede swirl".split()
maps = ALL if o.maps == "all" else o.maps.split(",")
GRID = [("join_mult", ["1.0f", "0.6f", "3.0f"]), ("overstaff_mult", ["0.3f", "0.03f"]), ("squad_soak", ["0.35", "1.0"]),
        ("team_soak", ["0.3", "1.0"]), ("gem_w", ["1.0", "4.0"]), ("gold_w", ["0.1", "1.0"]), ("camp_overhead", ["2.0", "10.0"]),
        ("clear_rate", ["0.7", "1.5", "2.5"]), ("recall_hp", ["0.25f", "0.5f"])]
work = ROOT / "bots" / o.work
if work.exists(): shutil.rmtree(work)
shutil.copytree(o.base, work, ignore=shutil.ignore_patterns(".cambc"))
PH = work / "src" / "map_policies.h"
out = ROOT / "out" / "pm"; out.mkdir(parents=True, exist_ok=True)
log = open(out / f"{o.work}.log", "a", encoding="utf8")
def say(*a):
    s = " ".join(map(str, a)); print(s, flush=True); log.write(s + "\n"); log.flush()
def add_override(text, mp, field, val):
    i = text.index(f"inline Policy {mp}()")
    j = text.index("return p;", i)
    return text[:j] + f"p.{field}={val};" + text[j:]
def evaluate(mp):
    tag = f"{o.work}_try"
    td = ROOT / "bots" / tag
    if td.exists(): shutil.rmtree(td)
    shutil.copytree(work, td, ignore=shutil.ignore_patterns(".cambc"))
    return td
def run(mp, botdir):
    mapname = mp.replace("_", "-") if mp == "rushbait_v2" else mp
    od = ROOT / "out" / "current-runtime" / "out" / "pm" / o.work
    shutil.rmtree(od, ignore_errors=True)
    subprocess.run([sys.executable, "tools/screen.py", f"bots/{botdir.name}", "--maps", mapname, "--opps", o.opps, "--jobs", str(o.jobs),
                    "--out", f"out/pm/{o.work}"], capture_output=True)
    f = od / (botdir.name + ".json")
    if not f.exists(): return None
    R = [r for r in json.load(open(f)) if not r.get("error")]
    n_exp = 2 * len(o.opps.split(","))
    if len(R) < n_exp - 1: return None
    return sum(r["won"] for r in R) / len(R), sum(r["mine"] - r["theirs"] for r in R) / len(R)
for mp in maps:
    base_txt = PH.read_text()
    td = evaluate(mp); best = run(mp, td); say(f"== {mp} base {best}")
    if best is None: continue
    for rnd in range(o.rounds):
        improved = False
        for field, vals in GRID:
            bestval = None
            for v in vals:
                txt = add_override(PH.read_text(), mp, field, v)
                td = evaluate(mp); (td / "src" / "map_policies.h").write_text(txt)
                sc = run(mp, td)
                say(f"  {mp} r{rnd} {field}={v}: {sc} (best {best})")
                if sc and (sc[0] > best[0] or (sc[0] == best[0] and sc[1] > best[1] + 25)):
                    best = sc; bestval = v
            if bestval is not None:
                PH.write_text(add_override(PH.read_text(), mp, field, bestval)); improved = True
                say(f"  ACCEPT {mp}: {field}={bestval} -> {best}")
        if not improved: break
    say(f"== {mp} final {best}")
say("DONE")
