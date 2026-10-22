"""Per-game diagnosis from a TRACE build: python tools/gamediag.py bots/v42 elkring [opp=v36] [side=1]
Prints time budget, camp targets, clears, bank trips, deaths timeline and per-champion budgets (our team only)."""
import re, subprocess, sys, pathlib, collections, zipfile, shutil
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import rt
ROOT = pathlib.Path(__file__).resolve().parent.parent
bot, m = sys.argv[1], sys.argv[2]
opp = sys.argv[3] if len(sys.argv) > 3 else "v36"; side = int(sys.argv[4]) if len(sys.argv) > 4 else 0
tmp = ROOT / "bots" / "diag_tmp"
if not (tmp / "src").exists():   # prepare bots/diag_tmp yourself: copy of the bot with TRACE=true in params.base.h, then tools/gen_tune.py
    sys.exit("bots/diag_tmp missing")
rt.prep("bots/diag_tmp"); oppb = ("bots/" + opp) if opp != "idle" else "bots/idle"; rt.prep(oppb)
for b in ("bots/diag_tmp", oppb): subprocess.run([rt.EXE, "build", b], cwd=rt.HOME, capture_output=True)
out = rt.HOME / "out" / "gd"; shutil.rmtree(out, ignore_errors=True); out.mkdir(parents=True)
a, b = ("bots/diag_tmp", oppb) if side == 0 else (oppb, "bots/diag_tmp")
subprocess.run([rt.EXE, "run", a, b, "--map", f"maps/{m}.map26a", "-o", str(out / "r"), *rt.stats_args(out / "s.json"), *rt.RUN_FLAGS,
                "--log-limit", "0"] if False else [rt.EXE, "run", a, b, "--map", f"maps/{m}.map26a", "-o", str(out / "r"), *rt.stats_args(out / "s.json"), *rt.RUN_FLAGS],
               cwd=rt.HOME, capture_output=True, text=True)
rep = sorted((out / "r").glob("*.repl26a"))[0]
z = zipfile.ZipFile(rep); name = "team-a.stdout" if side == 0 else "team-b.stdout"
txt = z.read(name).decode(errors="ignore").replace("\0", "")
L = re.compile(r'[AB] r(\d+) (\w+) (\w+) tgt(-?\d+) pos\((-?\d+), (-?\d+)\) hp(\d+) gems(\d+) gold(\d+)')
rows = [(int(a_), b_, c_, int(d_), (int(e_), int(f_)), int(g_), int(h_)) for a_, b_, c_, d_, e_, f_, g_, h_, i_ in L.findall(txt)]
s = rt.load_stats(out / "s.json"); me = side
ch = [c for c in s["champions"] if c["team"] == me]
print(f"{m} vs {opp} (we are side {side}): round {s['round']} gems {s['teams'][me]['submittedGems']}:{s['teams'][1-me]['submittedGems']} "
      f"deaths {sum(c['deaths'] for c in ch):.0f} kills {sum(c['kills'] for c in ch):.0f} camp dmg {sum(c['monsterDamageDone'] for c in ch)/1000:.0f}k")
n = len(rows); acts = collections.Counter(x[2] for x in rows)
print("time:", {k: f"{100*v/n:.0f}%" for k, v in acts.most_common(10)})
per = collections.defaultdict(collections.Counter)
for r, c, a_, *_ in rows: per[c][a_] += 1
for c, cc in per.items():
    t = sum(cc.values()); dd = [x for x in ch if x["name"].lower().startswith(c[:4])]
    print(f"  {c:9}", {k: f"{100*v/t:.0f}%" for k, v in cc.most_common(6)}, ("deaths %.0f camp %.0fk gold %.0f" % (dd[0]['deaths'], dd[0]['monsterDamageDone']/1000, dd[0]['earnedGold'])) if dd else "")
tg = collections.Counter(t for _, _, a_, t, *_ in rows if a_ in ("fight", "fight_stray", "capturing", "walk_camp"))
print("camp targets (turns):", tg.most_common(8))
dead = collections.defaultdict(list); lastd = {}
for r, c, a_, *_ in rows:
    if a_ == "dead" and not lastd.get(c): dead[c].append(r)
    lastd[c] = (a_ == "dead")
print("death rounds:", {c: v for c, v in dead.items()})
last = {}; trips = []
for r, c, a_, t, p, hp, g in rows:
    pv = last.get(c, 0)
    if pv > 0 and g == 0 and a_ not in ("dead",): trips.append(pv)
    last[c] = g
print(f"bank trips {len(trips)} avg bag {sum(trips)/max(1,len(trips)):.0f}")
shutil.rmtree(tmp, ignore_errors=True)
