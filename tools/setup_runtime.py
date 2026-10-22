"""Creates the game runtime the training tools need, so nobody has to do it by hand.

The tools look for an engine in this order: $CAMBC_HOME, out/current-runtime, rt/ (created here), project root.
If none has an engine (a fresh clone: out/ is not in git) this builds ./rt/ the same way tools/ci_setup.sh does on Linux:
  pip install cambc (if the cambc command is missing) -> cambc init in ./rt -> copy maps_pool/*.map26a into rt/maps ->
  copy the cambc launcher into rt/ (rt/cambc.exe on Windows, rt/cambc elsewhere)
and sets CAMBC_HOME=rt for this process and every tool it starts. Safe to call every time: a no-op when an engine exists.
Override the launcher with CAMBC_LAUNCHER=<path to a cambc executable>."""
import os, pathlib, shutil, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
EXE_NAME = "cambc.exe" if os.name == "nt" else "cambc"


def _log(msg):
    print(f"[setup_runtime] {msg}", flush=True)


def _has_engine(home):
    return (pathlib.Path(home) / EXE_NAME).exists()


def _find_launcher():
    env = os.environ.get("CAMBC_LAUNCHER")
    if env and pathlib.Path(env).exists():
        return pathlib.Path(env)
    w = shutil.which("cambc")
    if w:
        return pathlib.Path(w)
    scripts = pathlib.Path(sys.executable).parent / ("Scripts" if os.name == "nt" else "bin")
    for name in ("cambc.exe", "cambc"):
        if (scripts / name).exists():
            return scripts / name
    return None


def ensure_runtime():
    env = os.environ.get("CAMBC_HOME")
    if env:
        target = (ROOT / env).resolve()
        if _has_engine(target):
            return target
    else:
        if _has_engine(ROOT / "out" / "current-runtime"):
            return ROOT / "out" / "current-runtime"
        if _has_engine(ROOT / "rt"):
            os.environ["CAMBC_HOME"] = "rt"
            return ROOT / "rt"
        if _has_engine(ROOT):
            return ROOT
        target = ROOT / "rt"
    launcher = _find_launcher()
    if launcher is None:
        _log("the cambc command is missing: installing the competition toolkit with pip (pip install cambc)")
        r = subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--upgrade", "cambc"], capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit("[setup_runtime] pip install cambc failed:\n" + (r.stdout + r.stderr)[-800:] +
                             "\nInstall it by hand (pip install cambc inside your virtualenv) and run again.")
        launcher = _find_launcher()
    if launcher is None:
        raise SystemExit("[setup_runtime] could not find the cambc command after installing it. Activate your virtualenv "
                         "(the one where `pip install cambc` ran) or set CAMBC_LAUNCHER=<path to cambc>.")
    _log(f"creating the game runtime in {target} (one time, about a minute) using {launcher}")
    target.mkdir(parents=True, exist_ok=True)
    r = subprocess.run([str(launcher), "init", "--yes", "."], cwd=target, capture_output=True, text=True)
    if r.returncode != 0:
        _log("cambc init reported a problem (continuing, the folders are created below): " + (r.stdout + r.stderr)[-300:].replace("\n", " "))
    (target / "maps").mkdir(exist_ok=True)
    (target / "bots").mkdir(exist_ok=True)
    pool = ROOT / "maps_pool"
    if pool.exists():
        for m in pool.glob("*.map26a"):
            shutil.copy2(m, target / "maps" / m.name)
    try:   # the current published pool (the week-2 pool has 21 maps named 00*/01*); needs a logged-in CLI, harmless if it fails
        r2 = subprocess.run([str(launcher), "maps", "pull"], cwd=target, capture_output=True, text=True, timeout=180)
        _log("maps pull: " + (r2.stdout + r2.stderr).strip().replace("\n", " ")[-120:])
    except Exception as e:
        _log(f"maps pull skipped ({e}); using the maps from maps_pool/")
    dst = target / EXE_NAME
    if not dst.exists():
        shutil.copy2(launcher, dst)
        try:
            dst.chmod(0o755)
        except OSError:
            pass
    if not _has_engine(target):
        raise SystemExit(f"[setup_runtime] runtime setup failed: {dst} does not exist")
    os.environ["CAMBC_HOME"] = os.path.relpath(target, ROOT) if str(target).startswith(str(ROOT)) else str(target)
    n_maps = len(list((target / "maps").glob("*.map26a")))
    _log(f"runtime ready: {target} ({n_maps} maps). Set CAMBC_HOME={os.environ['CAMBC_HOME']} in your shell if you start tools outside this one.")
    return target


if __name__ == "__main__":
    ensure_runtime()
