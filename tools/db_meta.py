"""Fetch match metadata (teams, drafts, map, side, result) for every replay in a Match Database folder.
python tools/db_meta.py <replay folder> <out.jsonl> [workers]   (resumable: skips ids already in out.jsonl)"""
import json, os, pathlib, subprocess, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
EXE = str(pathlib.Path(__file__).resolve().parent.parent / "out" / "current-runtime" / "cambc.exe")
src, out = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]); workers = int(sys.argv[3]) if len(sys.argv) > 3 else 6
ids = sorted(f.stem for f in src.iterdir() if f.suffix == ".repl26a")
done = set()
if out.exists():
    for line in open(out, encoding="utf8"):
        try: done.add(json.loads(line)["matchId"])
        except Exception: pass
todo = [i for i in ids if i not in done]
import random; random.Random(7).shuffle(todo)   # any prefix of the results is a random sample
print(len(ids), "replays;", len(done), "already fetched;", len(todo), "to do", flush=True)
lock = threading.Lock(); fh = open(out, "a", encoding="utf8"); cnt = [0]; t0 = time.time(); fails = [0]
def get(i):
    for attempt in range(8):
        r = subprocess.run([EXE, "matches", "show", i, "--json"], capture_output=True, text=True, encoding="utf-8", errors="replace")
        try:
            d = json.loads(r.stdout)["matches"][0]
            with lock:
                fh.write(json.dumps(d) + "\n"); fh.flush(); cnt[0] += 1
                if cnt[0] % 200 == 0: print(f"{cnt[0]}/{len(todo)} {time.time()-t0:.0f}s", flush=True)
            return
        except Exception:
            time.sleep(2 + attempt * 3)
    with lock: fails[0] += 1
with ThreadPoolExecutor(workers) as ex: list(ex.map(get, todo))
print("done", cnt[0], "fetched,", fails[0], "failed", flush=True)
