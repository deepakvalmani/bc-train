"""python tools/playbook_stats.py <sumdir> <mine.json> [<mine2.json> ...]
Behaviour comparison us vs the opponents (shopping, banking, wards): what the top teams DO that we do not."""
import collections, glob, json, os, sys
ME = "Stubborn Shard Casters"
sd = sys.argv[1]; meta = {}
for mj in sys.argv[2:]:
    for m in json.load(open(mj, encoding="utf8"))["matches"]:
        meta[m["matchId"][:8]] = m
agg = {"us": collections.defaultdict(list), "them": collections.defaultdict(list)}
items = {"us": collections.Counter(), "them": collections.Counter()}
byrole = {"us": collections.defaultdict(collections.Counter), "them": collections.defaultdict(collections.Counter)}
n = 0; seen = set()
for f in glob.glob(sd + "/*.json"):
    k = os.path.basename(f)[:8]; m = meta.get(k)
    if not m: continue
    side = {t["name"]: t["side"] for t in m["teams"]}
    if ME not in side: continue
    oname = [t["name"] for t in m["teams"] if t["name"] != ME][0]
    sig = (m["map"], oname, side[ME])
    if sig in seen: continue
    seen.add(sig); n += 1
    d = json.load(open(f, encoding="utf8"))
    me = "teamA" if side[ME] == "a" else "teamB"
    for who, team in (("us", me), ("them", "teamB" if me == "teamA" else "teamA")):
        buys = [(x["timestamp"]["round"], e["owner"]["name"], x["target"]["name"], x["amount"]) for e in d["events"] if e["kind"] == "buyItem" and e["owner"].get("team") == team for x in e["entries"]]
        cons = [(x["timestamp"]["round"], x["target"]["name"]) for e in d["events"] if e["kind"] == "buyConsumable" and e["owner"].get("team") == team for x in e["entries"]]
        comb = [x["timestamp"]["round"] for e in d["events"] if e["kind"] == "itemCombination" and e["owner"].get("team") == team for x in e["entries"]]
        subs = [(x["timestamp"]["round"], float(x["value"])) for e in d["events"] if e["kind"] == "gemSubmission" and e["owner"].get("team") == team for x in e["entries"]]
        wards = [x["timestamp"]["round"] for e in d["events"] if e["kind"] == "wardPlacement" and e["owner"].get("team") == team for x in e["entries"]]
        ch = [c for c in d["champions"] if c["team"] == team]
        agg[who]["buys<=300"].append(sum(1 for b in buys if b[0] <= 300))
        agg[who]["spent_gold"].append(sum(float(c["metrics"].get("spentGold", 0)) for c in ch))
        agg[who]["earned_gold"].append(sum(float(c["metrics"].get("earnedGold", 0)) for c in ch))
        agg[who]["combos"].append(len(comb))
        agg[who]["consumables"].append(len(cons))
        agg[who]["submissions"].append(len(subs))
        agg[who]["avg_submit"].append(sum(v for _, v in subs) / len(subs) if subs else 0)
        agg[who]["first_submit"].append(min((r for r, _ in subs), default=0))
        agg[who]["wards"].append(len(wards))
        agg[who]["first_buy"].append(min((b[0] for b in buys), default=0))
        agg[who]["heal"].append(sum(float(c["metrics"].get("healingDone", 0)) for c in ch))
        agg[who]["shield"].append(sum(float(c["metrics"].get("shieldingDone", 0)) for c in ch))
        agg[who]["assists"].append(sum(float(c["metrics"].get("assists", 0)) for c in ch))
        for b in buys: items[who][b[2]] += 1
        for b in buys:
            if b[0] <= 300: byrole[who][b[1]][b[2]] += 1
        for c in cons: items[who]["consumable:" + c[1]] += 1
print(n, "games\n")
avg = lambda xs: sum(xs) / len(xs) if xs else 0
print(f"{'metric':16}{'us':>10}{'them':>10}")
for k in agg["us"]:
    print(f"{k:16}{avg(agg['us'][k]):>10.1f}{avg(agg['them'][k]):>10.1f}")
print("\nmost bought items per game (us | them):")
names = sorted(set(items["us"]) | set(items["them"]), key=lambda x: -(items["them"][x] + items["us"][x]))
for x in names[:22]:
    print(f"  {x[:44]:44}{items['us'][x] / n:>6.2f} |{items['them'][x] / n:>6.2f}")
