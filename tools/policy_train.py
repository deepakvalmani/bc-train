"""Resumable decision learning and guarded source-only Battlecode deployment.

Collection, fitting and validation are separate stages. Instrumented games train
the model but never establish a release win rate. Standard-library Python only.
"""
import argparse
import json
import math
from pathlib import Path
import re
import signal
import sys
import time

import policy_learning as policy
import train
import source_repairs
import economy_learning
import fuel_audit
import compact_telemetry


class PolicyTrainer(train.Trainer):
    def progress(self, stage, message, **metrics):
        record=dict(stage=stage, message=message,
                    completed_cycles=self.state.get('policy_cycles',0),
                    accepted_improvements=self.state.get('promotions',0),
                    optimizer_updates=self.state.get('optimizer_updates',0), **metrics)
        self.state['learning_progress']=record
        train.atomic_json(self.folder/'learning_status.json',record)
        print(f"[{stage.upper()}] {message}",flush=True)

    def __init__(self, *args):
        super().__init__(*args)
        self.data = self.folder / "decisions"
        self.data.mkdir(parents=True, exist_ok=True)

    def build(self, digest):
        fresh = digest not in self.built
        super().build(digest)
        if fresh and digest in self.compiled:
            fingerprints = self.state.setdefault("policy_binaries", {})
            previous = fingerprints.get(digest)
            if previous and previous != self.compiled[digest]:
                raise ValueError("Compiled policy binary changed; use a new run before reusing match results")
            fingerprints[digest] = self.compiled[digest]
            self.save()  # Pin the executable before any of its results are cached.

    def load_policy(self, seed, upgrade_from, adopt_audit_policy=False):
        existed = (self.folder / "state.json").exists()
        if existed and adopt_audit_policy:
            previous=json.loads((self.folder/'state.json').read_text())
            old_config=previous['config']
            expected=json.loads(json.dumps(old_config))
            expected['policy']['fuel_audit_mode']='baseline_relative'
            if self.config!=old_config and (self.config!=expected or previous.get('incumbent_validation') or previous.get('policy_cycle')):
                raise ValueError('Audit migration only permits the baseline-relative audit option on an unqualified run')
            if self.config!=old_config:
                if previous.get('policy_contract')!=train.source_hash(train.ROOT/self.config['start']):
                    raise ValueError('Bot source changed; audit migration cannot reuse this run')
                requested=self.config
                self.config=old_config
                self.load(seed,upgrade_from)  # Verify pinned runtime/checkpoints before changing policy.
                self.config=requested
                self.state['config']=requested
                self.state.setdefault('audit_policy_migrations',[]).append(dict(
                    from_mode=old_config['policy'].get('fuel_audit_mode','strict_zero'),
                    to_mode='baseline_relative',reason='Legal suspend/resume is measured against baseline; fuel quantum stays 100000'))
                self.save()
        self.load(seed, upgrade_from)
        contract = train.source_hash(train.ROOT / self.config["start"])
        if existed and self.state.get("policy_contract"):
            if self.state.get("policy_contract") != contract:
                raise ValueError("Policy source/schema changed; use a new --run directory and --upgrade-from")
        else:
            self.state["policy_contract"] = contract
            imported = self.state.get("imported_genes")
            if imported:
                prior_folder = Path(imported["run"])
                original = prior_folder / "checkpoints" / imported["checkpoint"]
                if train.source_hash(original) != imported["checkpoint"]:
                    raise ValueError("Changed imported teacher source")
                self.state["teacher"] = self.snapshot(original)
                weights, enabled = policy.read_header(original)
                best = self.variant(self.state["incumbent"], weights, enabled=enabled)
                self.state["incumbent"] = best
                self.state["champions"] = [best]
            else:
                self.state["teacher"] = self.state["incumbent"]
            self.state["holdouts"] = [self.snapshot(train.ROOT / path) for path in self.config["policy"]["holdouts"]]
            if set(self.state["holdouts"]) & {self.state["teacher"], *self.state["anchors"], *self.state["champions"]}:
                raise ValueError("Held-out sources overlap training opponents")
            self.state["policy_cycles"] = 0
            self.state["exploiters"] = []
            if self.config["policy"].get("repair_movement_v1", False):
                import tempfile
                mapping = {}
                for digest in dict.fromkeys([self.state["teacher"], self.state["incumbent"],
                                             *self.state["anchors"], *self.state["holdouts"]]):
                    with tempfile.TemporaryDirectory(prefix="repair_", dir=self.folder) as directory:
                        path = Path(directory)
                        train.copy_source(self.checkpoints / digest, path)
                        source_repairs.repair_movement(path)
                        mapping[digest] = self.snapshot(path)
                self.state["teacher"] = mapping[self.state["teacher"]]
                self.state["incumbent"] = mapping[self.state["incumbent"]]
                self.state["anchors"] = list(dict.fromkeys(mapping[d] for d in self.state["anchors"]))
                self.state["holdouts"] = list(dict.fromkeys(mapping[d] for d in self.state["holdouts"]))
                self.state["champions"] = [self.state["incumbent"]]
                self.state["source_repairs"] = dict(version=2, checkpoints=mapping)
                if set(self.state["holdouts"]) & {self.state["teacher"], *self.state["anchors"], self.state["incumbent"]}:
                    raise ValueError("Repaired held-out sources overlap training opponents")
            self.save()
        for digest in [self.state["teacher"], *self.state["holdouts"], *self.state.get("exploiters", [])]:
            if train.source_hash(self.checkpoints / digest) != digest:
                raise ValueError("Changed policy teacher/held-out source")
        cycle = self.state.get("policy_cycle")
        if cycle:
            if cycle["parent"] != self.state["incumbent"]:
                raise ValueError("Pending policy cycle has a stale parent")
            for digest in [cycle["collector"], *cycle.get("candidates", []), *cycle["opponents"],
                           *cycle.get("validation_opponents", [])]:
                if train.source_hash(self.checkpoints / digest) != digest:
                    raise ValueError("Changed pending policy source")

    def variant(self, source, weights, enabled=True, telemetry=False, audit=False, exploration=0, exploration_seed=0):
        # Reuse the checkpoint transaction; changes to the policy header get a
        # distinct content identity, so instrumented matches cannot pollute release caches.
        import tempfile
        with tempfile.TemporaryDirectory(prefix="policy_source_", dir=self.folder) as folder:
            path = Path(folder)
            train.copy_source(self.checkpoints / source, path)
            (path / "src" / "policy_weights.h").write_text(
                policy.header(weights, enabled, telemetry, audit, exploration, exploration_seed), encoding="utf-8")
            if telemetry:
                compact_telemetry.apply(path/'src/policy.h')
            return self.snapshot(path)

    def consume_game_artifacts(self, bot, opponent, map_name, side, row, work):
        other_stdout = train.bot_stdout(work, 1-side)
        if other_stdout is not None:
            row["enemy_faults"] = row.get("enemy_faults",0) + other_stdout.count("bot error:")
        header = self.checkpoints / bot / "src" / "policy_weights.h"
        if not header.exists():
            return
        source = header.read_text(encoding="utf-8")
        collecting = bool(re.search(r"\btelemetry\s*=\s*true", source))
        auditing = bool(re.search(r"\baudit\s*=\s*true", source))
        if not collecting and not auditing:
            return
        stdout = train.bot_stdout(work, side)
        if stdout is None:
            parsed = dict(schema=policy.SCHEMA, usable=False, diagnostics=dict(missing_or_oversized_log=True), decisions=[])
        else:
            parsed = policy.parse(stdout, dict(row, reward_weights=self.config['policy'].get('reward_weights'),
                require_economic_telemetry=collecting and self.config['policy'].get('economic_exploration',False),
                sparse_economic_telemetry=compact_telemetry.MARKER in (self.checkpoints/bot/'src/policy.h').read_text()))
            parsed['diagnostics']['stdout_bytes']=getattr(stdout,'raw_bytes',len(stdout.encode('utf-8')))
            if parsed['diagnostics']['stdout_bytes']>=1048576:
                parsed['diagnostics']['log_truncated']=True
                parsed.update(usable=False,audit_passed=False,decisions=[])
        parsed['diagnostics']['engine_economy']=row.get('economy')
        parsed['diagnostics']['engine_champion_economy']=row.get('champion_economy')
        row["policy_audit"] = dict(usable=parsed.get("audit_passed",False), diagnostics=parsed["diagnostics"])
        if collecting:
            for decision in parsed["decisions"]:
                decision["map"] = map_name
            train.atomic_json(self.data / f"{bot}_{opponent}_{map_name}_{side}.json", dict(
                **parsed, collector=bot, opponent=opponent, map=map_name, side=side,
                runtime=self.state["runtime"], result=dict(row)))

    def pool(self, best):
        return list(dict.fromkeys([best, self.state["teacher"], *self.state["anchors"],
                                   *self.state["champions"][-3:], *self.state.get("exploiters", [])[-3:]]))

    def full(self, bot, opponents):
        for digest in dict.fromkeys([bot, *opponents]):
            if train.source_hash(self.checkpoints/digest) != digest:
                raise ValueError("Checkpoint source changed before evaluation")
        rows = self.evaluate(bot, opponents, self.config["validation_maps"])
        train.require_complete_evaluation(rows, opponents, self.config["validation_maps"])
        if any(r.get("enemy_faults",0) for r in rows):
            train.atomic_json(self.folder / "failed_comparison.json", dict(
                bot=bot, failures=[r for r in rows if r.get("faults") or r.get("enemy_faults")],
                note="Faulty opponent results cannot qualify a release. Inspect logs/*stdout."))
            raise ValueError("Opponent faults invalidate this comparison; inspect match statistics/logs")
        return rows

    def audit(self, candidate, establish_baseline=False):
        weights, enabled = policy.read_header(self.checkpoints / candidate)
        instrumented = self.variant(candidate, weights, enabled, audit=True)
        rows = self.full(instrumented, [self.state["teacher"]])
        good = all(r["faults"] == 0 and r.get("policy_audit", {}).get("usable") for r in rows)
        cases=[dict(map=r['map'],side=r['side'],faults=r['faults'],**r.get('policy_audit',{})) for r in rows]
        mode=self.config['policy'].get('fuel_audit_mode','strict_zero')
        comparisons=[]
        if mode=='baseline_relative':
            reference=self.state.get('incumbent_validation',{}).get('fuel_audit')
            if reference is None and not establish_baseline:
                raise ValueError('No accepted fuel reference; cannot validate a learned candidate')
            good,comparisons=fuel_audit.judge(cases,reference['diagnostics'] if reference else None)
        report = dict(passed=good, mode=mode, games=len(rows), diagnostics=cases,
                      comparison=comparisons,
                      strict_zero_suspension_passed=all(r['faults']==0 and r.get('policy_audit',{}).get('usable') for r in rows),
                      note="Conservative instrumented fuel check on configured maps; not a proof for unseen states")
        train.atomic_json(self.folder / "fuel_audit.json", report)
        return report

    def heldout_allowed(self, candidate, baseline):
        guard = dict(self.config, min_win_gain=0.0)
        return (train.promotion_allowed(candidate, baseline, guard)
                and train.summarize(candidate)["share"] >= train.summarize(baseline)["share"] - 0.01)

    def publish(self, digest):
        economic=self.checkpoints/digest/'src/economy_weights.h'
        if economic.exists():
            economy_learning.header(economy_learning.read(economic))  # Validate all export bounds.
        source = (self.checkpoints / digest / "src" / "policy_weights.h").read_text(encoding="utf-8")
        policy.read_header(self.checkpoints / digest)
        if (not re.search(r"\btelemetry\s*=\s*false", source)
                or not re.search(r"\baudit\s*=\s*false", source)
                or not re.search(r"\bexploration\s*=\s*0\.0+f", source)
                or not re.search(r"\bexploration_seed\s*=\s*0\s*;", source)):
            raise ValueError("Refusing to publish instrumented/exploring policy")
        super().publish(digest)

    def ready(self):
        if self.state.get("incumbent_validation"):
            super().ready()
            path = self.folder / "ready.json"
            if path.exists():
                data = json.loads(path.read_text())
                _, enabled = policy.read_header(self.checkpoints / self.state["incumbent"])
                data["decision_policy"] = dict(schema=policy.SCHEMA, coefficients=48, enabled=enabled,
                                                heads=list(policy.NAMES), baseline_qualification=self.state["promotions"] == 0)
                economic=self.checkpoints / self.state['incumbent'] / 'src/economy_weights.h'
                if economic.exists():
                    data['economic_policy']=dict(settings=economy_learning.read(economic),
                        continuous_settings=len(economy_learning.DEFAULTS),feature_flags=len(economy_learning.GROUPS),
                        risk_estimate='observable-threat heuristic; not calibrated probability')
                train.atomic_json(path, data)

    def qualify_baseline(self):
        if self.state.get("incumbent_validation"):
            return
        best, teacher = self.state["incumbent"], self.state["teacher"]
        opponents = self.pool(best)
        print("Qualifying the imported teacher: every map, both sides, training and held-out pools.", flush=True)
        self.progress('qualification','Step 1/5: teacher versus league. Learning has not started.')
        base=self.full(teacher,opponents)
        self.progress('qualification','Step 2/5: starting bot versus league. Learning has not started.')
        candidate=self.full(best,opponents)
        self.progress('qualification','Step 3/5: teacher versus held-out opponents. Learning has not started.')
        held_base = self.full(teacher, self.state["holdouts"])
        self.progress('qualification','Step 4/5: starting bot versus held-out opponents. Learning has not started.')
        held = self.full(best, self.state["holdouts"])
        guard = dict(self.config, min_win_gain=0.0)
        if not train.promotion_allowed(candidate, base, guard) or not self.heldout_allowed(held, held_base):
            faults = [dict(pool=pool, map=r['map'], side=r['side'],
                           opponent=r['opponent'], faults=r['faults'])
                      for pool, rows in [('league', candidate), ('heldout', held)]
                      for r in rows if r['faults']]
            train.atomic_json(self.folder / 'baseline_failure.json', dict(
                teacher=teacher, candidate=best, faults=faults,
                league=dict(candidate=train.summarize(candidate), baseline=train.summarize(base)),
                heldout=dict(candidate=train.summarize(held), baseline=train.summarize(held_base))))
            detail = ('; bot faults: ' + ', '.join(
                f"{r['map']} side {r['side']} ({r['pool']}, {r['faults']} faults)" for r in faults)) if faults else ''
            raise ValueError("Starting bot failed baseline qualification" + detail
                             + "; inspect baseline_failure.json and logs/*stdout. Old run is unchanged")
        self.progress('qualification','Step 5/5: fuel audit. No learned update accepted yet.')
        audit = self.audit(best,establish_baseline=True)
        if not audit["passed"]:
            raise ValueError("Baseline audit failed: inspect fuel_audit.json for missing logs, malformed records or fuel failures")
        self.publish(best)
        self.state["incumbent_validation"] = self.validation(best, candidate, base, held, held_base, audit)
        self.save()
        self.ready()
        self.progress('qualified','Starting bot qualified. Next: collect training decisions; qualification itself did not train weights.')

    def validation(self, digest, rows, baseline, held, held_base, audit):
        maps = self.config["validation_maps"]
        return dict(checkpoint=digest, maps=maps, complete=True, games=len(rows),
                    economic_metrics={m:[r.get('economy') for r in rows if r['map']==m] for m in maps},
                    opponents=list(dict.fromkeys(r["opponent"] for r in rows)),
                    per_map={m: train.summarize([r for r in rows if r["map"] == m]) for m in maps},
                    baseline_per_map={m: train.summarize([r for r in baseline if r["map"] == m]) for m in maps},
                    heldout=dict(candidate=train.summarize(held), baseline=train.summarize(held_base),
                                 games=len(held), opponents=self.state["holdouts"],
                                 per_map={m: dict(candidate=train.summarize([r for r in held if r["map"] == m]),
                                                  baseline=train.summarize([r for r in held_base if r["map"] == m])) for m in maps}),
                    fuel_audit=audit)

    def collect(self, best):
        cycle = self.state.get("policy_cycle")
        if cycle is None:
            weights, enabled = policy.read_header(self.checkpoints / best)
            collector = self.variant(best, weights, enabled, telemetry=True,
                                     exploration=0.0 if self.state["policy_cycles"] == 0 else 0.08,
                                     exploration_seed=(self.state["policy_cycles"] * 2654435761) % (2**32))
            league = self.pool(best)
            start = self.state["policy_cycles"] % len(league)
            opponents = [league[start], league[(start+1) % len(league)]]
            cycle = dict(parent=best, collector=collector, opponents=list(dict.fromkeys(opponents)), stage="collect")
            self.state["policy_cycle"] = cycle
            self.save()
        if cycle["parent"] != best:
            raise ValueError("Pending policy cycle belongs to a different incumbent")
        if cycle['stage'] in ('collect','fit') and compact_telemetry.MARKER not in (self.checkpoints/cycle['collector']/'src/policy.h').read_text():
            weights,enabled=policy.read_header(self.checkpoints/best)
            cycle['collector']=self.variant(best,weights,enabled,telemetry=True,
                exploration=0.0 if self.state['policy_cycles']==0 else 0.08,
                exploration_seed=(self.state['policy_cycles']*2654435761)%(2**32))
            cycle['stage']='collect'
            self.save()
            self.progress('collection_upgrade','Compact logger avoids the engine stdout cap; recollecting with a new immutable collector.')
        if cycle["stage"] == "collect":
            self.progress('collection',f"Cycle {self.state['policy_cycles']+1}: recording decisions and outcomes; no weight update yet.")
            print(f"Collecting decisions on all {len(self.config['train_maps'])} configured maps against {len(cycle['opponents'])} league opponents.", flush=True)
            self.full(cycle["collector"], cycle["opponents"])
            cycle["stage"] = "fit"
            self.save()
        return cycle

    def dataset(self):
        files = sorted(self.data.glob("*.json"), key=lambda p: (p.stat().st_mtime_ns,p.name))[-96:]
        decisions, summaries = [], []
        for path in files:
            episode = json.loads(path.read_text(encoding="utf-8"))
            if episode["runtime"] != self.state["runtime"] or episode["schema"] != policy.SCHEMA:
                raise ValueError("Incompatible decision data")
            summaries.append(dict(map=episode["map"], usable=episode["usable"], **episode["diagnostics"]))
            if episode["usable"]:
                decisions.extend(episode["decisions"])
        counts = {m: sum(d["map"] == m for d in decisions) for m in self.config["train_maps"]}
        train.atomic_json(self.folder / "loss_diagnostics.json", dict(
            episodes=summaries, decisions_by_map=counts,
            decisions_by_head={name: sum(d["head"] == h for d in decisions) for h,name in enumerate(policy.NAMES)},
            note="Gem losses and interruptions are estimates; they are not causal explanations."))
        if any(n == 0 for n in counts.values()):
            missing=[m for m,n in counts.items() if not n]
            self.progress('data_blocked',f"No clean decisions on: {', '.join(missing)}. No weights fitted.",
                          usable_decisions=len(decisions),missing_maps=missing)
            raise ValueError("Clean decision data is missing on a map; inspect loss_diagnostics.json (no policy fitted)")
        self.progress('data_ready',f"{len(decisions)} usable decisions from {len(files)} episodes; all {len(counts)} maps represented.",
                      usable_decisions=len(decisions),episodes=len(files),decisions_by_map=counts,
                      usable_episodes=sum(bool(s['usable']) for s in summaries))
        return decisions

    def fit_cycle(self, cycle):
        if cycle["stage"] != "fit":
            return
        decisions = self.dataset()
        best = cycle["parent"]
        initial, _ = policy.read_header(self.checkpoints / best)
        self.progress('fitting',f"Fitting 48 coefficients from {len(decisions)} decisions. Changed weights still need match validation.")
        fitted, report = policy.fit(initial, decisions, self.state["policy_cycles"], self.deadline)
        if not report["complete"]:
            self.progress('fit_incomplete',f"Budget ended after {report['updates']} optimizer steps. Partial fit will not be deployed.")
            raise train.BudgetExpired()  # Dataset and stage survive; fitting repeats deterministically.
        changed=sum(abs(a-b)>1e-8 for x,y in zip(initial,fitted) for a,b in zip(x,y))
        delta=sum(abs(a-b) for x,y in zip(initial,fitted) for a,b in zip(x,y))
        report.update(changed_coefficients=changed,weight_change_l1=delta)
        candidates = []
        if self.config["policy"].get("economic_exploration", False):
            import tempfile
            values=economy_learning.read(self.checkpoints / best / 'src/economy_weights.h')
            for proposal in economy_learning.proposals(values,self.state['policy_cycles']):
                with tempfile.TemporaryDirectory(prefix='economic_',dir=self.folder) as directory:
                    path=Path(directory)
                    train.copy_source(self.checkpoints/best,path)
                    (path/'src/economy_weights.h').write_text(economy_learning.header(proposal),encoding='utf-8')
                    digest=self.snapshot(path)
                    if digest!=best and digest not in candidates:
                        candidates.append(digest)
            report['economic_search']='rotating banking, camps, survival, shopping, combat, mobility; bounded full-match selection'
        if self.config["policy"].get("sequence_exploration", False):
            # Search a bounded grammar of legal SDK action orders. Candidates
            # inherit accepted weights and still face every normal release gate.
            import tempfile
            orders = [(a,b) for a in range(4) for b in range(4)]
            start = (self.state["policy_cycles"] * 3) % len(orders)
            for offset in range(3):
                healthy, injured = orders[(start+offset) % len(orders)]
                with tempfile.TemporaryDirectory(prefix="sequence_", dir=self.folder) as folder:
                    path = Path(folder)
                    train.copy_source(self.checkpoints / best, path)
                    (path / "src" / "sequence_weights.h").write_text(
                        "#pragma once\nnamespace sequences {\n"
                        f"inline constexpr int healthy = {healthy}, injured = {injured};\n"
                        "static_assert(healthy >= 0 && healthy <= 3 && injured >= 0 && injured <= 3);\n}\n",
                        encoding="utf-8")
                    digest = self.snapshot(path)
                    if digest != best and digest not in candidates:
                        candidates.append(digest)
            report["sequence_search"] = "three rotating orders; healthy/injured contexts; full-match evolutionary selection"
        for strength in (0.25, 0.5, 1.0):
            weights = [[a+strength*(b-a) for a,b in zip(x,y)] for x,y in zip(initial,fitted)]
            digest = self.variant(best, weights)
            if digest != best and digest not in candidates:
                candidates.append(digest)
        # Keep draft, item and strategy evolution alongside decision learning.
        values, _, _ = self.propose(best)
        strategy = self.snapshot(self.checkpoints / best, values)
        if strategy != best and strategy not in candidates:
            candidates.append(strategy)
        cycle.update(stage="validate", candidates=candidates, cursor=0, fitting=report)
        self.state['optimizer_updates']=self.state.get('optimizer_updates',0)+report['updates']
        self.progress('fit_complete',f"{report['updates']} optimizer steps; {changed}/48 coefficients changed; "
                      f"total absolute change {delta:.6f}. Testing {len(candidates)} candidates; improvement is not confirmed.",
                      changed_coefficients=changed,weight_change_l1=delta,candidates=len(candidates))
        train.atomic_json(self.folder / "model_training.json", dict(schema=policy.SCHEMA,
                          parameters=48, samples=len(decisions), heads=list(policy.NAMES), weights=fitted,
                          algorithm="teacher-anchored return-weighted pairwise imitation", **report))
        self.save()

    def train_policy(self):
        self.qualify_baseline()
        while not train.STOP.is_set() and time.monotonic() < self.deadline:
            best = self.state["incumbent"]
            cycle = self.collect(best)
            self.fit_cycle(cycle)
            if "validation_opponents" not in cycle:
                cycle["validation_opponents"] = self.pool(best)
                self.save()
            opponents = cycle["validation_opponents"]
            baseline = self.full(best, opponents)
            promoted = False
            while cycle["cursor"] < len(cycle["candidates"]):
                candidate = cycle["candidates"][cycle["cursor"]]
                self.state["trials"] += 1 if cycle.get("active") != candidate else 0
                cycle["active"] = candidate
                self.save()
                print(f"Policy trial {self.state['trials']}: {candidate}; full league validation.", flush=True)
                self.progress('validation',f"Candidate {cycle['cursor']+1}/{len(cycle['candidates'])}: testing against the accepted bot's baseline.")
                rows = self.full(candidate, opponents)
                candidate_score=train.summarize(rows); baseline_score=train.summarize(baseline)
                gain=candidate_score['points']-baseline_score['points']
                self.progress('comparison',f"Win points {candidate_score['points']:.1%} versus baseline {baseline_score['points']:.1%}; "
                              f"change {gain*100:+.2f} percentage points. Map, held-out and fuel gates still apply.",
                              candidate_win_points=candidate_score['points'],baseline_win_points=baseline_score['points'],
                              win_points_gain=gain)
                accepted = train.promotion_allowed(rows, baseline, self.config)
                reason = None if accepted else "league win gain, map regression or fault gate"
                held = held_base = audit = None
                if accepted:
                    held_base = self.full(best, self.state["holdouts"])
                    held = self.full(candidate, self.state["holdouts"])
                    accepted = self.heldout_allowed(held, held_base)
                    if not accepted:
                        reason = "reserved-opponent regression gate"
                if accepted:
                    audit = self.audit(candidate)
                    accepted = audit["passed"]
                    if not accepted:
                        reason = "fuel audit gate"
                self.count("trials_completed")
                self.event(trial=self.state["trials"], candidate=candidate, parent=best,
                           status="policy_promoted" if accepted else "policy_rejected",
                           candidate_metrics=train.summarize(rows), baseline=train.summarize(baseline),
                           reason=reason, fuel_audit=audit,
                           heldout_candidate=train.summarize(held) if held else None,
                           heldout_baseline=train.summarize(held_base) if held_base else None)
                if accepted:
                    self.publish(candidate)
                    self.state["incumbent"] = candidate
                    self.state["champions"].append(candidate)
                    self.state["promotions"] += 1
                    self.state["incumbent_validation"] = self.validation(candidate, rows, baseline, held, held_base, audit)
                    promoted = True
                    self.state.pop("policy_cycle")
                    self.state["policy_cycles"] += 1
                    self.save()
                    self.ready()
                    self.progress('promoted',f"Accepted improvement #{self.state['promotions']}: ready.zip updated after all gates passed.",
                                  checkpoint=candidate,win_points_gain=gain)
                    print("PROMOTED after league, held-out and fuel checks.", flush=True)
                    break
                against_best = [r for r in rows if r["opponent"] == best]
                if (against_best and train.summarize(against_best)["points"] > 0.5
                        and all(r["faults"] == 0 for r in rows)):
                    archive = self.state.setdefault("exploiters", [])
                    if candidate not in archive:
                        archive.append(candidate)
                    self.state["exploiters"] = archive[-3:]
                    # The cycle keeps its original pool for fair comparisons;
                    # counter-strategies join the next cycle's league.
                cycle["cursor"] += 1
                self.save()
                print(f"Kept incumbent: {reason}.", flush=True)
                self.progress('rejected',f"Candidate rejected: {reason}. Previous validated bot retained; fitted weights were not adopted.",
                              checkpoint=candidate,win_points_gain=gain)
            if not promoted:
                self.state["policy_cycles"] += 1
                self.state.pop("policy_cycle")
                self.save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=train.ROOT / "tools/train_policy_config.json")
    parser.add_argument("--run", type=Path, default=train.ROOT / "out/training/decision-policy")
    parser.add_argument("--upgrade-from", type=Path)
    parser.add_argument("--minutes", type=float, default=60)
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--seed", type=int, default=20261016)
    parser.add_argument('--qualify-only',action='store_true',help='Check the starting bot without collecting or fitting a policy')
    parser.add_argument('--adopt-audit-policy',action='store_true',help='Reuse an unqualified run only when changing to baseline-relative fuel auditing')
    args = parser.parse_args()
    if not math.isfinite(args.minutes) or args.minutes <= 0 or args.jobs < 1:
        parser.error("Positive minutes and jobs required")
    folder = args.run.resolve()
    if args.upgrade_from and args.upgrade_from.resolve() == folder:
        parser.error("Use a separate new run for source upgrades")
    config = json.loads(args.config.read_text())
    train.validate_config(config)
    if not config.get("all_maps_required") or not config.get("validation_all_opponents"):
        parser.error("Decision learning requires full all-map validation")
    if not config["policy"].get("holdouts") or set(config["policy"]["holdouts"]) & set(config["opponents"]):
        parser.error("Separate held-out opponent sources are required")
    if config["policy"].get("schema") != policy.SCHEMA:
        parser.error("Unsupported decision-policy schema")
    if config['policy'].get('fuel_audit_mode','strict_zero') not in ('strict_zero','baseline_relative'):
        parser.error('Unsupported fuel audit mode')
    rewards=config['policy'].get('reward_weights')
    if rewards is not None and (set(rewards)!={'tribute','kills','gold','time','death','failure'}
            or any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=4 for v in rewards.values())
            or rewards['tribute']<=0):
        parser.error('Invalid bounded economic reward weights')
    if len(config["policy"]["holdouts"]) != len(set(config["policy"]["holdouts"])):
        parser.error("Held-out opponents must be unique")
    for opponent in config["policy"]["holdouts"]:
        if not (train.ROOT/opponent/"src").is_dir():
            parser.error(f"Missing held-out opponent: {opponent}")
    train.STOP.clear()
    signal.signal(signal.SIGINT, lambda *_: train.STOP.set())
    deadline = time.monotonic() + args.minutes*60
    with train.run_lock(folder / "trainer.lock"):
        trainer = PolicyTrainer(folder, config, args.jobs, deadline)
        trainer.load_policy(args.seed, args.upgrade_from,args.adopt_audit_policy)
        trainer.state["sessions"] += 1
        before = trainer.state["promotions"]
        started, status, error = time.monotonic(), "finished", None
        try:
            trainer.qualify_baseline() if args.qualify_only else trainer.train_policy()
        except train.BudgetExpired:
            status = "interrupted" if train.STOP.is_set() else "budget_reached"
        except (ValueError, RuntimeError, OSError, KeyError) as exc:
            status, error = "error", str(exc)
        finally:
            trainer.save()
            trainer.ready()
            report = dict(status=status, error=error, elapsed_seconds=round(time.monotonic()-started,1),
                          incumbent=trainer.state["incumbent"], session_promotions=trainer.state["promotions"]-before,
                          promotions_total=trainer.state["promotions"], trials_total=trainer.state["trials"],
                          policy_cycles=trainer.state["policy_cycles"], session_counts=trainer.session_counts,
                          validated_checkpoint=bool(trainer.state.get("incumbent_validation")),
                          ready=(folder/"ready.zip").exists(), pending_stage=trainer.state.get("policy_cycle",{}).get(
                              "stage","next_cycle" if trainer.state.get("incumbent_validation") else "baseline"))
            report["model_enabled"] = policy.read_header(trainer.checkpoints/trainer.state["incumbent"])[1]
            report["learned_coefficients"] = 48
            report["strategy_settings"] = len(config["parameters"])
            report['economic_settings']=len(economy_learning.DEFAULTS) if config['policy'].get('economic_exploration') else 0
            report['learning_progress']=trainer.state.get('learning_progress')
            report['optimizer_updates']=trainer.state.get('optimizer_updates',0)
            progress=dict(trainer.state.get('learning_progress',{}),session_status=status,error=error)
            train.atomic_json(folder/'learning_status.json',progress)
            train.atomic_json(folder/"last_session.json",report)
            if not trainer.state.get('incumbent_validation'):
                print('[SUMMARY] Still qualifying the starting bot; no policy learning completed. Completed games are cached for resume.',flush=True)
            else:
                print(f"[SUMMARY] Completed learning cycles: {trainer.state['policy_cycles']}; "
                      f"optimizer steps: {trainer.state.get('optimizer_updates',0)}; "
                      f"accepted improvements this session: {trainer.state['promotions']-before}.",flush=True)
            print(json.dumps(report,indent=2),flush=True)
        return 1 if error else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, RuntimeError, OSError, KeyError) as error:
        print(f"Policy setup error: {error}", file=sys.stderr)
        sys.exit(1)
