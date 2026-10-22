"""Fetch a team's most recent finished matches (default Intercontinental Fish) and download their replays.
python tools/fish_fetch.py N [team_id]  -> out/fish2/<matchId>.repl, list merged into out/fish2/list.json (rate-limit aware)."""
import json, subprocess, sys, os, time
T = sys.argv[2] if len(sys.argv) > 2 else "1890540d-1ffc-4847-adbf-d0d08772f268"
N = int(sys.argv[1]) if len(sys.argv) > 1 else 50
out = os.environ.get("TEAMDIR", "out/fish2"); os.makedirs(out, exist_ok=True)
EXE = os.path.abspath("rt_v5/cambc.exe")


def cli(*a):
    for k in range(12):
        r = subprocess.run([EXE, *a], capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout
        print("retry", k, (r.stderr or "")[:200].strip(), flush=True)
        time.sleep(10 * (k + 1))
    raise SystemExit("CLI failed: " + " ".join(a))


old = {}
if os.path.exists(out + "/list.json"):
    for m in json.load(open(out + "/list.json", encoding="utf-8")): old[m["matchId"]] = m
ms, cur = [], None
while len(ms) < N:
    d = json.loads(cli("matches", "list", "--team", T, "--limit", "50", "--json", *(["--cursor", cur] if cur else [])))
    ms += [m for m in d["matches"] if m["status"] == "finished"]
    cur = d.get("nextCursor")
    print("listed", len(ms), flush=True)
    if not cur: break
for m in ms[:N]: old[m["matchId"]] = m
json.dump(sorted(old.values(), key=lambda m: m["createdAt"], reverse=True), open(out + "/list.json", "w", encoding="utf-8"))
got = 0
for m in ms[:N]:
    f = f"{out}/{m['matchId']}.repl"
    if os.path.exists(f): continue
    for k in range(6):
        subprocess.run([EXE, "matches", "download", m["matchId"], "-o", f], capture_output=True)
        if os.path.exists(f): got += 1; break
        time.sleep(10 * (k + 1))
print("listed", len(ms[:N]), "new downloads", got, "total in list", len(old))
