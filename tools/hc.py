"""Hill climb a bot's params.h against a fixed opponent (head-to-head, all maps, both sides).
python tools/hc.py bots/v45 bots/v44 [--maps all] [--jobs 4]
State/log in out/hc/. Best bot kept in bots/hc_best."""
import json, os, re, shutil, subprocess, sys, pathlib, time, argparse
ROOT = pathlib.Path(__file__).resolve().parent.parent
os.chdir(ROOT)
ap = argparse.ArgumentParser(); ap.add_argument("base"); ap.add_argument("opp")
ap.add_argument("--maps", default="all"); ap.add_argument("--jobs", type=int, default=4); ap.add_argument("--rounds", type=int, default=2)
o = ap.parse_args()
KEYS = ["GEM_W","GOLD_W","CLAIMED_MULT","STICKY_MULT","JOIN_MULT","SQUAD_SOAK","TEAM_SOAK","RECALL_HP","BANK_AT","BANK_K",
        "BANK_MIN","BANK_MAX","SAFE_GEMS","BURST_FRAC","CASSI_RECALL_HP","CAMP_OVERHEAD","EMBLEM_COUNT","CUSTOM_EMBLEM_COUNT",
        "SHOP_GOLD","CASTER_FOCUS_SHARE","OVERSTAFF_MULT","WAIT_CLAIMED_MULT","BANK_AT_DANGER","STUN_FIRST_STR","SPAWN_HEAL_HP"]
out = ROOT / "out" / "hc"; out.mkdir(parents=True, exist_ok=True)
log = open(out / "log.txt", "a", encoding="utf8")
def say(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True); log.write(s + "\n"); log.flush()
best_dir = ROOT / "bots" / "hc_best"
if best_dir.exists(): shutil.rmtree(best_dir)
shutil.copytree(o.base, best_dir, ignore=shutil.ignore_patterns(".cambc"))
def getv(p, k):
    m = re.search(rf"\b{k}\s*=\s*([-0-9.eE]+)f?\s*;", p.read_text())
    return float(m.group(1)) if m else None
def setv(p, k, v):
    s = p.read_text()
    s, n = re.subn(rf"(\b{k}\s*=\s*)[-0-9.eE]+(f?)\s*;", lambda m: m.group(1) + (str(int(v)) if float(v).is_integer() and "." not in m.group(0) else repr(round(v, 4))) + m.group(2) + ";", s)
    p.write_text(s); return n
def evaluate(botdir, tag):
    od = ROOT / "out" / "current-runtime" / "out" / "hc" / tag
    if od.exists(): shutil.rmtree(od)
    subprocess.run([sys.executable, "tools/screen.py", "bots/" + pathlib.Path(botdir).name, "--maps", o.maps, "--opps", pathlib.Path(o.opp).name,
                    "--jobs", str(o.jobs), "--out", f"out/hc/{tag}"], capture_output=True)
    f = od / (pathlib.Path(botdir).name + ".json")
    if not f.exists(): return None
    R = [r for r in json.load(open(f)) if not r.get("error")]
    if len(R) < 30: return None
    return sum(r["won"] for r in R)/len(R), sum(r["mine"] - r["theirs"] for r in R) / len(R), len(R)
base_score = evaluate(best_dir, "base")
say("BASE", base_score)
P = best_dir / "src" / "params.h"
for rnd in range(o.rounds):
    for k in KEYS:
        cur = getv(P, k)
        if cur is None: continue
        for mult in (0.6, 1.6):
            v = cur * mult
            if float(cur).is_integer() and "." not in re.search(rf"\b{k}\s*=\s*([-0-9.eE]+)", P.read_text()).group(1): v = max(0, round(v)) if round(v) != cur else cur + (1 if mult > 1 else -1)
            if v == cur: continue
            tr = ROOT / "bots" / "hc_try"
            if tr.exists(): shutil.rmtree(tr)
            shutil.copytree(best_dir, tr, ignore=shutil.ignore_patterns(".cambc"))
            setv(tr / "src" / "params.h", k, v)
            sc = evaluate(tr, "try")
            say(f"r{rnd} {k} {cur} -> {v}: {sc}  (best {base_score})")
            if sc and (sc[0] > base_score[0] or (sc[0] == base_score[0] and sc[1] > base_score[1] + 15)):
                shutil.rmtree(best_dir); shutil.copytree(tr, best_dir, ignore=shutil.ignore_patterns(".cambc"))
                base_score = sc; say(f"  ACCEPT {k}={v}  new best {base_score}")
                break
say("DONE", base_score)



