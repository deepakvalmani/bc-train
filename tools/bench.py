"""A/B harness: python tools/bench.py bots/CAND bots/BASE [--jobs 8] [--maps a,b] [-v]
Plays every map with both side assignments. Reports wins, gem share (cand gems / all gems,
a less noisy signal than wins) and gem rate. Unparsed results are logged to out/bench_unknown.log."""
import argparse, concurrent.futures as cf, re, subprocess, sys, tempfile, pathlib, time

ROOT = pathlib.Path(__file__).resolve().parent.parent
CAMBC = str(ROOT / "cambc.exe")

def build(bot):
    r = subprocess.run([CAMBC, "build", bot], cwd=ROOT, capture_output=True, text=True)
    if r.returncode: sys.exit(f"build failed for {bot}\n{r.stdout}{r.stderr}")

def play(a, b, m, outdir):
    # Parallel runs occasionally collide on a temp file ("Access is denied"); retry those.
    for attempt in range(5):
        r = subprocess.run([CAMBC, "run", a, b, "--map", m, "-o", outdir],
                           cwd=ROOT, capture_output=True, text=True)
        t = r.stdout + r.stderr
        if "Access is denied" not in t: break
        time.sleep(1 + attempt)
    win = re.search(r"Team ([AB]) \(.*?\) wins: (.*)", t)
    rows = re.findall(r"^\s+([AB])\s+\S+\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)", t, re.M)
    fin = re.search(r"finished: round (\d+)", t)
    gems = {k: int(g) for k, g, *_ in rows}
    return dict(map=m, winner=win.group(1) if win else None,
                rounds=int(fin.group(1)) if fin else 2000, gems=gems, raw=t if not win else "")

def main():
    p = argparse.ArgumentParser()
    p.add_argument("cand"); p.add_argument("base")
    p.add_argument("--jobs", type=int, default=8)
    p.add_argument("--maps", default="")
    p.add_argument("-v", action="store_true", help="per-game table")
    o = p.parse_args()
    maps = o.maps.split(",") if o.maps else sorted(
        f.stem for f in (ROOT / "maps").glob("*.map26a"))
    build(o.cand); build(o.base)
    out = tempfile.mkdtemp(prefix="bench_")
    jobs = [(o.cand, o.base, m, "A") for m in maps] + [(o.base, o.cand, m, "B") for m in maps]
    res = []
    with cf.ThreadPoolExecutor(o.jobs) as ex:
        futs = {ex.submit(play, a, b, m, out): side for a, b, m, side in jobs}
        for f in cf.as_completed(futs):
            r = f.result(); r["cand_team"] = futs[f]; res.append(r)
    wins = losses = unknown = 0
    shares, rates = [], []
    per_map = {}
    for r in sorted(res, key=lambda r: (r["map"], r["cand_team"])):
        ct = r["cand_team"]; bt = "B" if ct == "A" else "A"
        cg, bg = r["gems"].get(ct, 0), r["gems"].get(bt, 0)
        if r["winner"] is None:
            unknown += 1; w = "?"
            with open(ROOT / "out" / "bench_unknown.log", "a") as fh:
                fh.write(f"=== {o.cand} vs {o.base} {r['map']} cand={ct}\n{r['raw'][-1500:]}\n")
        elif r["winner"] == ct: wins += 1; w = "CAND"
        else: losses += 1; w = "base"
        share = cg / (cg + bg) if cg + bg else 0.5
        shares.append(share); rates.append(cg / max(r["rounds"], 1))
        per_map.setdefault(r["map"], []).append(share)
        if o.v:
            print(f"{r['map']:<12}cand={ct}  {w:<5}{r['rounds']:>6}  {cg:>5} : {bg:<5}")
    n = len(res)
    worst = sorted(per_map.items(), key=lambda kv: sum(kv[1]))[:3]
    print("worst maps: " + ", ".join(f"{m} {sum(s)/len(s):.2f}" for m, s in worst))
    print(f"CAND {wins}/{n} wins ({100*wins/max(n,1):.0f}%), losses {losses}, unknown {unknown}"
          f" | gem share {sum(shares)/n:.3f} | gem/round {sum(rates)/n:.2f}")

if __name__ == "__main__":
    main()
