"""Deep analysis of engine-extracted games (out/db18/data/g_*.json, made by out/db18/web/extract.js) joined with metadata.
python tools/db_deep.py out/db18/meta.jsonl out/db18/data"""
import collections, glob, json, statistics as st, sys
sys.stdout.reconfigure(encoding="utf-8")
CH = {0: "Ryth", 1: "Vesper", 2: "Vendetta", 3: "Cassi+Issac", 4: "Stellar", 5: "Prism", 6: "Marcella", 7: "Willow", 8: "Ren", 9: "Varg", 10: "Tavi"}
meta = {}
for l in open(sys.argv[1], encoding="utf8"):
    r = json.loads(l); meta[r["matchId"]] = r
G = {}
for f in glob.glob(sys.argv[2] + "/g_*.json"):
    G.update(json.load(open(f, encoding="utf8")))
games = []
for i, g in G.items():
    m = meta.get(i)
    if not m or len(g["series"]) < 3: continue
    res = {x["side"]: x["result"] for x in m["teams"]}
    if set(res.values()) != {"win", "loss"}: continue
    win = 0 if res["a"] == "win" else 1
    games.append(dict(id=i, map=m["map"], kind=m["kind"], win=win, g=g, names=[x["name"] for x in sorted(m["teams"], key=lambda x: x["side"])]))
print(len(games), "games joined;", collections.Counter(x["kind"] for x in games), "| maps", len(set(x["map"] for x in games)))

def at(g, r, k):
    """series row at the last sample <= r"""
    best = None
    for row in g["series"]:
        if row[0] <= r: best = row
    return best

# --- 1. game length / how games end
ends = [x["g"]["rounds"] for x in games]
fin = [x for x in games if max(x["g"]["series"][-1][1:3]) >= 900]
print(f"\n== length: median last sampled round {st.median(ends):.0f}; games where someone reached >=900 gems: {len(fin)}/{len(games)}")

# --- 2. how early does the lead predict the winner
print("\n== does the team ahead on tributed gems at round R win? (games still running at R)")
for R in (100, 150, 200, 300, 400):
    n = ok = 0
    for x in games:
        row = at(x["g"], R, 0)
        if not row or row[0] < R - 12 or row[1] == row[2]: continue
        n += 1; ok += (0 if row[1] > row[2] else 1) == x["win"]
    if n: print(f"  r{R}: leader wins {ok}/{n} = {ok/n:.0%}")
print("== same with total gems collected+carried+tributed (series field gems carried col 7 + tributed):")
for R in (60, 100, 150, 200, 300):
    n = ok = 0
    for x in games:
        row = at(x["g"], R, 0)
        if not row or row[0] < R - 12: continue
        a = row[1] + row[3][7]; b = row[2] + row[4][7]
        if a == b: continue
        n += 1; ok += (0 if a > b else 1) == x["win"]
    if n: print(f"  r{R}: leader wins {ok}/{n} = {ok/n:.0%}")

# --- 3. winner vs loser profile by round
def prof(R, f):
    w = []; l = []
    for x in games:
        row = at(x["g"], R, 0)
        if not row or row[0] < R - 12: continue
        a, b = f(row, 0), f(row, 1)
        (w if x["win"] == 0 else l).append(a if x["win"] == 0 else a)  # placeholder
        # winner team index = x["win"]
    return None
fields = {"alive": 0, "hp": 1, "maxhp": 2, "strength": 3, "focus": 4, "items": 5, "gold held": 6, "gems carried": 7, "gold earned": 8, "kills": 9, "deaths": 10, "assists": 11}
print("\n== winner vs loser, mean per team (rows: round) ")
for name, k in fields.items():
    line = f"{name:13}"
    for R in (50, 100, 200, 300):
        W = []; L = []
        for x in games:
            row = at(x["g"], R, 0)
            if not row or row[0] < R - 12: continue
            w, l = row[3 + x["win"]], row[3 + 1 - x["win"]]
            W.append(w[k]); L.append(l[k])
        if W: line += f"  r{R}: {st.mean(W):7.0f} vs {st.mean(L):7.0f}"
    print(line)
print("(winner vs loser)")

# --- 4. deaths and first blood
first = collections.Counter(); fw = collections.Counter()
for x in games:
    d = x["g"]["deaths"]
    if not d: first["none"] += 1; continue
    t = min(d)[1]; first[t == x["win"]] += 1
print(f"\n== first blood: the team that lost the first champion won {first[False]} of {first[True]+first[False]} games ({first[False]/max(1,first[True]+first[False]):.0%}); games with no deaths: {first['none']}")
dw = [sum(1 for d in x["g"]["deaths"] if d[1] == x["win"]) for x in games]
dl = [sum(1 for d in x["g"]["deaths"] if d[1] != x["win"]) for x in games]
print(f"deaths per game: winner {st.mean(dw):.1f} vs loser {st.mean(dl):.1f} (medians {st.median(dw):.0f} / {st.median(dl):.0f}); zero-death winners {sum(1 for v in dw if v==0)}/{len(games)}")
ct = [x["g"]["contact"] for x in games if x["g"]["contact"]]
print(f"first contact round: median {st.median(ct):.0f} (n={len(ct)})")
# deaths by champion type for winners vs losers
dt = collections.defaultdict(lambda: [0, 0])
for x in games:
    for d in x["g"]["deaths"]: dt[d[2]][0 if d[1] == x["win"] else 1] += 1
print("deaths by champion type (winner team / loser team):", {CH.get(t, t): tuple(v) for t, v in sorted(dt.items(), key=lambda kv: -sum(kv[1]))[:8]})
al = [d[4] for x in games for d in x["g"]["deaths"] if d[1] != x["win"]]; fo = [d[5] for x in games for d in x["g"]["deaths"] if d[1] != x["win"]]
print(f"loser deaths: allies within 8 tiles {st.mean(al):.2f}, foes {st.mean(fo):.2f}, HP fraction above 75%: {sum(1 for x in games for d in x['g']['deaths'] if d[1]!=x['win'] and d[3]>0.75)/max(1,len(al)):.0%}")
al = [d[4] for x in games for d in x["g"]["deaths"] if d[1] == x["win"]]; fo = [d[5] for x in games for d in x["g"]["deaths"] if d[1] == x["win"]]
print(f"winner deaths: allies within 8 tiles {st.mean(al):.2f}, foes {st.mean(fo):.2f}" if al else "winner deaths: none")

# --- 5. camps held
print("\n== camp groups captured (series col 5: [team0, team1, neutral] at r100/200/300): winner vs loser")
for R in (100, 200, 300):
    W = []; L = []
    for x in games:
        row = at(x["g"], R, 0)
        if not row or row[0] < R - 12: continue
        gc = row[5]; W.append(gc[x["win"]]); L.append(gc[1 - x["win"]])
    if W: print(f"  r{R}: winner {st.mean(W):.1f} vs loser {st.mean(L):.1f}")

# --- 6. by map: winner speed
print("\n== by map: n, median round the winner reached its final gems, winner deaths/loser deaths")
bm = collections.defaultdict(list)
for x in games: bm[x["map"]].append(x)
for m, L in sorted(bm.items()):
    dw = st.mean(sum(1 for d in x["g"]["deaths"] if d[1] == x["win"]) for x in L); dl = st.mean(sum(1 for d in x["g"]["deaths"] if d[1] != x["win"]) for x in L)
    rr = [x["g"]["rounds"] for x in L]
    print(f"  {m:12}{len(L):>3}  last sampled round median {st.median(rr):>5.0f}   deaths {dw:4.1f} vs {dl:4.1f}")

# --- 7. first blood in detail
print("\n== first blood in detail")
fb = []
for x in games:
    d = sorted(x["g"]["deaths"])
    if not d: continue
    r, t, ty, hp, al, fo = d[0]
    fb.append(dict(round=r, victim_won=(t == x["win"]), type=ty, hp=hp, al=al, fo=fo, contact=x["g"]["contact"], map=x["map"]))
print(f"n={len(fb)}; first death round: median {st.median(f['round'] for f in fb):.0f}; gap after first contact: median {st.median(f['round']-f['contact'] for f in fb if f['contact']):.0f} rounds")
print(f"victim had allies within 8 tiles: {st.mean(f['al'] for f in fb):.2f}, foes {st.mean(f['fo'] for f in fb):.2f}; victim HP above 75%: {sum(1 for f in fb if f['hp']>0.75)/len(fb):.0%}")
print("first victim champion types:", {CH.get(t, t): c for t, c in collections.Counter(f['type'] for f in fb).most_common(6)})
out = collections.defaultdict(lambda: [0, 0])
for f in fb:
    k = "victim alone (0 allies)" if f["al"] == 0 else ("victim outnumbered (foes>allies+1)" if f["fo"] > f["al"] + 1 else "even or better")
    out[k][1] += 1; out[k][0] += not f["victim_won"]
print("first-blood team wins, by situation of the victim:", {k: f"{a}/{n}" for k, (a, n) in out.items()})
early = [f for f in fb if f["round"] <= 80]
print(f"first death before round 80: {len(early)} games; first-blood team won {sum(1 for f in early if not f['victim_won'])}/{len(early)}")
# --- 8. winning margin: how fast the winner finishes vs map
print("\n== winners' pace: tributed gems of the WINNER at r150/r250/r350 (median) vs loser")
for R in (150, 250, 350):
    W = []; L = []
    for x in games:
        row = at(x["g"], R, 0)
        if not row or row[0] < R - 12: continue
        W.append(row[1 + x["win"]]); L.append(row[1 + 1 - x["win"]])
    if W: print(f"  r{R}: winner {st.median(W):.0f}, loser {st.median(L):.0f}  (n={len(W)})")
