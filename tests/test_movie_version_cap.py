import unittest
from pathlib import Path
class MovieVersionCapTests(unittest.TestCase):
    def test_guard_has_configurable_version_cap(self):
        s=(Path(__file__).parents[1]/'rsssubscribe_smart'/'smart_guard.py').read_text()
        self.assertIn('max_versions=2',s)
        self.assertIn('self.max_versions = max(1, int(max_versions))',s)
        self.assertIn('len(movie_versions) >= cap',s)
        self.assertIn('达到版本上限',s)
