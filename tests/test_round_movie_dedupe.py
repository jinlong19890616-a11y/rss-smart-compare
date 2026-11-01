import unittest
from pathlib import Path
class RoundMovieDedupeTests(unittest.TestCase):
    def test_movie_round_guard_exists(self):
        s=(Path(__file__).parents[1]/'rsssubscribe_smart'/'__init__.py').read_text()
        self.assertIn('submitted_movie_keys = set()',s)
        self.assertIn('RSS_ROUND_MOVIE_DEDUPE',s)
        self.assertIn('submitted_movie_keys.add(movie_key)',s)
    def test_tv_is_not_round_deduped(self):
        s=(Path(__file__).parents[1]/'rsssubscribe_smart'/'__init__.py').read_text()
        self.assertIn('if mediainfo.type == MediaType.MOVIE:',s)
