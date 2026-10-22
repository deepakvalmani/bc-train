import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import package_v42
import train


class QualificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'bot'
        (self.source / 'src').mkdir(parents=True)
        (self.source / 'src/champion_maps_config.h').write_text(
            'CHAMPION_MAPS_TRACE=false; CHAMPION_MAPS_SINGLE_GROUP=-1; '
            'CHAMPION_MAPS_LAB_ACTOR=-1; CHAMPION_MAPS_LAB_COMPANION=-1;')
        (self.source / 'src/params.h').write_text('TRACE=false;')
        (self.source / 'src/policy_weights.h').write_text(
            'enabled=false; telemetry=false; audit=false; exploration=0.000000f;')
        config = json.loads((train.ROOT / 'tools/train_handbook_config.json').read_text())
        self.maps = sorted(set(config['train_maps'] + config['validation_maps']))
        digest = train.source_hash(self.source)
        self.report = dict(source=digest, opponents={'a': {}, 'b': {}},
                           fault_free=True, opponents_fault_free=True,
                           rows=[dict(opponent=op, map=m, side=side, faults=0, enemy_faults=0)
                                 for op in ('a', 'b') for m in self.maps for side in (0, 1)])
        self.report['games'] = len(self.report['rows'])
        (self.root / 'pin.json').write_text(json.dumps(
            dict(runtime='pinned', sources={'candidate': digest}, maps=self.maps)))
        self.report_path = self.root / 'report.json'
        self.save()

    def save(self):
        self.report_path.write_text(json.dumps(self.report))

    def qualify(self):
        with patch.object(package_v42, 'runtime_signature', return_value='pinned'):
            return package_v42.qualification(self.source, self.report_path)

    def test_complete_exact_source_qualifies(self):
        self.assertEqual(self.qualify()[2], train.source_hash(self.source))

    def test_partial_schedule_rejected(self):
        self.report['rows'].pop()
        self.save()
        with self.assertRaisesRegex(ValueError, 'Incomplete'):
            self.qualify()

    def test_source_changed_after_games_rejected(self):
        (self.source / 'src/params.h').write_text('TRACE=true;')
        with self.assertRaisesRegex(ValueError, 'source does not match'):
            self.qualify()

    def test_opponent_fault_cannot_qualify(self):
        self.report['rows'][0]['enemy_faults'] = 1
        self.save()
        with self.assertRaisesRegex(ValueError, 'Faulted'):
            self.qualify()


if __name__ == '__main__':
    unittest.main()
