"""Fetch matches summary JSON for a match list (rate-limit aware): python tools/fetch_sums.py <mine.json> <outdir> [since_iso]"""
import json,os,subprocess,sys,time,re
exe=os.path.abspath('rt_v3/cambc.exe' if os.path.exists('rt_v3/cambc.exe') else 'out/current-runtime/cambc.exe')
d=json.load(open(sys.argv[1],encoding='utf8')); od=sys.argv[2]; since=sys.argv[3] if len(sys.argv)>3 else ''
os.makedirs(od,exist_ok=True)
for m in d['matches']:
    if m['createdAt']<since: continue
    out=f"{od}/{m['matchId'][:8]}.json"
    while not os.path.exists(out):
        r=subprocess.run([exe,'matches','summary',m['matchId'],'--json','-o',out],capture_output=True,timeout=60)
        if os.path.exists(out): break
        mm=re.search(rb'after (\d+)',r.stderr+r.stdout); time.sleep(int(mm.group(1))+1 if mm else 5)
print('done')
