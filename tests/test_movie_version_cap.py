import unittest
from pathlib import Path
class MovieVersionCapTests(unittest.TestCase):
    def test_guard_has_two_version_cap(self):
        s=(Path(__file__).parents[1]/'rsssubscribe_smart'/'smart_guard.py').read_text()
        self.assertIn('len(movie_versions) >= 2',s)
        self.assertIn('同一电影已有两个版本',s)
