from pathlib import Path
import tempfile
import unittest
import compact_telemetry
import telemetry_actions
import policy_learning


class CompactTelemetryTests(unittest.TestCase):
    def test_codes_are_unique_and_round_trip(self):
        for action in telemetry_actions.NAMES:
            self.assertEqual(telemetry_actions.decode('@'+str(telemetry_actions.code(action))),action)
        self.assertEqual(telemetry_actions.decode('walk_camp'),'walk_camp')
        with self.assertRaises(ValueError):telemetry_actions.decode('@9999999')

    def test_patch_is_idempotent_and_only_copies_are_modified(self):
        source=Path(__file__).resolve().parent.parent/'bots/learner/src/policy.h'
        before=source.read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'policy.h';path.write_bytes(before)
            compact_telemetry.apply(path)
            first=path.read_bytes();compact_telemetry.apply(path)
            self.assertEqual(first,path.read_bytes())
            self.assertIn(b'rows < 128',first)
            self.assertIn(b'log.text(" @")',first)
        self.assertEqual(before,source.read_bytes())

    def test_compact_turn_is_parsed_as_original_action(self):
        value=telemetry_actions.code('capturing')
        parsed=policy_learning.parse(f'PT 16 0 @{value} 1 1000 20 0 0 50000 0\nPE 16 16 0\n',dict(points=1,faults=0))
        self.assertTrue(parsed['audit_passed'])
        self.assertEqual(parsed['diagnostics']['capture_turns'],1)


if __name__=='__main__':unittest.main()
