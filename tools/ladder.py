"""Analyse downloaded ladder logs (TRACE builds, e.g. submissions/v25t.zip).

    python tools/ladder.py [folder]      # default: project root

Unzips every <uuid>*.zip into out/ladder/<name>/ and prints per game: rounds, share of champion
turns per activity, turns lost (fuel), deaths with what preceded them, gems lost, and bot errors.
"""
import collections, glob, os, re, sys, zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = sys.argv[1] if len(sys.argv) > 1 else ROOT
OUT = os.path.join(ROOT, "out", "ladder")
G = {'walk_camp': 'walk', 'fight': 'fight', 'fight_stray': 'fight', 'capturing': 'capture', 'wait_respawn': 'wait',
     'wait_squad': 'wait', 'gather': 'wait', 'stuck_camp': 'stuck', 'no_target': 'idle', 'idle': 'idle',
     'walk_altar': 'bank', 'tribute_start': 'bank', 'tributing': 'bank', 'stuck_altar': 'stuck', 'bank_giveup': 'stuck',
     'break_lock': 'bank', 'lock_snipe': 'bank', 'recall_hp': 'recall', 'recall_shop': 'recall', 'recalling': 'recall',
     'retreat': 'recall', 'walk_home': 'recall', 'dead': 'dead', 'busy': 'busy', 'pvp': 'pvp', 'pvp_chase': 'pvp',
     'pvp_flee': 'pvp', 'protect_bag': 'pvp', 'join_fight': 'pvp', 'hunt_hit': 'pvp', 'hunt': 'pvp', 'contest': 'pvp'}
COLS = ['walk', 'fight', 'capture', 'wait', 'bank', 'recall', 'dead', 'pvp', 'stuck', 'busy', 'idle', 'other']
LINE = re.compile(r'A r(\d+) (\w+) (\w+) tgt(-?\d+) pos\((-?\d+), (-?\d+)\) hp(\d+) gems(\d+) gold(\d+)')

zips = [z for z in glob.glob(os.path.join(SRC, "*.zip")) if re.match(r'[0-9a-f]{8}-', os.path.basename(z))]
for z in zips:
    d = os.path.join(OUT, os.path.basename(z)[:-4])
    os.makedirs(d, exist_ok=True)
    with zipfile.ZipFile(z) as zf: zf.extractall(d)

print(f"{'game':14}{'rds':>5}{'lost':>6} " + ''.join(f"{c:>7}" for c in COLS) + f"{'deaths':>8}{'gemsLost':>9}{'errors':>7}")
all_pre = collections.Counter(); all_err = collections.Counter(); by_champ = collections.Counter()
for f in sorted(glob.glob(os.path.join(OUT, "*", "team-a.stdout"))):
    text = open(f, errors='ignore').read().replace('\0', '')
    hist = collections.defaultdict(dict)
    for m in LINE.finditer(text):
        hist[m.group(2)][int(m.group(1))] = (m.group(3), int(m.group(7)), int(m.group(8)))
    for e in re.findall(r'bot error: (.*)', text): all_err[e.strip()] += 1
    if not hist: print(os.path.basename(os.path.dirname(f))[:14], "no trace lines (not a TRACE build?)"); continue
    c = collections.Counter(); lost = tot = deaths = gl = 0
    for ch, d in hist.items():
        rs = sorted(d)
        for r in range(rs[0], rs[-1] + 1):
            tot += 1
            if r not in d: lost += 1; continue
            c[G.get(d[r][0], 'other')] += 1
        for a, b in zip(rs, rs[1:]):
            if d[b][0] == 'dead' and d[a][0] != 'dead':
                deaths += 1; gl += d[a][2]; by_champ[ch] += 1
                prev = [d[x][0] for x in rs if a - 3 <= x <= a]
                all_pre[' > '.join(prev)] += 1
    n = sum(c.values()) or 1
    maxr = max(max(d) for d in hist.values())
    errs = len(re.findall(r'bot error', text))
    print(f"{os.path.basename(os.path.dirname(f))[:14]:14}{maxr:>5}{100*lost/max(1,tot):>5.0f}% "
          + ''.join(f"{100*c[k]/n:>6.0f}%" for k in COLS) + f"{deaths:>8}{gl:>9}{errs:>7}")
print("\ndeaths by champion:", by_champ.most_common())
print("last actions before death:"); [print(f"  {n:3} {k}") for k, n in all_pre.most_common(8)]
print("errors:", all_err.most_common(5) or "none")
