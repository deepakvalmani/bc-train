r"""Runtime selector. Default: out/current-runtime (cambc 2.2.5, website engine 0.0.3, --release like the platform) when present.
Set CAMBC_HOME=. to use the project root (cambc 2.1.6). Candidate bots are copied into the runtime's bots/ folder automatically."""
import os, pathlib, shutil
ROOT = pathlib.Path(__file__).resolve().parent.parent
import sys as _sys
_sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import setup_runtime
setup_runtime.ensure_runtime()   # builds ./rt on a fresh clone (no engine found); no-op otherwise
_default = ROOT / "out" / "current-runtime"
_env = os.environ.get("CAMBC_HOME")
HOME = (ROOT / _env).resolve() if _env else (_default.resolve() if (_default / "cambc.exe").exists() else ROOT)
NEW = HOME != ROOT
EXE = str(HOME / ("cambc.exe" if os.name == "nt" else "cambc"))   # Linux CI: tools/ci_setup.sh copies the binary to $CAMBC_HOME/cambc
RUN_FLAGS = ["--release"] if NEW else []
def stats_args(path):
    return ["--statistics", str(path)] + (["--json"] if NEW else [])
def prep(bot):
    """bot like 'bots/v42'. Returns the path to pass to cambc (relative to HOME)."""
    if NEW:
        name = pathlib.Path(bot).name
        dst = HOME / "bots" / name
        if (ROOT / bot / "src").exists():
            (dst).mkdir(parents=True, exist_ok=True)
            if (dst / "src").exists(): shutil.rmtree(dst / "src")
            shutil.copytree(ROOT / bot / "src", dst / "src")
    return bot
def default_opps():
    return ["bots/v36", "bots/v38"] if NEW else ["bots/rep_v36", "bots/rep_v38"]

def load_stats(path):
    """Normalise statistics from either engine to the 2.1.6 shape:
    {round, outcome, teams:[{submittedGems}], champions:[{team 0/1, name, metrics...}], botFaults:[a,b]}."""
    import json
    s = json.load(open(path))
    if "match" not in s:
        return s
    num = lambda v: float(v) if isinstance(v, str) else v
    champs = []
    for c in s["champions"]:
        d = {k: num(v) for k, v in c["metrics"].items()}
        d["team"] = 0 if c["team"] == "teamA" else 1
        d["name"] = c["name"]
        champs.append(d)
    teams = [{"submittedGems": int(float(t["submittedGems"]))} for t in sorted(s["teams"], key=lambda t: t["team"])]
    f = s["diagnostics"]["botFaults"]
    return {"round": s["match"]["roundsStarted"], "outcome": s["match"]["outcome"], "teams": teams,
            "champions": champs, "botFaults": [f["teamA"], f["teamB"]], "seed": s["match"].get("seed")}
