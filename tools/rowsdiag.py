"""Rows-style diagnostics for a TRACE solo run: python tools/rowsdiag.py bots/vX [map]"""
import re, subprocess, sys, pathlib, collections, json
ROOT = pathlib.Path(__file__).resolve().parent.parent
bot = sys.argv[1]; m = sys.argv[2] if len(sys.argv) > 2 else "rows"
tb = ROOT / "bots" / "diag_tmp"
subprocess.run([sys.executable, str(ROOT / "tools/variant.py"), bot, str(tb.relative_to(ROOT)), "TRACE=true"], cwd=ROOT, capture_output=True)
subprocess.run([str(ROOT / "cambc.exe"), "build", "bots/diag_tmp"], cwd=ROOT, capture_output=True)
out = ROOT / "out" / "diag"; 
subprocess.run(["rm", "-rf", str(out)]); out.mkdir(parents=True)
subprocess.run([str(ROOT / "cambc.exe"), "run", "bots/diag_tmp", "bots/idle", "--map", f"maps/{m}.map26a", "-o", str(out / "r"), "--statistics", str(out / "s.json")], cwd=ROOT, capture_output=True)
rep = sorted((out / "r").glob("*.repl26a"))[0]
import zipfile
txt = zipfile.ZipFile(rep).read("team-a.stdout").decode(errors="ignore").replace("\0", "")
L = re.compile(r'A r(\d+) (\w+) (\w+) tgt(-?\d+) pos\((-?\d+), (-?\d+)\) hp(\d+) gems(\d+) gold(\d+)')
rows = [(int(a), b, c, int(d), (int(e), int(f)), int(h)) for a, b, c, d, e, f, g, h, i in L.findall(txt)]
s = json.load(open(out / "s.json"))
print(f"{m}: finished round {s['round']}, gems {s['teams'][0]['submittedGems']}, deaths {sum(c['deaths'] for c in s['champions'] if c['team']==0)}")
n = len(rows); acts = collections.Counter(a for _, _, a, _, _, _ in rows)
print("time:", {k: f"{100*v/n:.0f}%" for k, v in acts.most_common(9)})
tg = collections.Counter(t for _, _, a, t, _, _ in rows if a in ("fight", "fight_stray", "capturing", "walk_camp"))
print("targets:", tg.most_common(6))
per = collections.defaultdict(collections.Counter)
for _, c, a, _, _, _ in rows: per[c][a] += 1
for c, cc in per.items():
    t = sum(cc.values()); print(f"  {c:8}", {k: f"{100*v/t:.0f}%" for k, v in cc.most_common(6)})
cap = collections.defaultdict(list)
for r, c, a, t, _, _ in rows:
    if a == "capturing": cap[t].append(r)
ev = []
for t, rs in cap.items():
    rs = sorted(set(rs)); st = rs[0]; pv = rs[0]
    for x in rs[1:]:
        if x - pv > 6: ev.append((st, t)); st = x
        pv = x
    ev.append((st, t))
ev.sort(); print("clears:", len(ev), "avg gap %.0f" % (sum(b[0]-a[0] for a, b in zip(ev, ev[1:])) / max(1, len(ev)-1)), ev[:14])
