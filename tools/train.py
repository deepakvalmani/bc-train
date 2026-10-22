"""Resumable, wall-clock limited evolutionary training. Python standard library only."""
from __future__ import annotations

import argparse
import concurrent.futures as futures
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import zipfile
import learning
import search

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "cambc.exe"
STOP = threading.Event()
OFFICIAL_MAPS = ("collision", "corners", "elkring", "expanse", "interlock", "lanes", "monolith", "packs", "rows")
COMPETITION_RULES = dict(cpp_fuel=100000, max_rounds=2000, winning_gems=1000,
                         shared_memory_bytes=8, draft_memory_bytes=1024,
                         draft_choices=11, max_draft_picks=5, item_families=7, item_stats=3)


class BudgetExpired(Exception):
    pass


class BotStdout(str):
    def __new__(cls,text,raw_bytes):
        instance=super().__new__(cls,text)
        instance.raw_bytes=raw_bytes
        return instance


def bot_stdout(work, side):
    """Read only the requested log, including CLI replay bundles, with a size cap."""
    name = "team-a.stdout" if side == 0 else "team-b.stdout"
    loose = work / name
    if loose.exists() and loose.stat().st_size <= 16_000_000:
        return BotStdout(loose.read_text(encoding="utf-8", errors="replace").replace("\x00", ""),loose.stat().st_size)
    for bundle in sorted(work.glob("*.repl26a"), key=lambda p: p.stat().st_mtime, reverse=True):
        if not zipfile.is_zipfile(bundle):
            continue
        with zipfile.ZipFile(bundle) as archive:
            if name in archive.namelist() and archive.getinfo(name).file_size <= 16_000_000:
                return BotStdout(archive.read(name).decode("utf-8", errors="replace").replace("\x00", ""),archive.getinfo(name).file_size)
    return None


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def source_hash(bot):
    h = hashlib.sha256()
    for p in sorted((bot / "src").rglob("*")):
        if p.is_file():
            h.update(p.relative_to(bot).as_posix().encode())
            h.update(p.read_bytes())
    return h.hexdigest()[:20]


def copy_source(src, dst):
    # Only source is submitted; never copy local build caches or credentials.
    shutil.copytree(src / "src", dst / "src")


def param_pattern(name):
    return rf"(\b{re.escape(name)}(?:\[\])?\s*=\s*)([^;]+)(;)"


def valid_value(name, value, spec):
    kind = spec[0]
    if kind == "bool":
        valid = type(value) is bool
    elif kind == "permutation":
        valid = isinstance(value, list) and all(type(v) is int for v in value) and sorted(value) == sorted(spec[1])
    else:
        valid = (type(value) in (int, float) and math.isfinite(value)
                 and spec[1] <= value <= spec[2] and (kind != "int" or int(value) == value))
    if not valid:
        raise ValueError(f"Invalid value for {name}: {value}; expected {spec}")
    return value


def read_params(bot, space):
    source = (bot / "src" / "params.h").read_text()
    values = {}
    for name, spec in space.items():
        kind = spec[0]
        matches = list(re.finditer(param_pattern(name), source))
        if len(matches) != 1:
            raise ValueError(f"Expected one parameter {name} in {bot}")
        literal = matches[0][2].strip()
        if kind == "bool":
            if literal not in ("true", "false"):
                raise ValueError(f"Invalid Boolean literal for {name}")
            value = literal == "true"
        elif kind == "permutation":
            if not literal.startswith("{") or not literal.endswith("}"):
                raise ValueError(f"Invalid array literal for {name}")
            value = [int(v.strip()) for v in literal[1:-1].split(",")]
        else:
            value = float(literal.rstrip("f"))
        valid_value(name, value, spec)
        values[name] = int(value) if kind == "int" else value
    return values


def validate_gene_rules(values):
    """Immutable engine/encoding limits, independent of mutable search ranges."""
    for name, value in values.items():
        if name.startswith("DRAFT_") and isinstance(value, list):
            if sorted(value) != list(range(11)):
                raise ValueError(f"{name}: expected every legal draft ID exactly once (0..10)")
        if "_ITEM_FAMILY" in name and not 0 <= value <= 6:
            raise ValueError(f"{name}: item family must be 0..6")
        if ("_ITEM_STAT" in name or name.endswith("_POWER_STAT")) and not 0 <= value <= 2:
            raise ValueError(f"{name}: item stat must be 0..2")
    limits = {"DRAFT_OPEN_COUNT": (0, 11), "DRAFT_MAP_COUNT": (0, 11),
              "DRAFT_LARGE_SIZE": (3, 5), "DRAFT_STUN_COUNT": (1, 5),
              "CUSTOM_EMBLEM_COUNT": (0, 3), "ENGAGE_TTL": (0, 249),
              "FUEL_RESERVE": (1, 100000), "NAV_BUILD_FUEL": (1, 100000),
              "PATH_BUILD_FUEL": (1, 100000), "SPAWN_HEAL_HP": (0.0, 1.0)}
    for name, (low, high) in limits.items():
        if name in values and not low <= values[name] <= high:
            raise ValueError(f"{name}: outside engine/encoding bounds {low}..{high}")
    if "BANK_MIN" in values and "BANK_MAX" in values and not 0 < values["BANK_MIN"] <= values["BANK_MAX"]:
        raise ValueError("BANK_MIN must be positive and at most BANK_MAX")


def mutate(values, space, rng, names=None, dependencies=None, feedback=None, local_scale=0.15):
    result = dict(values)
    names = names or rng.sample(sorted(space), rng.randint(1, min(3, len(space))))
    for name in names:
        spec = space[name]
        kind = spec[0]
        if kind == "bool":
            result[name] = not values[name]
            continue
        if kind == "permutation":
            order = list(values[name])
            a, b = rng.sample(range(len(order)), 2)
            if rng.random() < 0.5:
                order[a], order[b] = order[b], order[a]
            else:
                order.insert(b, order.pop(a))
            result[name] = order
            continue
        low, high = spec[1:]
        # Mostly local changes, occasionally jump to explore a distant setting.
        guided = learning.numeric_proposal(feedback or {}, name, values[name], low, high, rng,
                                           scale=min(0.08, local_scale))
        v = guided if guided is not None else (
            rng.uniform(low, high) if rng.random() < (0.05 if local_scale < 0.15 else 0.15)
            else rng.gauss(values[name], (high - low) * local_scale))
        v = max(low, min(high, v))
        result[name] = int(round(v)) if kind == "int" else round(v, 4)
        # Integer rounding/boundaries should not silently waste a scheduled trial.
        if result[name] == values[name]:
            step = 1 if kind == "int" else min(0.0001, high - low)
            result[name] = values[name] + step if values[name] + step <= high else values[name] - step
    # Activate the branch whose thresholds/order are being explored. Explicit
    # mutations take priority over dependencies, allowing switches to turn off.
    requirements = {}
    def activate(name, visited):
        if name in visited:
            return
        for parent, required in (dependencies or {}).get(name, {}).items():
            if parent in requirements and requirements[parent] != required:
                # Conflicting branches are separate experiments, not invalid C++.
                continue
            requirements[parent] = required
            if parent not in names:
                result[parent] = required
                activate(parent, visited | {name})
    for name in names:
        activate(name, set())
    if "BANK_MIN" in result and "BANK_MAX" in result and result["BANK_MIN"] > result["BANK_MAX"]:
        result["BANK_MIN"] = min(result["BANK_MAX"], space["BANK_MIN"][2])
        result["BANK_MIN"] = max(result["BANK_MIN"], space["BANK_MIN"][1])
        result["BANK_MAX"] = max(result["BANK_MIN"], result["BANK_MAX"])
    for name, value in result.items():
        valid_value(name, value, space[name])
        if space[name][0] == "float":
            result[name] = float(value)
        elif space[name][0] == "int":
            result[name] = int(value)
    return result


def write_params(bot, values):
    p = bot / "src" / "params.h"
    source = p.read_text()
    for name, value in values.items():
        literal = ("true" if value else "false") if type(value) is bool else (
            "{" + ",".join(map(str, value)) + "}" if isinstance(value, list) else str(value))
        source, n = re.subn(param_pattern(name), lambda m: m[1] + literal + m[3], source)
        if n != 1:
            raise ValueError(f"Cannot rewrite {name}")
    # Debug printing is not gameplay; the engine enforces fuel independently.
    source = re.sub(param_pattern("TRACE"), lambda m: m[1] + "false" + m[3], source)
    p.write_text(source)


def coverage(bot, config):
    """Fail closed when an exposed setting has neither a search spec nor a reason."""
    source = (bot / "src" / "params.h").read_text()
    declared = set(re.findall(r"constexpr\s+\w+\s+(\w+)(?:\[\])?\s*=", source))
    trained, fixed = set(config["parameters"]), set(config.get("fixed_parameters", {}))
    if config.get("require_full_coverage"):
        if declared != trained | fixed or trained & fixed:
            raise ValueError(f"Parameter coverage mismatch: unaccounted={sorted(declared-trained-fixed)}, "
                             f"unknown={sorted((trained|fixed)-declared)}, overlap={sorted(trained&fixed)}")
    return dict(total_declared=len(declared), trainable=len(trained),
                by_type={kind: sum(s[0] == kind for s in config["parameters"].values())
                         for kind in ("bool", "int", "float", "permutation")},
                fixed=config.get("fixed_parameters", {}))


@contextmanager
def run_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0)
        if not handle.read(1):
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            raise RuntimeError("Another trainer is using this run directory") from e
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def command(args, deadline, log):
    if STOP.is_set() or time.monotonic() >= deadline:
        raise BudgetExpired()
    flags = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    with log.open("w", encoding="utf-8") as output:
        proc = subprocess.Popen([str(x) for x in args], cwd=ROOT, stdout=output, stderr=subprocess.STDOUT, **flags)
        while proc.poll() is None:
            if STOP.is_set() or time.monotonic() >= deadline:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
                else:
                    os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
                raise BudgetExpired()
            time.sleep(0.1)
    if proc.returncode:
        raise RuntimeError(f"Command failed ({proc.returncode}); see {log}\n{log.read_text(encoding='utf-8')[-1200:]}")


def parse_stats(stats, side, rules=None):
    if rules and (stats.get("outcome") not in ("teamA", "teamB") or
                  not 1 <= int(stats["round"]) <= rules["max_rounds"]):
        raise ValueError("Result does not match competition terminal outcome/round rules")
    if stats.get("outcome") not in ("teamA", "teamB", "draw"):
        raise ValueError(f"Unknown outcome: {stats.get('outcome')}")
    teams = {int(t["team"]): t for t in stats["teams"]}
    own = int(teams[side]["submittedGems"])
    enemy = int(teams[1 - side]["submittedGems"])
    rounds = int(stats["round"])
    if rounds <= 0 or min(own, enemy) < 0:
        raise ValueError("Invalid final statistics")
    won = stats["outcome"] == ("teamA" if side == 0 else "teamB")
    points = 1.0 if won else 0.5 if stats["outcome"] == "draw" else 0.0
    champions = [c for c in stats.get("champions", []) if int(c["team"]) == side]
    row = dict(points=points, share=own / (own + enemy) if own + enemy else 0.5,
                rate=own / rounds, rounds=rounds, gems=own, enemy_gems=enemy,
                faults=int(stats["botFaults"][side]),
                enemy_faults=int(stats["botFaults"][1-side]),
                deaths=sum(c.get("deaths", 0) for c in champions))
    if champions and all('collectedGems' in c for c in champions):
        row['economy']={key:sum(c[key] for c in champions) for key in
                        ('collectedGems','submittedGems','earnedGold','spentGold','kills')}
        row['champion_economy']=[{key:c[key] for key in
            ('champion','type','collectedGems','submittedGems','earnedGold','spentGold','kills','deaths')} for c in champions]
    return row


def summarize(rows):
    if not rows:
        raise ValueError("Empty evaluation")
    return {k: sum(r[k] for r in rows) / len(rows) for k in ("points", "share", "rate", "faults", "deaths")}


def improved(candidate, baseline, margin):
    if candidate["faults"] > baseline["faults"]:
        return False
    if candidate["points"] > baseline["points"] + 1e-9:
        return True
    if abs(candidate["points"] - baseline["points"]) > 1e-9:
        return False
    if candidate["share"] >= baseline["share"] + margin:
        return True
    return (candidate["share"] >= baseline["share"] - 1e-9
            and candidate["rate"] > baseline["rate"] * 1.01)


def promotion_allowed(candidate, baseline, config, require_improvement=True):
    if len(candidate) != len(baseline):
        raise ValueError("Incomplete paired evaluation")
    if config.get("require_fault_free") and any(r["faults"] != 0 for r in candidate):
        return False
    if config.get("all_maps_required"):
        opponents = list(dict.fromkeys(r["opponent"] for r in baseline))
        require_complete_evaluation(candidate, opponents, config["validation_maps"])
        require_complete_evaluation(baseline, opponents, config["validation_maps"])
    # Layout/order of both lists is exactly the same (opponent, map, side).
    for a, b in zip(candidate, baseline):
        if (a["map"], a["opponent"], a["side"]) != (b["map"], b["opponent"], b["side"]):
            raise ValueError("Mismatched paired evaluation")
    a, b = summarize(candidate), summarize(baseline)
    win_objective = config.get("promotion_objective") == "wins"
    if require_improvement:
        if win_objective:
            if a["points"] < b["points"] + config["min_win_gain"] - 1e-9:
                return False
        elif not improved(a, b, config["gem_margin"]):
            return False
    if not require_improvement and (a["points"] < b["points"] - 1e-9 or
                                   a["share"] < b["share"] - config["gem_margin"] or
                                   a["faults"] > b["faults"]):
        return False
    for m in {r["map"] for r in candidate}:
        a = summarize([r for r in candidate if r["map"] == m])
        b = summarize([r for r in baseline if r["map"] == m])
        if config.get("strict_per_map") and any(a[k] < b[k] - 1e-9 for k in ("points", "share", "rate")):
            return False
        if win_objective and a["points"] < b["points"] - config["max_map_win_regression"] - 1e-9:
            return False
        if a["share"] < b["share"] - config["max_map_gem_regression"] or a["faults"] > b["faults"]:
            return False
    return True


def require_complete_evaluation(rows, opponents, maps):
    expected = {(op, m, side) for op in opponents for m in maps for side in (0, 1)}
    observed = [(r["opponent"], r["map"], r["side"]) for r in rows]
    if len(observed) != len(expected) or set(observed) != expected:
        raise ValueError("Incomplete evaluation: every map/opponent/team assignment must finish exactly once")


class Trainer:
    def __init__(self, folder, config, jobs, deadline):
        self.folder, self.config, self.jobs, self.deadline = folder, config, jobs, deadline
        self.fast_search = False
        self.checkpoints = folder / "checkpoints"
        self.logs = folder / "logs"
        self.cache = folder / "cache"
        for p in (self.checkpoints, self.logs, self.cache):
            p.mkdir(parents=True, exist_ok=True)
        self.built = set()
        self.rng = random.Random()
        self.compiled = {}
        self.result_cache = {}
        self.counters_lock = threading.Lock()
        self.session_counts = dict(new_games=0, cache_hits=0, builds=0, trials_completed=0,
                                   early_games_avoided=0, skipped_profiles=0)

    def count(self, name, amount=1):
        with self.counters_lock:
            self.session_counts[name] += amount

    def save(self):
        self.state["rng"] = self.rng.getstate()
        atomic_json(self.folder / "state.json", self.state)
        if self.state.get("feedback"):
            feedback = self.state["feedback"]
            atomic_json(self.folder / "learning_summary.json", dict(
                comparisons=feedback.get("observations", 0),
                map_baselines=feedback.get("map_baselines", {}),
                parameter_feedback=feedback.get("parameters", {}),
                note="Observed associations guide proposals; full all-map validation decides promotion."))
        adaptive = self.state.get("adaptive_search")
        if adaptive:
            atomic_json(self.folder / "search_progress.json", dict(
                parent=adaptive["parent"], useful_leads=adaptive["leaders"],
                queued_refinements=len(adaptive["frontier"]),
                complete_candidates=len(adaptive["results"]),
                session_counts=self.session_counts,
                note="Search leads are measured on the local suite; only ready.zip is accepted for deployment."))

    def event(self, **event):
        event["time"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        with (self.folder / "history.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")

    def snapshot(self, src, values=None):
        # A unique scratch directory means interrupted copies are never checkpoints.
        import tempfile
        temp = Path(tempfile.mkdtemp(prefix="source_", dir=self.folder))
        try:
            copy_source(src, temp)
            if values is not None:
                write_params(temp, values)
            digest = source_hash(temp)
            dest = self.checkpoints / digest
            if not dest.exists():
                os.replace(temp, dest)
            return digest
        finally:
            if temp.exists():
                shutil.rmtree(temp)

    def load(self, seed, upgrade_from=None, adopt_policy=False):
        state_path = self.folder / "state.json"
        # Pin engine, SDK and maps: never reuse fitness from a different runtime.
        runtime = hashlib.sha256(ENGINE.read_bytes())
        for p in [ROOT / "cambc.toml", *sorted((ROOT / "sdk" / "cpp").rglob("*"))]:
            if p.is_file():
                runtime.update(p.read_bytes())
        for name in dict.fromkeys(self.config["train_maps"] + self.config["validation_maps"]):
            runtime.update((ROOT / "maps" / (name + ".map26a")).read_bytes())
        signature = runtime.hexdigest()
        if state_path.exists():
            self.state = json.loads(state_path.read_text())
            if self.state["runtime"] != signature:
                raise ValueError("Config, engine, SDK or maps changed. Use a new --run directory.")
            changed_policy = self.state["config"] != self.config
            if changed_policy:
                allowed = {"promotion_objective", "min_win_gain", "strict_per_map",
                           "max_map_gem_regression", "max_map_win_regression",
                           "screen_min_win_rate", "screen_min_gem_share"}
                previous = self.state["config"]
                changed = {k for k in previous.keys() | self.config.keys() if previous.get(k) != self.config.get(k)}
                if not adopt_policy or not changed <= allowed:
                    raise ValueError("Config changed. For promotion-policy-only changes use --adopt-policy; otherwise use a new --run directory.")
            def tuples(x):
                return tuple(tuples(v) for v in x) if isinstance(x, list) else x
            self.rng.setstate(tuples(self.state["rng"]))
            for digest in set(self.state["champions"] + self.state["anchors"] + self.state.get("explorers", [])):
                if source_hash(self.checkpoints / digest) != digest:
                    raise ValueError(f"Checkpoint changed or missing: {digest}")
            if self.state.get("pending"):
                pending = self.state["pending"]
                if pending["parent"] != self.state["incumbent"] or source_hash(self.checkpoints / pending["candidate"]) != pending["candidate"]:
                    raise ValueError("Pending candidate is missing, changed, or based on a different incumbent")
            if changed_policy:
                # Same source, maps, opponents and runtime: existing match results
                # remain valid. Only the acceptance criteria are changing.
                self.state.setdefault("policy_changes", []).append(dict(
                    from_policy={k: previous.get(k) for k in sorted(allowed)},
                    to_policy={k: self.config.get(k) for k in sorted(allowed)},
                    incumbent=self.state["incumbent"], trial=self.state["trials"]))
                self.state["config"] = self.config
                history = self.folder / "history.jsonl"
                reviewed = []
                if history.exists():
                    for line in history.read_text(encoding="utf-8").splitlines():
                        record = json.loads(line)
                        if record.get("status") in ("validation_rejected", "validation_early_rejected", "screen_early_rejected"):
                            reviewed.append((1, record.get("candidate_metrics", {}).get("points", 0), record["candidate"]))
                        elif self.config.get("promotion_objective") == "wins" and record.get("status") == "screen_rejected":
                            screen = record.get("screen", {})
                            if (screen.get("faults", 1) == 0 and screen.get("points", 0) >= self.config["screen_min_win_rate"]
                                and screen.get("share", 0) >= self.config["screen_min_gem_share"]):
                                reviewed.append((0, screen["points"], record["candidate"]))
                review_queue = []
                # Fully cached small gains go first, rather than spending the
                # next hour replaying arbitrary historical failures.
                ranked = []
                opponents = self.validation_opponents(self.state["incumbent"])
                for priority, score, candidate in reviewed:
                    rows, baseline = self.cached_comparison(candidate, self.state["incumbent"], opponents) if time.monotonic() < self.deadline else ([], [])
                    if rows:
                        result = search.rank_result(rows, baseline, self.config, complete=True)
                        if not result["useful"] and not promotion_allowed(rows, baseline, self.config):
                            continue  # A complete cached failure needs no replay.
                        priority = 3 if result["useful"] else 2
                        score = result["win_gain"]
                    ranked.append((priority, score, candidate))
                for _, _, candidate in sorted(ranked, reverse=True):
                    if candidate not in review_queue and candidate != self.state["incumbent"]:
                        if source_hash(self.checkpoints / candidate) != candidate:
                            raise ValueError(f"Cannot reconsider changed or missing checkpoint: {candidate}")
                        review_queue.append(candidate)
                self.state["policy_review_queue"] = review_queue
                self.save()
                print(f"Adopted new acceptance policy; preserved completed games and queued {len(review_queue)} earlier candidates for reconsideration.", flush=True)
            return
        self.rng.seed(seed)
        start = ROOT / self.config["start"]
        read_params(start, self.config["parameters"])
        values = read_params(start, self.config["parameters"])
        imported = None
        if upgrade_from:
            prior_folder = Path(upgrade_from).resolve()
            prior = json.loads((prior_folder / "state.json").read_text())
            prior_bot = prior_folder / "checkpoints" / prior["incumbent"]
            if source_hash(prior_bot) != prior["incumbent"]:
                raise ValueError("Upgrade source checkpoint changed or missing")
            old = read_params(prior_bot, prior["config"]["parameters"])
            for name in values.keys() & old.keys():
                spec, value = self.config["parameters"][name], old[name]
                if spec[0] in ("float", "int"):
                    value = min(spec[2], max(spec[1], value))
                values[name] = valid_value(name, value, spec)
            if values.get("BANK_MIN", 0) > values.get("BANK_MAX", float("inf")):
                values["BANK_MIN"] = values["BANK_MAX"]
            imported = dict(run=str(prior_folder), checkpoint=prior["incumbent"])
        if self.config.get("competition_rules"):
            validate_gene_rules(values)
        best = self.snapshot(start, values)
        anchors = list(dict.fromkeys(self.snapshot(ROOT / p) for p in self.config["opponents"]))
        self.state = dict(version=1, config=self.config, runtime=signature, incumbent=best,
                          champions=[best], anchors=anchors, trials=0, promotions=0, sessions=0)
        if imported:
            self.state["imported_genes"] = imported
        self.save()

    def cached_comparison(self, candidate, parent, opponents):
        rows, baseline = [], []
        for opponent in opponents:
            for map_name in self.config["validation_maps"]:
                for side in (0, 1):
                    own = self.cache / f"{candidate}_{opponent}_{map_name}_{side}.json"
                    prior = self.cache / f"{parent}_{opponent}_{map_name}_{side}.json"
                    if not own.exists() or not prior.exists():
                        return [], []
                    rows.append(json.loads(own.read_text(encoding="utf-8")))
                    baseline.append(json.loads(prior.read_text(encoding="utf-8")))
        require_complete_evaluation(rows, opponents, self.config["validation_maps"])
        require_complete_evaluation(baseline, opponents, self.config["validation_maps"])
        return rows, baseline

    def search_state(self, best):
        context = search.profile_key(dict(parent=best, opponents=self.validation_opponents(best),
                                         config=self.config))
        current = self.state.get("adaptive_search")
        if current is None or current["context"] != context:
            current = dict(context=context, parent=best, leaders=[], frontier=[], offered={},
                           tried={}, results={}, proposal_tick=0, bootstrapped=False)
            self.state["adaptive_search"] = current
        return current

    def offer_refinements(self, best, candidate, result):
        adaptive = self.search_state(best)
        space = self.config["parameters"]
        base = read_params(self.checkpoints / best, space)
        donor = read_params(self.checkpoints / candidate, space)
        adaptive["tried"][search.profile_key(donor)] = True
        adaptive["results"][candidate] = result
        if not result["useful"]:
            return
        leaders = [r for r in adaptive["leaders"] if r["candidate"] != candidate]
        leaders.append(dict(candidate=candidate, **result))
        leaders.sort(key=lambda r: (r["win_gain"], r["gem_gain"], r["rate_gain"]), reverse=True)
        adaptive["leaders"] = leaders[:6]
        proposals = search.local_candidates(base, donor, space, self.config.get("dependencies"))
        donors = [read_params(self.checkpoints / r["candidate"], space) for r in adaptive["leaders"]]
        proposals += search.combine_candidates(base, donors, space)
        for values, names in proposals:
            key = search.profile_key(values)
            if key in adaptive["offered"] or key in adaptive["tried"] or values == base:
                continue
            if len(adaptive["frontier"]) >= 64:
                break
            # Validate the actual merged profile before it can enter the queue.
            if self.config.get("competition_rules"):
                validate_gene_rules(values)
            adaptive["frontier"].append(dict(patch={n: values[n] for n in names}, origin="refine:" + candidate))
            adaptive["offered"][key] = True

    def continue_refinements(self, previous, best):
        """Rebase proposals after promotion without carrying comparison scores."""
        prior = self.state.get("adaptive_search", {})
        carried = list(prior.get("frontier", [])) if prior.get("parent") == previous else []
        adaptive = self.search_state(best)
        if adaptive.get("seeded_from") == previous:
            return
        space = self.config["parameters"]
        old = read_params(self.checkpoints / previous, space)
        new = read_params(self.checkpoints / best, space)
        proposals = [values for values, _ in search.local_candidates(old, new, space,
                                                                    self.config.get("dependencies"))]
        proposals += [dict(new, **item["patch"]) for item in carried]
        added = 0
        for values in proposals:
            changed = [n for n in space if values[n] != new[n]]
            key = search.profile_key(values)
            if not changed or key in adaptive["offered"] or key in adaptive["tried"]:
                continue
            if len(adaptive["frontier"]) >= 64:
                break
            try:
                for name, value in values.items():
                    valid_value(name, value, space[name])
                if self.config.get("competition_rules"):
                    validate_gene_rules(values)
            except ValueError:
                continue  # A patch can conflict with a newly accepted setting.
            adaptive["frontier"].append(dict(patch={n: values[n] for n in changed},
                                              origin="continue:" + best))
            adaptive["offered"][key] = True
            added += 1
        adaptive["seeded_from"] = previous
        if added:
            print(f"Queued {added} refinements around the promoted bot; each needs a new complete comparison.", flush=True)

    def prepare_search(self, best):
        if not self.fast_search:
            return
        champions = self.state["champions"]
        if len(champions) > 1 and champions[-1] == best:
            # Also recover the winning coordinate when resuming a run promoted
            # by an older trainer that discarded its pending refinements.
            self.continue_refinements(champions[-2], best)
        adaptive = self.search_state(best)
        if adaptive["bootstrapped"]:
            return
        scores = self.state.get("feedback", {}).get("candidate_scores", {})
        # Only complete schedules establish reusable leaders. Partial positive
        # feedback may select settings, but can never establish a better parent.
        candidates = [c for c, r in scores.items() if r.get("parent") == best]
        for candidate in candidates:
            if STOP.is_set() or time.monotonic() >= self.deadline:
                raise BudgetExpired()
            rows, baseline = self.cached_comparison(candidate, best, self.validation_opponents(best))
            if rows:
                if source_hash(self.checkpoints / candidate) != candidate:
                    raise ValueError(f"Changed cached search candidate: {candidate}")
                result = search.rank_result(rows, baseline, self.config, complete=True)
                self.offer_refinements(best, candidate, result)
        adaptive["bootstrapped"] = True
        self.save()
        if adaptive["leaders"]:
            print(f"Recovered {len(adaptive['leaders'])} complete useful search leads; "
                  f"queued {len(adaptive['frontier'])} local refinements.", flush=True)

    def propose(self, best):
        space = self.config["parameters"]
        adaptive = self.search_state(best) if self.fast_search else None
        if adaptive is not None:
            tick = adaptive.get("proposal_tick", 0)
            adaptive["proposal_tick"] = tick + 1
            coverage_turn = tick % 3 == 2
            if not coverage_turn:
                while adaptive["frontier"]:
                    item = adaptive["frontier"].pop(0)
                    base = read_params(self.checkpoints / best, space)
                    trial = dict(base, **item["patch"])
                    key = search.profile_key(trial)
                    if key in adaptive["tried"]:
                        continue
                    for name, value in trial.items():
                        valid_value(name, value, space[name])
                    if self.config.get("competition_rules"):
                        validate_gene_rules(trial)
                    return trial, list(item["patch"]), item["origin"]
        else:
            coverage_turn = True
        queue = self.state.setdefault("mutation_queue", [])
        if not queue:
            queue.extend(sorted(space))
            self.rng.shuffle(queue)
        memory = self.state.get("feedback", {}) if self.config.get("promotion_objective") == "wins" else {}
        target = None
        if self.fast_search and self.rng.random() < 0.7:
            per_map = adaptive.get("baseline_per_map") or self.state.get("incumbent_validation", {}).get("per_map", {})
            if per_map:
                maps = sorted(per_map)
                target = self.rng.choices(maps, weights=[max(0.05, 1-per_map[m]["points"]) ** 2 for m in maps], k=1)[0]
        available = queue if coverage_turn else list(space)
        if self.fast_search and not coverage_turn and adaptive["leaders"] and self.rng.random() < 0.7:
            base = read_params(self.checkpoints / best, space)
            promising = set()
            for leader in adaptive["leaders"][:3]:
                genes = read_params(self.checkpoints / leader["candidate"], space)
                promising.update(n for n in space if genes[n] != base[n])
            if promising:
                available = sorted(promising)
        if memory.get("observations"):
            primary = self.rng.choices(available, weights=[learning.parameter_weight(memory, n, target) for n in available], k=1)[0]
            if coverage_turn:
                queue.remove(primary)
        else:
            primary = queue.pop() if coverage_turn else self.rng.choice(available)
        names = [primary]
        groups = [g for g in self.config.get("groups", {}).values() if primary in g]
        primary_feedback = memory.get("parameters", {}).get(primary, {})
        focused = primary_feedback.get("observations", 0) >= 2 and primary_feedback.get("effect", 0) < -0.01
        if self.fast_search:
            # Most proposals isolate one setting plus required branch switches.
            # Related combinations remain available for interaction discovery.
            if groups and self.rng.random() < 0.2:
                others = [n for n in self.rng.choice(groups) if n != primary]
                names += self.rng.sample(others, min(len(others), self.rng.randint(1, 2)))
        elif focused:
            pass  # Isolate a poorly understood setting instead of stacking more changes.
        elif groups and self.rng.random() < 0.4:
            others = [n for n in self.rng.choice(groups) if n != primary]
            names += self.rng.sample(others, min(len(others), self.rng.randint(1, 4)))
        else:
            others = [n for n in space if n != primary]
            names += self.rng.sample(others, min(len(others), self.rng.randint(0, 2)))
        gene_parent = best
        if adaptive is not None and adaptive["leaders"] and not coverage_turn:
            gene_parent = adaptive["leaders"][0]["candidate"]
        elif not self.fast_search and self.state.get("explorers") and self.rng.random() < self.config.get("exploration_probability", 0):
            parents = self.state["explorers"]
            gene_parent = self.rng.choices(parents, weights=learning.parent_weights(memory, parents, best), k=1)[0]
        values = read_params(self.checkpoints / gene_parent, space)
        trial = mutate(values, space, self.rng, names, self.config.get("dependencies"), memory,
                       local_scale=0.035 if self.fast_search and not coverage_turn else 0.15)
        if self.config.get("competition_rules"):
            validate_gene_rules(trial)
        return trial, names, gene_parent

    def learn_from_results(self, parent, candidate, rows, baseline=None, stage="screen", planned_games=None):
        if self.config.get("promotion_objective") != "wins":
            return
        if baseline is None:
            # Both contestants' scores come from the SAME completed head-to-head
            # games. This comparison requires no additional matches.
            baseline = [dict(r, points=1-r["points"], share=1-r["share"],
                             rate=r.get("enemy_gems", 0) / max(1, r["rounds"]), faults=0) for r in rows]
        old = read_params(self.checkpoints / parent, self.config["parameters"])
        new = read_params(self.checkpoints / candidate, self.config["parameters"])
        report = learning.observe(self.state.setdefault("feedback", {}), parent, candidate,
                                  old, new, rows, baseline, stage,
                                  coverage=len(rows) / planned_games if planned_games else 1.0)
        if report:
            with (self.folder / "learning_history.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(report) + "\n")
            worst = report["worst_map"]
            print(f"  Feedback: signal {report['signal']:+.3f}; weakest change on {worst} "
                  f"(win delta {report['maps'][worst]['win_delta']:+.1%})", flush=True)

    def bootstrap_feedback(self):
        if self.config.get("promotion_objective") != "wins":
            return
        memory = self.state.setdefault("feedback", {})
        if memory.get("history_bootstrapped"):
            return
        history = self.folder / "history.jsonl"
        lines = history.read_text(encoding="utf-8").splitlines() if history.exists() else []
        parent = memory.get("bootstrap_parent", self.state["champions"][0])
        for index in range(memory.get("bootstrap_cursor", 0), len(lines)):
            if STOP.is_set() or time.monotonic() >= self.deadline:
                raise BudgetExpired()
            try:
                record = json.loads(lines[index])
            except json.JSONDecodeError:
                return  # An interrupted partial log line is not match evidence.
            candidate = record.get("candidate", "")
            status = record.get("status")
            if re.fullmatch(r"[0-9a-f]{20}", candidate) and status in ("screen_rejected", "validation_rejected", "promoted"):
                if source_hash(self.checkpoints / candidate) != candidate:
                    raise ValueError(f"Feedback source changed or missing: {candidate}")
                rows, base = [], []
                if status == "screen_rejected":
                    for m in self.config["train_maps"]:
                        for side in (0, 1):
                            cached = self.cache / f"{candidate}_{parent}_{m}_{side}.json"
                            if cached.exists():
                                rows.append(json.loads(cached.read_text(encoding="utf-8")))
                    if len(rows) == 2 * len(self.config["train_maps"]):
                        self.learn_from_results(parent, candidate, rows)
                else:
                    # Reconstruct only complete, exactly matched cached schedules.
                    matched = {}
                    for path in self.cache.glob(candidate + "_*.json"):
                        row = json.loads(path.read_text(encoding="utf-8"))
                        counterpart = self.cache / f"{parent}_{row['opponent']}_{row['map']}_{row['side']}.json"
                        if counterpart.exists():
                            matched[(row["opponent"], row["map"], row["side"])] = (row, json.loads(counterpart.read_text(encoding="utf-8")))
                    for opponent in sorted({k[0] for k in matched}):
                        keys = [(opponent, m, side) for m in self.config["validation_maps"] for side in (0, 1)]
                        if all(k in matched for k in keys):
                            rows.extend(matched[k][0] for k in keys)
                            base.extend(matched[k][1] for k in keys)
                    if rows:
                        self.learn_from_results(parent, candidate, rows, base, "validation")
                if status == "promoted":
                    parent = candidate
            memory["bootstrap_cursor"] = index + 1
            memory["bootstrap_parent"] = parent
        memory["history_bootstrapped"] = True
        self.save()

    def remember_explorer(self, candidate):
        size = self.config.get("exploration_archive", 0)
        if size:
            archive = self.state.setdefault("explorers", [])
            if candidate in archive:
                archive.remove(candidate)
            archive.append(candidate)
            self.state["explorers"] = archive[-size:]

    def training_maps(self, changed):
        if self.config.get("all_maps_required"):
            maps = list(self.config["train_maps"])
            if self.fast_search:
                per_map = self.search_state(self.state["incumbent"]).get("baseline_per_map") or self.state.get("incumbent_validation", {}).get("per_map", {})
                required = {m for n in changed for m in self.config.get("screen_required_maps", {}).get(n, [])}
                maps.sort(key=lambda m: (m not in required, per_map.get(m, {}).get("points", 0.5)))
            return maps
        required = list(dict.fromkeys(m for n in changed
            for m in self.config.get("screen_required_maps", {}).get(n, [])))
        others = [m for m in self.config["train_maps"] if m not in required]
        count = max(self.config["screen_maps_per_trial"], len(required))
        return required + self.rng.sample(others, count - len(required))

    def validation_opponents(self, best):
        recent = self.state["champions"][-self.config["recent_opponents"]:] if self.config["recent_opponents"] else []
        pool = [op for op in dict.fromkeys([*self.state["anchors"], *recent]) if op != best]
        others = pool if self.config.get("validation_all_opponents") else self.rng.sample(
            pool, min(len(pool), self.config["validation_opponents"] - 1))
        return [best, *others]

    def build(self, digest):
        if digest not in self.built:
            command([ENGINE, "build", self.checkpoints / digest], self.deadline, self.logs / (digest + "_build.log"))
            self.built.add(digest)
            self.count("builds")
            artifacts = [self.checkpoints / digest / ".cambc" / "build" / name
                         for name in ("bot.wasm", "bot-injected.wasm")]
            if all(path.exists() for path in artifacts):
                fingerprint = hashlib.sha256()
                for path in artifacts:
                    fingerprint.update(path.name.encode())
                    fingerprint.update(path.read_bytes())
                self.compiled[digest] = fingerprint.hexdigest()

    def publish(self, digest):
        self.build(digest)
        # Finish a versioned artifact first; state.json is the atomic promotion commit.
        bundle = self.checkpoints / digest / "submission.zip"
        if not bundle.exists():
            temp = bundle.with_name("submission.tmp.zip")
            command([ENGINE, "bundle", self.checkpoints / digest, "--output", temp],
                    self.deadline, self.logs / (digest + "_bundle.log"))
            with zipfile.ZipFile(temp) as archive:
                if archive.testzip() or not archive.namelist():
                    raise ValueError("Invalid submission archive")
            os.replace(temp, bundle)

    def ready(self):
        digest = self.state["incumbent"]
        bundle = self.checkpoints / digest / "submission.zip"
        if bundle.exists():
            tmp = self.folder / "ready.tmp.zip"
            shutil.copyfile(bundle, tmp)
            os.replace(tmp, self.folder / "ready.zip")
            atomic_json(self.folder / "ready.json", dict(checkpoint=digest, source=str(bundle.parent),
                        trials=self.state["trials"], promotions=self.state["promotions"],
                        validation_status=("passed_all_maps" if self.config.get("all_maps_required") else "passed_configured_validation")
                            if self.state.get("incumbent_validation") else "baseline_not_validated_this_run",
                        validation=self.state.get("incumbent_validation"),
                        parameters=read_params(bundle.parent, self.config["parameters"])))

    def game(self, bot, opponent, map_name, side):
        key = f"{bot}_{opponent}_{map_name}_{side}"
        if key in self.result_cache:
            self.count("cache_hits")
            return self.result_cache[key]
        cached = self.cache / (key + ".json")
        if cached.exists():
            self.count("cache_hits")
            row = json.loads(cached.read_text())
            self.result_cache[key] = row
            return row
        work = self.folder / "matches" / key
        work.mkdir(parents=True, exist_ok=True)
        stats_path = work / "statistics.json"
        a, b = self.checkpoints / bot, self.checkpoints / opponent
        if side == 1:
            a, b = b, a
        for attempt in range(3):
            stats_path.unlink(missing_ok=True)
            log = self.logs / (key + ".log")
            try:
                args = [ENGINE, "run", a, b, "--map", ROOT / "maps" / (map_name + ".map26a"),
                        "-o", work, "--statistics", stats_path]
                if self.config.get("competition_rules"):
                    args += ["--fuel", self.config["competition_rules"]["cpp_fuel"]]
                command(args, self.deadline, log)
                break
            except RuntimeError:
                if attempt == 2 or "Access is denied" not in log.read_text(encoding="utf-8"):
                    raise
        row = parse_stats(json.loads(stats_path.read_text()), side, self.config.get("competition_rules"))
        stdout = bot_stdout(work, side)
        # Bot main catches API exceptions, so these need not appear in botFaults.
        if stdout is not None:
            row["faults"] += stdout.count("bot error:")
        self.consume_game_artifacts(bot, opponent, map_name, side, row, work)
        if row.get("faults") or row.get("enemy_faults"):
            for team_side in (0, 1):
                diagnostic = bot_stdout(work, team_side)
                if diagnostic is not None:
                    (self.logs / f"{key}_side{team_side}.stdout").write_text(diagnostic, encoding="utf-8")
        row.update(map=map_name, opponent=opponent, side=side)
        atomic_json(cached, row)
        self.result_cache[key] = row
        self.count("new_games")
        # Keep statistics and command logs, not multi-megabyte replay archives.
        for p in work.iterdir():
            if p.is_file() and p.name != "statistics.json":
                p.unlink()
        return row

    def consume_game_artifacts(self, bot, opponent, map_name, side, row, work):
        """Optional offline diagnostics hook, before replay/stdout cleanup."""
        pass

    def evaluate(self, bot, opponents, maps):
        if len(set(maps)) != len(maps) or len(set(opponents)) != len(opponents):
            raise ValueError("Duplicate maps or opponents in evaluation schedule")
        for digest in dict.fromkeys([bot, *opponents]):
            self.build(digest)
        cases = [(bot, op, m, side) for op in opponents for m in maps for side in (0, 1)]
        with futures.ThreadPoolExecutor(max_workers=self.jobs) as pool:
            pending = {pool.submit(self.game, *case): i for i, case in enumerate(cases)}
            try:
                rows = [None] * len(cases)
                started = last = time.monotonic()
                print(f"  Evaluating {bot}: {len(cases)} games, {len(maps)} maps, both sides", flush=True)
                for done, future in enumerate(futures.as_completed(pending), 1):
                    rows[pending[future]] = future.result()
                    now = time.monotonic()
                    if done == len(cases) or now - last >= 10:
                        row = rows[pending[future]]
                        print(f"    {done}/{len(cases)} complete ({now-started:.0f}s); {row['map']} side {row['side']}", flush=True)
                        last = now
                return rows
            except BaseException as error:
                if not isinstance(error, BudgetExpired):
                    STOP.set()
                for future in pending:
                    future.cancel()
                raise

    def fast_screen(self, candidate, best, maps):
        """Reject only when even perfect remaining games cannot pass screening."""
        rows, total = [], 2 * len(maps)
        batch_size = max(1, self.jobs // 2)
        for index in range(0, len(maps), batch_size):
            rows.extend(self.evaluate(candidate, [best], maps[index:index + batch_size]))
            remaining = total - len(rows)
            if remaining and any(r["faults"] for r in rows):
                return rows, "candidate fault"
            for metric, threshold in (("points", self.config["screen_min_win_rate"]),
                                      ("share", self.config["screen_min_gem_share"])):
                if remaining and (sum(r[metric] for r in rows) + remaining) / total < threshold - 1e-9:
                    return rows, f"cannot reach screening {metric} threshold"
        return rows, None

    def fast_validation(self, candidate, opponents, maps, baseline):
        """Partial results can reject; only the original complete gate can promote."""
        rows = []
        lookup = {(r["opponent"], r["map"], r["side"]): r for r in baseline}
        total = len(baseline)
        for map_name in maps:
            part = self.evaluate(candidate, opponents, [map_name])
            rows.extend(part)
            before = [lookup[(r["opponent"], r["map"], r["side"])] for r in part]
            a, b = summarize(part), summarize(before)
            reason = None
            if self.config.get("require_fault_free") and any(r["faults"] for r in part):
                reason = "candidate fault"
            elif a["points"] < b["points"] - self.config["max_map_win_regression"] - 1e-9:
                reason = f"{map_name} win regression exceeds limit"
            elif a["share"] < b["share"] - self.config["max_map_gem_regression"] or a["faults"] > b["faults"]:
                reason = f"{map_name} gem-share or fault regression exceeds limit"
            elif self.config.get("strict_per_map") and any(a[k] < b[k] - 1e-9 for k in ("points", "share", "rate")):
                reason = f"{map_name} strict regression limit"
            elif ((sum(r["points"] for r in rows) + total - len(rows)) / total
                  < summarize(baseline)["points"] + self.config["min_win_gain"] - 1e-9):
                paired_so_far = [lookup[(r["opponent"], r["map"], r["side"])] for r in rows]
                partial_gain = summarize(rows)["points"] - summarize(paired_so_far)["points"]
                partial_gems = summarize(rows)["share"] - summarize(paired_so_far)["share"]
                # Finish a measured near miss so it can become a search parent.
                # It still cannot deploy unless the full promotion gate passes.
                if not (partial_gain > 1e-9 or (abs(partial_gain) <= 1e-9 and partial_gems > 1e-9)):
                    reason = "cannot reach required overall win gain"
            if reason and len(rows) < total:
                paired = [lookup[(r["opponent"], r["map"], r["side"])] for r in rows]
                return rows, paired, reason
        # Restore the baseline schedule's order for the unchanged promotion gate.
        completed = {(r["opponent"], r["map"], r["side"]): r for r in rows}
        return [completed[(r["opponent"], r["map"], r["side"])] for r in baseline], baseline, None

    def train(self):
        self.bootstrap_feedback()
        self.publish(self.state["incumbent"])
        self.ready()
        print("Deployable baseline saved. Searching for improvements...", flush=True)
        while not STOP.is_set() and time.monotonic() < self.deadline:
            best = self.state["incumbent"]
            self.prepare_search(best)
            pending = self.state.get("pending")
            if pending is None:
                values = read_params(self.checkpoints / best, self.config["parameters"])
                review = self.state.get("policy_review_queue", [])
                if review:
                    candidate = review.pop(0)
                    if source_hash(self.checkpoints / candidate) != candidate:
                        raise ValueError(f"Changed or missing review candidate: {candidate}")
                    trial_values = read_params(self.checkpoints / candidate, self.config["parameters"])
                    scheduled, gene_parent = [], "policy_review"
                else:
                    trial_values, scheduled, gene_parent = self.propose(best)
                if trial_values == values:
                    continue
                cand = self.snapshot(self.checkpoints / best, trial_values)
                if gene_parent != "policy_review" and self.state.get("feedback", {}).get("completed_profiles", {}).get(best + ":" + cand):
                    self.count("skipped_profiles")
                    continue  # Do not spend another trial rediscovering the same mistake.
                if self.fast_search:
                    adaptive = self.search_state(best)
                    key = search.profile_key(trial_values)
                    if gene_parent != "policy_review" and key in adaptive["tried"]:
                        self.count("skipped_profiles")
                        continue
                    adaptive["tried"][key] = True
                self.state["trials"] += 1
                changed = [n for n in trial_values if trial_values[n] != values[n]]
                maps = self.training_maps(changed)
                pending = dict(candidate=cand, parent=best, maps=maps, opponents=self.validation_opponents(best),
                               scheduled=scheduled, gene_parent=gene_parent,
                               changed=changed)
                self.state["pending"] = pending
                # Resume the SAME candidate, schedule and cached games next session.
                self.save()
            cand, maps = pending["candidate"], pending["maps"]
            required = self.config.get("required_maps", OFFICIAL_MAPS)
            if self.config.get("all_maps_required") and (len(maps) != len(required) or set(maps) != set(required)):
                raise ValueError("Pending trial does not include every official training map")
            number = self.state["trials"]
            print(f"Trial {number}: {cand}, screening {', '.join(maps)}; "
                  f"changed {', '.join(pending.get('changed', []))}", flush=True)
            try:
                if self.fast_search:
                    self.build(best)
                    self.build(cand)
                    if cand in self.compiled and self.compiled.get(best) == self.compiled[cand]:
                        self.count("skipped_profiles")
                        self.count("trials_completed")
                        self.event(trial=number, candidate=cand, status="identical_executable", parent=best,
                                   changed=pending.get("changed", []))
                        self.state.pop("pending", None)
                        self.save()
                        print("  Skipped: compiled executable is identical to incumbent; no matches needed.", flush=True)
                        continue
                early_reason = None
                if self.fast_search:
                    screen, early_reason = self.fast_screen(cand, best, maps)
                else:
                    screen = self.evaluate(cand, [best], maps)
                if early_reason:
                    self.learn_from_results(best, cand, screen, stage="screen_partial", planned_games=2*len(maps))
                    self.count("early_games_avoided", 2*len(maps)-len(screen))
                    self.count("trials_completed")
                    self.event(trial=number, candidate=cand, status="screen_early_rejected",
                               reason=early_reason, games=len(screen), planned_games=2*len(maps),
                               changed=pending.get("changed", []))
                    self.state.pop("pending", None)
                    self.save()
                    print(f"  Early rejection after {len(screen)}/{2*len(maps)} games: {early_reason}", flush=True)
                    continue
                if self.config.get("all_maps_required"):
                    require_complete_evaluation(screen, [best], maps)
                # Head-to-head: both sides must be complete; win points dominate gems.
                s = summarize(screen)
                passed = s["faults"] == 0 and (s["points"] > 0.5 or
                         (s["points"] == 0.5 and s["share"] >= 0.5 + self.config["gem_margin"]))
                if self.config.get("promotion_objective") == "wins":
                    # Self-play is a filter, not the final objective. A candidate
                    # can lose narrowly to us yet beat the wider opponent pool.
                    passed = (s["faults"] == 0 and s["points"] >= self.config["screen_min_win_rate"]
                              and s["share"] >= self.config["screen_min_gem_share"])
                if not passed:
                    self.learn_from_results(best, cand, screen)
                    if s["faults"] == 0 and s["share"] >= 0.4:
                        self.remember_explorer(cand)
                    self.event(trial=number, candidate=cand, status="screen_rejected", screen=s,
                               changed=pending.get("changed", []))
                    self.count("trials_completed")
                    self.state.pop("pending", None)
                    self.save()
                    print(f"  Rejected: win points {s['points']:.1%}, gem share {s['share']:.3f}", flush=True)
                    continue
                opponents = pending["opponents"]
                all_maps = self.config["validation_maps"]
                if self.config.get("promotion_all_maps"):
                    all_maps = list(dict.fromkeys(self.config["train_maps"] + all_maps))
                print(f"  Promotion check: {len(opponents)} opponents, {len(all_maps)} maps, both sides", flush=True)
                baseline = self.evaluate(best, opponents, all_maps)
                if self.fast_search:
                    self.search_state(best)["baseline_per_map"] = {
                        m: summarize([r for r in baseline if r["map"] == m]) for m in all_maps}
                if self.fast_search:
                    ordered_maps = [m for m in maps if m in all_maps] + [m for m in all_maps if m not in maps]
                    candidate, paired, early_reason = self.fast_validation(cand, opponents, ordered_maps, baseline)
                    if early_reason:
                        self.learn_from_results(best, cand, candidate, paired, "validation_partial", planned_games=len(baseline))
                        self.count("early_games_avoided", len(baseline)-len(candidate))
                        self.count("trials_completed")
                        self.event(trial=number, candidate=cand, status="validation_early_rejected",
                                   reason=early_reason, games=len(candidate), planned_games=len(baseline),
                                   changed=pending.get("changed", []))
                        self.state.pop("pending", None)
                        self.save()
                        print(f"  Early rejection after {len(candidate)}/{len(baseline)} validation games: {early_reason}", flush=True)
                        continue
                else:
                    candidate = self.evaluate(cand, opponents, all_maps)
                if self.config.get("all_maps_required"):
                    require_complete_evaluation(baseline, opponents, all_maps)
                    require_complete_evaluation(candidate, opponents, all_maps)
                self.learn_from_results(best, cand, candidate, baseline, "validation")
                result = search.rank_result(candidate, baseline, self.config, complete=True)
                if self.fast_search:
                    self.offer_refinements(best, cand, result)
                self.count("trials_completed")
                accepted = promotion_allowed(candidate, baseline, self.config)
                if accepted and self.config.get("promotion_all_maps") and not self.config.get("all_maps_required"):
                    held_out = set(self.config["validation_maps"])
                    accepted = promotion_allowed([r for r in candidate if r["map"] in held_out],
                        [r for r in baseline if r["map"] in held_out], self.config, require_improvement=False)
                if accepted:
                    self.publish(cand)
                    self.state["incumbent"] = cand
                    self.state["champions"].append(cand)
                    self.state["promotions"] += 1
                    if self.fast_search:
                        self.continue_refinements(best, cand)
                    # Historical comparisons used the previous incumbent;
                    # spend the next trials adapting the new one instead.
                    self.state["policy_review_queue"] = []
                    self.state["incumbent_validation"] = dict(checkpoint=cand, maps=all_maps,
                        opponents=opponents, games=len(candidate), complete=True,
                        per_map={m: summarize([r for r in candidate if r["map"] == m]) for m in all_maps},
                        baseline_per_map={m: summarize([r for r in baseline if r["map"] == m]) for m in all_maps})
                    self.state.pop("pending", None)
                    self.save()
                    self.ready()
                else:
                    self.remember_explorer(cand)
                    self.state.pop("pending", None)
                    self.save()
                self.event(trial=number, candidate=cand, status="promoted" if accepted else "validation_rejected",
                           baseline=summarize(baseline), candidate_metrics=summarize(candidate),
                           changed=pending.get("changed", []))
                print(f"  Complete comparison: win gain {result['win_gain']:+.2%} "
                      f"(required {self.config.get('min_win_gain', 0):.2%}); "
                      f"safe search lead: {result['useful']}", flush=True)
                print(f"  {'PROMOTED' if accepted else 'Kept incumbent'}: {summarize(candidate)}", flush=True)
            except BudgetExpired:
                self.event(trial=number, candidate=cand, status="incomplete_budget")
                raise
            except (RuntimeError, ValueError, OSError, KeyError) as e:
                self.event(trial=number, candidate=cand, status="error", error=str(e))
                # Fail visibly rather than spin through a whole hour of broken games.
                raise


def validate_config(c, start_bot=None):
    if "competition_rules" in c and c["competition_rules"] != COMPETITION_RULES:
        raise ValueError("Competition constants cannot be changed by training configuration")
    train, val = c["train_maps"], c["validation_maps"]
    required = c.get("required_maps", OFFICIAL_MAPS)
    if not required or len(set(required)) != len(required) or not set(OFFICIAL_MAPS).issubset(required):
        raise ValueError("Required map manifest must contain the original pool without duplicates")
    if c.get("all_maps_required"):
        if any(len(maps) != len(required) or set(maps) != set(required) for maps in (train, val)):
            raise ValueError("All-map mode requires every manifest map exactly once in BOTH training and validation")
        if (c["screen_maps_per_trial"] != len(required) or not c.get("promotion_all_maps")
            or not c.get("require_fault_free") or not c.get("validation_all_opponents")):
            raise ValueError("All-map mode cannot weaken map coverage, opponent coverage or fault checks")
        if c.get("promotion_objective") == "wins":
            if (not 0 < c.get("min_win_gain", 0) <= 1 or
                not 0 <= c.get("max_map_win_regression", -1) <= 0.25 or
                not 0 <= c["max_map_gem_regression"] <= 0.1 or
                not 0 <= c.get("screen_min_win_rate", -1) <= 1 or
                not 0 <= c.get("screen_min_gem_share", -1) <= 1):
                raise ValueError("Win-focused mode requires a positive win gain and bounded map regressions")
        elif not c.get("strict_per_map") or c["max_map_gem_regression"] != 0:
            raise ValueError("Strict mode cannot weaken per-map regression checks")
    elif not train or not val or set(train) & set(val) or len(set(train + val)) != len(train + val):
        raise ValueError("Legacy training and validation maps must be nonempty, unique and disjoint")
    if not 1 <= c["screen_maps_per_trial"] <= len(train):
        raise ValueError("Invalid screening map count")
    if c["recent_opponents"] < 0 or c["validation_opponents"] < 1 or not 0 < c["gem_margin"] < 1 or not 0 <= c["max_map_gem_regression"] < 1:
        raise ValueError("Invalid promotion settings")
    if not c["parameters"]:
        raise ValueError("No parameters configured")
    for name, spec in c["parameters"].items():
        kind = spec[0]
        valid = ((kind == "bool" and len(spec) == 1) or
                 (kind == "permutation" and len(spec) == 2 and len(spec[1]) >= 2
                  and all(type(v) is int for v in spec[1]) and len(set(spec[1])) == len(spec[1])) or
                 (kind in ("int", "float") and len(spec) == 3 and all(type(v) in (int, float)
                  and math.isfinite(v) for v in spec[1:]) and spec[1] < spec[2]))
        if not valid:
            raise ValueError(f"Invalid parameter specification: {name}")
    for members in c.get("groups", {}).values():
        if not members or not set(members) <= set(c["parameters"]):
            raise ValueError("Mutation group contains an unknown parameter")
    for name, maps in c.get("screen_required_maps", {}).items():
        if name not in c["parameters"] or not set(maps) <= set(train):
            raise ValueError(f"Invalid required screening maps for {name}")
    for name, requirements in c.get("dependencies", {}).items():
        if name not in c["parameters"]:
            raise ValueError(f"Unknown dependent parameter: {name}")
        for parent, value in requirements.items():
            if parent not in c["parameters"]:
                raise ValueError(f"Unknown prerequisite: {parent}")
            valid_value(parent, value, c["parameters"][parent])
    if not 0 <= c.get("exploration_probability", 0) <= 1 or c.get("exploration_archive", 0) < 0:
        raise ValueError("Invalid exploration settings")
    for m in train + val:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", m) or not (ROOT / "maps" / (m + ".map26a")).is_file():
            raise ValueError(f"Missing or invalid map: {m}")
    for bot in [c["start"], *c["opponents"]]:
        if not (ROOT / bot / "src" / "params.h").is_file():
            raise ValueError(f"Missing bot: {bot}")
    starter = start_bot or ROOT / c["start"]
    coverage(starter, c)
    if c.get("competition_rules"):
        values = read_params(starter, c["parameters"])
        validate_gene_rules(values)
        # Validate both ends too: custom config cannot broaden legal ID/fuel ranges.
        for edge in (1, 2):
            extreme = dict(values)
            for name, spec in c["parameters"].items():
                if spec[0] in ("int", "float"):
                    extreme[name] = spec[edge]
            # BANK_MIN/MAX are a coupled strategy constraint, repaired during mutation.
            extreme.pop("BANK_MIN", None)
            extreme.pop("BANK_MAX", None)
            validate_gene_rules(extreme)
        for name, spec in c["parameters"].items():
            if spec[0] == "permutation":
                validate_gene_rules({name: spec[1]})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minutes", type=float, default=60, help="Wall-clock budget INCLUDING builds and validation")
    parser.add_argument("--jobs", type=int, default=2, help="Concurrent games; default 2 limits CPU/memory pressure")
    parser.add_argument("--fast-search", action="store_true", help="Focus proposals and stop mathematically rejected candidates early; full promotion validation is unchanged")
    parser.add_argument("--run", type=Path, default=ROOT / "out" / "training" / "master-all-maps")
    parser.add_argument("--config", type=Path, default=ROOT / "tools" / "train_win_config.json")
    parser.add_argument("--seed", type=int, default=20261016, help="Used only for a NEW run")
    parser.add_argument("--check", action="store_true", help="Validate setup without building or playing games")
    parser.add_argument("--list-params", action="store_true", help="Show every trainable setting and fixed-setting reason")
    parser.add_argument("--upgrade-from", type=Path, help="Import incumbent genes from an older run into a NEW experiment; re-evaluates under current rules")
    parser.add_argument("--adopt-policy", action="store_true", help="Adopt promotion-only policy changes in an existing run, preserving valid cached matches and reconsidering earlier candidates")
    args = parser.parse_args(argv)
    if not math.isfinite(args.minutes) or args.minutes <= 0 or args.jobs < 1:
        parser.error("--minutes and --jobs must be positive")
    config = json.loads(args.config.read_text())
    start_bot = ROOT / config["start"]
    if (args.run / "state.json").exists():
        saved = json.loads((args.run / "state.json").read_text())
        start_bot = args.run / "checkpoints" / saved["incumbent"]
    validate_config(config, start_bot)
    read_params(start_bot, config["parameters"])
    if not ENGINE.is_file():
        raise ValueError("Missing cambc.exe")
    if args.check or args.list_params:
        print(f"Setup OK: {len(config['parameters'])} parameters, {len(config['train_maps'])} training maps, "
              f"{len(config['validation_maps'])} validation maps. No matches played.")
        print(json.dumps(coverage(start_bot, config), indent=2))
        if args.list_params:
            for name, spec in config["parameters"].items():
                print(f"  {name}: {spec}")
        return 0
    STOP.clear()
    signal.signal(signal.SIGINT, lambda *_: STOP.set())
    deadline = time.monotonic() + args.minutes * 60
    folder = args.run.resolve()
    with run_lock(folder / "trainer.lock"):
        trainer = Trainer(folder, config, args.jobs, deadline)
        if args.fast_search and (config.get("promotion_objective") != "wins" or not config.get("all_maps_required")):
            raise ValueError("--fast-search requires a win-focused all-map configuration")
        trainer.fast_search = args.fast_search
        trainer.load(args.seed, args.upgrade_from, args.adopt_policy)
        if trainer.fast_search:
            print("Fast search enabled: small local refinements, complete search leads, 2:1 exploitation/coverage; complete validation required for promotion.", flush=True)
        atomic_json(folder / "parameter_coverage.json", coverage(trainer.checkpoints / trainer.state["incumbent"], config))
        trainer.state["sessions"] += 1
        trainer.save()
        initial_promotions = trainer.state["promotions"]
        initial_incumbent = trainer.state["incumbent"]
        started = time.monotonic()
        status, error = "finished", None
        try:
            trainer.train()
        except BudgetExpired:
            status = "interrupted" if STOP.is_set() else "budget_reached"
        except Exception as e:
            status, error = "error", str(e)
        finally:
            trainer.save()
            trainer.ready()
            report = dict(status=status, error=error, elapsed_seconds=round(time.monotonic() - started, 1),
                          incumbent=trainer.state["incumbent"], trials_total=trainer.state["trials"],
                          promotions_total=trainer.state["promotions"], sessions=trainer.state["sessions"],
                          ready=(folder / "ready.zip").exists())
            report["validated_checkpoint"] = bool(trainer.state.get("incumbent_validation"))
            report["feedback_comparisons"] = trainer.state.get("feedback", {}).get("observations", 0)
            report["settings_with_feedback"] = len(trainer.state.get("feedback", {}).get("parameters", {}))
            report["session_promotions"] = trainer.state["promotions"] - initial_promotions
            report["session_start_incumbent"] = initial_incumbent
            report["session_counts"] = trainer.session_counts
            adaptive = trainer.state.get("adaptive_search", {})
            report["useful_search_leads"] = len(adaptive.get("leaders", [])) if adaptive.get("parent") == trainer.state["incumbent"] else 0
            atomic_json(folder / "last_session.json", report)
            print(json.dumps(report, indent=2), flush=True)
            if report["ready"]:
                print(f"Submission: {folder / 'ready.zip'}", flush=True)
            else:
                print("No bundle yet: allow more startup time and rerun.", flush=True)
        if error:
            print(error, file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"Training setup error: {exc}", file=sys.stderr)
        sys.exit(1)
