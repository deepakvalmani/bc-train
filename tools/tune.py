"""Self-play tuner: hill-climb params.h by playing mutated bots against the current best.

    python tools/tune.py [--start bots/v13] [--iters 50] [--accept 0.53]

Each iteration mutates 1-3 parameters of the current best, benches the candidate against it
(9 maps x both sides via tools/bench.py), and keeps the candidate if its gem share beats the
threshold. The best bot so far always lives in bots/tuned; every trial is appended to
out/tune_log.jsonl so nothing is lost if the run is interrupted (rerun to resume from bots/tuned).
"""
import argparse, json, pathlib, random, re, shutil, subprocess, sys, time

ROOT = pathlib.Path(__file__).resolve().parent.parent
LOG = ROOT / "out" / "tune_log.jsonl"

# name: (kind, low, high) for numbers, or ("bool",) for switches.
SPACE = {
    "BANK_AT":           ("int", 10, 60),
    "BANK_NEAR":         ("int", 0, 10),
    "RECALL_HP":         ("float", 0.2, 0.5),
    "SQUAD_SOAK":        ("float", 0.3, 1.0),
    "TEAM_SOAK":         ("float", 0.3, 1.0),
    "OVERSTAFF_MULT":    ("float", 0.05, 0.6),
    "JOIN_MULT":         ("float", 1.0, 3.0),
    "STICKY_MULT":       ("float", 1.0, 2.0),
    "WAIT_CLAIMED_MULT": ("float", 0.02, 0.5),
    "GOLD_W":            ("float", 0.0, 1.0),
    "STUN_FIRST_STR":    ("float", 20.0, 200.0),
    "SHOP_GOLD":         ("int", 0, 400),
    "HUNT_MIN_GEMS":     ("int", 10, 60),
    "LOCKED_DETOUR":     ("int", 0, 25),
    "WARDS":             ("bool",),
    "CONTEST":           ("bool",),
    "LOCK_SNIPE":        ("bool",),
    "OWN_LOCKS":         ("bool",),
    "GEM_HUNT":          ("bool",),
    "USE_SHIELD":        ("bool",),
}

def read_params(bot):
    s = (ROOT / bot / "src" / "params.h").read_text()
    out = {}
    for k in SPACE:
        m = re.search(rf"\b{k}\s*=\s*([^;]+);", s)
        if m: out[k] = m.group(1).strip().rstrip("f")
    return out

def mutate(params, rng):
    new = dict(params)
    for k in rng.sample(sorted(SPACE), rng.randint(1, 3)):
        spec = SPACE[k]
        if spec[0] == "bool":
            new[k] = "false" if params.get(k) == "true" else "true"
        else:
            lo, hi = spec[1], spec[2]
            cur = float(params.get(k, (lo + hi) / 2))
            v = min(hi, max(lo, cur + rng.gauss(0, (hi - lo) * 0.25)))
            new[k] = str(int(round(v))) if spec[0] == "int" else f"{v:.3f}"
    return new

def make_bot(src, dst, params):
    args = [f"{k}={v}" for k, v in params.items()]
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "variant.py"), src, dst, *args],
                       cwd=ROOT, capture_output=True, text=True)
    if r.returncode: raise RuntimeError(r.stdout + r.stderr)

def bench(cand, base):
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "bench.py"), cand, base],
                       cwd=ROOT, capture_output=True, text=True)
    m = re.search(r"CAND (\d+)/(\d+) wins.*gem share ([\d.]+)", r.stdout)
    if not m: raise RuntimeError(r.stdout[-800:] + r.stderr[-800:])
    return int(m.group(1)), int(m.group(2)), float(m.group(3))

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="bots/v13")
    p.add_argument("--iters", type=int, default=50)
    p.add_argument("--accept", type=float, default=0.53)
    p.add_argument("--seed", type=int, default=int(time.time()))
    o = p.parse_args()
    rng = random.Random(o.seed)
    best = ROOT / "bots" / "tuned"
    if not best.exists():
        shutil.copytree(ROOT / o.start, best, ignore=shutil.ignore_patterns(".cambc"))
    LOG.parent.mkdir(exist_ok=True)
    for it in range(o.iters):
        params = read_params("bots/tuned")
        trial = mutate(params, rng)
        changed = {k: (params.get(k), v) for k, v in trial.items() if params.get(k) != v}
        make_bot("bots/tuned", "bots/tune_cand", {k: v for k, (_, v) in changed.items()})
        t0 = time.time()
        try:
            wins, n, share = bench("bots/tune_cand", "bots/tuned")
        except RuntimeError as e:
            print("bench failed:", e); continue
        accepted = share >= o.accept
        rec = dict(iter=it, time=time.strftime("%H:%M"), changed=changed, wins=wins, games=n,
                   share=share, accepted=accepted, secs=round(time.time() - t0))
        with open(LOG, "a") as fh: fh.write(json.dumps(rec) + "\n")
        print(json.dumps(rec), flush=True)
        if accepted:
            shutil.rmtree(best)
            shutil.copytree(ROOT / "bots" / "tune_cand", best, ignore=shutil.ignore_patterns(".cambc"))

if __name__ == "__main__":
    main()
