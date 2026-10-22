"""Table from match summaries: python tools/sumstat.py <sumdir> <mine.json>"""
import json,sys,glob,os,collections
sd,mj=sys.argv[1],sys.argv[2]
meta={m['matchId'][:8]:m for m in json.load(open(mj,encoding='utf8'))['matches']}
tot=collections.defaultdict(list)
print(f"{'opp':12}{'map':11}{'dth':>4}{'odth':>5}{'earn':>6}{'oearn':>6}{'cdmg':>6}{'ocdmg':>6}{'gems':>5}{'ogems':>6}  deathsByChamp")
for f in sorted(glob.glob(sd+'/*.json')):
    k=os.path.basename(f)[:8]; m=meta[k]; d=json.load(open(f,encoding='utf8'))
    side={t['name']:t['side'] for t in m['teams']}
    me='teamA' if side['Stubborn Shard Casters']=='a' else 'teamB'; op='teamB' if me=='teamA' else 'teamA'
    oname=[t['name'] for t in m['teams'] if 'Stubborn' not in t['name']][0].split()[0]
    def S(team,key): return sum(float(c['metrics'][key]) for c in d['champions'] if c['team']==team)
    g={t['team']:int(t['submittedGems']) for t in d['teams']}
    dc=collections.Counter()
    for c in d['champions']:
        if c['team']==me: dc[c['name']]+=int(c['metrics']['deaths'])
    row=(S(me,'deaths'),S(op,'deaths'),S(me,'earnedGold'),S(op,'earnedGold'),S(me,'monsterDamageDone')/1000,S(op,'monsterDamageDone')/1000,g[me],g[op])
    print(f"{oname:12}{m['map']:11}{row[0]:4.0f}{row[1]:5.0f}{row[2]:6.0f}{row[3]:6.0f}{row[4]:6.0f}{row[5]:6.0f}{row[6]:5}{row[7]:6}  {dict(dc.most_common(4))}")
    tot[oname].append(row)
print()
for o,r in tot.items(): print(o,len(r),'avg deaths %.1f vs %.1f, gold %.0f vs %.0f'%(sum(x[0] for x in r)/len(r),sum(x[1] for x in r)/len(r),sum(x[2] for x in r)/len(r),sum(x[3] for x in r)/len(r)))
