"""Regression checks for diagnostics stored inside CLI replay bundles."""
import pathlib
import tempfile
import unittest
import zipfile

import train


class ReplayLogs(unittest.TestCase):
    def test_each_side_reads_its_own_bundled_log(self):
        with tempfile.TemporaryDirectory() as directory:
            work = pathlib.Path(directory)
            with zipfile.ZipFile(work / 'match.repl26a', 'w') as archive:
                archive.writestr('team-a.stdout', '\x00PT ally\n')
                archive.writestr('team-b.stdout', 'bot error: enemy\n')
                archive.writestr('../outside', 'must never be extracted')
            self.assertEqual(train.bot_stdout(work, 0), 'PT ally\n')
            self.assertEqual(train.bot_stdout(work,0).raw_bytes,len('\x00PT ally\n'))
            self.assertEqual(train.bot_stdout(work, 1), 'bot error: enemy\n')
            self.assertEqual(list(work.iterdir()), [work / 'match.repl26a'])

    def test_missing_log_is_distinct_from_empty_log(self):
        with tempfile.TemporaryDirectory() as directory:
            work = pathlib.Path(directory)
            self.assertIsNone(train.bot_stdout(work, 0))
            (work / 'team-a.stdout').write_text('')
            self.assertEqual(train.bot_stdout(work, 0), '')


if __name__ == '__main__':
    unittest.main()
