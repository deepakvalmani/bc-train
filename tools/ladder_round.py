"""One-command ladder test of the CURRENTLY UPLOADED bot against the top N teams on every map, then the full analysis.

    python tools/ladder_round.py [--top 10] [--out out/round_<date>] [--no-queue]

Needs the cambc CLI logged in (out/current-runtime/cambc.exe) and a bot already uploaded on the website by a person.
Queues unranked match groups (5 maps each, 4 groups per team cover all 17 maps), waits for them, downloads the summaries
(rate limited, about 4 per minute) and runs tools/ladder_analyze.py. Unranked matches have shown no visible quota: 100 games finish in 15-35 min.
--no-queue only collects + analyses matches created since --since (use after an interrupted run).
Result: <out>/report.txt plus <out>/sum/*.json. Compare reports from two uploads to see what a change did (deaths, gems@300, clears@300)."""
import argparse, datetime, json, pathlib, re, subprocess, sys, time

ROOT = pathlib.Path(__file__).resolve().parent.parent
EXE = str(ROOT / "rt_v5" / "cambc.exe") if (ROOT / "rt_v5" / "cambc.exe").exists() else str(ROOT / "rt_v3" / "cambc.exe") if (ROOT / "rt_v3" / "cambc.exe").exists() else str(ROOT / "out" / "current-runtime" / "cambc.exe")   # new CLI (3.x) reads engine-1.0 summaries
TEAM = "3881272c-9c7f-4b3d-94f9-4c0788a3b27a"
GROUPS = ["00ambush,00collision,00contest,00corners,00eight", "00elkring,00expanse,00fragment,00interlock,00lanes",
          "00monolith,01big_world,01boss_battle,01broken_curve,01concentrated_wealth", "01corridors,01elk_arena,01fracture,01gold_rush,01hooks",
          "01islands,01big_world,01fracture,01boss_battle,00contest"]   # the 21 platform maps (week 2); last group repeats the hard new ones
ap = argparse.ArgumentParser()
ap.add_argument("--top", type=int, default=10)
ap.add_argument("--maps", default="", help="semicolon-separated groups of 5 comma-separated maps (overrides the default 5 groups), e.g. \"01fracture,01islands,01big_world,01corridors,01broken_curve\"; 50 unranked matches per hour are allowed, so one group x 10 teams = 1 hour")
ap.add_argument("--skip", default="", help="comma list of team names not to challenge (already queued in an earlier run)")
ap.add_argument("--above", type=int, default=0, help="challenge the N teams ranked just ABOVE us on the ladder (overrides --first/--top)")
ap.add_argument("--first", type=int, default=1, help="first ladder rank to challenge (e.g. --first 11 --top 20 = ranks 11-20)")
ap.add_argument("--out", default="")
ap.add_argument("--no-queue", action="store_true")
ap.add_argument("--since", default="", help="ISO time; only matches created after it are analysed (default: when this script starts)")
o = ap.parse_args()
if o.maps:
    GROUPS = [g.strip() for g in o.maps.split(";") if g.strip()]
out = ROOT / (o.out or f"out/round_{datetime.datetime.now():%Y%m%d_%H%M}")
(out / "sum").mkdir(parents=True, exist_ok=True)
since = o.since or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M")


def cli(*a):
    return subprocess.run([EXE, *a], capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=ROOT)


def list_matches():
    allm, cur = {}, None
    for _ in range(40):
        r = cli("matches", "list", "--team", TEAM, "--kind", "unranked", "--limit", "25", "--json", *(["--cursor", cur] if cur else []))
        try:
            d = json.loads(r.stdout)
        except Exception:
            break
        for m in d["matches"]:
            allm[m["matchId"]] = m
        cur = d.get("nextCursor")
        if not cur or min(m["createdAt"] for m in d["matches"]) < since:
            break
    return [m for m in allm.values() if m["createdAt"] >= since]


if not o.no_queue:
    if o.above:
        lad = []
        for page in range(1, 12):
            d = json.loads(cli("ladder", "--json", "--limit", "100", "--page", str(page)).stdout)["teams"]
            lad += d
            if any(x["teamId"] == TEAM for x in d) or not d:
                break
        mine = [x for x in lad if x["teamId"] == TEAM]
        myrank = mine[0]["rank"] if mine else None
        print("our rank:", myrank, flush=True)
        top = [x for x in lad if myrank and myrank - o.above <= x["rank"] < myrank]
    else:
        lad = json.loads(cli("ladder", "--json").stdout)["teams"]
        top = [t for t in lad if t["teamId"] != TEAM and o.first <= t["rank"] <= o.top]
    print("opponents:", ", ".join(f"{t['rank']} {t['name']}" for t in top), flush=True)
    q0 = time.time()
    skip = {x.strip() for x in o.skip.split(",") if x.strip()}
    dead = set()
    for t in top:
        if t["name"] in skip:
            continue
        for g in GROUPS:
            if t["name"] in dead:
                break
            while True:
                r = cli("match-groups", "create", t["teamId"], "--maps", g, "--json")
                if "groupId" in r.stdout:
                    break
                if "eligible bot" in (r.stdout + r.stderr) or "HTTP 409" in (r.stdout + r.stderr):
                    print("skipping", t["name"], "(no eligible bot)", flush=True)
                    dead.add(t["name"])
                    break
                if time.time() - q0 > 6 * 3600:
                    print("gave up queueing", t["name"], g, flush=True)
                    break
                print(time.strftime("%H:%M:%S"), "rate limited, waiting 4 min:", (r.stdout + r.stderr)[:80].replace("\n", " "), flush=True)
                time.sleep(240)
    print("queued; waiting for the matches", flush=True)

t0 = time.time()
while time.time() - t0 < 4 * 3600:
    ms = list_matches()
    pend = sum(1 for m in ms if m["status"] != "finished")
    print(time.strftime("%H:%M:%S"), f"{len(ms)} matches, {pend} not finished", flush=True)
    if ms and pend == 0:
        break
    time.sleep(120)
json.dump({"matches": ms}, open(out / "matches.json", "w"))
print("downloading summaries (rate limited, about 4 per minute) ...", flush=True)
subprocess.run([sys.executable, str(ROOT / "tools" / "fetch_sums.py"), str(out / "matches.json"), str(out / "sum")], cwd=ROOT)
rep = subprocess.run([sys.executable, str(ROOT / "tools" / "ladder_analyze.py"), str(out / "sum"), str(out / "matches.json")],
                     capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=ROOT)
(out / "report.txt").write_text(rep.stdout + rep.stderr, encoding="utf8")
print(rep.stdout[:6000])
print("full report:", out / "report.txt")
