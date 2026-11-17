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
    nodes = [node for node in tree.body if isinstance(node, ast.ClassDef)
             and node.name == 'RssSubscribeSmart']
    namespace['_PluginBase'] = object
    exec(compile(ast.Module(body=nodes, type_ignores=[]), '<production_plugin>', 'exec',
                 flags=__future__.annotations.compiler_flag), namespace)
    return namespace['RssSubscribeSmart']


class PluginFlowTests(unittest.TestCase):
    def setUp(self):
        import datetime
        import re
        from preflight import (DeferCache, actual_episodes, disc_format_reason,
                               hash_exists, looks_like_torrent, torrent_payload_diagnostic)
        from smart_guard import exclusive, rule_matches
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.releases, self.submissions, self.tasks, self.logs = [], [], [], []
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
            if title in self.accepted_falsy:
                self.tasks.append({'hash': title, 'state': 'error'})
                return None
            return title

        logger = N(**{level: lambda msg, *args: self.logs.append(str(msg))
                      for level in ('info', 'warning', 'warn', 'error')})
        server = N(get_torrents=lambda: (self.tasks, False))
        self.namespace = {
            'datetime': datetime, 're': re, 'Guard': Guard, 'resolution': resolution,
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


if __name__ == '__main__':
    unittest.main(verbosity=2)
