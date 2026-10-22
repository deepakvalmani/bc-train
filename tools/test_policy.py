"""Synthetic decision-policy regressions; no engine or matches required."""
import copy
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import policy_learning as policy
import policy_train
import train


def log():
    x = "1000 200 100 100 0 0 1000 0 0 0 0 0"
    y = "1000 900 500 100 0 0 1000 0 0 0 0 0"
    return ("PT 16 0 walk_camp 1 1000 20 10 0 50000 0\n"
            f"PD 16 0 0 1 1 1000 1000 1000 {x}\n"
            f"PD 16 0 0 2 0 900 900 900 {y}\n"
            "PE 16 16\n"
            "PT 17 0 capturing 1 1000 44 20 0 50000 0\nPE 17 17\n")


class PolicyTests(unittest.TestCase):
    def test_identical_faulted_baseline_reports_the_failing_case(self):
        import contextlib, io, json
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as directory:
            trainer = policy_train.PolicyTrainer.__new__(policy_train.PolicyTrainer)
            trainer.folder = Path(directory)
            trainer.state = dict(incumbent='same', teacher='same', holdouts=['heldout'],
                                 policy_cycles=0, promotions=0)
            trainer.config = dict(require_fault_free=True, promotion_objective='wins',
                                  gem_margin=0.01, min_win_gain=0.01)
            trainer.pool = Mock(return_value=['opponent'])
            trainer.full = Mock(return_value=[dict(map='lanes', side=0, opponent='opponent',
                faults=1, points=1, share=0.6, rate=2, deaths=0)])
            trainer.audit = Mock()
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(
                    ValueError, 'lanes side 0'):
                trainer.qualify_baseline()
            report = json.loads((trainer.folder/'baseline_failure.json').read_text())
            self.assertEqual(report['faults'][0]['map'], 'lanes')
            trainer.audit.assert_not_called()

    def test_progress_reports_learning_without_claiming_a_promotion(self):
        import contextlib,io,json
        trainer=policy_train.PolicyTrainer.__new__(policy_train.PolicyTrainer)
        trainer.state=dict(policy_cycles=0,promotions=0,optimizer_updates=12)
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()) as output:
            trainer.folder=Path(directory)
            trainer.progress('fit_complete','Weights changed; improvement unconfirmed.',changed_coefficients=3)
            data=json.loads((trainer.folder/'learning_status.json').read_text())
            self.assertEqual(data['optimizer_updates'],12)
            self.assertEqual(data['accepted_improvements'],0)
            self.assertEqual(data['changed_coefficients'],3)
            self.assertIn('[FIT_COMPLETE]',output.getvalue())

    def test_one_champions_suspension_does_not_erase_teammates_clean_choices(self):
        text=log()+"PT 16 1 pvp 1 500 0 0 0 50000 1\nPE 15 16 1\n"
        data=policy.parse(text,dict(points=1,faults=0))
        self.assertTrue(data['usable'])
        self.assertFalse(data['audit_passed'])
        self.assertEqual(len(data['decisions']),1)

    def test_economic_collection_requires_complete_extended_records(self):
        data=policy.parse(log(),dict(points=1,faults=0,require_economic_telemetry=True))
        self.assertFalse(data['usable'])
        self.assertGreater(data['diagnostics']['malformed'],0)

    def test_sparse_economic_records_can_keep_clean_decision_windows(self):
        text=log()+'PX 16 0 1 1 20 0 100 100 1000 0 0 0 0\n'
        parsed=policy.parse(text,dict(points=1,faults=0,require_economic_telemetry=True,sparse_economic_telemetry=True))
        self.assertTrue(parsed['usable'])

    def test_parse_groups_choices_and_preserves_sample_scope(self):
        data = policy.parse(log(), dict(points=1, faults=0))
        self.assertTrue(data["usable"])
        self.assertEqual(data["diagnostics"]["turns"], 2)
        self.assertEqual(len(data["decisions"]), 1)
        sample = data["decisions"][0]
        self.assertEqual(sample["selected"], 0)
        self.assertEqual(sample["teacher"], 0)
        self.assertEqual(len(sample["choices"][0]["x"]), 12)

    def test_suspended_malformed_missing_and_faulted_logs_are_not_training_data(self):
        for text, result in ((log().replace("PE 16 16", "PE 16 17"), dict(points=1, faults=0)),
                             (log().replace("50000 0", "50000 1"), dict(points=1, faults=0)),
                             (log().replace("PE 17 17", ""), dict(points=1, faults=0)),
                             (log()+"PD malformed\n", dict(points=1, faults=0)),
                             (log(), dict(points=1, faults=1)), ("", dict(points=1, faults=0))):
            with self.subTest(text=text[-25:], result=result):
                data = policy.parse(text, result)
                self.assertFalse(data["usable"])
                self.assertEqual(data["decisions"], [])

    def test_export_is_bounded_and_collection_modes_are_explicit(self):
        weights = [[0.0]*12 for _ in range(4)]
        with tempfile.TemporaryDirectory() as name:
            bot = Path(name)
            (bot/"src").mkdir()
            text = policy.header(weights)
            (bot/"src/policy_weights.h").write_text(text)
            self.assertEqual(policy.read_header(bot), (weights, True))
            self.assertIn("telemetry = false, audit = false", text)
            self.assertIn("exploration = 0.000000f", text)
        bad = copy.deepcopy(weights)
        bad[0][0] = float("nan")
        with self.assertRaises(ValueError):
            policy.header(bad)
        with self.assertRaises(ValueError):
            policy.header([[1.0]*12 for _ in range(4)])
        with self.assertRaises(ValueError):
            policy.header(weights, exploration=0.1)

    def test_fitting_changes_weights_without_exceeding_export_bounds(self):
        sample = policy.parse(log(), dict(points=1, faults=0))["decisions"][0]
        decisions = [dict(sample, map=name) for name in train.OFFICIAL_MAPS]
        initial = [[0.0]*12 for _ in range(4)]
        original = copy.deepcopy((initial, decisions))
        fitted, report = policy.fit(initial, decisions, 1, time.monotonic()+10)
        self.assertTrue(report["complete"])
        self.assertGreater(report["updates"], 0)
        self.assertNotEqual(fitted, initial)
        self.assertEqual((initial, decisions), original)
        policy.check_weights(fitted)

    def test_deadline_does_not_fabricate_completed_fitting(self):
        sample = policy.parse(log(), dict(points=1, faults=0))["decisions"][0]
        weights = [[0.0]*12 for _ in range(4)]
        _, report = policy.fit(weights, [dict(sample, map="rows")], 1, time.monotonic()-1)
        self.assertFalse(report["complete"])

    def test_instrumented_source_cannot_be_published(self):
        with tempfile.TemporaryDirectory() as name:
            t = policy_train.PolicyTrainer.__new__(policy_train.PolicyTrainer)
            t.checkpoints = Path(name)
            source = t.checkpoints/"candidate/src"
            source.mkdir(parents=True)
            weights = [[0.0]*12 for _ in range(4)]
            for mode in (dict(telemetry=True), dict(audit=True), dict(telemetry=True, exploration=0.08)):
                (source/"policy_weights.h").write_text(policy.header(weights, **mode))
                with self.subTest(mode=mode), patch.object(train.Trainer, "publish") as publish:
                    with self.assertRaisesRegex(ValueError, "instrumented"):
                        t.publish("candidate")
                    publish.assert_not_called()


if __name__ == "__main__":
    unittest.main()
