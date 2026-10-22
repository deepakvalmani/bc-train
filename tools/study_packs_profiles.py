"""Qualify every non-pair packs champion profile with matched full games."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import zipfile

import train
from release_check import ReleaseCheck


PROFILES = {
    "ryth": 0,
    "vesper_vale": 1,
    "vendetta": 2,
    "stellar": 5,
    "prism": 6,
    "marcella": 7,
    "willow": 8,
    "ren": 9,
    "varg": 10,
    "tavi": 11,
}

# Draft choice IDs differ from physical champion IDs after Cassi & Issac.
DRAFT_CHOICES = {
    "ryth": 0,
    "vesper_vale": 1,
    "vendetta": 2,
    "stellar": 4,
    "prism": 5,
    "marcella": 6,
    "willow": 7,
    "ren": 8,
    "varg": 9,
    "tavi": 10,
}


def inspect(folder, report, assets):
    for row in report["rows"]:
        work = next((folder / "matches").glob(
            f'{report["source"]}_*_packs_{row["side"]}'))
        output = work / "inspection.json"
        if not output.exists():
            with zipfile.ZipFile(next(work.glob("*.repl26a"))) as archive:
                (work / "replay.raw").write_bytes(archive.read("replay.repl26a"))
            subprocess.run([
                "node", "--no-warnings",
                str(train.ROOT / "tools/inspect_packs_replay.mjs"),
                str(assets), str(work / "replay.raw"), str(output),
            ], check=True, timeout=120)
        terminal = json.loads(output.read_text())["terminal"]
        side = row["side"]
        expected = (row["rounds"], row["gems"], row["enemy_gems"])
        observed = (terminal["round"], terminal["gems"][side],
                    terminal["gems"][1 - side])
        if observed != expected:
            raise ValueError(f"Decoded replay disagrees with statistics: {observed} != {expected}")


def configure(source, champion, profile, with_tavi):
    config = source / "src/champion_maps_config.h"
    text = config.read_text()
    text = re.sub(r"CHAMPION_MAPS_EXTENDED=(true|false)",
                  f"CHAMPION_MAPS_EXTENDED={'true' if profile is not None else 'false'}", text)
    text = re.sub(r"CHAMPION_MAPS_PROFILE=-?\d+",
                  f"CHAMPION_MAPS_PROFILE={profile if profile is not None else -1}", text)
    second = 11 if with_tavi and profile != 11 else -1
    text = re.sub(r"CHAMPION_MAPS_PROFILE2=-?\d+",
                  f"CHAMPION_MAPS_PROFILE2={second}", text)
    text = re.sub(r"CHAMPION_MAPS_BANK_ROUTE=(true|false)",
                  "CHAMPION_MAPS_BANK_ROUTE=true", text)
    config.write_text(text)
    # Packs normally drafts pair + Stellar + Tavi. For an individual profile,
    # replace Stellar with that champion so the code under test really runs.
    tested = 4 if champion == "baseline" else DRAFT_CHOICES[champion]
    order = [3, tested, 10]
    order.extend(i for i in range(11) if i not in order)
    train.write_params(source, {
        "MAP_DRAFT": False,
        "DRAFT_BY_SIZE": False,
        "DRAFT_ORDER": order,
    })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--jobs", type=int, default=2, choices=[1, 2])
    parser.add_argument("--assets", type=Path)
    parser.add_argument("--profiles", nargs="+", choices=list(PROFILES),
                        default=list(PROFILES),
                        help="Profiles to qualify; defaults to every non-pair champion")
    parser.add_argument("--controls", action="store_true",
                        help="Also run an identical-draft disabled-profile control")
    parser.add_argument("--controls-only", action="store_true",
                        help="Run baseline and disabled-profile controls only")
    parser.add_argument("--with-tavi", action="store_true",
                        help="Keep Tavi's selected profile active in every case")
    args = parser.parse_args()
    root = args.out.resolve()
    root.mkdir(parents=True, exist_ok=False)

    assets = args.assets
    if assets is None:
        candidates = list((Path(os.environ["LOCALAPPDATA"]) / "cambc/assets").glob(
            "*/visualiser/assets"))
        assets = next((p for p in candidates
                       if (p / "v0_0_1-ctH8uuEb.wasm").exists()), None)
    if assets is None:
        raise ValueError("Supported local visualiser assets not found; pass --assets")

    cases = [("baseline", "baseline", 11 if args.with_tavi else None)]
    for champion in args.profiles:
        if args.controls or args.controls_only:
            cases.append((f"{champion}-control", champion, None))
        if not args.controls_only:
            cases.append((champion, champion, PROFILES[champion]))
    labels = [label for label, _, _ in cases]
    sources = {}
    for label, champion, profile in cases:
        source = root / label
        train.copy_source(train.ROOT / "bots/champion-maps", source)
        configure(source, champion, profile, args.with_tavi)
        sources[label] = str(source)
    sources["v36"] = str(train.ROOT / "bots/v36")
    manifest = dict(sources=sources, maps=["packs"])
    train.atomic_json(root / "manifest.json", manifest)

    check = ReleaseCheck(root / "results", manifest, args.jobs, keep_artifacts=True)
    summary = []
    for index, label in enumerate(labels, 1):
        print(f"[PROFILE {index}/{len(labels)}] {label}", flush=True)
        report = check.evaluate(label, ["v36"], ["packs"])
        inspect(root / "results", report, assets)
        rows = report["rows"]
        summary.append({
            "profile": label,
            "source": report["source"],
            "wins": sum(row["gems"] > row["enemy_gems"] for row in rows),
            "games": len(rows),
            "faults": sum(row.get("faults", 0) for row in rows),
            "rows": [{k: row[k] for k in ("side", "rounds", "gems", "enemy_gems")}
                     for row in rows],
        })
        train.atomic_json(root / "summary.json", {"profiles": summary})
    print(json.dumps({"profiles": summary}, indent=2))


if __name__ == "__main__":
    main()
