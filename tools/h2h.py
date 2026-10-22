"""python tools/h2h.py bots/X [opp=v44] [jobs=3] : head-to-head on all maps, prints win rate and mean gem diff."""
import json,subprocess,sys,pathlib,shutil
R=pathlib.Path(__file__).resolve().parent.parent
bot=sys.argv[1]; opp=sys.argv[2] if len(sys.argv)>2 else "v44"; jobs=sys.argv[3] if len(sys.argv)>3 else "3"
n=pathlib.Path(bot).name
od=R/"out"/"current-runtime"/"out"/"h2h"/n
shutil.rmtree(od,ignore_errors=True)
subprocess.run([sys.executable,"tools/screen.py",bot,"--maps","all","--opps",opp,"--jobs",jobs,"--out",f"out/h2h/{n}"],cwd=R,capture_output=True)
f=od/(n+".json")
if not f.exists(): print(n,"FAILED"); sys.exit()
r=[x for x in json.load(open(f)) if not x.get("error")]
w=sum(x["won"] for x in r)
print(n,f"wins {w}/{len(r)} = {w/len(r):.3f}  gemdiff {sum(x['mine']-x['theirs'] for x in r)/len(r):.1f}", flush=True)
