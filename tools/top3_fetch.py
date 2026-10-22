import json,subprocess,sys,os
TEAMS={"fish":"1890540d-1ffc-4847-adbf-d0d08772f268","procless":"8df7e1cd-0d60-413b-9331-f5427ce9ca88","c3":"bbe481a7-4575-4826-9a3e-f81c28205de8"}
N=int(sys.argv[1]) if len(sys.argv)>1 else 40
E={**os.environ,"CAMBC_HOME":"rt_v3"}
for name,T in TEAMS.items():
    out=f"out/top3/{name}"; os.makedirs(out,exist_ok=True); ms=[]; cur=None
    while len(ms)<N:
        c=["cambc","matches","list","--team",T,"--limit","50","--json"]+(["--cursor",cur] if cur else [])
        r=subprocess.run(c,capture_output=True,text=True,encoding="utf-8",env=E)
        try: d=json.loads(r.stdout)
        except Exception: print(name,"list fail",r.stdout[:200],r.stderr[:200]); break
        ms+=[m for m in d["matches"] if m["status"]=="finished"]; cur=d.get("nextCursor")
        if not cur: break
    ms=ms[:N]; json.dump(ms,open(out+"/list.json","w"))
    for m in ms:
        f=f"{out}/{m['matchId']}.repl"
        if not os.path.exists(f):
            subprocess.run(["cambc","matches","download",m["matchId"],"-o",f],capture_output=True,env=E)
    print(name,len(ms),len(os.listdir(out)),flush=True)
