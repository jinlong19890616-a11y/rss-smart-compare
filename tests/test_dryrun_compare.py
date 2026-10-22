import json
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parents[1] / 'rsssubscribe_smart'))
from dryrun_compare import compare_fixture, parse_episodes

class DryRunTests(unittest.TestCase):
    def test_episode_range(self):
        self.assertEqual(parse_episodes('Show.S02E03-E07.1080p'), (2, {3,4,5,6,7}))
        self.assertEqual(parse_episodes('Show.S01E09'), (1, {9}))
        self.assertEqual(parse_episodes('Show.S01.1080p'), (1, None))
        self.assertIsNone(parse_episodes('Show.2160p'))

    def test_comparison_fixture(self):
        data=json.loads((Path(__file__).parent/'fixtures/basic.json').read_text())
        rows=compare_fixture(data)
        self.assertEqual(rows[0].missing_episodes, [3])
        self.assertEqual(rows[0].smart, '下载全部候选集')
        self.assertEqual(rows[1].missing_episodes, [3,5])
        self.assertEqual(rows[1].smart, '只下载缺失集')
        self.assertEqual(rows[2].missing_episodes, [21,22])
        self.assertEqual(rows[3].smart, '延后人工处理')

if __name__ == '__main__': unittest.main(verbosity=2)
