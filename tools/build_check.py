"""python tools/build_check.py bots/v46 : regenerate tune headers, copy to runtime, build, print errors (names to exclude)."""
import subprocess, sys, pathlib, re
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import rt
bot = sys.argv[1]
r = subprocess.run([sys.executable, "tools/gen_tune.py", bot], capture_output=True, text=True, cwd=rt.ROOT); print(r.stdout.strip(), r.stderr.strip()[:300])
rt.prep(bot)
b = subprocess.run([rt.EXE, "build", bot], cwd=rt.HOME, capture_output=True, text=True)
out = (b.stdout + b.stderr)
errs = [l for l in out.splitlines() if "error" in l.lower()]
print("rc", b.returncode, "errors", len(errs))
for l in errs[:40]: print(l[:260])
