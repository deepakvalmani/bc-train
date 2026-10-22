"""Analyse Match Database metadata (tools/db_meta.py output): who wins, on which side, with which champions.
python tools/db_analyze.py out/db18/meta.jsonl"""
import collections, json, sys, math
sys.stdout.reconfigure(encoding="utf-8")
CH = {0: "Ryth", 1: "Vesper", 2: "Vendetta", 3: "Cassi+Issac", 4: "Stellar", 5: "Prism", 6: "Marcella", 7: "Willow", 8: "Ren", 9: "Varg", 10: "Tavi"}
rows = [json.loads(l) for l in open(sys.argv[1], encoding="utf8")]
rows = [r for r in rows if r.get("status") == "finished" and len(r["teams"]) == 2 and {x["result"] for x in r["teams"]} == {"win", "loss"}]
print(len(rows), "decided games;", collections.Counter(r["kind"] for r in rows))

def win(r):  # winning team dict
    return [x for x in r["teams"] if x["result"] == "win"][0]

# ---- side advantage
side = collections.Counter(win(r)["side"] for r in rows)
print(f"\n== side: side b wins {side['b']}/{len(rows)} = {side['b']/len(rows):.3f} (95% CI +-{1.96*math.sqrt(.25/len(rows)):.3f})")
bm = collections.defaultdict(lambda: [0, 0])
for r in rows:
    bm[r["map"]][1] += 1; bm[r["map"]][0] += win(r)["side"] == "b"
print("side-b win rate by map:", " ".join(f"{m}:{a}/{n}" for m, (a, n) in sorted(bm.items(), key=lambda kv: -kv[1][0] / kv[1][1])))

# ---- champions: pick rate and win rate, overall and by team strength
tw = collections.Counter(); tn = collections.Counter()
for r in rows:
    for x in r["teams"]: tn[x["name"]] += 1; tw[x["name"]] += x["result"] == "win"
strong = {n for n in tn if tn[n] >= 6 and tw[n] / tn[n] >= 0.65}
print(f"\n== champions (win rate when picked; 'strong' = teams with >=6 games and >=65% wins, {len(strong)} teams)")
pk = collections.defaultdict(lambda: [0, 0]); pks = collections.defaultdict(lambda: [0, 0])
for r in rows:
    for x in r["teams"]:
        for c in set(int(v) for v in x["draftPicks"]):
            pk[c][1] += 1; pk[c][0] += x["result"] == "win"
            if x["name"] in strong: pks[c][1] += 1; pks[c][0] += x["result"] == "win"
n_team_games = len(rows) * 2
print(f"{'champion':12}{'pick%':>7}{'win%':>7}{'n':>6} | strong teams: pick% win% n")
ns = sum(1 for r in rows for x in r['teams'] if x['name'] in strong)
for c, (w, n) in sorted(pk.items(), key=lambda kv: -kv[1][1]):
    sw, sn = pks[c]
    print(f"{CH.get(c, c):12}{n/n_team_games*100:>6.0f}%{w/n*100:>6.0f}%{n:>6} |  {sn/max(1,ns)*100:>5.0f}% {sw/max(1,sn)*100:>4.0f}% {sn:>4}")

# ---- team sizes and lineups
size = collections.defaultdict(collections.Counter)
for r in rows:
    for x in r["teams"]: size[r["map"]][len(x["draftPicks"])] += 1
print("\n== picks per team by map (team size):", {m: dict(c) for m, c in sorted(size.items())})
lin = collections.defaultdict(lambda: [0, 0])
for r in rows:
    for x in r["teams"]:
        key = tuple(sorted(int(v) for v in x["draftPicks"]))
        lin[key][1] += 1; lin[key][0] += x["result"] == "win"
print("\n== most common lineups (win%):")
for k, (w, n) in sorted(lin.items(), key=lambda kv: -kv[1][1])[:12]:
    print(f"  {n:4} games {w/n*100:4.0f}%  " + "+".join(CH.get(c, str(c)) for c in k))
print("\n== best lineups with >=12 games:")
for k, (w, n) in sorted([kv for kv in lin.items() if kv[1][1] >= 12], key=lambda kv: -kv[1][0] / kv[1][1])[:8]:
    print(f"  {n:4} games {w/n*100:4.0f}%  " + "+".join(CH.get(c, str(c)) for c in k))

# ---- first pick
fp = collections.defaultdict(lambda: [0, 0])
for r in rows:
    for x in r["teams"]:
        if x["draftPicks"]:
            c = int(x["draftPicks"][0]); fp[c][1] += 1; fp[c][0] += x["result"] == "win"
print("\n== first draft pick (win%):", " ".join(f"{CH.get(c,c)}:{w/n*100:.0f}%({n})" for c, (w, n) in sorted(fp.items(), key=lambda kv: -kv[1][1])[:6]))
print("\n== most successful teams (>=8 games):")
for n in sorted([n for n in tn if tn[n] >= 8], key=lambda n: -tw[n] / tn[n])[:12]: print(f"  {n[:30]:30} {tw[n]}/{tn[n]} = {tw[n]/tn[n]:.2f}")
