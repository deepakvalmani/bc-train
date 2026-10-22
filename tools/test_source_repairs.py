import pathlib
import tempfile
import unittest
import source_repairs
import train


class SourceRepairTests(unittest.TestCase):
    def test_archived_sources_unchanged_and_repair_is_idempotent(self):
        for name in ('v33', 'v35', 'v36', 'v37', 'v38', 'v40', 'learner'):
            with self.subTest(bot=name), tempfile.TemporaryDirectory() as directory:
                source = train.ROOT / 'bots' / name
                before = train.source_hash(source)
                copy = pathlib.Path(directory)
                train.copy_source(source, copy)
                source_repairs.repair_movement(copy)
                repaired = train.source_hash(copy)
                source_repairs.repair_movement(copy)
                self.assertEqual(repaired, train.source_hash(copy))
                self.assertEqual(before, train.source_hash(source))
                text = (copy / 'src/bot.cpp').read_text()
                self.assertIn('if (blocked_tiles().is_set(choices[i].second)) continue;', text)
                self.assertIn('catch (const cambc::error&)', text)
                self.assertIn('position.x >= 0 && position.y >= 0', text)
                self.assertIn('cambc::round_number() != planning_round || !me.is_alive()', text)

    def test_unknown_source_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            source = pathlib.Path(directory) / 'src'
            source.mkdir()
            (source / 'bot.cpp').write_text('unknown source')
            with self.assertRaisesRegex(ValueError, 'Unknown movement'):
                source_repairs.repair_movement(source.parent)


if __name__ == '__main__':
    unittest.main()
