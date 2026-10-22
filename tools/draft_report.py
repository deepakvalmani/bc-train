"""python tools/draft_report.py bots/v46 [--md docs/DRAFT_REPORT.md] : which champions each map picks / benches, with the trainer's measured per-champion value.

Reads <bot>/tuning.json (written by pm_train.py). Maps without a trained draft show the default order; the champion statistics and
team size appear after the trainer has played games on that map with this version of the trainer."""
import json, pathlib, sys
CHAMP = {0: "Ryth", 1: "Vesper", 2: "Vendetta", 3: "Cassi+Issac", 4: "Stellar", 5: "Prism", 6: "Marcella", 7: "Willow", 8: "Ren", 9: "Varg", 10: "Tavi"}
DEFAULT = [3, 4, 10, 9, 0, 2, 7, 6, 1, 8, 5]
DEATH_W = 20.0
bot = pathlib.Path(sys.argv[1])
st = json.load(open(bot / "tuning.json"))["maps"]
out = []
def value(a):
    g = max(1, a["games"])
    return (a["gems"] + a["md"] / 400 + a["cd"] / 300 + 15 * a["kills"] - DEATH_W * a["deaths"]) / g
for mp in sorted(st):
    m = st[mp]
    order = m.get("draft") or DEFAULT
    size = m.get("team_size")
    out.append(f"## {mp}  (draft {'trained' if m.get('draft') else 'default'}, team size {size or 'unknown'})")
    if size:
        out.append("- picked : " + ", ".join(CHAMP[c] for c in order[:size]))
        out.append("- benched: " + ", ".join(CHAMP[c] for c in order[size:]))
    else:
        out.append("- order  : " + ", ".join(CHAMP[c] for c in order) + "  (team size not measured yet)")
    ch = m.get("champs", {})
    for cid, a in sorted(ch.items(), key=lambda kv: -value(kv[1])):
        out.append(f"  - {CHAMP[int(cid)]:12} games {a['games']:4}  value/game {value(a):+7.1f}  gems/game {a['gems']/max(1,a['games']):6.1f}  deaths/game {a['deaths']/max(1,a['games']):4.2f}")
    for k, t in sorted(m.get("sets", {}).items(), key=lambda kv: (-kv[1]["wins"] / kv[1]["games"], -kv[1]["gemdiff"] / kv[1]["games"]))[:3]:
        out.append(f"  - set {'+'.join(CHAMP[int(x)] for x in k.split(','))}: {t['wins']}/{t['games']} wins, gemdiff {t['gemdiff']/t['games']:+.0f}")
    out.append("")
text = chr(10).join(out)
print(text)
if "--md" in sys.argv:
    pathlib.Path(sys.argv[sys.argv.index("--md") + 1]).write_text("# Draft report" + chr(10) + chr(10) + text, encoding="utf8")
