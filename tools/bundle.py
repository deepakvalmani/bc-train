"""python tools/bundle.py bots/X [name]   -> submissions/<name or X>.zip, built from headers that are guaranteed to match
tuning.json: regenerates them if they are stale, builds, bundles, then re-checks the headers INSIDE the zip."""
import pathlib, shutil, subprocess, sys
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import check_headers
bot = sys.argv[1]; name = sys.argv[2] if len(sys.argv) > 2 else pathlib.Path(bot).name
ok, miss, _ = check_headers.check(bot)
if not ok:
    print(f"headers were stale ({len(miss)} values missing): regenerating")
    subprocess.run([sys.executable, "tools/pm_train.py", bot, "--merge-from", "none"], cwd=ROOT, check=True)
    ok, miss, _ = check_headers.check(bot)
    if not ok: sys.exit("ERROR: headers still do not match tuning.json")
r = subprocess.run([sys.executable, "tools/build_check.py", bot], cwd=ROOT, capture_output=True, text=True)
if "errors 0" not in r.stdout: sys.exit("ERROR: build check failed\n" + r.stdout[-600:])
exe = ROOT / "out" / "current-runtime" / "cambc.exe"
subprocess.run([str(exe), "bundle", bot], cwd=ROOT, check=True)
z = ROOT / (pathlib.Path(bot).name + ".zip")
(ROOT / "submissions").mkdir(exist_ok=True)
dst = ROOT / "submissions" / (name + ".zip")
shutil.move(str(z), dst)
ok, miss, extra = check_headers.check(bot, dst)
if not ok: sys.exit(f"ERROR: zip headers do not match tuning.json ({len(miss)} missing)")
print(f"OK {dst} ({dst.stat().st_size} bytes), zip headers match tuning.json")
