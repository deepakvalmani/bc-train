"""Roadmap screen: candidate vs the repaired v36/v38 on chosen maps, both sides.

    python tools/screen.py bots/v43 --maps rows,elkring [--opps rep_v36,rep_v38] [--out out/screen]

Per game: winner, final round, our/their submitted gems, our deaths, fuel-suspension count if reported.
Prints a per-map table and totals; writes JSON to out/screen/<cand>.json. Local engine (cambc 2.1.6),
so numbers differ slightly from the website-engine qualification in docs/RELEASE_V42.md.
"""
import argparse, json, pathlib, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import rt

ROOT = rt.HOME
ALL = ("ambush collision contest corners eight elkring expanse fragment interlock lanes monolith packs "
       "pilgrimage rows rushbait-v2 stampede swirl").split()


# `cambc run` re-checks / rebuilds BOTH bots before every game. Games that start together collide on the same build files
# ("ninja: error: failed recompaction: Permission denied") and the second one fails, so a trainer baseline could never get
# its 7-of-8 games. Fix: only one game at a time may be in its build phase (a lock shared by all processes); once the
# game prints that it is drafting/running, the lock is released and the game plays in parallel with the others.
import threading, time, os, shutil
_BUILD_LOCAL = threading.Lock()
_BUILD_DIR = ROOT / "out" / ".buildlock"


def _acquire_build_lock():
    for _ in range(1200):
        try:
            os.makedirs(_BUILD_DIR.parent, exist_ok=True)
            os.mkdir(_BUILD_DIR)
            return True
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(_BUILD_DIR) > 300:   # stale lock from a crashed run
                    shutil.rmtree(_BUILD_DIR, ignore_errors=True)
            except OSError:
                pass
            time.sleep(0.5)
        except OSError:
            time.sleep(0.5)
    return False


def run_game(cmd, cwd):
    with _BUILD_LOCAL:
        got = _acquire_build_lock()
        p = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        buf = b""
        t0 = time.time()
        try:
            while time.time() - t0 < 300:
                chunk = p.stdout.read1(4096)
                if not chunk:
                    break
                buf += chunk
                if b"drafting" in buf or b"running" in buf:
                    break
        finally:
            if got:
                shutil.rmtree(_BUILD_DIR, ignore_errors=True)
    rest, _ = p.communicate()
    return p.returncode, (buf + rest).decode("utf-8", errors="replace")


def run(cand, opp, side, m, outdir):
    a, b = (cand, opp) if side == 0 else (opp, cand)
    tag = f"{pathlib.Path(cand).name}-{pathlib.Path(opp).name}-{m}-{side}"
    out = outdir / tag
    st = outdir / f"{tag}.json"
    for _ in range(6):
        import time; time.sleep(0 if _ == 0 else 3)
        run_game([rt.EXE, "run", a, b, "--map", (str(rt.HOME / "maps" / f"{m}.map26a") if (rt.HOME / "maps" / f"{m}.map26a").exists() else f"maps/{m}.map26a"), "-o", str(out), *rt.stats_args(st), *rt.RUN_FLAGS], rt.HOME if rt.NEW else ROOT)
        if st.exists():
            break
    if not st.exists():
        return dict(map=m, opp=opp, side=side, error=True)
    s = rt.load_stats(st)
    me = side
    ch = [c for c in s["champions"] if c["team"] == me]
    th = [c for c in s["champions"] if c["team"] != me]
    mine = s["teams"][me]["submittedGems"]
    theirs = s["teams"][1 - me]["submittedGems"]
    return dict(map=m, opp=opp, side=side, round=s["round"], mine=mine, theirs=theirs,
                won=(s.get("outcome") == ("teamA" if me == 0 else "teamB")),
                deaths=sum(c["deaths"] for c in ch), kills=sum(c["kills"] for c in ch),
                gold=sum(c["earnedGold"] for c in ch) / max(1, len(ch)),
                md=sum(c["monsterDamageDone"] for c in ch) / 1000,
                their_md=sum(c["monsterDamageDone"] for c in th) / 1000,
                faults=sum(s.get("botFaults", [0, 0])),
                champs=[dict(name=c["name"], gems=c.get("submittedGems", 0), collected=c.get("collectedGems", 0),
                             md=c.get("monsterDamageDone", 0), cd=c.get("championDamageDone", 0),
                             deaths=c.get("deaths", 0), kills=c.get("kills", 0), gold=c.get("earnedGold", 0)) for c in ch],
                their_champs=[c["name"] for c in th])


def main():
    p = argparse.ArgumentParser()
    p.add_argument("cand")
    p.add_argument("--maps", default="rows,elkring")
    p.add_argument("--opps", default="")
    p.add_argument("--jobs", type=int, default=2)
    p.add_argument("--out", default="out/screen")
    o = p.parse_args()
    maps = ALL if o.maps == "all" else o.maps.split(",")
    opps = [f"bots/{x}" for x in o.opps.split(",")] if o.opps else rt.default_opps()
    for x in [o.cand] + opps: rt.prep(x)
    outdir = ROOT / o.out
    outdir.mkdir(parents=True, exist_ok=True)
    subprocess.run([rt.EXE, "build", o.cand], cwd=rt.HOME if rt.NEW else ROOT, capture_output=True)
    for x in opps:
        subprocess.run([rt.EXE, "build", x], cwd=rt.HOME if rt.NEW else ROOT, capture_output=True)
    jobs = [(o.cand, x, s, m, outdir) for m in maps for x in opps for s in (0, 1)]
    with ThreadPoolExecutor(o.jobs) as ex:
        res = list(ex.map(lambda j: run(*j), jobs))
    json.dump(res, open(outdir / f"{pathlib.Path(o.cand).name}.json", "w"), indent=1)
    print(f"{'map':11}{'W/L':>7}{'gems(us:them)':>16}{'deaths':>8}{'rounds':>8}{'camp dmg k':>12}")
    tw = tn = 0
    for m in maps:
        L = [r for r in res if r["map"] == m and not r.get("error")]
        w = sum(r["won"] for r in L)
        tw += w
        tn += len(L)
        if L:
            print(f"{m:11}{w:>3}/{len(L):<3}{sum(r['mine'] for r in L) / len(L):>9.0f}:{sum(r['theirs'] for r in L) / len(L):<6.0f}"
                  f"{sum(r['deaths'] for r in L) / len(L):>8.1f}{sum(r['round'] for r in L) / len(L):>8.0f}"
                  f"{sum(r['md'] for r in L) / len(L):>7.0f}/{sum(r['their_md'] for r in L) / len(L):<4.0f}")
    print(f"TOTAL {tw}/{tn}   faults {sum(r.get('faults', 0) for r in res if not r.get('error'))}   errors {sum(1 for r in res if r.get('error'))}")


if __name__ == "__main__":
    main()
