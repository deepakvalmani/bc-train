"""Analyse ladder/challenge match summaries against many opponents.
python tools/ladder_analyze.py <sumdir> <mine.json> [<mine2.json> ...]   (mine files = {"matches": [...]} from `cambc matches list --json`)

Prints: per-opponent table, per-map table, speed milestones (round to 250/500/750/1000 gems, us vs them), death timing,
camp clears by round 300, draft usage and per-champion deaths/damage. Reusable after every challenge round."""
import collections, glob, json, os, sys

ME = "let's jump into it"
sd = sys.argv[1]
meta = {}
for mj in sys.argv[2:]:
    for m in json.load(open(mj, encoding="utf8"))["matches"]:
        meta[m["matchId"][:8]] = m
MILE = (250, 500, 750, 1000)


def reach(runs, target):
    """round at which a cumulative-run series first reaches `target` (None if never)"""
    t = 0
    for r in runs:
        if float(r["value"]) >= target:
            return t
        t += r["duration"]
    return None


def final(runs):
    return float(runs[-1]["value"]) if runs else 0.0


def at_round(runs, rnd):
    t, v = 0, 0.0
    for r in runs:
        if t > rnd:
            break
        v = float(r["value"]); t += r["duration"]
    return v


rows = []
for f in glob.glob(sd + "/*.json"):
    k = os.path.basename(f)[:8]
    m = meta.get(k)
    if not m:
        continue
    d = json.load(open(f, encoding="utf8"))
    side = {t["name"]: t["side"] for t in m["teams"]}
    if ME not in side:
        continue
    me = "teamA" if side[ME] == "a" else "teamB"
    op = "teamB" if me == "teamA" else "teamA"
    oname = [t["name"] for t in m["teams"] if t["name"] != ME][0]
    res = [t["result"] for t in m["teams"] if t["name"] == ME][0]
    tl = {(t["owner"], t["metric"]): t["runs"] for t in d["teamTimelines"]}
    mg, og = tl.get((me, "submittedGems"), []), tl.get((op, "submittedGems"), [])
    ch = d["champions"]
    S = lambda team, key: sum(float(c["metrics"].get(key, 0)) for c in ch if c["team"] == team)
    deaths = {me: [], op: []}
    clears = {me: [], op: []}
    for e in d["events"]:
        team = e["owner"].get("team") if isinstance(e.get("owner"), dict) else None
        if e["kind"] == "death" and team in deaths:
            deaths[team] += [x["timestamp"]["round"] for x in e["entries"]]
        if e["kind"] == "campClear" and team in clears:
            clears[team] += [x["timestamp"]["round"] for x in e["entries"]]
    names = {t: sorted(c["name"] for c in ch if c["team"] == t) for t in (me, op)}
    rows.append(dict(opp=oname, map=m["map"], won=res == "win", rounds=d["match"]["roundsCompleted"],
                     gems=final(mg), ogems=final(og),
                     mile={x: reach(mg, x) for x in MILE}, omile={x: reach(og, x) for x in MILE},
                     g300=at_round(mg, 300), og300=at_round(og, 300),
                     dth=len(deaths[me]), odth=len(deaths[op]), d_early=sum(1 for r in deaths[me] if r <= 150),
                     d_mid=sum(1 for r in deaths[me] if 150 < r <= 300), d_late=sum(1 for r in deaths[me] if r > 300),
                     clr=len(clears[me]), oclr=len(clears[op]), clr300=sum(1 for r in clears[me] if r <= 300),
                     oclr300=sum(1 for r in clears[op] if r <= 300),
                     mon=S(me, "monsterDamageDone"), omon=S(op, "monsterDamageDone"),
                     cdm=S(me, "championDamageDone"), ocdm=S(op, "championDamageDone"),
                     gold=S(me, "earnedGold"), ogold=S(op, "earnedGold"),
                     heal=S(me, "healingDone"), oheal=S(op, "healingDone"),
                     me_names=names[me], op_names=names[op],
                     champs={c["name"]: dict(d=float(c["metrics"].get("deaths", 0)), mon=float(c["metrics"].get("monsterDamageDone", 0)),
                                             cd=float(c["metrics"].get("championDamageDone", 0)), g=float(c["metrics"].get("gems", 0)))
                             for c in ch if c["team"] == me}))

print(len(rows), "analysed matches,", sum(r["won"] for r in rows), "wins\n")
avg = lambda xs: sum(xs) / len(xs) if xs else float("nan")


def table(key, title):
    G = collections.defaultdict(list)
    for r in rows:
        G[r[key]].append(r)
    print(f"== {title}")
    print(f"{key:14}{'n':>3}{'win':>4}{'gems':>6}{'ogems':>6}{'g@300':>6}{'og@300':>7}{'dth':>5}{'odth':>5}{'clr300':>7}{'oclr300':>8}{'mon k':>6}{'omon k':>7}")
    for k, v in sorted(G.items(), key=lambda kv: -avg([r["ogems"] - r["gems"] for r in kv[1]])):
        print(f"{k:14}{len(v):>3}{sum(r['won'] for r in v):>4}{avg([r['gems'] for r in v]):>6.0f}{avg([r['ogems'] for r in v]):>6.0f}"
              f"{avg([r['g300'] for r in v]):>6.0f}{avg([r['og300'] for r in v]):>7.0f}{avg([r['dth'] for r in v]):>5.1f}{avg([r['odth'] for r in v]):>5.1f}"
              f"{avg([r['clr300'] for r in v]):>7.1f}{avg([r['oclr300'] for r in v]):>8.1f}{avg([r['mon'] for r in v]) / 1000:>6.0f}{avg([r['omon'] for r in v]) / 1000:>7.0f}")
    print()


table("opp", "per opponent (sorted by gem gap)")
table("map", "per map (sorted by gem gap)")

print("== speed milestones: mean round to reach N submitted gems (reached/total games), us vs them")
for x in MILE:
    a = [r["mile"][x] for r in rows if r["mile"][x] is not None]
    b = [r["omile"][x] for r in rows if r["omile"][x] is not None]
    print(f"  {x:>4} gems: us {avg(a):>6.0f} ({len(a)}/{len(rows)})   them {avg(b):>6.0f} ({len(b)}/{len(rows)})")

print("\n== our deaths by game phase (all games): rounds 0-150 / 150-300 / 300+;  zero-death games:",
      sum(1 for r in rows if r["dth"] == 0))
print("  ", round(sum(r["d_early"] for r in rows)), "/", round(sum(r["d_mid"] for r in rows)), "/", round(sum(r["d_late"] for r in rows)))
low = [r for r in rows if r["dth"] <= 5]
high = [r for r in rows if r["dth"] > 5]
print(f"  games with <=5 deaths: n={len(low)} our gems {avg([r['gems'] for r in low]):.0f} vs {avg([r['ogems'] for r in low]):.0f}"
      f" | >5 deaths: n={len(high)} our gems {avg([r['gems'] for r in high]):.0f} vs {avg([r['ogems'] for r in high]):.0f}")

print("\n== our champions: deaths / monster dmg(k) / champion dmg(k) / gems per appearance")
C = collections.defaultdict(list)
for r in rows:
    for n, v in r["champs"].items():
        C[n].append(v)
for n, v in sorted(C.items(), key=lambda kv: -len(kv[1])):
    print(f"  {n:8} games {len(v):>3}  deaths {avg([x['d'] for x in v]):>5.1f}  mon {avg([x['mon'] for x in v]) / 1000:>5.1f}  champ {avg([x['cd'] for x in v]) / 1000:>5.1f}  gems {avg([x['g'] for x in v]):>6.0f}")

print("\n== draft usage (share of games a champion is in the lineup)")
us, th = collections.Counter(), collections.Counter()
for r in rows:
    us.update(set(r["me_names"])); th.update(set(r["op_names"]))
names = sorted(set(us) | set(th), key=lambda n: -(th[n] + us[n]))
for n in names:
    print(f"  {n:8} us {us[n] / len(rows) * 100:>4.0f}%   them {th[n] / len(rows) * 100:>4.0f}%")

print("\n== near misses (deaths <=5 and they won): opp map gems/ogems deaths round")
for r in sorted((r for r in rows if r["dth"] <= 5 and not r["won"]), key=lambda r: -r["gems"]):
    print(f"  {r['opp'][:14]:14} {r['map']:12} {r['gems']:>5.0f}/{r['ogems']:>5.0f}  dth {r['dth']}  r{r['rounds']}")
