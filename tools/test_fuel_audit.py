import copy
import unittest
import fuel_audit
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
import policy_train


def case(map_name='lanes',side=0,flags=10,turns=1000):
    return dict(map=map_name,side=side,faults=0,
                diagnostics=dict(turns=turns,audit_ends=turns,malformed=0,fuel_failures=flags))


class FuelAuditTests(unittest.TestCase):
    def test_migration_rejects_unrelated_configuration_changes(self):
        trainer=policy_train.PolicyTrainer.__new__(policy_train.PolicyTrainer)
        old=dict(start='bots/learner',policy=dict(schema=1),jobs_setting=2)
        trainer.config=dict(start='bots/learner',policy=dict(schema=1,fuel_audit_mode='baseline_relative'),jobs_setting=3)
        with tempfile.TemporaryDirectory() as directory:
            trainer.folder=Path(directory)
            (trainer.folder/'state.json').write_text(json.dumps(dict(config=old)))
            with self.assertRaisesRegex(ValueError,'only permits'):
                trainer.load_policy(1,None,True)
            self.assertEqual(json.loads((trainer.folder/'state.json').read_text())['config'],old)

    def test_migration_rejects_source_changes(self):
        trainer=policy_train.PolicyTrainer.__new__(policy_train.PolicyTrainer)
        old=dict(start='bots/learner',policy=dict(schema=1))
        trainer.config=dict(start='bots/learner',policy=dict(schema=1,fuel_audit_mode='baseline_relative'))
        with tempfile.TemporaryDirectory() as directory:
            trainer.folder=Path(directory)
            (trainer.folder/'state.json').write_text(json.dumps(dict(config=old,policy_contract='old')))
            with patch('train.source_hash',return_value='new'),self.assertRaisesRegex(ValueError,'source changed'):
                trainer.load_policy(1,None,True)
    def test_legal_baseline_suspension_is_measured_not_hidden(self):
        passed,rows=fuel_audit.judge([case()])
        self.assertTrue(passed)
        self.assertEqual(rows[0]['fuel_flags'],10)
        self.assertEqual(rows[0]['fuel_flags_per_turn'],0.01)

    def test_every_case_must_not_regress(self):
        baseline=[case(),case(side=1,flags=0)]
        self.assertTrue(fuel_audit.judge([case(flags=5),case(side=1,flags=0)],baseline)[0])
        self.assertFalse(fuel_audit.judge([case(flags=0),case(side=1,flags=1)],baseline)[0])

    def test_normalization_handles_different_match_lengths(self):
        baseline=[case(flags=10,turns=1000)]
        self.assertTrue(fuel_audit.judge([case(flags=20,turns=2000)],baseline)[0])
        self.assertFalse(fuel_audit.judge([case(flags=11,turns=1000)],baseline)[0])

    def test_missing_malformed_or_faulty_records_cannot_qualify(self):
        for patch in (dict(turns=0),dict(audit_ends=999),dict(malformed=1),dict(missing_or_oversized_log=True)):
            broken=case();broken['diagnostics'].update(patch)
            self.assertFalse(fuel_audit.judge([broken])[0])
        broken=case();broken['faults']=1
        self.assertFalse(fuel_audit.judge([broken])[0])
        self.assertFalse(fuel_audit.judge([case()],[broken])[0])

    def test_missing_or_duplicate_comparison_cases_are_rejected(self):
        with self.assertRaises(ValueError):fuel_audit.judge([case()],[case(),case(side=1)])
        with self.assertRaises(ValueError):fuel_audit.judge([case(),case()])
        with self.assertRaises(ValueError):fuel_audit.judge([])


if __name__=='__main__':unittest.main()
