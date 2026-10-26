"""Parallel general-bot trainer (one global settings block for ALL maps).

    python -u tools/gtrain.py bots/g65 --hours 10                       # all CPU cores, resumable
    python -u tools/gtrain.py bots/g65 --hours 10 --lanes 6 --shard 0/2  # machine A of two (disjoint fields)
    python tools/gtrain.py bots/g65 --merge-from bots/g65_a,bots/g65_b   # combine shard results, verify, write into bots/g65

Why it is built this way
  * LANES: every lane is an isolated runtime copy (cambc.exe + sdk + maps) with its own opponent builds. One lane = one
    candidate at a time (build ~35 s, then its games one after another). N lanes = N candidates at once, no build lock clashes.
  * 3 stages, all deterministic (a game result never changes, so the accepted candidate's own scores become the new baseline):
      S0  quick screen  : few games, must not lose
      S1  train screen  : 8 maps x 2 sparring bots x both sides
      S2  confirm       : 8 OTHER maps x 3 other sparring bots, must not get worse
    Final check (--final) plays the best bot and the start bot on EVERY map in the pool.
  * score = win rate, then gems - death_w*(deaths-kills) + speed_w*gems/round (same shape as pm_train).
  * Settings trained: all ~210 numeric/bool fields of tune_fields.txt, 13 policy fields, and the champion draft order (incl. Heart of Ruin).
  * Results are written in the standard tuning.json (map "general") and generated headers, so tools/bundle.py works unchanged.
"""
import argparse, json, os, pathlib, random, shutil, subprocess, sys, threading, time, zlib
from concurrent.futures import ThreadPoolExecutor

ROOT = pathlib.Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT / "tools"))
import safeio

EXE_NAME = "cambc.exe" if os.name == "nt" else "cambc"
ap = argparse.ArgumentParser()
ap.add_argument("base")
ap.add_argument("--runtime", default="rt_v6", help="runtime folder to clone for every lane (cambc.exe, sdk, cmake, maps, cambc.toml)")
ap.add_argument("--lanes", type=int, default=max(1, (os.cpu_count() or 4) // 2), help="parallel candidates; default = half the cores so a laptop stays usable (each lane runs one game at a time)")
ap.add_argument("--hours", type=float, default=8.0)
ap.add_argument("--seed", type=int, default=1)
ap.add_argument("--shard", default="0/1", help="i/N: this process only tries fields whose index %% N == i (run shards on different machines, then --merge-from)")
ap.add_argument("--s0-maps", default="00eight,01hooks,00corners,01the-farm")
ap.add_argument("--s0-opps", default="v63")
ap.add_argument("--s1-maps", default="00eight,00corners,00lanes,00fragment,01hooks,01starfish,01gold-rush,01the-farm")
ap.add_argument("--s1-opps", default="v63,v1.0.0")
ap.add_argument("--s2-maps", default="00collision,00swirl,01islands,01corridors,01shortcut,01starvation,00gemfight,00great-wall")
ap.add_argument("--s2-opps", default="v64,v53_3,v46cloud")
ap.add_argument("--final-maps", default="all")
ap.add_argument("--final-opps", default="v63,v64")
ap.add_argument("--death-w", type=float, default=60.0)
ap.add_argument("--speed-w", type=float, default=150.0)
ap.add_argument("--fault-w", type=float, default=400.0, help="penalty per bot fault (fuel overrun / suspended turn / error) of the candidate")
ap.add_argument("--trade-w", type=float, default=0.02, help="reward per point of (champion damage dealt - taken)")
ap.add_argument("--gold-w", type=float, default=0.02, help="reward per gold earned (shop power)")
ap.add_argument("--win-w", type=float, default=300.0, help="bonus for a win, scaled by how early it ends (1 - round/3000)")
ap.add_argument("--margin", type=float, default=25.0)
ap.add_argument("--s0-margin", type=float, default=-15.0, help="S0 passes when win rate is not lower and score > baseline + this")
ap.add_argument("--max-candidates", type=int, default=0)
ap.add_argument("--no-draft", action="store_true")
ap.add_argument("--final", action="store_true", help="only run the final all-maps comparison of the base bot vs its starting settings and exit")
ap.add_argument("--merge-from", default="")
ap.add_argument("--tag", default="gt")
ap.add_argument("--from", dest="src", default="g65", help="bot to copy when BASE does not exist yet (default g65)")
ap.add_argument("--count", action="store_true", help="print how many candidate changes exist and exit")
o = ap.parse_args()

BASE = pathlib.Path(o.base) if pathlib.Path(o.base).is_absolute() else ROOT / o.base
if not (BASE / "src").exists():   # first run: make the private training copy from the general base bot
    srcbot = ROOT / "bots" / o.src
    if not (srcbot / "src").exists():
        sys.exit(f"!! {BASE} does not exist and the source bot {srcbot} was not found. Run: python tools/make_general.py")
    shutil.copytree(srcbot, BASE, ignore=shutil.ignore_patterns(".cambc", "compile_commands.json"))
    print(f"created private training copy {BASE} from {srcbot}", flush=True)
RTSRC = ROOT / o.runtime
OUT = ROOT / "out" / "gt" / BASE.name
OUT.mkdir(parents=True, exist_ok=True)
logf = open(OUT / "train.log", "a", encoding="utf8")
LOCK = threading.RLock()
STOP = threading.Event()
PROG = {}


def say(*a):
    s = time.strftime("%H:%M:%S ") + " ".join(map(str, a))
    print(s, flush=True)
    with LOCK:
        logf.write(s + "\n"); logf.flush()


# ---------------------------------------------------------------- settings state (standard tuning.json schema)
TJ = BASE / "tuning.json"
state = json.load(open(TJ)) if TJ.exists() else {"maps": {}}
G = state["maps"].setdefault("general", {"tune": {}, "policy": {}, "draft": None, "score": None, "cscore": None, "tested": [], "accepted": 0,
                                         "team_size": None, "champs": {}, "sets": {}})
fields = {}
for line in (BASE / "src" / "tune_fields.txt").read_text().splitlines():
    if not line.strip(): continue
    t, n, v = line.split(None, 2)
    try:
        fields[n] = (t, (v.strip() == "true") if t == "bool" else float(v.strip().rstrip("f")))
    except ValueError:
        pass
SKIP = {"TRACE", "MARK_PRIORITY", "KILL_PRIORITY", "PATH_BUILD_FUEL", "NAV_BUILD_FUEL", "FUEL_RESERVE", "FUEL_GUARD", "STATE_FROM_SNAPSHOT",
        "LOCAL_BITS", "STATIC_NAV", "NAV_BIG", "NAV_BIG_AREA", "CHOICE_CACHE", "CHOICE_TTL", "PRUNE_CAMPS"}
POLICY = {"clear_rate": ("float", 1.0), "gold_only_scale": ("float", 1.0), "near_k": ("int", 0), "death_memory": ("bool", False),
          "lone_flee": ("bool", False), "lone_foes": ("int", 3), "rally": ("bool", False), "respawn_gate": ("int", 0), "home_only": ("bool", False),
          "gate_buddies": ("int", 1), "spiral_deaths": ("int", 0), "flee_outnumbered": ("bool", False), "solo_capture": ("bool", False)}
DEFAULT_DRAFT = [3, 4, 8, 0, 9, 10, 2, 7, 6, 1, 5, 11]
CHAMPS = [11, 8, 4, 3, 0, 1, 2, 6, 9, 10, 7, 5]   # ids: ryth0 vesper1 vendetta2 cassi+issac3 stellar4 prism5 marcella6 willow7 ren8 varg9 tavi10 heart_of_ruin11


def lit(t, v):
    if t == "bool": return "true" if v else "false"
    if t == "int": return str(int(v))
    return repr(round(float(v), 4)) + ("f" if t == "float" else "")


def parse(t, s):
    return s == "true" if t == "bool" else float(str(s).rstrip("f"))


def write_headers(botdir, st):
    g = st["maps"].get("general", {})
    tl = [f"        t.{n} = {v};" for n, v in sorted(g.get("tune", {}).items())]
    pl = [f"        p.{n} = {v};" for n, v in sorted(g.get("policy", {}).items())]
    if g.get("draft"):
        pl += ["        p.explicit_draft = true;", "        p.draft = {" + ",".join(map(str, g["draft"])) + "};"]
    cases = ("    case M::unknown:\n" + "\n".join(tl) + "\n        break;") if tl else ""
    pcases = ("    case Map::unknown:\n" + "\n".join(pl) + "\n        break;") if pl else ""
    (botdir / "src" / "map_tuning.h").write_text(
        '#pragma once\n// GENERATED by tools/gtrain.py from tuning.json. Included inside namespace tune.\n#include "map_policies.h"\n'
        "inline void apply_map(map_policies::Map m, Tune& t) {\n    using M = map_policies::Map;\n    (void)t; (void)m;\n    switch (m) {\n"
        + cases + "\n    default: break;\n    }\n}\n", encoding="utf8")
    (botdir / "src" / "policy_tuning.h").write_text(
        "#pragma once\n// GENERATED by tools/gtrain.py from tuning.json. Included inside namespace map_policies.\n"
        "namespace policy_tuning {\ninline void apply(Map m, Policy& p) {\n    (void)p;\n    switch (m) {\n" + pcases + "\n    default: break;\n    }\n}\n}\n", encoding="utf8")


def save():
    safeio.dump_json(TJ, state)
    write_headers(BASE, state)


def GEN():
    return state["maps"]["general"]


def apply_cand(st, c):
    st = json.loads(json.dumps(st))
    g = st["maps"]["general"]
    kind, n, v = c
    if kind == "draft": g["draft"] = [int(x) for x in v.split(",")]
    elif kind == "bundle":   # several settings that only make sense together
        for k2, d2 in json.loads(v).items(): g[k2].update(d2)
    else: g[kind][n] = v
    return st


def candidates(rng, shard):
    g = G
    C = []
    DEP = {"SPAWN_DEF_FOES": "SPAWN_DEF", "SPAWN_DEF_SEE": "SPAWN_DEF", "SPAWN_DEF_SLACK": "SPAWN_DEF", "SPAWN_DEF_R": "SPAWN_DEF", "SPAWN_DEF_HOLD": "SPAWN_DEF",
           "FISH_SPELL_PCT": "FISH_SPELL_FIRST", "FISH_ENGAGE_HP": "FISH_ENGAGE", "FISH_ENGAGE_SLACK": "FISH_ENGAGE"}
    for n, (t, d) in fields.items():
        if n in SKIP: continue
        if n in DEP and str(g["tune"].get(DEP[n], "false")) != "true": continue
        if n == "TOGETHER_FROM" and float(str(g["tune"].get("TOGETHER_MULT", "1.0")).rstrip("f")) == 1.0: continue
        cur = d if n not in g["tune"] else parse(t, g["tune"][n])
        if t == "bool": vals = [not cur]
        elif t == "int": vals = sorted({max(0, int(round(cur * 0.5))), int(round(cur * 2)) if cur else 1, int(cur) + 1})
        else: vals = [cur * 0.5, cur * 2] if cur else [0.1, 0.5]
        for v in vals:
            if t != "bool" and v == cur: continue
            if "HP" in n and t != "bool" and v > 1.0 and cur <= 1.0: continue
            C.append(("tune", n, lit(t, v)))
    for n, (t, d) in POLICY.items():
        cur = d if n not in g["policy"] else parse(t, g["policy"][n])
        if t == "bool": vals = [not cur]
        elif n == "near_k": vals = [0, 10, 20]
        elif n == "lone_foes": vals = [2, 4]
        elif n == "respawn_gate": vals = [0, 25, 50, 80]
        elif n == "gate_buddies": vals = [1, 2, 3]
        elif n == "spiral_deaths": vals = [0, 2, 3, 4]
        else: vals = [cur * 0.5, cur * 2] if cur else [0.5, 2.0]
        for v in vals:
            if v != cur: C.append(("policy", n, lit(t, v)))
    B = lambda **kw: ("bundle", "FISH_BUNDLE_" + "_".join(sorted(kw)), json.dumps({"tune": {k: lit("bool", v) if isinstance(v, bool) else v for k, v in kw.items()}}, sort_keys=True))
    for kw in (dict(FISH_LOWEST_HP=True, FISH_SPELL_FIRST=True, FISH_CHAMP_FIRST=True),
               dict(FISH_LOWEST_HP=True, FISH_SPELL_FIRST=True, FISH_CHAMP_FIRST=True, FISH_ENGAGE=True),
               dict(FISH_CHAMP_FIRST=True, FISH_ENGAGE=True),
               dict(FISH_CHAMP_FIRST=True, FISH_LOWEST_HP=True),
               dict(SPAWN_DEF=True, FISH_ENGAGE=True),
               dict(SPAWN_DEF=True, FISH_CHAMP_FIRST=True, FISH_LOWEST_HP=True),
               dict(SPAWN_DEF=True, FISH_LOWEST_HP=True, FISH_SPELL_FIRST=True, FISH_CHAMP_FIRST=True, FISH_ENGAGE=True),
               dict(TOGETHER_MULT="4.0")):
        C.append(B(**kw))
    # Sprint 3 patch: new emblem families 7 tribute, 8 capture (capture 5 -> 3 turns), 9 prospector, 10 hunter (+50 gold per kill), 11 skirmish (+5% champion damage), 12 greed, 13 collector
    for fam in (8, 9, 10, 11, 7):
        for slot in (1, 2, 3):
            C.append(("bundle", f"EMBLEM_SLOT{slot}_FAM{fam}", json.dumps({"tune": {f"{r}_ITEM_FAMILY{slot}": str(fam) for r in ("TANK", "CASTER", "MELEE")}}, sort_keys=True)))
    C.append(("draft", "draft", "1,11,6,0,2,8,4,5,10,7,9,3"))   # top-5 teams' draft: Vesper, Heart of Ruin, Marcella, Ryth, ...
    if not o.no_draft:
        base = g["draft"] or DEFAULT_DRAFT
        for c in CHAMPS:
            for pos in range(4):
                d = [x for x in base if x != c]; d.insert(pos, c)
                if d != base: C.append(("draft", "draft", ",".join(map(str, d))))
    i, nsh = map(int, shard.split("/"))
    C = [c for k, c in enumerate(sorted(C, key=lambda c: zlib.crc32((c[1] + c[2]).encode()))) if k % nsh == i]
    C = [c for c in C if f"{c[0]}:{c[1]}={c[2]}" not in g["tested"]]
    SPEED = ("JOIN_MULT", "CLAIMED_MULT", "OVERSTAFF_MULT", "WAIT_CLAIMED_MULT", "STICKY_MULT", "CAMP_OVERHEAD", "GEM_W", "GOLD_W", "SQUAD_SOAK",
             "TEAM_SOAK", "ZONE_W", "BANK_AT", "BANK_MIN", "BANK_MAX", "SHOP_GOLD", "RECALL_HP", "clear_rate", "gold_only_scale", "near_k", "solo_capture", "draft")
    FIGHT = ("SPAWN_DEF", "FISH_LOWEST_HP", "FISH_SPELL_FIRST", "FISH_CHAMP_FIRST", "FISH_ENGAGE", "TOGETHER_MULT", "LANCH_ON", "LANCH_GATE", "LANCH_RECALL_HP", "LANCH_MIN", "AOE_PVP", "KITE", "CHASE", "BURST_EXIT", "lone_flee", "flee_outnumbered")
    rng.shuffle(C)
    C.sort(key=lambda c: -1 if c[0] == 'bundle' else 0 if c[1] in FIGHT else 1 if c[1] in SPEED else 2)
    return C


# ---------------------------------------------------------------- lanes
def make_runtime(i):
    d = OUT / f"lane{i}"
    if not (d / EXE_NAME).exists():
        d.mkdir(parents=True, exist_ok=True)
        for item in RTSRC.iterdir():
            if item.name in ("bots", "out", "replays") or item.suffix == ".txt":
                continue
            dst = d / item.name
            if item.is_dir(): shutil.copytree(item, dst, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".cambc"))
            else: shutil.copy2(item, dst)
        (d / "bots").mkdir(exist_ok=True)
    return d


def opp_dir(lane, name):
    return lane / "bots" / name


def ensure_opp(lane, name):
    dst = opp_dir(lane, name)
    if not (dst / "src").exists():
        safeio.copytree(ROOT / "bots" / name, dst, ignore=shutil.ignore_patterns(".cambc"))
    if not (dst / ".cambc" / "build").exists():
        subprocess.run([str(lane / EXE_NAME), "build", f"bots/{name}"], cwd=lane, capture_output=True)


def load_stats(path):
    import rt
    return rt.load_stats(path)


def run_games(lane, tag, maps, opps, deadline, progress=None):
    """Play candidate `tag` (already built in `lane`) vs every opp on every map, both sides. Returns list of result dicts."""
    res = []
    for m in maps:
        mp = lane / "maps" / f"{m}.map26a"
        if not mp.exists(): continue
        for opp in opps:
            for side in (0, 1):
                if time.time() > deadline or STOP.is_set(): return res
                a, b = (f"bots/{tag}", f"bots/{opp}") if side == 0 else (f"bots/{opp}", f"bots/{tag}")
                st = lane / f"stat_{tag}_{m}_{opp}_{side}.json"
                od = lane / f"rep_{tag}"
                shutil.rmtree(od, ignore_errors=True)
                try:
                    subprocess.run([str(lane / EXE_NAME), "run", a, b, "--map", str(mp), "-o", str(od), "--statistics", str(st), "--json", "--release"],
                                   cwd=lane, capture_output=True, timeout=900)
                except subprocess.TimeoutExpired:
                    continue
                shutil.rmtree(od, ignore_errors=True)
                if not st.exists(): continue
                try:
                    s = load_stats(st)
                except Exception:
                    st.unlink(missing_ok=True); continue
                st.unlink(missing_ok=True)
                ch = [c for c in s["champions"] if c["team"] == side]
                mine, theirs = s["teams"][side]["submittedGems"], s["teams"][1 - side]["submittedGems"]
                if progress is not None:
                    with LOCK:
                        PROG[progress] = PROG.get(progress, 0) + 1
                res.append(dict(map=m, opp=opp, side=side, round=s["round"], mine=mine, theirs=theirs, won=s.get("outcome") == ("teamA" if side == 0 else "teamB"),
                                deaths=sum(c["deaths"] for c in ch), kills=sum(c["kills"] for c in ch),
                                faults=(s.get("botFaults") or [0, 0])[side],
                                trade=sum(c.get("championDamageDone", 0) - c.get("championDamageTaken", 0) for c in ch),
                                gold=sum(c.get("earnedGold", 0) for c in ch)))
    return res


def score_of(R, need):
    if len(R) < need: return None
    win = sum(r["won"] for r in R) / len(R)
    sc = sum(r["mine"] - r["theirs"] - o.death_w * (r["deaths"] - r["kills"]) + o.speed_w * r["mine"] / max(1, r["round"])
             - o.fault_w * r.get("faults", 0) + o.trade_w * r.get("trade", 0) + o.gold_w * r.get("gold", 0)
             + (o.win_w * max(0.0, 1 - r["round"] / 3000) if r["won"] else 0) for r in R) / len(R)
    return (win, sc)


def fmt(x):
    return "n/a" if x is None else f"wins {x[0] * 100:.0f}% score {x[1]:+.0f}"


def better(a, b, margin):
    return a[0] > b[0] or (a[0] == b[0] and a[1] > b[1] + margin)


def lists(s): return [x for x in s.split(",") if x]


S0M, S0O = lists(o.s0_maps), lists(o.s0_opps)
S1M, S1O = lists(o.s1_maps), lists(o.s1_opps)
S2M, S2O = lists(o.s2_maps), lists(o.s2_opps)
NEED = {0: len(S0M) * len(S0O) * 2, 1: len(S1M) * len(S1O) * 2, 2: len(S2M) * len(S2O) * 2}
STAGE = {0: (S0M, S0O), 1: (S1M, S1O), 2: (S2M, S2O)}


class Lane:
    def __init__(self, i):
        self.i, self.dir = i, make_runtime(i)
        self.tag = f"cand{i}"

    def prepare(self):
        for opp in sorted(set(S0O + S1O + S2O + lists(o.final_opps))):
            ensure_opp(self.dir, opp)

    def build(self, st):
        td = self.dir / "bots" / self.tag
        shutil.rmtree(td, ignore_errors=True)
        safeio.copytree(BASE, td, ignore=shutil.ignore_patterns(".cambc"))
        write_headers(td, st)
        r = subprocess.run([str(self.dir / EXE_NAME), "build", f"bots/{self.tag}"], cwd=self.dir, capture_output=True, text=True, errors="replace")
        return (td / ".cambc" / "build").exists() or "built" in r.stdout

    def stage(self, k, deadline):
        maps, opps = STAGE[k]
        return score_of(run_games(self.dir, self.tag, maps, opps, deadline), NEED[k] - 1)


# ---------------------------------------------------------------- final comparison / merge helpers
def all_maps():
    return sorted(p.name[:-7] for p in (RTSRC / "maps").glob("*.map26a"))


def eval_state_on(lanes, st, maps, opps, label="eval"):
    """Distribute the games of one state over all lanes (each builds it once). Returns (score tuple, results). Prints progress every minute."""
    total = len(maps) * len(opps) * 2
    key = f"{label}-{id(maps)}-{time.time()}"
    PROG[key] = 0

    def job(args):
        lane, chunk = args
        if not lane.build(st): return []
        out = []
        for m in chunk:
            if STOP.is_set(): break
            out += run_games(lane.dir, lane.tag, [m], opps, time.time() + 4 * 3600, progress=key)
        return out
    chunks = [maps[k::len(lanes)] for k in range(len(lanes))]
    done = threading.Event()

    def reporter():
        t0 = time.time()
        while not done.wait(60):
            n = PROG.get(key, 0)
            say(f"   {label}: {n}/{total} games done ({(time.time() - t0) / 60:.0f} min)")
    rt_ = threading.Thread(target=reporter, daemon=True); rt_.start()
    ex = ThreadPoolExecutor(len(lanes))
    try:
        parts = list(ex.map(job, zip(lanes, chunks)))
    except KeyboardInterrupt:
        STOP.set()
        ex.shutdown(wait=False, cancel_futures=True)   # do not wait for the running games: Ctrl-C must stop quickly
        raise
    finally:
        done.set()
    ex.shutdown(wait=True)
    R = [r for p in parts for r in p]
    return score_of(R, int(total * 0.9)), R


def final_compare(lanes, st_new, st_old, label_new, label_old):
    maps = all_maps() if o.final_maps == "all" else lists(o.final_maps)
    opps = lists(o.final_opps)
    say(f"== final: {len(maps)} maps x {len(opps)} opponents x 2 sides, {label_new} vs {label_old}")
    sn, Rn = eval_state_on(lanes, st_new, maps, opps)
    so, Ro = eval_state_on(lanes, st_old, maps, opps)
    say(f"   {label_new}: {fmt(sn)}   {label_old}: {fmt(so)}")
    pm = {}
    for tag, R in (("new", Rn), ("old", Ro)):
        for r in R: pm.setdefault(r["map"], {}).setdefault(tag, []).append(r["won"])
    for m in sorted(pm):
        a, b = pm[m].get("new", []), pm[m].get("old", [])
        say(f"   {m:22} new {sum(a)}/{len(a)}  old {sum(b)}/{len(b)}")
    return sn, so


# ---------------------------------------------------------------- main
def main():
    if o.count:
        C = candidates(random.Random(o.seed), o.shard)
        import collections
        print('candidates', len(C), dict(collections.Counter(c[0] for c in C)), 'tune fields', len([n for n in fields if n not in SKIP]), 'policy fields', len(POLICY))
        return
    lanes = [Lane(i) for i in range(o.lanes)]
    say(f"== gtrain: base {o.base}, lanes {len(lanes)}, hours {o.hours}, shard {o.shard}, fields {len(fields)}, S0 {NEED[0]} games / S1 {NEED[1]} / S2 {NEED[2]}")
    say("preparing lanes: copying the runtime and building the sparring bots once per lane (first run only, about 3-5 minutes) ...")
    with ThreadPoolExecutor(len(lanes)) as ex: list(ex.map(lambda l: l.prepare(), lanes))
    say("lanes ready")
    start_state = json.loads(json.dumps(state))
    if o.merge_from:
        merge(lanes, start_state); return
    if o.final:
        final_compare(lanes, state, {"maps": {}}, "current", "defaults"); return
    t_end = time.time() + o.hours * 3600
    ver = [0]
    base_sc = {}
    say("measuring the baseline first: S0 + S1 + S2 = %d games; with %d lanes expect about %d minutes (progress line every minute)" % (sum(NEED.values()), len(lanes), sum(NEED.values()) * 40 // 60 // max(1, len(lanes)) + 3))

    def base_job(k):
        lane = lanes[k % len(lanes)]
        if not lane.build(state): return k, None
        return k, lane.stage(k, time.time() + 2 * 3600)
    # split S1/S2 baselines over several lanes by running stage maps in chunks
    def measure_base():
        res = {}
        cache = OUT / "baseline.json"
        sig = json.dumps([state["maps"]["general"], S0M, S0O, S1M, S1O, S2M, S2O, o.death_w, o.speed_w, o.fault_w, o.trade_w, o.gold_w, o.win_w], sort_keys=True)
        if cache.exists():
            try:
                c = json.load(open(cache))
                if c.get("sig") == sig:
                    say("baseline loaded from cache (same settings and stage sets)")
                    return {int(k): tuple(v) for k, v in c["res"].items()}
            except Exception:
                pass
        for k in (0, 1, 2):
            maps, opps = STAGE[k]
            say(f"baseline stage S{k}: {len(maps) * len(opps) * 2} games on {len(lanes)} lanes ...")
            s_, R = eval_state_on(lanes, state, maps, opps, label=f"baseline S{k}")
            res[k] = s_
            say(f"baseline S{k}: {fmt(s_)}")
            if STOP.is_set(): return res
        if all(v is not None for v in res.values()):
            json.dump({"sig": sig, "res": {str(k): list(v) for k, v in res.items()}}, open(cache, "w"))
        return res
    base_sc.update(measure_base())
    say("baseline:", {k: fmt(v) for k, v in base_sc.items()})
    if any(v is None for v in base_sc.values()):
        say("!! baseline incomplete (games failed). Check `python tools/screen.py ...` by hand."); return
    GEN()["score"], GEN()["cscore"] = list(base_sc[1]), list(base_sc[2]); save()
    rng = random.Random(o.seed)
    queue = candidates(rng, o.shard)
    if o.max_candidates: queue = queue[:o.max_candidates]
    say(f"{len(queue)} candidates queued")
    qlock = threading.Lock()
    tested = [0]; accepted = [0]

    def worker(lane):
        while time.time() < t_end and not STOP.is_set():
            with qlock:
                if not queue: return
                c = queue.pop(0)
            for attempt in range(2):
                v0 = ver[0]
                with LOCK: cur = json.loads(json.dumps(state)); b0, b1, b2 = base_sc[0], base_sc[1], base_sc[2]
                st = apply_cand(cur, c)
                if not lane.build(st):
                    say(f"[{lane.i}] build failed for {c}"); break
                key = f"{c[0]}:{c[1]}={c[2]}"
                s0 = lane.stage(0, t_end)
                if s0 is None: break
                if not (s0[0] >= b0[0] and s0[1] > b0[1] + o.s0_margin):
                    with LOCK: GEN()["tested"].append(key); tested[0] += 1
                    break
                s1 = lane.stage(1, t_end)
                if s1 is None or not better(s1, b1, o.margin):
                    with LOCK: GEN()["tested"].append(key); tested[0] += 1
                    say(f"[{lane.i}] drop {key} (S0 {fmt(s0)} S1 {fmt(s1)} vs {fmt(b1)})")
                    break
                s2 = lane.stage(2, t_end)
                if s2 is None or s2[0] < b2[0] or (s2[0] == b2[0] and s2[1] < b2[1] - 10):
                    with LOCK: GEN()["tested"].append(key); tested[0] += 1
                    say(f"[{lane.i}] reject {key} (S1 {fmt(s1)} but confirm {fmt(s2)} vs {fmt(b2)})")
                    break
                with LOCK:
                    if ver[0] != v0:   # another accept happened while we were testing: re-test this one on the new state
                        say(f"[{lane.i}] {key} passed on an old state, retesting on the new one")
                        continue
                    state.update(apply_cand(state, c)); G2 = GEN()
                    base_sc[0], base_sc[1], base_sc[2] = s0, s1, s2
                    G2["score"], G2["cscore"] = list(s1), list(s2); G2["accepted"] = G2.get("accepted", 0) + 1
                    G2["tested"].append(key); ver[0] += 1; accepted[0] += 1; tested[0] += 1
                    save()
                say(f"[{lane.i}] ACCEPT {key}: S1 {fmt(s1)} confirm {fmt(s2)}   (accepted {accepted[0]}, tested {tested[0]}, left {len(queue)})")
                break
            else:
                with LOCK: GEN()["tested"].append(key)
            if tested[0] % 10 == 0:
                with LOCK: save()
                say(f"progress: tested {tested[0]}, accepted {accepted[0]}, left {len(queue)}, baseline S1 {fmt(base_sc[1])}")

    ths = [threading.Thread(target=worker, args=(l,), daemon=True) for l in lanes]
    for t in ths: t.start()
    try:
        while any(t.is_alive() for t in ths): time.sleep(20)
    except KeyboardInterrupt:
        say("stopping ...")
    save()
    say(f"== done: tested {tested[0]}, accepted {accepted[0]}; settings in {TJ}. Next: python tools/gtrain.py {o.base} --final   then python tools/bundle.py {o.base}")


def merge(lanes, start_state):
    """Union of the accepted changes of several shard bots, applied one by one on top of this bot; each must keep S1+S2 not worse."""
    merged = json.loads(json.dumps(state))
    mg = merged["maps"]["general"]
    changes = []
    for wd in lists(o.merge_from):
        wp = pathlib.Path(wd) if pathlib.Path(wd).is_absolute() else ROOT / wd
        wj = wp / "tuning.json"
        if not wj.exists(): continue
        wg = json.load(open(wj))["maps"].get("general", {})
        for kind in ("tune", "policy"):
            for n, v in wg.get(kind, {}).items():
                if mg[kind].get(n) != v: changes.append((kind, n, v))
        if wg.get("draft") and wg["draft"] != mg.get("draft"): changes.append(("draft", "draft", ",".join(map(str, wg["draft"]))))
    groups = []
    for wd in lists(o.merge_from):
        wp = pathlib.Path(wd) if pathlib.Path(wd).is_absolute() else ROOT / wd
        if not (wp / "tuning.json").exists(): continue
        wg = json.load(open(wp / "tuning.json"))["maps"].get("general", {})
        dd = {k: {n: v for n, v in wg.get(k, {}).items() if mg[k].get(n) != v} for k in ("tune", "policy")}
        if len(dd["tune"]) + len(dd["policy"]) > 1: groups.append(("bundle", "shard_" + wp.name, json.dumps(dd, sort_keys=True)))
    changes = groups + changes
    say(f"merging {len(changes)} changes from {o.merge_from}")
    cur = merged; best = None
    for c in changes:
        trial = apply_cand(cur, c)
        s1, _ = eval_state_on(lanes, trial, S1M, S1O)
        s2, _ = eval_state_on(lanes, trial, S2M, S2O)
        if best is None:
            b1, _ = eval_state_on(lanes, cur, S1M, S1O); b2, _ = eval_state_on(lanes, cur, S2M, S2O); best = (b1, b2)
        ok = s1 is not None and s2 is not None and (s1[0] > best[0][0] or (s1[0] == best[0][0] and s1[1] >= best[0][1] - 5)) and s2[0] >= best[1][0] and s2[1] >= best[1][1] - 10
        if not ok and s1 is not None and s2 is not None and s1[0] >= best[0][0] and s2[0] >= best[1][0] and (s1[0] > best[0][0] or s2[0] > best[1][0]): ok = True   # more wins on a stage, none lost on the other
        say(f"   {c[1]}={c[2]}: S1 {fmt(s1)} S2 {fmt(s2)} vs {fmt(best[0])} / {fmt(best[1])} -> {'KEEP' if ok else 'skip'}")
        if ok: cur = trial; best = (s1, s2)
    state.clear(); state.update(cur)
    save(); say("merged state written to", TJ)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        STOP.set()
        say("Ctrl-C: stopping after the running games finish (up to a minute). Settings found so far are saved; run the same command to continue.")
        try:
            save()
        except Exception:
            pass
        time.sleep(1)
        os._exit(0)
