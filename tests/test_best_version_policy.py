"""Regression tests for "pick the largest release, download it only once".

The production logs showed two 1080p releases of the same episode being
downloaded in one round (995.49M then 4.45G, and 565.31M then 918.29M).
The cause was a resolution-only sort: the smaller release was submitted
first and the guard then treated the larger one as a size upgrade.
"""
import ast
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as N

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'rsssubscribe_smart'))
from smart_guard import Guard, blocks, resolution  # noqa: E402

GB = 1024 ** 3
MB = 1024 ** 2


def load_release_rank():
    """Extract the pure ranking helper without importing the MoviePilot app."""
    tree = ast.parse((ROOT / 'rsssubscribe_smart' / '__init__.py').read_text())
    node = next(n for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name == 'release_rank')
    namespace = {'resolution': resolution}
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<release_rank>', 'exec'),
         namespace)
    return namespace['release_rank']


class FakeServer:
    def __init__(self, torrents, files):
        self._torrents = torrents
        self._files = files

    def get_torrents(self):
        return self._torrents, False

    def get_files(self, _hash):
        return self._files


class FakeHistory:
    def __init__(self, rows):
        self._rows = rows

    def get_by_hashes(self, _hashes):
        return self._rows


class ReleaseRankTests(unittest.TestCase):
    def setUp(self):
        self.rank = load_release_rank()

    def test_same_resolution_largest_first(self):
        releases = [
            {'title': 'Oh My Guard S01E07 1080p WEB-DL', 'size': 995.49 * MB},
            {'title': 'Oh! My Guard S01E07 1080p WEB-DL', 'size': 4.45 * GB},
            {'title': 'Magical Explorer S01E08 1080p WEB-DL', 'size': 565.31 * MB},
            {'title': 'MagicalExplorer S01E08 1080p WEB-DL', 'size': 918.29 * MB},
        ]
        releases.sort(key=self.rank, reverse=True)
        self.assertEqual([r['size'] for r in releases],
                         [4.45 * GB, 995.49 * MB, 918.29 * MB, 565.31 * MB])

    def test_resolution_still_wins_over_raw_size(self):
        releases = [
            {'title': 'Show S01E01 1080p BluRay REMUX', 'size': 20 * GB},
            {'title': 'Show S01E01 2160p WEB-DL', 'size': 3 * GB},
        ]
        releases.sort(key=self.rank, reverse=True)
        self.assertIn('2160p', releases[0]['title'])

    def test_bad_sizes_do_not_break_the_round(self):
        releases = [
            {'title': 'Show S01E01 1080p', 'size': 'unknown'},
            {'title': 'Show S01E01 1080p', 'size': None},
            {'title': 'Show S01E01 1080p', 'size': 2 * GB},
        ]
        releases.sort(key=self.rank, reverse=True)
        self.assertEqual(releases[0]['size'], 2 * GB)

    def test_larger_first_then_smaller_is_blocked(self):
        # Old order: small first, larger seen as an upgrade -> two downloads.
        self.assertFalse(blocks(1080, 1080, 4.45 * GB, 995.49 * MB))
        # New order: large first, smaller is rejected by the quality check.
        self.assertTrue(blocks(1080, 1080, 995.49 * MB, 4.45 * GB))


class VersionCapBehaviourTests(unittest.TestCase):
    def _guard(self, root, media, meta, torrents, files, rows, cap):
        module = N(get_instances=lambda: {'qb': FakeServer(torrents, files)})
        guard = Guard(root, module, FakeHistory(rows), None, max_versions=cap)
        return guard.decide(media, meta, None)

    def test_movie_cap_one_blocks_upgrade_cap_two_allows(self):
        media = N(type=N(value='电影'), tmdb_id=123)
        meta = N(begin_season=None, season_list=[], episode_list=[],
                 org_string='Movie.1080p.WEB-DL', orginal_title='',
                 _rss_resolution=1080, _rss_size=int(3 * GB))
        torrents = [{'hash': 'h1', 'name': 'Movie.1080p.WEB-DL.mkv',
                     'size': int(1 * GB), 'state': 'downloading', 'tags': 'MOVIEPILOT'}]
        rows = {'h1': N(type='电影', tmdbid=123, downloader='qb', seasons='',
                        torrent_name='Movie.1080p.WEB-DL.mkv')}
        with tempfile.TemporaryDirectory() as root:
            reason_one, _ = self._guard(root, media, meta, torrents, [], rows, 1)
            reason_two, _ = self._guard(root, media, meta, torrents, [], rows, 2)
        self.assertTrue(reason_one)
        self.assertIn('版本上限', reason_one)
        self.assertIsNone(reason_two)

    def test_tv_episode_cap_one_blocks_upgrade_cap_two_allows(self):
        media = N(type=N(value='电视剧'), tmdb_id=334517)
        meta = N(begin_season=1, season_list=[1], episode_list=[7],
                 org_string='Oh My Guard S01E07 1080p WEB-DL', orginal_title='',
                 _rss_resolution=1080, _rss_size=int(4.45 * GB),
                 _rss_actual_episodes={7})
        torrents = [{'hash': 'h1', 'name': 'Oh My Guard S01E07 1080p WEB-DL',
                     'size': int(995.49 * MB), 'state': 'downloading',
                     'tags': 'MOVIEPILOT'}]
        files = [{'name': 'Oh My Guard S01E07 1080p WEB-DL.mkv',
                  'priority': 1, 'size': int(995.49 * MB)}]
        rows = {'h1': N(type='电视剧', tmdbid=334517, downloader='qb',
                        seasons='S01',
                        torrent_name='Oh My Guard S01E07 1080p WEB-DL')}
        with tempfile.TemporaryDirectory() as root:
            reason_one, _ = self._guard(root, media, meta, torrents, files, rows, 1)
            reason_two, _ = self._guard(root, media, meta, torrents, files, rows, 2)
        self.assertTrue(reason_one)
        self.assertIn('版本上限', reason_one)
        self.assertIsNone(reason_two)

    def test_cap_is_clamped_to_at_least_one(self):
        with tempfile.TemporaryDirectory() as root:
            guard = Guard(root, N(get_instances=lambda: {}), FakeHistory({}),
                          None, max_versions=0)
            self.assertEqual(guard.max_versions, 1)


class RoundReplayTests(unittest.TestCase):
    """Replay the two production double-download cases through the real Guard."""

    CASES = [
        ('不着边际的你 S01E07', 'Oh My Guard S01E07 1080p WEB-DL',
         'Oh! My Guard S01E07 1080p WEB-DL', 995.49 * MB, 4.45 * GB, 334517, 7),
        ('魔法★探险家 S01E08', 'Magical Explorer S01E08 1080p WEB-DL',
         'MagicalExplorer S01E08 1080p WEB-DL', 565.31 * MB, 918.29 * MB, 335194, 8),
    ]

    def _meta(self, title, size, episode):
        return N(begin_season=1, season_list=[1], episode_list=[episode],
                 org_string=title, orginal_title='', _rss_resolution=1080,
                 _rss_size=int(size), _rss_actual_episodes={episode})

    def _run_round(self, root, releases, cap, sort_best_first, tmdb_id, episode):
        rank = load_release_rank()
        order = sorted(releases, key=rank, reverse=True) if sort_best_first else list(releases)
        submitted = []
        for i, release in enumerate(order):
            media = N(type=N(value='电视剧'), tmdb_id=tmdb_id)
            meta = self._meta(release['title'], release['size'], episode)
            module = N(get_instances=lambda: {'qb': FakeServer([], [])})
            guard = Guard(root, module, FakeHistory({}), None, max_versions=cap)
            reason, _ = guard.decide(media, meta, None)
            if not reason:
                guard.reserve(media, meta, 'hash-%d' % i, [episode])
                submitted.append(release['size'])
        return submitted

    def test_088_publish_order_downloads_both(self):
        """0.8.8: RSS order put the small release first -> two downloads."""
        for label, small_title, large_title, small, large, tmdb_id, ep in self.CASES:
            releases = [{'title': small_title, 'size': small},
                        {'title': large_title, 'size': large}]
            with self.subTest(case=label), tempfile.TemporaryDirectory() as root:
                submitted = self._run_round(root, releases, 2, False, tmdb_id, ep)
                self.assertEqual(len(submitted), 2)
                self.assertEqual(submitted[0], small)

    def test_089_downloads_only_the_largest_once(self):
        for label, small_title, large_title, small, large, tmdb_id, ep in self.CASES:
            releases = [{'title': small_title, 'size': small},
                        {'title': large_title, 'size': large}]
            for cap in (1, 2):
                with self.subTest(case=label, cap=cap), tempfile.TemporaryDirectory() as root:
                    submitted = self._run_round(root, releases, cap, True, tmdb_id, ep)
                    self.assertEqual(len(submitted), 1)
                    self.assertEqual(submitted[0], large)


class WiringTests(unittest.TestCase):
    def test_default_is_one_download_and_round_dedupe_is_present(self):
        s = (ROOT / 'rsssubscribe_smart' / '__init__.py').read_text()
        self.assertIn('_max_versions: int = 1', s)
        self.assertIn('"max_versions": 1', s)
        self.assertIn('max_versions=self._max_versions', s)
        self.assertIn('batch.sort(key=release_rank, reverse=True)', s)
        self.assertIn('submitted_tv_keys = set()', s)
        self.assertIn('RSS_ROUND_TV_DEDUPE', s)
        self.assertIn('submitted_tv_keys.add(tv_key)', s)


if __name__ == '__main__':
    unittest.main(verbosity=2)
