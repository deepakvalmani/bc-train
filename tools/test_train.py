"""Fast trainer checks using synthetic results; no competition matches."""
import copy
import json
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

import train


CONFIG = json.loads((train.ROOT / "tools" / "train_config.json").read_text())
WIDE = json.loads((train.ROOT / "tools" / "train_all_config.json").read_text())


def row(points=0.5, share=0.5, rate=1, faults=0, map_name="elkring", side=0):
    return dict(points=points, share=share, rate=rate, faults=faults, deaths=0,
                map=map_name, side=side, opponent="anchor")


class TrainerTests(unittest.TestCase):
    def setUp(self):
        train.STOP.clear()

    def test_full_coverage_has_no_hidden_or_unused_search_dimensions(self):
        train.validate_config(WIDE)
        audit = train.coverage(train.ROOT / WIDE["start"], WIDE)
        self.assertEqual(audit["trainable"], 201)
        broken = copy.deepcopy(WIDE)
        del broken["parameters"]["CUSTOM_SHOP"]
        with self.assertRaisesRegex(ValueError, "coverage mismatch"):
            train.coverage(train.ROOT / WIDE["start"], broken)

    def test_mixed_mutations_round_trip_and_keep_legal_drafts(self):
        space = WIDE["parameters"]
        values = train.read_params(train.ROOT / WIDE["start"], space)
        rng = random.Random(91)
        for _ in range(1000):
            values = train.mutate(values, space, rng, dependencies=WIDE["dependencies"])
            self.assertLessEqual(values["BANK_MIN"], values["BANK_MAX"])
            for name, spec in space.items():
                if spec[0] == "permutation":
                    self.assertEqual(sorted(values[name]), list(range(11)))
        with tempfile.TemporaryDirectory() as folder:
            dest = Path(folder) / "bot"
            train.copy_source(train.ROOT / WIDE["start"], dest)
            train.write_params(dest, values)
            self.assertEqual(train.read_params(dest, space), values)
            self.assertNotRegex((dest / "src/params.h").read_text(), r"=\s*(True|False)\b")

    def test_threshold_and_draft_mutations_enable_the_relevant_branch(self):
        space = WIDE["parameters"]
        values = train.read_params(train.ROOT / WIDE["start"], space)
        for name, expected in [("TANK_ITEM_STAT1", {"CUSTOM_SHOP": True, "SMART_SHOP": True}),
                               ("DRAFT_ORDER5", {"MAP_DRAFT": False, "DRAFT_BY_SIZE": True}),
                               ("SHOP_STYLE", {"UNIV_SHOP": True, "CUSTOM_SHOP": False}),
                               ("CHASE_HP", {"CHASE": True})]:
            mutated = train.mutate(values, space, random.Random(1), [name], WIDE["dependencies"])
            for key, value in expected.items():
                self.assertEqual(mutated[key], value)

    def test_competition_limits_cannot_be_broadened_by_config(self):
        for name, spec in [("TANK_ITEM_FAMILY1", ["int", 0, 7]),
                           ("TANK_POWER_STAT", ["int", 0, 3]),
                           ("DRAFT_LARGE_SIZE", ["int", 3, 6]),
                           ("FUEL_RESERVE", ["int", 1, 200000]),
                           ("DRAFT_ORDER", ["permutation", list(range(12))])]:
            config = copy.deepcopy(WIDE)
            config["parameters"][name] = spec
            with self.subTest(name=name), self.assertRaises(ValueError):
                train.validate_config(config)
        config = copy.deepcopy(WIDE)
        config["competition_rules"]["cpp_fuel"] = 200000
        with self.assertRaisesRegex(ValueError, "Competition constants"):
            train.validate_config(config)

    def test_legacy_genes_upgrade_without_reusing_old_fitness(self):
        with tempfile.TemporaryDirectory() as folder:
            old = train.Trainer(Path(folder) / "old", CONFIG, 1, time.monotonic() + 60)
            old.load(1)
            values = train.read_params(old.checkpoints / old.state["incumbent"], CONFIG["parameters"])
            values["BANK_K"] = 12.3
            learned = old.snapshot(old.checkpoints / old.state["incumbent"], values)
            old.state["incumbent"] = learned
            old.state["champions"].append(learned)
            old.save()
            new = train.Trainer(Path(folder) / "new", WIDE, 1, time.monotonic() + 60)
            new.load(2, old.folder)
            genes = train.read_params(new.checkpoints / new.state["incumbent"], WIDE["parameters"])
            self.assertEqual(genes["BANK_K"], 12.3)
            self.assertEqual(genes["SPAWN_HEAL_HP"], 1.0)
            self.assertEqual(new.state["promotions"], 0)
            self.assertEqual(list(new.cache.iterdir()), [])
            self.assertEqual(new.state["imported_genes"]["checkpoint"], learned)
            resumed = train.Trainer(new.folder, WIDE, 1, time.monotonic() + 60)
            resumed.load(3, old.folder)
            self.assertEqual(resumed.state["incumbent"], new.state["incumbent"])

    def test_finalized_promotion_requires_zero_faults(self):
        baseline = [row(faults=1)]
        candidate = [row(points=1, faults=1)]
        self.assertFalse(train.promotion_allowed(candidate, baseline, WIDE))

    def test_competition_stats_reject_draw_and_excess_rounds(self):
        stats = dict(outcome="draw", round=2000, teams=[dict(team=0, submittedGems=0),
                     dict(team=1, submittedGems=0)], botFaults=[0, 0], champions=[])
        with self.assertRaises(ValueError):
            train.parse_stats(stats, 0, train.COMPETITION_RULES)
        stats.update(outcome="teamB", round=2000)
        self.assertEqual(train.parse_stats(stats, 1, train.COMPETITION_RULES)["points"], 1)
        stats["round"] = 2001
        with self.assertRaises(ValueError):
            train.parse_stats(stats, 1, train.COMPETITION_RULES)

    def test_all_parameters_are_scheduled_and_queue_resumes_exactly(self):
        with tempfile.TemporaryDirectory() as folder:
            t = train.Trainer(Path(folder), WIDE, 1, time.monotonic() + 60)
            t.load(51)
            best = t.state["incumbent"]
            visited = [t.propose(best)[1][0] for _ in range(len(WIDE["parameters"]))]
            self.assertEqual(set(visited), set(WIDE["parameters"]))
            self.assertEqual(len(visited), len(set(visited)))
            t.propose(best)
            t.save()
            expected = t.propose(best)
            resumed = train.Trainer(Path(folder), WIDE, 1, time.monotonic() + 60)
            resumed.load(999)
            self.assertEqual(resumed.propose(best), expected)

    def test_mutations_remain_bounded_and_round_trip(self):
        space = CONFIG["parameters"]
        original = train.read_params(train.ROOT / "bots/v38", space)
        rng = random.Random(42)
        values = original
        with tempfile.TemporaryDirectory() as folder:
            dest = Path(folder) / "bot"
            train.copy_source(train.ROOT / "bots/v38", dest)
            for _ in range(300):
                values = train.mutate(values, space, rng)
                train.write_params(dest, values)
                self.assertEqual(train.read_params(dest, space), values)
                self.assertLessEqual(values["BANK_MIN"], values["BANK_MAX"])
            self.assertIn("TRACE        = false", (dest / "src/params.h").read_text())

    def test_wins_dominate_gems_and_faults_block(self):
        self.assertFalse(train.improved(row(points=0.4, share=0.9), row(points=0.5), 0.01))
        self.assertTrue(train.improved(row(points=0.6, share=0.4), row(), 0.01))
        self.assertFalse(train.improved(row(points=1, faults=1), row(), 0.01))
        self.assertTrue(train.improved(row(share=0.52), row(), 0.01))
        self.assertFalse(train.improved(row(rate=10, share=0.49), row(), 0.01))

    def test_per_map_regression_and_missing_pairs_block_promotion(self):
        base = [row(map_name=m) for m in ("a", "b", "c")]
        cand = [row(share=s, map_name=m) for s, m in zip((0.8, 0.8, 0.2), ("a", "b", "c"))]
        self.assertFalse(train.promotion_allowed(cand, base, CONFIG))
        cand[2]["share"] = 0.51
        self.assertTrue(train.promotion_allowed(cand, base, CONFIG))
        with self.assertRaises(ValueError):
            train.promotion_allowed(cand[:-1], base, CONFIG)
        cand.reverse()
        with self.assertRaises(ValueError):
            train.promotion_allowed(cand, base, CONFIG)

    def test_map_specific_gains_can_promote_without_regressing_other_maps(self):
        baseline = [row(map_name=m, side=s) for m in train.OFFICIAL_MAPS for s in (0, 1)]
        candidate = copy.deepcopy(baseline)
        for r in candidate:
            if r["map"] == "rows":
                r.update(points=1, share=0.8)
        self.assertTrue(train.promotion_allowed(candidate, baseline, WIDE))
        candidate[0]["points"] = 0.0
        self.assertFalse(train.promotion_allowed(candidate, baseline, WIDE))

    def test_all_maps_required_in_both_stages_and_checks_cannot_be_weakened(self):
        for field in ("train_maps", "validation_maps"):
            config = copy.deepcopy(WIDE)
            config[field].pop()
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "every manifest map"):
                train.validate_config(config)
        for field, value in [("screen_maps_per_trial", 2), ("strict_per_map", False),
                             ("max_map_gem_regression", 0.01), ("validation_all_opponents", False)]:
            config = copy.deepcopy(WIDE)
            config[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                train.validate_config(config)

    def test_all_map_schedule_is_exhaustive_and_opponents_are_not_sampled(self):
        with tempfile.TemporaryDirectory() as folder:
            t = train.Trainer(Path(folder), WIDE, 1, time.monotonic() + 60)
            t.state = dict(champions=["old", "best"], anchors=["a", "b", "c", "d"])
            self.assertEqual(t.training_maps(["DRAFT_ROWS"]), list(train.OFFICIAL_MAPS))
            self.assertEqual(t.validation_opponents("best"), ["best", "a", "b", "c", "d", "old"])

    def test_promotion_rejects_a_missing_map_side_or_duplicate_result(self):
        baseline = [row(map_name=m, side=s) for m in train.OFFICIAL_MAPS for s in (0, 1)]
        candidate = [dict(r, points=1, share=0.8) for r in baseline]
        with self.assertRaisesRegex(ValueError, "Incomplete evaluation"):
            train.promotion_allowed(candidate[:-1], baseline[:-1], WIDE)
        candidate[-1] = dict(candidate[0])
        with self.assertRaisesRegex(ValueError, "Incomplete evaluation"):
            train.promotion_allowed(candidate, baseline, WIDE)

    def test_aggregate_improvement_cannot_hide_any_map_regression(self):
        baseline = [row(map_name=m, side=s) for m in train.OFFICIAL_MAPS for s in (0, 1)]
        for metric in ("points", "share", "rate"):
            candidate = [dict(r, points=1, share=0.8, rate=2) for r in baseline]
            candidate[0][metric] = 0
            candidate[1][metric] = 0
            with self.subTest(metric=metric):
                self.assertFalse(train.promotion_allowed(candidate, baseline, WIDE))

    def test_parse_outcomes_both_sides_and_draw(self):
        stats = dict(outcome="teamA", round=100, teams=[dict(team=1, submittedGems=400),
                     dict(team=0, submittedGems=1000)], botFaults=[0, 1], champions=[])
        self.assertEqual(train.parse_stats(stats, 0)["points"], 1)
        self.assertEqual(train.parse_stats(stats, 1)["points"], 0)
        self.assertEqual(train.parse_stats(stats, 1)["faults"], 1)
        stats["outcome"] = "draw"
        self.assertEqual(train.parse_stats(stats, 1)["points"], 0.5)
        stats["outcome"] = "unknown"
        with self.assertRaises(ValueError):
            train.parse_stats(stats, 0)

    def test_resume_keeps_pending_trial_rng_and_immutable_sources(self):
        with tempfile.TemporaryDirectory() as folder:
            t = train.Trainer(Path(folder), CONFIG, 1, time.monotonic() + 10)
            t.load(123)
            incumbent = t.state["incumbent"]
            # Existing bot files changing must not alter a pinned training opponent.
            t.state["pending"] = dict(candidate=incumbent, parent=incumbent, maps=["rows"], opponents=[incumbent])
            t.save()
            expected = t.rng.random()
            resumed = train.Trainer(Path(folder), CONFIG, 1, time.monotonic() + 10)
            resumed.load(999)
            self.assertEqual(expected, resumed.rng.random())
            self.assertEqual(resumed.state["pending"], t.state["pending"])
            p = resumed.checkpoints / incumbent / "src/params.h"
            p.write_text(p.read_text() + "\n// edited\n")
            with self.assertRaisesRegex(ValueError, "Checkpoint changed"):
                resumed.load(123)

    def test_cached_games_do_not_launch_engine(self):
        with tempfile.TemporaryDirectory() as folder:
            t = train.Trainer(Path(folder), CONFIG, 1, time.monotonic() - 1)
            train.atomic_json(t.cache / "bot_op_rows_0.json", row())
            with patch.object(train, "command", side_effect=AssertionError("engine launched")):
                self.assertEqual(t.game("bot", "op", "rows", 0), row())

    def test_expired_budget_does_not_launch_process(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(subprocess, "Popen", side_effect=AssertionError("process launched")):
                with self.assertRaises(train.BudgetExpired):
                    train.command(["unused"], time.monotonic() - 1, Path(folder) / "log")

    def test_process_terminated_at_deadline(self):
        with tempfile.TemporaryDirectory() as folder:
            started = time.monotonic()
            with self.assertRaises(train.BudgetExpired):
                train.command([sys.executable, "-c", "import time; time.sleep(30)"],
                              started + 0.25, Path(folder) / "log")
            self.assertLess(time.monotonic() - started, 5)

    def test_incomplete_validation_preserves_bundle_and_pending(self):
        with tempfile.TemporaryDirectory() as folder:
            t = train.Trainer(Path(folder), CONFIG, 1, time.monotonic() + 10)
            t.load(42)
            before = t.state["incumbent"]

            def publish(digest):
                with zipfile.ZipFile(t.checkpoints / digest / "submission.zip", "w") as z:
                    z.writestr("src/bot.cpp", "baseline")

            calls = []

            def evaluate(bot, opponents, maps):
                calls.append(bot)
                if len(calls) == 1:
                    return [row(points=1, share=0.9)]  # screening passes
                raise train.BudgetExpired()  # validation is interrupted

            with patch.object(t, "publish", side_effect=publish), patch.object(t, "evaluate", side_effect=evaluate):
                with self.assertRaises(train.BudgetExpired):
                    t.train()
            self.assertEqual(t.state["incumbent"], before)
            self.assertIsNotNone(t.state["pending"])
            t.save()
            t.ready()
            self.assertEqual(json.loads((t.folder / "ready.json").read_text())["checkpoint"], before)
            resumed = train.Trainer(Path(folder), CONFIG, 1, time.monotonic() + 10)
            resumed.load(5)
            self.assertEqual(resumed.state["pending"], t.state["pending"])

    def test_changed_configuration_cannot_reuse_fitness(self):
        with tempfile.TemporaryDirectory() as folder:
            t = train.Trainer(Path(folder), CONFIG, 1, time.monotonic() + 10)
            t.load(1)
            changed = copy.deepcopy(CONFIG)
            changed["gem_margin"] = 0.02
            with self.assertRaisesRegex(ValueError, "changed"):
                train.Trainer(Path(folder), changed, 1, time.monotonic() + 10).load(1)

    def test_successful_promotion_commits_matching_source_and_bundle(self):
        with tempfile.TemporaryDirectory() as folder:
            t = train.Trainer(Path(folder), CONFIG, 1, time.monotonic() + 10)
            t.load(42)
            before = t.state["incumbent"]

            def publish(digest):
                with zipfile.ZipFile(t.checkpoints / digest / "submission.zip", "w") as z:
                    z.writestr("checkpoint.txt", digest)

            calls = []

            def evaluate(bot, opponents, maps):
                calls.append(bot)
                if len(calls) == 1:
                    return [row(points=1, share=0.9)]
                # Paired schedule identical; candidate wins more often on every map.
                return [row(points=0.5 if bot == before else 1, map_name=m) for m in maps]

            original_ready = t.ready

            def ready():
                original_ready()
                if t.state["promotions"]:
                    train.STOP.set()

            with patch.object(t, "publish", side_effect=publish), patch.object(t, "evaluate", side_effect=evaluate), patch.object(t, "ready", side_effect=ready):
                t.train()
            self.assertNotEqual(t.state["incumbent"], before)
            self.assertNotIn("pending", t.state)
            saved = json.loads((t.folder / "state.json").read_text())
            self.assertEqual(saved["incumbent"], t.state["incumbent"])
            with zipfile.ZipFile(t.folder / "ready.zip") as z:
                self.assertEqual(z.read("checkpoint.txt").decode(), saved["incumbent"])


if __name__ == "__main__":
    unittest.main()
