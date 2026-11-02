import unittest
from pathlib import Path
class TvVersionCapTests(unittest.TestCase):
    def test_cap_is_per_episode(self):
        s=(Path(__file__).parents[1]/'rsssubscribe_smart'/'smart_guard.py').read_text()
        self.assertIn('tv_versions = {}', s)
        self.assertIn('本季目标集均已有两个版本', s)
        self.assertIn('for ep in p[\'episodes\']', s)
