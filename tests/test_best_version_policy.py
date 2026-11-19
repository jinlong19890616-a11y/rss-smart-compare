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

    def test_zero_cap_means_unlimited(self):
        with tempfile.TemporaryDirectory() as root:
            guard = Guard(root, N(get_instances=lambda: {}), FakeHistory({}),
                          None, max_versions=0)
            self.assertEqual(guard.max_versions, 0)


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
    def test_default_is_unlimited_and_round_dedupe_is_present(self):
        s = (ROOT / 'rsssubscribe_smart' / '__init__.py').read_text()
        self.assertIn('_max_versions: int = 0', s)
        self.assertIn('"max_versions": 0', s)
        self.assertIn('max_versions=self._max_versions', s)
        self.assertIn('batch.sort(key=release_rank, reverse=True)', s)
        self.assertIn('submitted_tv_episodes = {}', s)
        self.assertIn('RSS_ROUND_TV_DEDUPE', s)
        self.assertIn('submitted_tv_episodes.setdefault(tv_key, set()).update(download_episodes)', s)


class UnlimitedUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.media = N(type=N(value='电视剧'), tmdb_id=123)
        self.meta = self.make_meta(100)
        self.tasks, self.files, self.rows, self.transfers = [], {}, {}, []
        server = N(get_torrents=lambda: (self.tasks, False),
                   get_files=lambda h: self.files[h])
        self.guard = Guard(self.root, N(get_instances=lambda: {'qb': server}),
                           N(get_by_hashes=lambda hs: self.rows), None,
                           transferred=lambda ident, season: self.transfers,
                           max_versions=0)

    def make_meta(self, size, quality=1080, episodes=(1,)):
        mark = f'S01E{episodes[0]:02}' if len(episodes) == 1 else 'S01.Complete'
        return N(begin_season=1, season_list=[1], episode_list=list(episodes),
                 org_string=f'Show.{mark}.{quality}p', _rss_resolution=quality,
                 _rss_size=size, _rss_actual_episodes=set(episodes))

    def add_live(self, size, quality=1080, ep=1):
        h = f'h{len(self.tasks)}'
        self.tasks.append({'hash': h, 'name': f'Show.{quality}p', 'size': size,
                           'state': 'downloading'})
        self.files[h] = [{'name': f'Show.S01E{ep:02}.{quality}p.mkv',
                          'size': size, 'priority': 1}]
        self.rows[h] = N(type=self.media.type.value, tmdbid=123,
                         downloader='qb', seasons='S01')

    def add_transfer(self, size=100, quality=1080, ep=1, local=True):
        p = self.root / f'{len(self.transfers)}.Show.S01E{ep:02}.{quality}p.mkv'
        if local:
            p.write_bytes(b'x' * size)
        self.transfers.append(N(dest=str(p)))
        return p

    def test_tv_four_successive_live_upgrades_without_cap(self):
        for size in (100, 125, 157, 197, 247):
            meta = self.make_meta(size)
            self.assertEqual(self.guard.decide(self.media, meta, None), (None, None))
            self.add_live(size)
        self.assertEqual(len(self.tasks), 5)

    def test_movie_four_successive_live_upgrades_without_cap(self):
        self.media.type.value = '电影'
        self.test_tv_four_successive_live_upgrades_without_cap()

    def test_tv_four_successive_pending_upgrades_without_cap(self):
        for size in (100, 125, 157, 197, 247):
            meta = self.make_meta(size)
            self.assertEqual(self.guard.decide(self.media, meta, None), (None, None))
            self.guard.reserve(self.media, meta, str(size), {1})

    def test_movie_four_successive_pending_upgrades_without_cap(self):
        self.media.type.value = '电影'
        self.test_tv_four_successive_pending_upgrades_without_cap()

    def test_tv_four_successive_transferred_upgrades_with_library(self):
        self.add_transfer()
        for size in (125, 157, 197, 247):
            meta = self.make_meta(size)
            self.assertEqual(self.guard.decide(self.media, meta, N(seasons={1: [1]})),
                             (None, None))
            self.add_transfer(size)

    def test_movie_four_successive_transferred_upgrades_with_library(self):
        self.media.type.value = '电影'
        self.test_tv_four_successive_transferred_upgrades_with_library()

    def test_equal_small_growth_and_unknown_do_not_upgrade(self):
        self.add_live(100)
        for quality, size in ((1080, 100), (1080, 124), (1080, 99),
                              (1080, 0), (0, 200)):
            with self.subTest(quality=quality, size=size):
                self.assertTrue(self.guard.decide(self.media, self.make_meta(size, quality), None)[0])
        self.assertEqual(self.guard.decide(self.media, self.make_meta(125), None), (None, None))

    def test_unknown_existing_resolution_or_size_blocks(self):
        for quality, size in ((0, 100), (1080, 0)):
            self.tasks.clear()
            self.add_live(size, quality)
            self.assertTrue(self.guard.decide(self.media, self.make_meta(200), None)[0])

    def test_better_live_version_blocks_regardless_of_order(self):
        for sizes in ((100, 200), (200, 100)):
            self.tasks.clear()
            for size in sizes:
                self.add_live(size)
            self.assertTrue(self.guard.decide(self.media, self.make_meta(150), None)[0])

    def test_movie_equal_small_growth_and_unknown_do_not_upgrade(self):
        self.media.type.value = '电影'
        self.test_equal_small_growth_and_unknown_do_not_upgrade()

    def test_movie_better_live_version_blocks_regardless_of_order(self):
        self.media.type.value = '电影'
        self.test_better_live_version_blocks_regardless_of_order()

    def test_legacy_caps_apply_across_live_and_pending_versions(self):
        for kind in ('电视剧', '电影'):
            with self.subTest(kind=kind):
                self.media.type.value = kind
                self.tasks.clear()
                self.guard.pending.write_text('[]')
                self.add_live(80)
                self.guard.reserve(self.media, self.make_meta(100), 'pending', {1})
                self.guard.max_versions = 2
                self.assertTrue(self.guard.decide(self.media, self.make_meta(200), None)[0])
                self.guard.max_versions = 0
                self.assertEqual(self.guard.decide(self.media, self.make_meta(200), None), (None, None))

    def test_transferred_pack_total_does_not_reopen_library_episodes(self):
        self.add_transfer()
        self.assertEqual(self.guard.decide(self.media, self.make_meta(1000, episodes=(1, 2)),
                                           N(seasons={1: [1]})), (None, {2}))

    def test_other_episode_file_cannot_reopen_library_coverage(self):
        self.add_transfer(ep=2)
        self.assertTrue(self.guard.decide(self.media, self.make_meta(200),
                                          N(seasons={1: [1]}))[0])

    def test_better_pending_version_blocks_regardless_of_order(self):
        for sizes in ((100, 200), (200, 100)):
            if self.guard.pending.exists():
                self.guard.pending.write_text('[]')
            for size in sizes:
                self.guard.reserve(self.media, self.make_meta(size), str(size), {1})
            self.assertTrue(self.guard.decide(self.media, self.make_meta(150), None)[0])

    def test_transferred_tv_unknown_or_missing_keeps_library_coverage(self):
        for quality, size, local in ((0, 100, True), (1080, 100, False)):
            with self.subTest(quality=quality, local=local):
                self.transfers.clear()
                self.add_transfer(size, quality, local=local)
                self.assertTrue(self.guard.decide(self.media, self.make_meta(200),
                                                  N(seasons={1: [1]}))[0])

    def test_transferred_tv_unknown_candidate_size_keeps_coverage(self):
        self.add_transfer()
        self.assertTrue(self.guard.decide(self.media, self.make_meta(0, 2160),
                                          N(seasons={1: [1]}))[0])

    def test_transferred_tv_1080_to_2160_requires_comparable_sizes(self):
        self.add_transfer()
        self.assertTrue(self.guard.decide(self.media, self.make_meta(99, 2160),
                                          N(seasons={1: [1]}))[0])
        self.assertEqual(self.guard.decide(self.media, self.make_meta(100, 2160),
                                           N(seasons={1: [1]})), (None, None))

    def test_better_transferred_tv_version_blocks_in_both_orders(self):
        for sizes in ((100, 200), (200, 100)):
            self.transfers.clear()
            for size in sizes:
                self.add_transfer(size)
            self.assertTrue(self.guard.decide(self.media, self.make_meta(150),
                                              N(seasons={1: [1]}))[0])

    def test_missing_transfer_still_blocks_after_verified_low(self):
        self.add_transfer()
        self.add_transfer(local=False)
        self.assertTrue(self.guard.decide(self.media, self.make_meta(200),
                                          N(seasons={1: [1]}))[0])

    def test_library_without_file_evidence_stays_covered(self):
        self.assertTrue(self.guard.decide(self.media, self.make_meta(200),
                                          N(seasons={1: [1]}))[0])

    def test_pure_download_history_does_not_supply_permanent_coverage(self):
        self.rows['removed-task'] = N(type='电视剧', tmdbid=123, seasons='S01',
                                     downloader='qb', torrent_name='Show.S01E01.2160p')
        self.assertEqual(self.guard.decide(self.media, self.make_meta(100), None), (None, None))

    def test_legacy_caps_still_limit_transferred_tv_upgrades(self):
        for cap in (1, 2):
            self.transfers.clear()
            for size in (80, 100)[:cap]:
                self.add_transfer(size)
            self.guard.max_versions = cap
            self.assertIn('版本上限', self.guard.decide(self.media, self.make_meta(200),
                                                       N(seasons={1: [1]}))[0])

    def test_legacy_movie_caps_count_quality_allowed_pending_versions(self):
        self.media.type.value = '电影'
        for cap in (1, 2):
            self.guard.pending.write_text('[]')
            self.guard.max_versions = cap
            for size in (80, 100)[:cap]:
                self.guard.reserve(self.media, self.make_meta(size), str(size))
            self.assertIn('版本上限', self.guard.decide(self.media, self.make_meta(200), None)[0])


def load_plugin_class(namespace):
    # 提取原样生产类，不依赖 MoviePilot 安装；check/Guard 不做替代实现。
    import __future__
    tree = ast.parse((ROOT / 'rsssubscribe_smart' / '__init__.py').read_text())
    from threading import Lock
    namespace['Lock'] = Lock
    nodes = [node for node in tree.body
             if (isinstance(node, ast.ClassDef) and node.name == 'RssSubscribeSmart')
             or (isinstance(node, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == 'history_lock'
                         for t in node.targets))]
    namespace['_PluginBase'] = object
    exec(compile(ast.Module(body=nodes, type_ignores=[]), '<production_plugin>', 'exec',
                 flags=__future__.annotations.compiler_flag), namespace)
    return namespace['RssSubscribeSmart']


class PluginFlowTests(unittest.TestCase):
    def setUp(self):
        import datetime
        import re
        from copy import copy
        from unittest.mock import Mock
        from site_identity import match_site, snapshot_sites
        from recognition_review import RecognitionReviewer, apply_review
        from preflight import (DeferCache, actual_episodes, disc_format_reason,
                               hash_exists, looks_like_torrent, torrent_payload_diagnostic)
        from smart_guard import exclusive, rule_matches
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.releases, self.submissions, self.tasks, self.logs = [], [], [], []
        self.torrent_infos, self.submitted_infos = [], []
        self.warnings = []
        self.site_list = Mock(return_value=[])
        self.fail_titles, self.accepted_falsy = set(), set()
        from enum import Enum
        self.kind = Enum('MediaType', {'TV': '电视剧', 'MOVIE': '电影'})
        self.media = N(type=self.kind.TV, tmdb_id=123, year='2026', title='Show',
                       title_year='Show (2026)', original_title='Show', overview='',
                       get_poster_image=lambda: '')
        self.library = None
        self.transfers = []
        self.saved = {}

        class Meta:
            def __init__(inner, title, subtitle=''):
                inner.org_string = title
                inner.name, inner.year, inner.type = 'Show', '2026', None
                match = re.search(r'S(\d+)(?:E(\d+)(?:-E?(\d+))?)?', title)
                inner.begin_season = int(match[1]) if match else None
                inner.begin_episode = int(match[2]) if match and match[2] else None
                inner.end_episode = int(match[3] or match[2]) if match and match[2] else None
                inner.season_list = [inner.begin_season] if match else []
                inner.season_episode = inner.season = ''

            @property
            def episode_list(inner):
                if inner.begin_episode is None:
                    return []
                return list(range(inner.begin_episode, inner.end_episode + 1))

        def download_torrent(info):
            self.torrent_infos.append(info)
            release = next(r for r in self.releases if r['title'] == info.title)
            files = release.get('files')
            if files is None:
                files = [f'Show.S01E{ep:02}.mkv' for ep in release.get('eps', [1])]
            return b'd' + info.title.encode() + b'x' * 24, None, files

        def submit(**kwargs):
            title = kwargs['context'].torrent_info.title
            eps = kwargs['episodes']
            if title in self.fail_titles:
                return None
            self.submissions.append((title, None if eps is None else set(eps)))
            self.submitted_infos.append(kwargs['context'].torrent_info)
            if title in self.accepted_falsy:
                self.tasks.append({'hash': title, 'state': 'error'})
                return None
            return title

        logger = N(**{level: lambda msg, *args: self.logs.append(str(msg))
                      for level in ('info', 'warning', 'warn', 'error')})
        def warning(msg):
            self.warnings.append(str(msg))
            self.logs.append(str(msg))
        logger.warning = warning
        server = N(get_torrents=lambda: (self.tasks, False))
        self.namespace = {
            'datetime': datetime, 're': re, 'Guard': Guard, 'resolution': resolution,
            'copy': copy, 'match_site': match_site, 'snapshot_sites': snapshot_sites,
            'SiteOper': lambda: N(list=self.site_list),
            'RecognitionReviewer': RecognitionReviewer, 'apply_review': apply_review,
            'tmdb_review_detail': lambda *args: None,
            'release_rank': load_release_rank(), 'exclusive': exclusive,
            'rule_matches': rule_matches, 'DeferCache': DeferCache,
            'actual_episodes': actual_episodes, 'disc_format_reason': disc_format_reason,
            'hash_exists': hash_exists, 'looks_like_torrent': looks_like_torrent,
            'torrent_payload_diagnostic': torrent_payload_diagnostic,
            'settings': N(PLUGIN_DATA_PATH=self.temp.name), 'logger': logger,
            'DownloadChain': lambda: N(download_torrent=download_torrent, download_single=submit),
            'SubscribeChain': lambda: N(), 'DownloadHistoryOper': lambda: FakeHistory({}),
            'QbittorrentModule': lambda: N(get_instances=lambda: {'qb': server}),
            'verified_transfer_candidates': lambda ident, season: self.transfers,
            'SeasonIdentityFixer': lambda **kw: N(repair=lambda media, **kw: media,
                                                 stats={'suspect': 0}),
            'collect_tmdb_candidates': lambda name: [], 'force_recognize_by_id': lambda *args: None,
            'shared_identity_title_candidates': lambda title, desc: [title],
            'is_ambiguous_english_title': lambda *args: False,
            'MediaType': self.kind, 'MetaInfo': Meta, 'TorrentInfo': N, 'Context': N,
            'SystemConfigKey': N(SubscribeFilterRuleGroups='filters'),
            'Torrent': N(from_string=lambda content: N(info_hash=content[1:-24].decode())),
            'RssHelper': lambda: N(parse=lambda *args, **kw: self.releases),
        }
        self.plugin = load_plugin_class(self.namespace)()
        self.plugin._address, self.plugin._action = 'offline-feed', 'download'
        self.plugin.chain = N(recognize_media=lambda **kw: self.media,
                              media_exists=lambda **kw: self.library)
        self.plugin.systemconfig = N(get=lambda key: None)
        self.plugin.get_data = lambda key: self.saved.get(key)
        self.plugin.save_data = lambda key, value: self.saved.update({key: value})

    def release(self, mark='S01E01', size=100, quality=1080, eps=(1,), **extra):
        return dict(title=f'Show.{mark}.{quality}p.{size}', size=size, eps=eps, **extra)

    def run_round(self, releases):
        self.releases = releases
        self.plugin.check()
        errors = [line for line in self.logs if 'RSS_ITEM_DEFER' in line]
        self.assertEqual(errors, [])
        return [eps for title, eps in self.submissions]

    def test_config_defaults_and_explicit_legacy_values(self):
        for config, expected in ((None, 0), ({}, 0), ({'enabled': False}, 0),
                                 ({'max_versions': 0}, 0), ({'max_versions': 1}, 1),
                                 ({'max_versions': 2}, 2), ({'max_versions': '2'}, 2)):
            with self.subTest(config=config):
                self.plugin.init_plugin(config)
                self.assertEqual(self.plugin._max_versions, expected)
        self.plugin.init_plugin({})
        self.assertEqual(self.plugin._max_versions, 0)

    def test_ui_has_zero_and_default_zero(self):
        form, defaults = self.plugin.get_form()
        def walk(nodes):
            for node in nodes:
                yield node
                yield from walk(node.get('content', []))
        props = next(n['props'] for n in walk(form)
                     if n.get('props', {}).get('model') == 'max_versions')
        self.assertEqual([item['value'] for item in props['items']], [0, 1, 2])
        self.assertEqual(defaults['max_versions'], 0)

    def test_single_then_overlapping_pack_only_adds_other_episode(self):
        for cap in (0, 1, 2):
            with self.subTest(cap=cap):
                self.plugin._max_versions = cap
                self.submissions.clear()
                Path(self.temp.name, 'rss-download-pending.json').write_text('[]')
                # 使用同分辨率体积排序，确保先单集、再重叠包、最后不同集。
                self.assertEqual(self.run_round([
                    self.release(size=300),
                    self.release('S01E01-E02', size=200, eps=(1, 2)),
                    self.release('S01E02', size=100, eps=(2,)),
                    self.release('S01E03', size=90, eps=(3,)),
                ]), [{1}, {2}, {3}])

    def test_pack_then_single_and_overlapping_pack(self):
        self.assertEqual(self.run_round([
            self.release('S01E01-E02', size=300, eps=(1, 2)),
            self.release('S01E02-E03', size=200, eps=(2, 3)),
            self.release(size=100),
        ]), [{1, 2}, {3}])

    def test_round_overlap_remains_blocked_after_pending_window_expires(self):
        from unittest.mock import patch
        from smart_guard import time
        clock = [time.time()]
        reserve = Guard.reserve
        def reserve_then_advance(guard, *args, **kwargs):
            reserve(guard, *args, **kwargs)
            clock[0] += 121
        with patch('smart_guard.time.time', side_effect=lambda: clock[0]), \
                patch.object(Guard, 'reserve', reserve_then_advance):
            self.assertEqual(self.run_round([
                self.release('S01E01-E02', size=300, eps=(1, 2)),
                self.release('S01E02-E03', size=200, eps=(2, 3)),
                self.release(size=100),
            ]), [{1, 2}, {3}])

    def test_round_dedupe_blocks_resolution_upgrade_of_already_submitted_episode(self):
        # 2160小单集先于1080大包；包只能补E02，不能再下E01。
        self.assertEqual(self.run_round([
            self.release(size=100, quality=2160),
            self.release('S01E01-E02', size=1000, eps=(1, 2)),
        ]), [{1}, {2}])

    def test_failed_submission_does_not_claim_episodes(self):
        first = self.release(size=300)
        self.fail_titles.add(first['title'])
        self.assertEqual(self.run_round([first, self.release(size=200)]), [{1}])
        self.assertEqual(self.submissions[0][0], self.release(size=200)['title'])

    def test_falsy_but_accepted_submission_claims_episodes(self):
        first = self.release('S01E01-E02', size=300, eps=(1, 2))
        self.accepted_falsy.add(first['title'])
        self.assertEqual(self.run_round([
            first, self.release('S01E02-E03', size=200, eps=(2, 3)),
        ]), [{1, 2}, {3}])

    def test_new_round_allows_four_more_upgrades(self):
        for size in (100, 125, 157, 197, 247):
            self.run_round([self.release(size=size)])
        self.assertEqual(len(self.submissions), 5)

    def test_movie_round_selects_only_best_then_allows_later_upgrades(self):
        self.media.type = self.kind.MOVIE
        for size in (100, 125, 157, 197, 247):
            self.run_round([self.release(size=size), self.release(size=size - 1)])
        self.assertEqual(len(self.submissions), 5)
        self.assertEqual([title for title, eps in self.submissions],
                         [self.release(size=size)['title'] for size in (100, 125, 157, 197, 247)])

    def test_disc_falls_back_without_claiming_round(self):
        self.assertEqual(self.run_round([
            self.release(size=300, files=['Show/BDMV/index.bdmv']),
            self.release(size=200), self.release(size=100),
        ]), [{1}])
        self.assertEqual(self.submissions[0][0], self.release(size=200)['title'])

    def test_history_entry_does_not_prevent_later_upgrade(self):
        self.saved['history'] = [{'key': self.release(size=200)['title']}]
        self.assertEqual(self.run_round([self.release(size=200)]), [{1}])


class SiteMetadataFlowTests(unittest.TestCase):
    def setUp(self):
        # 复用离线夹具，执行完整的生产check而非匹配逻辑的替代实现。
        self.flow = PluginFlowTests()
        self.flow.setUp()
        self.addCleanup(self.flow.doCleanups)
        self.row = N(id=12, name='M-Team', domain='m-team.cc',
                     url='https://kp.m-team.cc/', rss='https://rss.m-team.cc/feed?token=fake',
                     cookie='fake-cookie', ua='fake-ua', downloader='fake-downloader', proxy=True)
        self.flow.site_list.return_value = [self.row]

    def test_decorates_both_download_contexts_and_only_identity_fields(self):
        f = self.flow
        release = f.release(link='https://kp.m-team.cc/details/1',
                            enclosure='https://rss.m-team.cc/download/1?token=fake')
        f.run_round([release])
        f.site_list.assert_called_once_with()
        self.assertEqual(len(f.torrent_infos), 1)
        self.assertIs(f.torrent_infos[0], f.submitted_infos[0])
        self.assertEqual(vars(f.torrent_infos[0]), dict(
            title=release['title'], description='', enclosure=release['enclosure'],
            page_url=release['link'], size=100, pubdate=None, site_proxy=False,
            site=12, site_name='M-Team'))
        self.assertFalse(any('RSS_SITE_' in log for log in f.logs))

    def test_config_loaded_once_per_round_not_per_feed_or_item(self):
        f = self.flow
        f.plugin._address = 'https://rss.m-team.cc/feed\nhttps://other.test/feed'
        f.run_round([f.release(), f.release('S01E02', eps=(2,))])
        self.assertEqual(len(f.submissions), 2)
        f.site_list.assert_called_once_with()
        f.run_round([f.release('S01E03', eps=(3,))])
        self.assertEqual(f.site_list.call_count, 2)

    def test_next_round_reloads_changed_site_config(self):
        f = self.flow
        f.run_round([f.release(link='https://m-team.cc/1')])
        f.site_list.return_value = [N(id=34, name='Renamed', domain='m-team.cc', url='', rss='')]
        f.run_round([f.release('S01E02', eps=(2,), link='https://m-team.cc/2')])
        self.assertEqual([(info.site, info.site_name) for info in f.submitted_infos],
                         [(12, 'M-Team'), (34, 'Renamed')])
        self.assertEqual(f.site_list.call_count, 2)

    def test_config_exception_is_generic_warning_and_download_continues(self):
        f = self.flow
        f.site_list.side_effect = RuntimeError('https://secret.test/feed?token=fake-cookie')
        f.run_round([f.release(link='https://m-team.cc/1')])
        self.assertEqual(len(f.submissions), 1)
        self.assertFalse(hasattr(f.torrent_infos[0], 'site'))
        self.assertEqual(f.warnings, ['RSS_SITE_CONFIG_DEFER 站点信息读取失败，本轮保留原有下载行为'])
        self.assertNotIn('secret.test', '\n'.join(f.logs))
        self.assertNotIn('fake-cookie', '\n'.join(f.logs))

    def test_config_constructor_failure_keeps_download(self):
        f = self.flow
        def fail():
            raise RuntimeError('fake-secret')
        f.namespace['SiteOper'] = fail
        f.run_round([f.release()])
        self.assertEqual(len(f.submissions), 1)
        self.assertEqual(f.warnings, ['RSS_SITE_CONFIG_DEFER 站点信息读取失败，本轮保留原有下载行为'])

    def test_snapshot_failure_keeps_download_without_sensitive_log(self):
        f = self.flow
        class BrokenSite:
            @property
            def id(self):
                raise ValueError('https://secret.test/?rss=fake')
        f.site_list.return_value = [BrokenSite()]
        f.run_round([f.release()])
        self.assertEqual(len(f.submissions), 1)
        self.assertEqual(f.warnings, ['RSS_SITE_CONFIG_DEFER 站点信息读取失败，本轮保留原有下载行为'])

    def test_feed_provenance_survives_merge_sort_and_does_not_mutate_input(self):
        f = self.flow
        first, second = f.release(size=100), f.release('S01E02', size=200, eps=(2,))
        first['_source_feed_url'] = 'https://forged.test/feed'
        originals = [dict(first), dict(second)]
        f.releases = [first, second]
        a, b = 'https://rss.m-team.cc/feed?token=fake', 'https://rss.other.test/feed?token=fake'
        other = N(id=34, name='Other', domain='other.test', url='', rss=b)
        f.site_list.return_value = [self.row, other]
        f.plugin._address = a + '\n' + b
        feeds = {a: [first], b: [second]}
        f.namespace['RssHelper'] = lambda: N(parse=lambda url, **kw: feeds[url])
        f.plugin.check()
        self.assertEqual([info.site for info in f.torrent_infos], [34, 12])
        self.assertEqual([first, second], originals)
        self.assertEqual([info.site_name for info in f.submitted_infos], ['Other', 'M-Team'])
        self.assertFalse(any('token=' in log for log in f.logs))

    def test_unknown_third_party_stays_unlabelled_despite_known_feed(self):
        f = self.flow
        f.plugin._address = self.row.rss
        f.run_round([f.release(link='https://third.test/details/1',
                               enclosure='https://third.test/?next=https://m-team.cc/1')])
        self.assertEqual(len(f.submissions), 1)
        self.assertFalse(hasattr(f.torrent_infos[0], 'site'))

    def test_conflict_still_downloads_without_identity(self):
        f = self.flow
        f.site_list.return_value.append(N(id=34, name='Other', domain='other.test', url='', rss=''))
        f.run_round([f.release(link='https://m-team.cc/1', enclosure='https://other.test/1')])
        self.assertEqual(len(f.submissions), 1)
        self.assertFalse(hasattr(f.torrent_infos[0], 'site'))

    def test_matching_failure_does_not_skip_current_or_next_item(self):
        from unittest.mock import Mock
        f = self.flow
        f.namespace['match_site'] = Mock(side_effect=[RuntimeError('https://secret.test/?token=fake'),
                                                     (12, 'M-Team')])
        f.run_round([f.release(size=200), f.release('S01E02', eps=(2,))])
        self.assertEqual(len(f.submissions), 2)
        self.assertFalse(hasattr(f.torrent_infos[0], 'site'))
        self.assertEqual(f.torrent_infos[1].site, 12)
        self.assertEqual(f.warnings, ['RSS_SITE_METADATA_DEFER 站点信息补充失败，保留原有下载行为'])

    def test_assignment_failure_is_atomic_and_keeps_download(self):
        f = self.flow
        class RejectName(N):
            def __setattr__(self, name, value):
                if name == 'site_name':
                    raise ValueError('fake-sensitive-error')
                super().__setattr__(name, value)
        f.namespace['TorrentInfo'] = RejectName
        f.run_round([f.release(link='https://m-team.cc/1')])
        self.assertEqual(len(f.submissions), 1)
        self.assertFalse(hasattr(f.torrent_infos[0], 'site'))
        self.assertFalse(hasattr(f.torrent_infos[0], 'site_name'))
        self.assertEqual(f.warnings, ['RSS_SITE_METADATA_DEFER 站点信息补充失败，保留原有下载行为'])

    def test_copy_failure_keeps_download(self):
        f = self.flow
        def fail(_):
            raise RuntimeError('fake-sensitive-error')
        f.namespace['copy'] = fail
        f.run_round([f.release(link='https://m-team.cc/1')])
        self.assertEqual(len(f.submissions), 1)
        self.assertFalse(hasattr(f.torrent_infos[0], 'site'))
        self.assertEqual(f.warnings, ['RSS_SITE_METADATA_DEFER 站点信息补充失败，保留原有下载行为'])

    def test_metadata_failure_does_not_skip_existing_filter(self):
        from unittest.mock import Mock
        f = self.flow
        f.plugin._filter = True
        f.namespace['match_site'] = Mock(side_effect=ValueError('fake-secret'))
        f.plugin.chain.filter_torrents = Mock(side_effect=lambda **kw: kw['torrent_list'])
        f.run_round([f.release(link='https://m-team.cc/1')])
        f.plugin.chain.filter_torrents.assert_called_once()
        self.assertEqual(len(f.submissions), 1)
        self.assertFalse(hasattr(f.submitted_infos[0], 'site'))

    def test_download_subscribe_gets_site_identity(self):
        f = self.flow
        f.plugin._action = 'download_subscribe'
        f.namespace['ensure_subscription'] = lambda *args: None
        f.run_round([f.release(enclosure='https://m-team.cc/1')])
        self.assertEqual(f.submitted_infos[0].site, 12)

    def test_subscription_only_does_not_read_sites_or_decorate(self):
        from unittest.mock import Mock
        f = self.flow
        f.plugin._action = 'subscribe'
        add = Mock()
        f.namespace['SubscribeChain'] = lambda: N(exists=lambda **kw: False, add=add)
        f.run_round([f.release(link='https://m-team.cc/1')])
        f.site_list.assert_not_called()
        add.assert_called_once()
        self.assertEqual(f.torrent_infos, [])

    def test_empty_feed_address_does_not_read_sites(self):
        f = self.flow
        f.plugin._address = ''
        f.plugin.check()
        f.site_list.assert_not_called()

    def test_sensitive_fields_are_not_accessed(self):
        f = self.flow
        class SafeFieldsOnly:
            id, name = 12, 'M-Team'
            domain, url, rss = 'm-team.cc', '', ''
            def __getattr__(self, name):
                raise AssertionError('不应访问下载设置或凭证字段')
        f.site_list.return_value = [SafeFieldsOnly()]
        f.run_round([f.release(link='https://m-team.cc/1')])
        self.assertEqual(f.torrent_infos[0].site, 12)
        self.assertEqual(f.warnings, [])

    def test_existing_proxy_flag_is_preserved(self):
        f = self.flow
        self.row.proxy = False
        f.plugin._proxy = True
        f.run_round([f.release(link='https://m-team.cc/1')])
        self.assertTrue(f.torrent_infos[0].site_proxy)

    def test_identity_available_to_existing_torrent_filter(self):
        f = self.flow
        f.plugin._filter = True
        captured = []
        def filter_torrents(**kw):
            captured.extend(kw['torrent_list'])
            return kw['torrent_list']
        f.plugin.chain.filter_torrents = filter_torrents
        f.run_round([f.release(link='https://m-team.cc/1')])
        self.assertEqual(captured[0].site, 12)
        self.assertIs(captured[0], f.submitted_infos[0])


class HistoryLifecycleTests(unittest.TestCase):
    """执行生产 init/check/delete_history，仅用内存存储和临时目录。"""

    def setUp(self):
        from copy import deepcopy
        from unittest.mock import Mock
        self.flow = PluginFlowTests()
        self.flow.setUp()
        self.addCleanup(self.flow.doCleanups)
        self.plugin = self.flow.plugin
        self.ns = self.flow.namespace
        self.ns['settings'].TZ = 'UTC'
        self.ns['settings'].API_TOKEN = 'offline-test-token'
        self.ns['schemas'] = N(Response=N)
        self.ns['pytz'] = N(timezone=lambda name: self.ns['datetime'].timezone.utc)
        self.scheduler = Mock()
        self.scheduler.get_jobs.return_value = [object()]
        self.scheduler.running = False
        self.ns['BackgroundScheduler'] = Mock(return_value=self.scheduler)
        self.ns['SubscribeChain'] = lambda: N(exists=lambda **kw: False, add=Mock())
        self.saved = self.flow.saved
        self.writes, self.configs = [], []
        self.copy = deepcopy
        self.plugin.get_data = lambda key: deepcopy(self.saved.get(key))
        self.plugin.save_data = self.save_data
        self.plugin.update_config = lambda value: self.configs.append(deepcopy(value))
        self.plugin.systemmessage = N(put=Mock())
        self.plugin._action = 'subscribe'
        self.config = self.plugin.get_form()[1]
        self.config.update(action='subscribe', address='offline-feed',
                           tv_min_resolution=2160, movie_min_resolution=1080,
                           tv_subtitle_mode='required', movie_subtitle_mode='any',
                           fix_season_identity=False, max_versions=2,
                           include='Show', exclude='CAM', save_path='/offline/library',
                           size_range='1-20', proxy=True, filter=True)
        self.old = dict(key='old-resource', title='同名作品', time='2026-01-01 00:00:00')
        self.other = dict(key='other-resource', title='同名作品', time='2026-01-02 00:00:00')
        self.saved['history'] = [self.copy(self.old), self.copy(self.other)]
        self.rss = Mock(side_effect=lambda *args, **kw: self.flow.releases)
        self.ns['RssHelper'] = Mock(return_value=N(parse=self.rss))

    def save_data(self, key, value):
        self.writes.append((key, self.copy(value)))
        self.saved[key] = self.copy(value)

    def peer(self):
        peer = type(self.plugin)()
        for attr in ('get_data', 'save_data', 'update_config', 'systemmessage',
                     'chain', 'systemconfig'):
            setattr(peer, attr, getattr(self.plugin, attr))
        return peer

    def clear(self, peer=None, **overrides):
        config = dict(self.config, clear=True, **overrides)
        (peer or self.plugin).init_plugin(config)
        return config

    def assert_no_rss(self):
        self.ns['RssHelper'].assert_not_called()
        self.flow.site_list.assert_not_called()
        self.assertEqual(self.flow.submissions, [])
        self.assertEqual(self.flow.torrent_infos, [])

    def test_clear_immediate_for_enabled_disabled_and_no_address(self):
        for enabled in (False, True):
            for address in ('', 'offline-feed'):
                with self.subTest(enabled=enabled, address=address):
                    self.saved['history'] = [self.copy(self.old)]
                    self.clear(self.peer(), enabled=enabled, address=address)
                    self.assertEqual(self.saved['history'], [])
                    self.assertEqual(self.peer().get_data('history'), [])
                    self.assertFalse(self.configs[-1]['clear'])
                    self.assertFalse(self.configs[-1]['onlyonce'])
        self.ns['BackgroundScheduler'].assert_not_called()
        self.assert_no_rss()

    def test_clear_only_does_not_touch_other_data_or_files(self):
        extras = {key: [{'untouched': key}] for key in
                  ('pending', 'defer', 'download_history', 'transfer_history', 'qb_tasks')}
        self.saved.update(self.copy(extras))
        paths = [Path(self.flow.temp.name, name) for name in
                 ('rss-download-pending.json', 'rss-defer-cache.json')]
        for path in paths:
            path.write_text('原样保留')
        self.clear()
        self.assertEqual({k: self.saved[k] for k in extras}, extras)
        self.assertEqual([p.read_text() for p in paths], ['原样保留'] * 2)
        self.assertEqual([key for key, value in self.writes], ['history_generation', 'history'])
        self.assert_no_rss()

    def test_clear_then_check_without_address_returns_without_writes(self):
        self.clear(address='')
        writes = self.copy(self.writes)
        self.plugin.check()
        self.assertEqual(self.writes, writes)
        self.assertEqual(self.saved['history'], [])
        self.assert_no_rss()

    def test_clear_survives_empty_and_failed_rss_fetch(self):
        for failure in (None, [], RuntimeError('离线抓取失败')):
            with self.subTest(failure=failure):
                self.saved['history'] = [self.copy(self.old)]
                self.clear()
                self.rss.side_effect = failure if isinstance(failure, Exception) else None
                self.rss.return_value = failure
                writes = self.copy(self.writes)
                self.plugin.check()
                self.assertEqual(self.saved['history'], [])
                self.assertEqual(self.writes, writes)
        self.assertEqual(self.rss.call_count, 3)

    def test_without_clear_failed_fetch_keeps_history(self):
        before = self.copy(self.saved)
        self.rss.return_value, self.rss.side_effect = [], None
        self.plugin.check()
        self.assertEqual(self.saved, before)
        self.assertEqual(self.writes, [])

    def test_clear_and_once_clears_before_job_and_resets_both_flags(self):
        self.scheduler.add_job.side_effect = lambda **kw: self.assertEqual(self.saved['history'], [])
        config = self.clear(onlyonce=True, address='')
        self.scheduler.add_job.assert_called_once()
        self.scheduler.start.assert_called_once()
        expected = dict(config, clear=False, onlyonce=False)
        self.assertEqual(self.configs, [expected])
        self.assertFalse(self.plugin._onlyonce)
        self.assertFalse(self.plugin._clear)
        self.assert_no_rss()
        self.scheduler.add_job.call_args.kwargs['func']()
        self.assertEqual(self.saved['history'], [])
        self.assert_no_rss()

    def test_clear_only_preserves_all_existing_settings(self):
        config = self.clear()
        self.assertEqual(self.configs, [dict(config, clear=False, onlyonce=False)])

    def test_once_only_preserves_all_settings_and_history(self):
        config = dict(self.config, onlyonce=True, clear=False)
        before = self.copy(self.saved)
        self.plugin.init_plugin(config)
        self.assertEqual(self.configs, [dict(config, onlyonce=False)])
        self.assertEqual(self.saved, before)
        self.assertEqual(self.writes, [])
        self.scheduler.add_job.assert_called_once()
        self.assert_no_rss()

    def test_delete_key_only_removes_one_same_title_resource(self):
        response = self.peer().delete_history(self.old['key'], 'offline-test-token')
        self.assertTrue(response.success)
        self.assertEqual(self.saved['history'], [self.other])
        self.assertEqual(self.saved['history_generation'], 1)

    def test_delete_key_takes_precedence_over_title(self):
        self.saved['history'].append(dict(key='third', title=self.old['key']))
        self.assertTrue(self.plugin.delete_history(self.old['key'], 'offline-test-token').success)
        self.assertEqual([h['key'] for h in self.saved['history']], ['other-resource', 'third'])

    def test_legacy_unique_title_and_keyless_row_can_be_deleted(self):
        for row in (self.old, dict(title='旧版无key', time=self.old['time'])):
            with self.subTest(row=row):
                self.saved['history'] = [self.copy(row)]
                self.assertTrue(self.plugin.delete_history(row['title'], 'offline-test-token').success)
                self.assertEqual(self.saved['history'], [])

    def test_ambiguous_title_unknown_key_and_wrong_token_do_not_write(self):
        for key, token in (('同名作品', 'offline-test-token'), ('missing', 'offline-test-token'),
                           (self.old['key'], 'wrong-token')):
            with self.subTest(key=key, token=token):
                before = self.copy(self.saved)
                self.assertFalse(self.plugin.delete_history(key, token).success)
                self.assertEqual(self.saved, before)
                self.assertEqual(self.writes, [])

    def test_page_uses_resource_key_with_legacy_fallback(self):
        self.saved['history'].append(dict(title='旧版无key', time=self.old['time']))
        page = self.plugin.get_page()
        params = [card['content'][0]['events']['click']['params'] for card in page[0]['content']]
        self.assertEqual({p['key'] for p in params}, {'old-resource', 'other-resource', '旧版无key'})
        self.assertTrue(all(p['apikey'] == 'offline-test-token' for p in params))

    def paused_round(self, mutation, releases=None):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        entered, resume = Event(), Event()
        self.flow.releases = releases or [self.flow.release()]
        def parse(*args, **kw):
            entered.set()
            if not resume.wait(10):
                raise AssertionError('等待并发操作超时')
            return self.flow.releases
        self.rss.side_effect = parse
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self.plugin.check)
            try:
                self.assertTrue(entered.wait(10), '生产check未到达RSS抓取')
                mutation()
            finally:
                resume.set()
            future.result(timeout=10)
        self.assertFalse(any('RSS_ITEM_DEFER' in line for line in self.flow.logs), self.flow.logs)
        self.rss.side_effect = lambda *args, **kw: self.flow.releases

    def test_old_round_cannot_restore_clear_from_another_instance(self):
        self.paused_round(lambda: self.clear(self.peer(), address=''))
        self.assertEqual(self.saved['history'], [])
        self.assertEqual([k for k, v in self.writes], ['history_generation', 'history'])
        # 清理后下一轮仍能正常记录，不永久阻断历史。
        self.flow.run_round([self.flow.release('S01E02', eps=(2,))])
        self.assertEqual([h['key'] for h in self.saved['history']], [self.flow.releases[0]['title']])

    def test_old_round_cannot_restore_single_deleted_record(self):
        release = self.flow.release()
        self.old['key'] = release['title']
        self.saved['history'] = [self.copy(self.old), self.copy(self.other)]
        # 下载模式会重新记录相同key，验证新增也不能复活已删记录。
        self.plugin._action = 'download'
        self.paused_round(lambda: self.assertTrue(
            self.peer().delete_history(release['title'], 'offline-test-token').success), [release])
        self.assertEqual(self.saved['history'], [self.other])
        self.assertEqual(len(self.flow.submissions), 1)
        self.flow.run_round([self.flow.release('S01E02', eps=(2,))])
        self.assertEqual(len(self.saved['history']), 2)
        self.assertEqual(self.saved['history'][0], self.other)

    def test_old_round_keeps_post_clear_new_round_history(self):
        new = self.flow.release('S01E02', eps=(2,))
        def mutation():
            peer = self.peer()
            self.clear(peer, size_range='', tv_min_resolution=0,
                       tv_subtitle_mode='any', filter=False)
            old_releases = self.flow.releases
            self.rss.side_effect = lambda *args, **kw: [new]
            peer.check()
            self.flow.releases = old_releases
        self.paused_round(mutation)
        self.assertEqual([h['key'] for h in self.saved['history']], [new['title']])

    def test_concurrent_rounds_merge_only_additions_without_lost_update(self):
        new = self.flow.release('S01E02', eps=(2,))
        def mutation():
            peer = self.peer()
            peer._address, peer._action = 'offline-feed', 'subscribe'
            self.rss.side_effect = lambda *args, **kw: [new]
            peer.check()
        self.paused_round(mutation)
        self.assertEqual({h['key'] for h in self.saved['history']},
                         {'old-resource', 'other-resource', new['title'], self.flow.release()['title']})

    def test_reinitializing_saved_clear_config_does_not_clear_again(self):
        self.clear()
        self.saved['history'] = [self.copy(self.other)]
        generation = self.saved['history_generation']
        self.plugin.init_plugin(self.configs[-1])
        self.assertEqual(self.saved['history'], [self.other])
        self.assertEqual(self.saved['history_generation'], generation)
        self.assertEqual(len(self.configs), 1)
        self.assert_no_rss()

    def test_old_round_without_additions_cannot_restore_deleted_snapshot(self):
        self.paused_round(lambda: self.assertTrue(
            self.peer().delete_history(self.old['key'], 'offline-test-token').success),
            releases=[{'title': ''}])
        self.assertEqual(self.saved['history'], [self.other])
        self.assertEqual([k for k, v in self.writes], ['history_generation', 'history'])

    def test_generation_survives_new_instance_and_new_class(self):
        self.clear()
        generation = self.saved['history_generation']
        namespace = dict(self.ns)
        peer = load_plugin_class(namespace)()
        peer.get_data, peer.save_data = self.plugin.get_data, self.plugin.save_data
        peer._merge_history(generation - 1, [self.old])
        self.assertEqual(self.saved['history'], [])
        peer._merge_history(generation, [self.other])
        self.assertEqual(self.saved['history'], [self.other])


if __name__ == '__main__':
    unittest.main(verbosity=2)
