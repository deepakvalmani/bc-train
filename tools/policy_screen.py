"""Replace a map's policy body in a copy of a bot, then screen it on that map vs the reference opponents.

    python tools/policy_screen.py bots/v42 elkring "<body>" ["<body>" ...]
A body is C++ that fills `Policy p;` (e.g. "p=accepted();p.home_only=true;"); the function returns p.
"""
import pathlib, re, shutil, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def replace_policy(text, mp, body):
    one_line = re.compile(r"inline Policy " + mp + r"\(\) *\{[^\n]*\}\n")
    multi = re.compile(r"inline Policy " + mp + r"\(\) *\{.*?\n\}\n", re.S)
    m = one_line.search(text) or multi.search(text)
    assert m, "policy function not found: " + mp
    new = "inline Policy " + mp + "() { Policy p; " + body + " return p; }\n"
    return text.replace(m.group(0), new, 1)


if __name__ == "__main__":
    src, mp = sys.argv[1], sys.argv[2]
    for i, body in enumerate(sys.argv[3:]):
        dst = ROOT / "bots" / f"ps_{mp}_{i}"
        if dst.exists():
            shutil.rmtree(dst, ignore_errors=True)
        shutil.copytree(ROOT / src, dst, ignore=shutil.ignore_patterns(".cambc"))
        f = dst / "src" / "map_policies.h"
        f.write_text(replace_policy(f.read_text(), mp, body))
        r = subprocess.run([sys.executable, str(ROOT / "tools" / "screen.py"), f"bots/ps_{mp}_{i}", "--maps", mp.replace("_", "-"),
                            "--jobs", "1", "--out", f"out/screen_{mp}_{i}"], cwd=ROOT, capture_output=True, text=True)
        lines = [l for l in r.stdout.splitlines() if l.startswith(mp) or l.startswith("TOTAL")]
        print(i, body[:120], "->", " | ".join(lines), flush=True)
