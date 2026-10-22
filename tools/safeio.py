"""Crash-proof file writes for the training tools. The repo lives in OneDrive, which (or antivirus) can briefly lock a
file and make open()/write/copy fail with OSError 22/5/13/32. Everything here writes a temp file, swaps it in with
os.replace and retries with a growing wait, so a lock never kills a multi-hour run and never leaves a half-written file."""
import json, os, pathlib, shutil, time


def _retry(fn, what, tries=30):
    for i in range(tries):
        try:
            return fn()
        except OSError as e:
            if i == tries - 1:
                raise
            print(f"!! {what}: retry {i + 1} ({e})", flush=True)
            time.sleep(min(2 + i, 15))


def write_text(path, text, encoding="utf8"):
    p = pathlib.Path(path)
    def go():
        tmp = p.with_name(p.name + ".tmp")
        with open(tmp, "w", encoding=encoding, newline="\n") as fh:
            fh.write(text)
        os.replace(tmp, p)
    _retry(go, f"write {p.name}")


def dump_json(path, obj, indent=1):
    write_text(path, json.dumps(obj, indent=indent))


def copytree(src, dst, **kw):
    _retry(lambda: shutil.copytree(src, dst, **kw), f"copy {pathlib.Path(src).name}")
