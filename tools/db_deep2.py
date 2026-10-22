"""Pass-2 analysis: casts, cohesion and approach of winners vs losers (out/db18/data/h_*.json from extract2.js).
python tools/db_deep2.py out/db18/meta.jsonl out/db18/data"""
import collections, glob, json, math, statistics as st, sys
sys.stdout.reconfigure(encoding="utf-8")
meta = {}
for l in open(sys.argv[1], encoding="utf8"):
    r = json.loads(l); meta[r["matchId"]] = r
H = {}
for f in glob.glob(sys.argv[2] + "/h_*.json"): H.update(json.load(open(f, encoding="utf8")))
games = []
for i, h in H.items():
    m = meta.get(i)
    if not m or len(h["rows"]) < 4: continue
    res = {x["side"]: x["result"] for x in m["teams"]}
    if set(res.values()) != {"win", "loss"}: continue
    games.append(dict(id=i, win=0 if res["a"] == "win" else 1, h=h, map=m["map"], kind=m["kind"]))
print(len(games), "games")
def team(x, role): return x["win"] if role == "w" else 1 - x["win"]
avg = lambda L: st.mean(L) if L else float("nan")
# casts per champion-round (approx: casts / (alive champions * rounds))
print("\n== ability casts (cooldown jumps), per game, winner vs loser")
for lab, idx in (("all casts away from enemies", 0), ("casts with an enemy within 8 tiles", 1)):
    W = [x["h"]["casts"][team(x, "w")][idx] for x in games]; L = [x["h"]["casts"][team(x, "l")][idx] for x in games]
    print(f"  {lab}: winner {avg(W):.1f} vs loser {avg(L):.1f}")
W = [x["h"]["castsEarly"][team(x, "w")] for x in games]; L = [x["h"]["castsEarly"][team(x, "l")] for x in games]
print(f"  casts in the first 150 rounds: winner {avg(W):.1f} vs loser {avg(L):.1f}")
# casts per round of fighting time -> normalise by number of rows
nW = [x["h"]["casts"][team(x, "w")][1] / max(1, len(x["h"]["rows"])) for x in games]; nL = [x["h"]["casts"][team(x, "l")][1] / max(1, len(x["h"]["rows"])) for x in games]
print(f"  fight casts per 10 rounds: winner {avg(nW):.2f} vs loser {avg(nL):.2f}")
print("\n== cohesion and approach (rows are every 10 rounds; per-team [alive, mean nearest-ally dist, largest cluster share, cx, cy])")
for lo, hi in ((20, 60), (60, 120), (120, 300)):
    nnw = []; nnl = []; clw = []; cll = []; cdist = []; alw = []; all_ = []
    for x in games:
        for row in x["h"]["rows"]:
            if lo <= row[0] < hi:
                w, l = row[1 + team(x, "w")], row[1 + team(x, "l")]
                if w[0] > 1: nnw.append(w[1]); clw.append(w[2])
                if l[0] > 1: nnl.append(l[1]); cll.append(l[2])
                alw.append(w[0]); all_.append(l[0])
                if w[0] and l[0]: cdist.append(max(abs(w[3] - l[3]), abs(w[4] - l[4])))
    print(f"  rounds {lo}-{hi}: nearest ally {avg(nnw):.1f} vs {avg(nnl):.1f} tiles | largest cluster share {avg(clw):.2f} vs {avg(cll):.2f} | alive {avg(alw):.2f} vs {avg(all_):.2f} | centroid distance {avg(cdist):.1f}   (winner vs loser)")
# who closes the distance in the opening: centroid movement toward the enemy r20-60
print("\n== opening movement (rounds 20-60): how far each team's centroid moves, and toward the enemy?")
mw = []; ml = []; tw = []; tl = []
for x in games:
    rows = [r for r in x["h"]["rows"] if 20 <= r[0] <= 60]
    if len(rows) < 3: continue
    a, b = rows[0], rows[-1]
    for role, lst, tlst in (("w", mw, tw), ("l", ml, tl)):
        t = team(x, role); o = 1 - t
        p0, p1 = a[1 + t], b[1 + t]; q0 = a[1 + o]
        if not (p0[0] and p1[0] and q0[0]): continue
        d = (p1[3] - p0[3], p1[4] - p0[4]); v = (q0[3] - p0[3], q0[4] - p0[4]); n = math.hypot(*v) or 1
        lst.append(math.hypot(*d)); tlst.append((d[0] * v[0] + d[1] * v[1]) / n)
print(f"  distance moved: winner {avg(mw):.1f} vs loser {avg(ml):.1f} tiles; component toward the enemy: winner {avg(tw):.1f} vs loser {avg(tl):.1f}")
# casts vs result by map group
print("\n== winner's fight casts / loser's fight casts by map")
bm = collections.defaultdict(lambda: [[], []])
for x in games:
    bm[x["map"]][0].append(x["h"]["casts"][team(x, "w")][1]); bm[x["map"]][1].append(x["h"]["casts"][team(x, "l")][1])
print("  " + "  ".join(f"{m}:{avg(a):.0f}/{avg(b):.0f}" for m, (a, b) in sorted(bm.items())))
