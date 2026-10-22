"""python tools/check_headers.py bots/X [zip]   exit 1 if the generated headers (what the compiler and the zip use) do not
match bots/X/tuning.json. With a zip, checks the headers inside the zip instead. Used by pm_merge.py and bundle.py."""
import json, pathlib, re, sys, zipfile
ROOT = pathlib.Path(__file__).resolve().parent.parent


def from_headers(h1, h2):
    out = set()
    for blk in re.split(r"case (?:M|Map)::", h1 + h2)[1:]:
        mp = blk.split(":")[0]
        for n, v in re.findall(r"\b[tp]\.(\w+) = ([^;]+);", blk):
            out.add((mp, n, v.strip()))
    return out


def from_json(js):
    out = set()
    for mp0, m in js["maps"].items():
        mp = "unknown" if mp0 == "general" else mp0   # the general bot compiles into Map::unknown
        for n, v in m["tune"].items():
            out.add((mp, n, str(v)))
        for n, v in m["policy"].items():
            out.add((mp, n, str(v).lower() if isinstance(v, bool) else str(v)))
        if m.get("draft"):
            out.add((mp, "explicit_draft", "true"))
            out.add((mp, "draft", "{" + ",".join(map(str, m["draft"])) + "}"))
    return out


def check(bot, zip_path=None):
    """returns (ok, missing, extra)"""
    bot = pathlib.Path(bot)
    want = from_json(json.load(open(ROOT / bot / "tuning.json")))
    if zip_path:
        z = zipfile.ZipFile(zip_path)
        have = from_headers(z.read("src/map_tuning.h").decode(), z.read("src/policy_tuning.h").decode())
    else:
        s = ROOT / bot / "src"
        have = from_headers((s / "map_tuning.h").read_text(encoding="utf8"), (s / "policy_tuning.h").read_text(encoding="utf8"))
    return want == have, sorted(want - have), sorted(have - want)


if __name__ == "__main__":
    ok, miss, extra = check(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    print("headers match tuning.json" if ok else f"MISMATCH: {len(miss)} values in tuning.json not in headers (e.g. {miss[:3]}), {len(extra)} extra")
    sys.exit(0 if ok else 1)
