"""Per-map trainer: tunes EVERY value separately for each map (camp choice, fighting, banking, shop, flee/rally, champion draft order).

    python tools/pm_train.py bots/v46 --hours 6                 # all maps, round-robin, resumable
    python tools/pm_train.py bots/v46 --maps lanes,corners --hours 2 --jobs 4

Results live in <bot>/tuning.json and are written into <bot>/src/map_tuning.h + policy_tuning.h after every accepted change.
A candidate is accepted only if it beats the map's current score vs the training opponents AND does not lose on a second
(confirmation) opponent set. Log: out/pm/train.log. Stop with Ctrl-C any time; rerun the same command to resume.
"""
from concurrent.futures import ThreadPoolExecutor
import argparse, json, os, random, shutil, subprocess, sys, pathlib, time

ROOT = pathlib.Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT / "tools"))
import safeio
import rt   # honours CAMBC_HOME (isolated runtime per parallel worker)
HOME = rt.HOME
ap = argparse.ArgumentParser()
ap.add_argument("base")
ap.add_argument("--maps", default="all")
ap.add_argument("--general", action="store_true", help="ONE set of settings for all maps (the pool changes every patch): candidates are scored on --pool and confirmed on --holdout maps the training never sees; saved under the pseudo-map 'general' and compiled into the bot's Map::unknown case (use with bots/v60)")
ap.add_argument("--pool", default="00collision,00corners,00elkring,00lanes,01broken-curve,01hooks,01gold-rush", help="general mode: training maps (file names in the runtime maps/ folder)")
ap.add_argument("--holdout", default="00eight,00expanse,01boss-battle,01corridors,01elk-arena", help="general mode: held-out maps used only for confirmation")
ap.add_argument("--solo-maps", default="00collision,01broken-curve", help="general mode: maps for the solo-farming term")
ap.add_argument("--opps", default="v44,v43,v36,v38")
ap.add_argument("--confirm", default="v42,v40,rep_v36,rep_v38")
ap.add_argument("--jobs", type=int, default=3)
ap.add_argument("--hours", type=float, default=2.0)
ap.add_argument("--per-map-minutes", type=float, default=12.0)
ap.add_argument("--seed", type=int, default=1)
ap.add_argument("--batch", type=int, default=3)
ap.add_argument("--tag", default="", help="prefix of temporary bot names (default pm_<bot>_ so trainers on different bots never collide)")
ap.add_argument("--log", default="train.log")
ap.add_argument("--merge-from", default="", help="comma list of worker bot folders: merge their tuning.json into BASE and exit")
ap.add_argument("--skip-saturated", action="store_true", help="skip maps already at 100% wins on both opponent sets. Default is to KEEP training them: eight was 100% locally but 0/10 on the ladder (16 deaths a game), local saturation says nothing about real opponents")
ap.add_argument("--patience", type=int, default=45)
ap.add_argument("--margin", type=float, default=25.0)
ap.add_argument("--speed-w", type=float, default=150.0, help="gem-equivalents per (our gems / round): rewards reaching gems sooner, i.e. shorter games when we win and a faster farm when we lose")
ap.add_argument("--solo-w", type=float, default=6.0, help="gem-equivalents per round saved in a solo run (bot vs idle bot, rounds to 1000 gems; reference 600); 0 disables the solo run")
ap.add_argument("--death-w", type=float, default=60.0, help="gem-equivalents charged per net death (own deaths - kills) in the gem score; a death costs a 60-round respawn, the bag and 50 gold. Raised 20 -> 60 on 19 Oct: top teams die 0.4/game, we die 20, and local opponents never punish deaths")
ap.add_argument("--pin", default="contest:respawn_gate,contest:gate_buddies", help="map:field pairs the trainer must not change (policy fields that only a hunting opponent can value; local bots never kill, so the trainer would undo them)")
ap.add_argument("--no-ren-first", action="store_true", help="do not force-test Ren lineups first (top teams pick Ren in ~75% of games, we in 5%)")
o = ap.parse_args()
BASE = pathlib.Path(o.base) if pathlib.Path(o.base).is_absolute() else ROOT / o.base
if not o.tag:
    o.tag = f"pm_{BASE.name}_"
LOCK = ROOT / "out" / "pm" / f".{BASE.name}.lock"   # heartbeat file: one trainer per bot folder
ALL = ("ambush collision contest corners eight elkring expanse fragment interlock lanes monolith packs "
       "pilgrimage rows rushbait_v2 stampede swirl").split()
# ladder priority (19 Oct top-10 round, gem gap + deaths): worst maps first, they are visited first and get the most revisits
PRIORITY = ("contest eight swirl fragment stampede collision pilgrimage interlock corners rushbait_v2 packs elkring ambush "
            "expanse lanes rows monolith").split()
maps = ["general"] if o.general else (PRIORITY if o.maps == "all" else o.maps.split(","))

# Preflight: fail loudly instead of printing "n/a" for hours when the engine or a bot folder is missing.
def preflight():
    problems = []
    if not pathlib.Path(rt.EXE).exists():
        problems.append(f"game engine not found: {rt.EXE}\n   The out/ folder is not in git. Set up a runtime: on Linux/WSL run bash tools/ci_setup.sh and export CAMBC_HOME=rt; "
                        "on Windows copy a teammate's out/current-runtime folder (cambc.exe + maps) into this clone, or run cambc init in a folder rt "
                        "with the maps from maps_pool/, copy the cambc launcher there as cambc.exe and set CAMBC_HOME=rt (see docs/TRAINING_GUIDE.md).")
    for b in [o.base] + ["bots/" + x for x in (o.opps + "," + o.confirm).split(",") if x]:
        bp = pathlib.Path(b) if pathlib.Path(b).is_absolute() else ROOT / b
        if not (bp / "src").exists():
            problems.append(f"bot folder missing or has no src/: {bp}")
    if LOCK.exists() and time.time() - LOCK.stat().st_mtime < 2400:
        problems.append(f"another trainer seems to be running on {BASE.name} (lock file {LOCK}, updated {int(time.time() - LOCK.stat().st_mtime)} s ago). "
                        "Two trainers on one bot overwrite each other's tuning.json. Stop the other one, or delete the lock file if it crashed.")
    if problems:
        print("!! Cannot start training:\n - " + ("\n - ").join(problems), flush=True)
        sys.exit(2)

SKIP = {"TRACE", "MARK_PRIORITY", "KILL_PRIORITY", "PATH_BUILD_FUEL", "NAV_BUILD_FUEL", "FUEL_RESERVE", "FUEL_GUARD",
        "STATE_FROM_SNAPSHOT", "LOCAL_BITS", "STATIC_NAV", "NAV_BIG", "NAV_BIG_AREA", "CHOICE_CACHE", "CHOICE_TTL", "PRUNE_CAMPS"}
POLICY_FIELDS = {"clear_rate": ("float", 1.0), "gold_only_scale": ("float", 1.0), "near_k": ("int", 0),
                 "death_memory": ("bool", False), "lone_flee": ("bool", False), "lone_foes": ("int", 3),
                 "rally": ("bool", False), "respawn_gate": ("int", 0), "home_only": ("bool", False),
                 "gate_buddies": ("int", 1), "spiral_deaths": ("int", 0), "flee_outnumbered": ("bool", False),
                 "solo_capture": ("bool", False)}
DEFAULT_DRAFT = [3, 4, 10, 9, 0, 2, 7, 6, 1, 8, 5]
CHAMP = {0: "Ryth", 1: "Vesper", 2: "Vendetta", 3: "Cassi+Issac", 4: "Stellar", 5: "Prism", 6: "Marcella", 7: "Willow", 8: "Ren", 9: "Varg", 10: "Tavi"}
NAME2ID = {"ryth": 0, "vesper": 1, "vendetta": 2, "cassi": 3, "issac": 3, "stellar": 4, "prism": 5, "marcella": 6, "willow": 7, "ren": 8, "varg": 9, "tavi": 10}
PICKLOG = []   # (map, picked ids tuple, per-game champion rows, won) appended by evaluation threads, merged into tuning.json by absorb()


def champ_id(name):
    return NAME2ID.get(name.lower().split()[0], -1)


def pick_ids(rows):
    """Draft ids actually on our team in one game (Cassi and Issac are one pick)."""
    return tuple(sorted({champ_id(c["name"]) for c in rows} - {-1}))

fields = {}
for line in (BASE / "src" / "tune_fields.txt").read_text().splitlines():
    t, n, v = line.split(None, 2)
    try:
        fields[n] = (t, (v.strip() == "true") if t == "bool" else float(v.strip().rstrip("f")))
    except ValueError:
        pass

(ROOT / "out" / "pm").mkdir(parents=True, exist_ok=True)
logf = open(ROOT / "out" / "pm" / o.log, "a", encoding="utf8")


def say(*a):
    s = time.strftime("%H:%M:%S ") + " ".join(map(str, a))
    print(s, flush=True)
    logf.write(s + "\n")
    logf.flush()


TJ = BASE / "tuning.json"
state = json.load(open(TJ)) if TJ.exists() else {"maps": {}}


def ms(st, mp):
    return st["maps"].setdefault(mp, {"tune": {}, "policy": {}, "draft": None, "score": None, "cscore": None,
                                      "tested": [], "accepted": 0, "team_size": None, "champs": {}, "sets": {}})


def lit(t, v):
    if t == "bool":
        return "true" if v else "false"
    if t == "int":
        return str(int(v))
    return repr(round(float(v), 4)) + ("f" if t == "float" else "")


def parse(t, s):
    if t == "bool":
        return s == "true"
    return float(s.rstrip("f"))


def CN(mp):
    return "unknown" if mp == "general" else mp   # the general bot compiles its single settings block into Map::unknown


def write_files(botdir, st):
    cases, pcases = [], []
    for mp in ALL + ["general"]:
        m = st["maps"].get(mp)
        if not m:
            continue
        lines = [f"        t.{n} = {v};" for n, v in sorted(m["tune"].items())]
        if lines:
            cases.append(f"    case M::{CN(mp)}:\n" + "\n".join(lines) + "\n        break;")
        pl = [f"        p.{n} = {v};" for n, v in sorted(m["policy"].items())]
        if m.get("draft"):
            pl += ["        p.explicit_draft = true;", "        p.draft = {" + ",".join(map(str, m["draft"])) + "};"]
        if pl:
            pcases.append(f"    case Map::{CN(mp)}:\n" + "\n".join(pl) + "\n        break;")
    safeio.write_text(botdir / "src" / "map_tuning.h", 
        '#pragma once\n// GENERATED by tools/pm_train.py from tuning.json. Included inside namespace tune.\n'
        '#include "map_policies.h"\ninline void apply_map(map_policies::Map m, Tune& t) {\n'
        "    using M = map_policies::Map;\n    (void)t; (void)m;\n    switch (m) {\n" + "\n".join(cases)
        + "\n    default: break;\n    }\n}\n", encoding="utf8")
    safeio.write_text(botdir / "src" / "policy_tuning.h", 
        "#pragma once\n// GENERATED by tools/pm_train.py from tuning.json. Included inside namespace map_policies.\n"
        "namespace policy_tuning {\ninline void apply(Map m, Policy& p) {\n    (void)p;\n    switch (m) {\n"
        + "\n".join(pcases) + "\n    default: break;\n    }\n}\n}\n", encoding="utf8")


def absorb():
    """Merge the champion/pick-set observations gathered by the evaluation threads into tuning.json."""
    while PICKLOG:
        mp, ids, rows, won, gd = PICKLOG.pop()
        m = ms(state, mp)
        m.setdefault("champs", {}); m.setdefault("sets", {})
        if not o.general:
            m["team_size"] = len(ids)
        k = ",".join(map(str, ids))
        t = m["sets"].setdefault(k, {"games": 0, "wins": 0, "gemdiff": 0.0})
        t["games"] += 1; t["wins"] += int(won); t["gemdiff"] += gd
        for c in rows:
            cid = str(champ_id(c["name"]))
            a = m["champs"].setdefault(cid, {"games": 0, "gems": 0.0, "md": 0.0, "cd": 0.0, "deaths": 0.0, "kills": 0.0, "gold": 0.0, "bodies": 0})
            a["bodies"] += 1
            for f in ("gems", "md", "cd", "deaths", "kills", "gold"):
                a[f] += float(c.get(f, 0))
        for cid in set(ids):
            m["champs"][str(cid)]["games"] += 1


def champ_value(a):
    """Per-game value of one champion: gems it tributed + damage to camps/champions (gem-equivalents) - deaths."""
    g = max(1, a["games"])
    return (a["gems"] + a["md"] / 400 + a["cd"] / 300 + 15 * a["kills"] - o.death_w * a["deaths"]) / g


def draft_table(mp):
    m = ms(state, mp)
    size = m.get("team_size") or 0
    order = m["draft"] or DEFAULT_DRAFT
    picks = [c for c in order][:size] if size else []
    lines = [f"{mp}: team size {size or '?'}, draft {'custom' if m['draft'] else 'default'}"]
    lines.append("   picked : " + (", ".join(CHAMP[c] for c in picks) if picks else "unknown yet"))
    lines.append("   benched: " + ", ".join(CHAMP[c] for c in order[size:]) if size else "   benched: unknown yet")
    for cid, a in sorted(m.get("champs", {}).items(), key=lambda kv: -champ_value(kv[1])):
        lines.append(f"      {CHAMP[int(cid)]:12} games {a['games']:4}  value/game {champ_value(a):+7.1f}  gems/game {a['gems']/max(1,a['games']):6.1f}  deaths/game {a['deaths']/max(1,a['games']):4.2f}")
    best = sorted(m.get("sets", {}).items(), key=lambda kv: (-kv[1]["wins"] / kv[1]["games"], -kv[1]["gemdiff"] / kv[1]["games"]))[:3]
    for k, t in best:
        lines.append(f"      set {'+'.join(CHAMP[int(x)] for x in k.split(','))}: {t['wins']}/{t['games']} wins, gemdiff {t['gemdiff']/t['games']:+.0f}")
    return chr(10).join(lines)


def save():
    """tuning.json + generated headers, written atomically with retries (OneDrive locks)."""
    absorb()
    try:
        LOCK.parent.mkdir(parents=True, exist_ok=True)
        LOCK.write_text(str(os.getpid()))   # heartbeat
    except OSError:
        pass
    safeio.dump_json(TJ, state)
    write_files(BASE, state)


_seq = [0]
LAST_SCREEN = [""]   # tail of the last screen.py output, shown when evaluations fail


def play(st, mp, opps, attempts=2, solo=False, floor=None, kind="train"):
    """(win rate, score). solo=True adds o.solo_w x (600 - rounds to 1000 gems with nobody opposing)."""
    for _ in range(attempts):
        r = _play_once(st, mp, opps, kind=kind)
        if r is not None:
            if solo and o.solo_w > 0 and (floor is None or r[0] >= floor):   # skip the solo run when the fight result already cannot win
                rounds = _play_once(st, mp, "idle", rounds_only=True, kind="solo")
                if rounds is None:
                    continue
                r = (r[0], r[1] + o.solo_w * ((2500 if o.general else 600) - rounds))
            return r
    return None


def _play_once(st, mp, opps, rounds_only=False, kind="train"):
    _seq[0] += 1
    tag = f"{o.tag}{_seq[0]}"
    td = ROOT / "bots" / tag
    shutil.rmtree(td, ignore_errors=True)
    safeio.copytree(BASE, td, ignore=shutil.ignore_patterns(".cambc"))
    write_files(td, st)
    mapname = "rushbait-v2" if mp == "rushbait_v2" else mp
    if o.general:
        mapname = {"train": o.pool, "confirm": o.holdout, "solo": o.solo_maps}[kind]
    n_games = len(mapname.split(",")) * len(opps.split(",")) * 2
    od = HOME / "out" / "pm" / tag
    shutil.rmtree(od, ignore_errors=True)
    r = subprocess.run([sys.executable, "tools/screen.py", f"bots/{tag}", "--maps", mapname, "--opps", opps,
                        "--jobs", str(o.jobs), "--out", f"out/pm/{tag}"], capture_output=True, text=True, errors="replace")
    LAST_SCREEN[0] = (r.stdout + r.stderr)[-600:]
    f = od / f"{tag}.json"
    res = None
    if f.exists():
        R = [r for r in json.load(open(f)) if not r.get("error")]
        if not rounds_only:
            for r in R:
                if r.get("champs"):
                    PICKLOG.append((mp, pick_ids(r["champs"]), r["champs"], bool(r["won"]), r["mine"] - r["theirs"]))
        if rounds_only and R:
            res = sum(r["round"] if r["mine"] >= 1000 else (2000 + 1000 - r["mine"] if o.general else 1200) for r in R) / len(R)
        elif len(R) >= (n_games - 1 if n_games <= 8 else int(n_games * 0.85)):
            res = (sum(r["won"] for r in R) / len(R), sum(r["mine"] - r["theirs"] - o.death_w * (r.get("deaths", 0) - r.get("kills", 0)) + o.speed_w * r["mine"] / max(1, r.get("round", 1000)) for r in R) / len(R))
    for d in (td, HOME / "bots" / tag, od):
        shutil.rmtree(d, ignore_errors=True)
    return res


def fmt(x):
    return "n/a" if x is None else f"wins {x[0]*100:.0f}% score {x[1]:+.0f}"


def better(a, b, margin):
    return a[0] > b[0] or (a[0] == b[0] and a[1] > b[1] + margin)


def candidates(mp, rng):
    m = ms(state, mp)
    C = []
    for n, (t, d) in fields.items():
        if n in SKIP:
            continue
        cur = d if n not in m["tune"] else parse(t, m["tune"][n])
        if t == "bool":
            vals = [not cur]
        elif t == "int":
            vals = sorted({max(0, int(round(cur * 0.5))), int(round(cur * 2)) if cur else 1, int(cur) + 1})
        else:
            vals = [cur * 0.5, cur * 2] if cur else [0.1, 0.5]
        for v in vals:
            if t != "bool" and v == cur:
                continue
            if "HP" in n and t != "bool" and v > 1.0 and cur <= 1.0:
                continue
            C.append(("tune", n, lit(t, v)))
    for n, (t, d) in POLICY_FIELDS.items():
        if f"{mp}:{n}" in o.pin.split(","):
            continue
        cur = d if n not in m["policy"] else parse(t, m["policy"][n])
        if t == "bool":
            vals = [not cur]
        elif n == "near_k":
            vals = [0, 10, 20]
        elif n == "lone_foes":
            vals = [2, 4]
        elif n == "respawn_gate":
            vals = [0, 25, 50, 80]
        elif n == "gate_buddies":
            vals = [1, 2, 3]
        elif n == "spiral_deaths":
            vals = [0, 2, 3, 4]
        else:
            vals = [cur * 0.5, cur * 2] if cur else [0.5, 2.0]
        for v in vals:
            if v != cur:
                C.append(("policy", n, lit(t, v)))
    base = m["draft"] or DEFAULT_DRAFT
    size = m.get("team_size") or 0
    if size:
        # Only the SET of the first `size` picks matters (opponent picks never block ours), so candidates swap one
        # picked champion for one benched champion. Weakest picked (by measured value/game) and best benched go first.
        picked, bench = list(base[:size]), list(base[size:])
        val = lambda c: champ_value(m["champs"][str(c)]) if str(c) in m.get("champs", {}) else 0.0
        picked.sort(key=val)
        bench.sort(key=lambda c: -val(c))
        for out_c in picked:
            for in_c in bench:
                if in_c == 6:    # Marcella: 5.7 deaths/game on the ladder (worst champion), never draft her by swap
                    continue
                d = [in_c if c == out_c else c for c in base[:size]] + [out_c if c == in_c else c for c in base[size:]]
                C.append(("draft", "draft", ",".join(map(str, d))))
    else:
        for champ in (8, 7, 5, 6, 2, 1):
            d = [c for c in base if c != champ]
            d.insert(2, champ)
            C.append(("draft", "draft", ",".join(map(str, d))))
    ren_first = []
    if not o.no_ren_first:
        # top-5 ladder teams pick Ren (id 8) in ~75% of games; our trainer almost never sampled it (5-8 games per map).
        # Lineups that put Ren in place of one non-core picked champion (keep Cassi+Issac=3 and Stellar=4) are tested FIRST.
        pk = list(base[:size]) if size else list(base[:4])
        for new_c in (8, 0):   # Ren (69% of top-team lineups), Ryth (59%)
            if new_c in pk:
                continue
            for out_c in pk:
                if out_c in (3, 4):
                    continue
                d = [new_c if c == out_c else c for c in base]
                d = [c for c in d[:len(pk)]] + [c for c in base[len(pk):] if c not in d[:len(pk)]]
                if out_c not in d:
                    d.append(out_c)
                ren_first.append(("draft", "draft", ",".join(map(str, d))))
    for v in ("0.6", "1.0", "1.3"):
        C.append(("tune", "LANCH_MIN", v + "f"))
    C = [c for c in C if f"{c[0]}:{c[1]}={c[2]}" not in m["tested"]]
    ren_first = [c for c in ren_first if f"{c[0]}:{c[1]}={c[2]}" not in m["tested"]]
    C = [c for c in C if c not in ren_first]
    rng.shuffle(C)
    # new Lanchester fight/gate switches first: they are the untried decision rules
    SPEED = ("JOIN_MULT", "CLAIMED_MULT", "OVERSTAFF_MULT", "WAIT_CLAIMED_MULT", "STICKY_MULT", "CAMP_OVERHEAD", "GEM_W", "GOLD_W",
             "SQUAD_SOAK", "TEAM_SOAK", "ZONE_W", "BANK_AT", "BANK_MIN", "BANK_MAX", "SHOP_GOLD", "CHOICE_TTL",
             "DEAD_SKIP_TURNS", "CAPTURE_SKIP_TURNS", "clear_rate", "gold_only_scale", "near_k", "solo_capture", "home_only")
    FIGHT = ("LANCH_ON", "LANCH_GATE", "LANCH_RECALL_HP")
    C.sort(key=lambda c: 0 if c[1] in FIGHT else 1 if (c[1] in SPEED or c[0] == 'draft') else 2)
    return ren_first + C


def apply_cand(st, mp, c):
    st = json.loads(json.dumps(st))
    m = ms(st, mp)
    kind, n, v = c
    if kind == "draft":
        m["draft"] = [int(x) for x in v.split(",")]
    else:
        m[kind][n] = v
    return st


if o.merge_from:
    for wd in o.merge_from.split(","):
        wp = pathlib.Path(wd) if pathlib.Path(wd).is_absolute() else ROOT / wd
        wj = wp / "tuning.json"
        if not wj.exists():
            continue
        for mp, mv in json.load(open(wj))["maps"].items():
            cur = state["maps"].get(mp)
            if cur is None or len(mv["tested"]) >= len(cur["tested"]):
                state["maps"][mp] = mv
    save()
    print("merged into", TJ)
    sys.exit(0)

rng = random.Random(o.seed)
t0 = time.time()
t_end = t0 + o.hours * 3600
done_flag = {}
consec_fail = 0
map_fail = {}
preflight()
import atexit
atexit.register(lambda: LOCK.unlink(missing_ok=True))
LOCK.parent.mkdir(parents=True, exist_ok=True)
LOCK.write_text(str(os.getpid()))
say(f"== train start: bot {o.base}, maps {len(maps)}, up to {o.hours}h, patience {o.patience}, train opps {o.opps}, confirm {o.confirm}")
say("   stops when: time limit reached, OR every map has `patience` consecutive candidates without improvement, OR Ctrl-C (resumable)")
while time.time() < t_end:
    active = 0
    for mp in maps:
        if time.time() >= t_end:
            break
        m = ms(state, mp)
        m.setdefault("stalled", 0)
        wsig = [o.death_w, o.speed_w, o.solo_w]
        if m["score"] is not None and m.get("wsig") != wsig:   # old scores used other weights: re-baseline and give the map a fresh patience budget
            say(f"[{mp}] scoring weights changed ({m.get('wsig')} -> {wsig}): re-measuring the baseline, patience reset")
            m["score"] = None
            m["cscore"] = None
            m["stalled"] = 0
            m.pop("sat_logged", None)
        if m["stalled"] >= o.patience:
            continue
        if (o.skip_saturated and m["score"] and m["cscore"] and m["score"][0] >= 1.0 and m["cscore"][0] >= 1.0):
            if not m.get("sat_logged"):
                m["sat_logged"] = True
                say(f"[{mp}] SATURATED: 100% wins on both opponent sets, skipping (use a stronger opponent / self-play snapshot to continue)")
                save()
            continue
        active += 1
        if m["score"] is None:
            sc = play(state, mp, o.opps, solo=True)
            cs = play(state, mp, o.confirm, kind="confirm")
            say(f"[{mp}] baseline: train win-rate/gem-diff {fmt(sc)}  confirm {fmt(cs)}")
            if sc is None or cs is None:
                say(f"[{mp}] !! baseline produced no game results. Last screen.py output:\n{LAST_SCREEN[0]}\n   Run `python tools/screen.py {o.base} --maps {mp} --opps v38 --jobs 1` by hand to see the real error.")
                continue
            m["score"], m["cscore"] = sc, cs
            m["wsig"] = wsig
            save()
        visit_end = min(t_end, time.time() + o.per_map_minutes * 60)
        cands = candidates(mp, rng)
        total = len(cands) + len(m["tested"])
        say(f"[{mp}] visiting: {len(m['tested'])}/{total} candidates tested, {m['accepted']} accepted, current {fmt(m['score'])}, stalled {m['stalled']}/{o.patience}")
        while cands and time.time() < visit_end and time.time() < t_end and m["stalled"] < o.patience:
            batch, cands = cands[:o.batch], cands[o.batch:]
            sts = [apply_cand(state, mp, c) for c in batch]
            with ThreadPoolExecutor(len(batch)) as ex:
                scs = list(ex.map(lambda st: play(st, mp, o.opps, solo=True, floor=m["score"][0]), sts))
            fails = sum(1 for x in scs if x is None)
            if fails == len(scs) and len(scs) > 1:
                # Whole batch failed (long games vs strong opponents + parallel load, or file locks): retry it one candidate
                # at a time before counting a failure, so a heavy map does not stop the run.
                say(f"[{mp}] whole batch failed ({len(scs)} candidates in parallel): retrying one at a time")
                scs = [play(st, mp, o.opps, solo=True, floor=m["score"][0]) for st in sts]
                fails = sum(1 for x in scs if x is None)
            map_fail[mp] = map_fail.get(mp, 0) + 1 if fails == len(scs) else 0
            consec_fail = consec_fail + 1 if fails == len(scs) else 0
            if map_fail[mp] >= 3:
                say(f"[{mp}] !! evaluations keep failing on this map (no game results even one at a time): skipping it for now")
                map_fail[mp] = 0
                save()
                break
            if consec_fail >= 12:
                say('!! ERROR: evaluations keep failing on every map (no game results). Check the opponent bots build in this runtime; stopping.')
                sys.exit(2)
            winners = []
            for c, st2, sc in zip(batch, sts, scs):
                key = f"{c[0]}:{c[1]}={c[2]}"
                if sc is not None and better(sc, tuple(m["score"]), o.margin):
                    winners.append((sc, key, st2))
                elif sc is not None:
                    m["tested"].append(key)
                    m["stalled"] += 1
            winners.sort(key=lambda w: (w[0][0], w[0][1]), reverse=True)
            for sc, key, st2 in winners[:1]:   # state changes on accept: other winners are retested later
                cs = play(st2, mp, o.confirm, kind="confirm")
                if cs is not None and (cs[0] > m["cscore"][0] or (cs[0] == m["cscore"][0] and cs[1] >= m["cscore"][1] - 10)):
                    state = st2
                    m = ms(state, mp)
                    m["score"], m["cscore"] = sc, cs
                    m["accepted"] += 1
                    m["stalled"] = 0
                    say(f"[{mp}] ACCEPT {key}: train {fmt(sc)} confirm {fmt(cs)}")
                else:
                    m["tested"].append(key)
                    m["stalled"] += 1
                    say(f"[{mp}] reject {key} (train {fmt(sc)} but confirm {fmt(cs)} vs {fmt(m['cscore'])})")
            save()
            if winners:
                say(draft_table(mp))
            el = (time.time() - t0) / 60
            say(f"[{mp}] progress: {len(m['tested'])} tested, {len(cands)} left, {m['accepted']} accepted, score {fmt(m['score'])}, stalled {m['stalled']}/{o.patience}, elapsed {el:.0f} min")
    if active == 0:
        say("== converged: every map reached its patience limit")
        break
say("== champion draft per map (picked / benched, per-champion measured value)")
for mp in maps:
    say(draft_table(mp))
safeio.write_text(ROOT / "out" / "pm" / "draft_report.txt", chr(10).join(draft_table(mp) for mp in maps))
say("== table (map: accepted changes, final train score)")
for mp in maps:
    m = ms(state, mp)
    say(f"   {mp:12} accepted {m['accepted']:3}  tested {len(m['tested']):4}  score {fmt(m['score'])}")
say("== train finished; trained values saved in " + str(TJ) + " (rerun the same command to continue)")
save()
