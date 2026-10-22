"""Self-play generation loop on top of tools/pm_train.py.

    python tools/selfplay_loop.py --seed-bot v46 --hours 10 --gens 3

Each gen: a copy of the current best is trained per map vs (frozen copy of the best, older best / v44, v45); confirm vs v43/v42/v45.
A generation ends when every map is saturated / at patience, or its time slice runs out (remaining time / remaining gens).
Gate: a generation is promoted only if it wins >=50% head-to-head (34 games) vs the current best; otherwise it is dropped.
"""
import argparse, json, pathlib, shutil, subprocess, sys, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import safeio

ROOT = pathlib.Path(__file__).resolve().parent.parent
ap = argparse.ArgumentParser()
ap.add_argument("--seed-bot", default="v48")
ap.add_argument("--hours", type=float, default=10.0)
ap.add_argument("--gens", type=int, default=3)
ap.add_argument("--maps", default="all")
ap.add_argument("--jobs", type=int, default=3)
ap.add_argument("--batch", type=int, default=3)
ap.add_argument("--per-map-minutes", type=float, default=10.0)
ap.add_argument("--patience", type=int, default=45)
o = ap.parse_args()
log = open(ROOT / "out" / "sp_loop.log", "a", encoding="utf8")


def say(*a):
    s = time.strftime("%d %H:%M:%S ") + " ".join(map(str, a))
    print(s, flush=True); log.write(s + "\n"); log.flush()


def clone(src, dst):
    shutil.rmtree(ROOT / "bots" / dst, ignore_errors=True)
    shutil.copytree(ROOT / "bots" / src, ROOT / "bots" / dst, ignore=shutil.ignore_patterns(".cambc", ".done"))


def reset_scores(bot):
    f = ROOT / "bots" / bot / "tuning.json"
    st = json.load(open(f))
    for m in st["maps"].values():
        m.update(score=None, cscore=None, tested=[], stalled=0, accepted=0)
        m.pop("sat_logged", None)
    safeio.dump_json(f, st)


import re
t_end = time.time() + o.hours * 3600
best, older = o.seed_bot, "v44"
say(f"== selfplay loop: seed {best}, {o.hours}h, {o.gens} gens")


def h2h(bot, opp):
    r = subprocess.run([sys.executable, "tools/h2h.py", f"bots/{bot}", opp, "4"], cwd=ROOT, capture_output=True, text=True)
    m = re.search(r"wins (\d+)/(\d+) = ([\d.]+)\s+gemdiff (-?[\d.]+)", r.stdout)
    return (int(m[1]), int(m[2]), float(m[4])) if m else None


for g in range(1, o.gens + 1):
    cur = f"sp_g{g}"
    left = (t_end - time.time()) / 3600
    if left < 0.5:
        break
    budget = left / (o.gens - g + 1)
    frozen = f"{best}_frozen"
    clone(best, frozen)                      # frozen copy of the current best = self-play opponent
    clone(best, cur)
    reset_scores(cur)
    train_opps = f"{frozen},{older},v44" if older != "v44" else f"{frozen},v44,v45"
    confirm = "v45,v43" if older != "v44" else "v43,v42"
    say(f"-- gen {g}: train {cur} (from {best}) vs {train_opps} (confirm {confirm}) budget {budget:.2f}h")
    rc = subprocess.call([sys.executable, "-u", "tools/pm_train.py", f"bots/{cur}", "--maps", o.maps, "--hours", f"{budget:.3f}",
                          "--opps", train_opps, "--confirm", confirm, "--jobs", str(o.jobs), "--batch", str(o.batch),
                          "--per-map-minutes", str(o.per_map_minutes), "--patience", str(o.patience), "--margin", "60",
                          "--seed", str(g), "--tag", f"spt{g}_", "--log", f"sp_g{g}.log"], cwd=ROOT)
    say(f"-- gen {g} trainer exit {rc}")
    # direction gate: promote only if the new gen beats the current best head-to-head on all maps, both sides
    r = h2h(cur, best)
    r2 = h2h(cur, "v44")
    say(f"-- gate: {cur} vs {best}: {r}   vs v44: {r2}   (wins, games, mean gem diff)")
    if r and r[0] / r[1] >= 0.5 and r[2] >= 0:
        older, best = best, cur
        say(f"-- PROMOTED {cur}; best is now {best}")
    else:
        say(f"-- REJECTED {cur} (not better than {best}); next gen restarts from {best} with a new seed")

say(f"== done. best = {best}. Bundle: out/current-runtime/cambc.exe bundle bots/{best}")
