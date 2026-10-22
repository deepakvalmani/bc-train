"""Solo farming speed of policy variants on one map.

    python tools/policy_bisect.py bots/v42 rows "p=accepted();" "p=accepted();p.home_only=true;" ...
"""
import pathlib, shutil, subprocess, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from policy_screen import replace_policy

ROOT = pathlib.Path(__file__).resolve().parent.parent
src, mp = sys.argv[1], sys.argv[2]
for i, body in enumerate(sys.argv[3:]):
    dst = ROOT / "bots" / f"pb_{mp}_{i}"
    if dst.exists():
        shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(ROOT / src, dst, ignore=shutil.ignore_patterns(".cambc"))
    f = dst / "src" / "map_policies.h"
    f.write_text(replace_policy(f.read_text(), mp, body))
    out = subprocess.run([sys.executable, str(ROOT / "tools" / "solo.py"), f"bots/pb_{mp}_{i}", "--maps", mp],
                         cwd=ROOT, capture_output=True, text=True)
    print(i, body[:110], "->", out.stdout.strip().splitlines()[-1] if out.stdout.strip() else out.stderr[-200:], flush=True)
