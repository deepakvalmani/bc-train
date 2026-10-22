"""Synthetic adaptive-search regressions; no engine, builds, or matches required."""
import copy
import math
from pathlib import Path
import unittest
from unittest.mock import patch

import learning
import search
import train


MAPS = ("collision", "corners", "elkring", "expanse", "interlock",
        "lanes", "monolith", "packs", "rows")
OPPONENTS = tuple("opponent-" + str(i) for i in range(6))


def config(maps=MAPS):
    return dict(validation_maps=list(maps), all_maps_required=True,
                promotion_objective="wins", min_win_gain=0.03,
                max_map_win_regression=0.2, max_map_gem_regression=0.08,
                strict_per_map=False, require_fault_free=True)


def schedule(maps=MAPS, opponents=OPPONENTS):
    return [dict(opponent=opponent, map=name, side=side,
                 points=float(side), share=0.5, rate=1.0, faults=0, deaths=0)
            for opponent in opponents for name in maps for side in (0, 1)]


class ResultRankingTests(unittest.TestCase):
    def test_complete_small_gain_is_search_lead_below_deployment_threshold(self):
        baseline = schedule()
        candidate = copy.deepcopy(baseline)
        # Two extra wins over the same 108 cases: useful for refinement even
        # though the existing three-percentage-point promotion gate rejects it.
        candidate[0].update(points=1.0, share=0.55, rate=1.05)
        candidate[2].update(points=1.0, share=0.55, rate=1.05)
        original = copy.deepcopy((candidate, baseline))
        result = search.rank_result(candidate, baseline, config(), complete=True)
        self.assertTrue(result["complete"])
        self.assertTrue(result["safe"])
        self.assertTrue(result["useful"])
        self.assertAlmostEqual(result["win_gain"], 2 / 108)
        self.assertFalse(train.promotion_allowed(candidate, baseline, config()))
        small_step_policy = config()
        small_step_policy["min_win_gain"] = 0.01
        self.assertTrue(train.promotion_allowed(candidate, baseline, small_step_policy))
        self.assertEqual({k: v for k, v in small_step_policy.items() if k != "min_win_gain"},
                         {k: v for k, v in config().items() if k != "min_win_gain"})
        self.assertEqual((candidate, baseline), original)

    def test_positive_partial_result_is_never_an_eligible_lead(self):
        baseline = schedule()[:12]
        candidate = copy.deepcopy(baseline)
        for row in candidate:
            row.update(points=1.0, share=0.7, rate=2.0)
        result = search.rank_result(candidate, baseline, config(), complete=False)
        self.assertGreater(result["win_gain"], 0)
        self.assertFalse(result["complete"])
        self.assertFalse(result["safe"])
        self.assertFalse(result["useful"])

    def test_fault_and_map_regressions_cannot_become_leads(self):
        baseline = schedule()
        for failure in ("fault", "map_wins", "map_gems", "strict_speed"):
            candidate = copy.deepcopy(baseline)
            settings = config()
            # An overall gain must not hide a safety failure on another map.
            for row in candidate:
                if row["map"] != "collision":
                    row["points"] = 1.0
            if failure == "fault":
                candidate[-1]["faults"] = 1
            elif failure == "map_wins":
                for row in candidate:
                    if row["map"] == "collision":
                        row["points"] = 0.0
            elif failure == "map_gems":
                for row in candidate:
                    if row["map"] == "collision":
                        row["share"] = 0.4
            else:
                settings["strict_per_map"] = True
                candidate[0]["rate"] = 0.5
            with self.subTest(failure=failure):
                result = search.rank_result(candidate, baseline, settings, complete=True)
                self.assertGreater(result["win_gain"], 0)
                self.assertFalse(result["safe"])
                self.assertFalse(result["useful"])

    def test_complete_requires_every_map_both_sides_and_exact_pairing(self):
        baseline = schedule()
        variants = {
            "missing_side": (baseline[:-1], baseline[:-1]),
            "missing_map": ([r for r in baseline if r["map"] != "rows"],
                            [r for r in baseline if r["map"] != "rows"]),
            "mismatched_order": (list(reversed(baseline)), baseline),
            "duplicate_case": (baseline + baseline[:1], baseline + baseline[:1]),
        }
        for failure, (candidate, paired) in variants.items():
            with self.subTest(failure=failure), self.assertRaises(ValueError):
                search.rank_result(candidate, paired, config(), complete=True)

    def test_nonfinite_metrics_are_rejected(self):
        baseline = schedule()
        for key in ("points", "share", "rate", "faults"):
            candidate = copy.deepcopy(baseline)
            candidate[0][key] = math.nan
            with self.subTest(metric=key), self.assertRaises(ValueError):
                search.rank_result(candidate, baseline, config(), complete=True)


class PartialFeedbackTests(unittest.TestCase):
    def test_twelve_of_108_cases_have_less_influence_than_full_validation(self):
        baseline = schedule()
        candidate = copy.deepcopy(baseline)
        for row in candidate:
            row["points"] = 1.0
        partial, unscaled_partial, full = {}, {}, {}
        old, new = {"threshold": 0.5}, {"threshold": 0.6}
        report = learning.observe(partial, "parent", "candidate", old, new,
                                  candidate[:12], baseline[:12], "validation_partial",
                                  coverage=12 / 108)
        learning.observe(unscaled_partial, "parent", "candidate", old, new,
                         candidate[:12], baseline[:12], "validation_partial", coverage=1.0)
        learning.observe(full, "parent", "candidate", old, new,
                         candidate, baseline, "validation", coverage=1.0)
        self.assertEqual(report["cases"], 12)
        self.assertAlmostEqual(report["coverage"], 12 / 108)
        self.assertEqual(partial["observations"], 1)
        partial_effect = partial["parameters"]["threshold"]["effect"]
        self.assertGreater(partial_effect, 0)
        self.assertLess(partial_effect,
                        unscaled_partial["parameters"]["threshold"]["effect"])
        self.assertLess(partial_effect, full["parameters"]["threshold"]["effect"])
        self.assertLess(partial["candidate_scores"]["candidate"]["score"],
                        full["candidate_scores"]["candidate"]["score"])
        # Cached replay of the same comparison must not add a second vote.
        saved = copy.deepcopy(partial)
        self.assertIsNone(learning.observe(
            partial, "parent", "candidate", old, new, candidate[:12], baseline[:12],
            "validation_partial", coverage=12 / 108))
        self.assertEqual(partial, saved)


class LocalProposalTests(unittest.TestCase):
    def test_refinements_stay_legal_unique_and_preserve_donor_branch(self):
        space = {"shield": ["float", 0.0, 1.0], "radius": ["int", 0, 20],
                 "enabled": ["bool"], "draft": ["permutation", [0, 1, 2]]}
        base = dict(shield=0.9, radius=10, enabled=False, draft=[0, 1, 2])
        donor = dict(shield=0.9885, radius=19, enabled=True, draft=[1, 0, 2])
        original = copy.deepcopy((base, donor, space))
        proposals = search.local_candidates(base, donor, space)
        self.assertTrue(proposals)
        self.assertLessEqual(len(proposals), 16)
        identities = {search.profile_key(values) for values, _ in proposals}
        self.assertEqual(len(identities), len(proposals))
        self.assertNotIn(search.profile_key(base), identities)
        self.assertNotIn(search.profile_key(donor), identities)
        for values, names in proposals:
            self.assertGreaterEqual(values["shield"], 0.0)
            self.assertLessEqual(values["shield"], 1.0)
            self.assertIsInstance(values["radius"], int)
            self.assertGreaterEqual(values["radius"], 0)
            self.assertLessEqual(values["radius"], 20)
            self.assertTrue(values["enabled"])
            self.assertEqual(values["draft"], donor["draft"])
            self.assertEqual(names, sorted(n for n in base if values[n] != base[n]))
        self.assertEqual((base, donor, space), original)
        # A consumer changing a queued profile must not alter its donor or
        # another queued profile through aliased draft lists.
        proposals[0][0]["draft"].reverse()
        self.assertEqual(donor, original[1])
        if len(proposals) > 1:
            self.assertEqual(proposals[1][0]["draft"], donor["draft"])

    def test_refinements_repair_banking_order_inside_bounds(self):
        space = {"BANK_MIN": ["int", 0, 20], "BANK_MAX": ["int", 0, 20]}
        base = dict(BANK_MIN=10, BANK_MAX=15)
        donor = dict(BANK_MIN=14, BANK_MAX=15)
        proposals = search.local_candidates(base, donor, space)
        self.assertTrue(proposals)
        for values, _ in proposals:
            self.assertLessEqual(values["BANK_MIN"], values["BANK_MAX"])
            self.assertTrue(all(0 <= v <= 20 for v in values.values()))

    def test_disjoint_donor_changes_combine_without_input_mutation(self):
        space = {"x": ["int", 0, 10], "y": ["int", 0, 10],
                 "draft": ["permutation", [0, 1, 2]]}
        base = dict(x=1, y=1, draft=[0, 1, 2])
        donors = [dict(x=2, y=1, draft=[0, 1, 2]),
                  dict(x=1, y=3, draft=[0, 1, 2])]
        original = copy.deepcopy((base, donors, space))
        proposals = search.combine_candidates(base, donors, space)
        self.assertEqual(proposals, [(dict(x=2, y=3, draft=[0, 1, 2]), ["x", "y"])])
        self.assertEqual((base, donors, space), original)
        proposals[0][0]["draft"].reverse()
        self.assertEqual((base, donors, space), original)

    def test_conflicting_donors_and_incompatible_banking_are_omitted(self):
        space = {"x": ["int", 0, 10], "y": ["int", 0, 10]}
        base = dict(x=1, y=1)
        self.assertEqual(search.combine_candidates(
            base, [dict(x=2, y=1), dict(x=3, y=2)], space), [])
        banking = {"BANK_MIN": ["int", 0, 20], "BANK_MAX": ["int", 0, 20]}
        self.assertEqual(search.combine_candidates(
            dict(BANK_MIN=2, BANK_MAX=15),
            [dict(BANK_MIN=12, BANK_MAX=15), dict(BANK_MIN=2, BANK_MAX=5)],
            banking), [])


class PromotionContinuationTests(unittest.TestCase):
    def test_rebases_queued_changes_without_reusing_old_scores(self):
        trainer = train.Trainer.__new__(train.Trainer)
        trainer.config = dict(parameters={"shield": ["float", 0.0, 1.0],
                                          "radius": ["int", 0, 10]})
        trainer.checkpoints = Path("unused-checkpoints")
        trainer.validation_opponents = lambda best: ["anchor", best]
        trainer.state = dict(incumbent="new", champions=["old", "new"],
                             adaptive_search=dict(parent="old", context="old-context",
                                                  frontier=[dict(patch={"radius": 6}, origin="old")],
                                                  leaders=[dict(candidate="new", win_gain=0.02)]))
        genes = {"old": dict(shield=0.9, radius=5), "new": dict(shield=0.9885, radius=5)}
        with patch.object(train, "read_params", side_effect=lambda path, space: copy.deepcopy(genes[path.name])):
            trainer.continue_refinements("old", "new")
            current = trainer.state["adaptive_search"]
            self.assertEqual(current["parent"], "new")
            self.assertEqual(current["seeded_from"], "old")
            self.assertEqual(current["leaders"], [])
            self.assertEqual(current["results"], {})
            self.assertIn({"radius": 6}, [item["patch"] for item in current["frontier"]])
            self.assertTrue(any("shield" in item["patch"] for item in current["frontier"]))
            before = copy.deepcopy(current)
            trainer.continue_refinements("old", "new")
            self.assertEqual(trainer.state["adaptive_search"], before)

    def test_recovers_refinements_once_in_a_previously_promoted_run(self):
        trainer = train.Trainer.__new__(train.Trainer)
        trainer.config = dict(parameters={"shield": ["float", 0.0, 1.0]})
        trainer.checkpoints = Path("unused-checkpoints")
        trainer.validation_opponents = lambda best: ["anchor", best]
        trainer.state = dict(incumbent="new", champions=["old", "new"])
        current = trainer.search_state("new")
        current["bootstrapped"] = True
        current["tried"][search.profile_key(dict(shield=1.0))] = True
        genes = {"old": dict(shield=0.9), "new": dict(shield=0.9885)}
        with patch.object(train, "read_params", side_effect=lambda path, space: copy.deepcopy(genes[path.name])):
            trainer.continue_refinements("old", "new")
            queue = current["frontier"]
            self.assertTrue(queue)
            self.assertTrue(all(item["patch"]["shield"] not in (0.9885, 1.0) for item in queue))
            self.assertTrue(current["bootstrapped"])
            before = copy.deepcopy(current)
            trainer.continue_refinements("old", "new")
            self.assertEqual(current, before)


class FastValidationTests(unittest.TestCase):
    def trainer_with_results(self, candidate, baseline):
        trainer = train.Trainer.__new__(train.Trainer)
        trainer.config = config(("collision", "corners", "rows"))
        calls = []

        def evaluate(digest, opponents, maps):
            self.assertEqual(digest, "candidate")
            self.assertEqual(opponents, ["anchor", "self"])
            calls.extend(maps)
            # Return valid cases in an order different from the baseline.
            return [copy.deepcopy(r) for r in reversed(candidate) if r["map"] in maps]

        trainer.evaluate = evaluate
        return trainer, calls

    def test_complete_unchanged_result_reaches_full_gate_and_restores_order(self):
        maps, opponents = ("collision", "corners", "rows"), ("anchor", "self")
        baseline = schedule(maps, opponents)
        candidate = copy.deepcopy(baseline)
        trainer, calls = self.trainer_with_results(candidate, baseline)
        rows, paired, reason = trainer.fast_validation(
            "candidate", list(opponents), ["rows", "corners", "collision"], baseline)
        self.assertIsNone(reason)
        self.assertEqual(calls, ["rows", "corners", "collision"])
        self.assertEqual(rows, candidate)
        self.assertEqual(paired, baseline)
        self.assertFalse(train.promotion_allowed(rows, paired, trainer.config))

    def test_full_schedule_map_failure_is_a_complete_result(self):
        maps, opponents = ("collision", "corners", "rows"), ("anchor", "self")
        baseline = schedule(maps, opponents)
        candidate = copy.deepcopy(baseline)
        for row in candidate:
            if row["map"] == "rows":
                row["points"] = 0.0
        trainer, calls = self.trainer_with_results(candidate, baseline)
        rows, paired, reason = trainer.fast_validation(
            "candidate", list(opponents), list(maps), baseline)
        self.assertIsNone(reason)
        self.assertEqual(calls, list(maps))
        self.assertEqual(rows, candidate)
        self.assertEqual(paired, baseline)
        result = search.rank_result(rows, paired, trainer.config, complete=True)
        self.assertFalse(result["safe"])
        self.assertFalse(train.promotion_allowed(rows, paired, trainer.config))

    def test_map_failure_before_completion_stops_with_exact_paired_subset(self):
        maps, opponents = ("collision", "corners", "rows"), ("anchor", "self")
        baseline = schedule(maps, opponents)
        candidate = copy.deepcopy(baseline)
        for row in candidate:
            if row["map"] == "rows":
                row["points"] = 0.0
        trainer, calls = self.trainer_with_results(candidate, baseline)
        rows, paired, reason = trainer.fast_validation(
            "candidate", list(opponents), ["rows", "corners", "collision"], baseline)
        self.assertEqual(calls, ["rows"])
        self.assertIn("rows win regression", reason)
        self.assertEqual(len(rows), 4)
        self.assertEqual([(r["opponent"], r["map"], r["side"]) for r in rows],
                         [(r["opponent"], r["map"], r["side"]) for r in paired])
        result = search.rank_result(rows, paired, trainer.config, complete=False)
        self.assertFalse(result["useful"])


if __name__ == "__main__":
    unittest.main()
