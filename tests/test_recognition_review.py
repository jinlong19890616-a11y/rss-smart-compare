import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).parents[1] / 'rsssubscribe_smart'))
from recognition_review import RecognitionReviewer, apply_review, structured_evidence


def show(cid, name, year, genres, capacities, aliases=()):
    return dict(id=cid, name=name, original_name=name, names=list(aliases),
                first_air_date=f'{year}-01-01', genre_ids=genres,
                seasons=[dict(season_number=s, episode_count=count, air_date=f'{y}-01-01')
                         for s, count, y in capacities])


RUN_WRONG = show(157765, 'Running man', 2017, [], [(1, 48, 2017)])
RUN_RIGHT = show(33238, 'Running Man', 2010, [35, 10764], [(1, 831, 2010)])
FIGHT_WRONG = show(81500, '斗破苍穹', 2018, [10765, 10759], [(1, 45, 2018)],
                   ['Fights Break Sphere'])
FIGHT_RIGHT = show(79481, '斗破苍穹', 2017, [16, 10759],
                   [(1, 12, 2017), (2, 12, 2018), (3, 12, 2019), (4, 24, 2021), (5, 219, 2022)],
                   ['Fights Break Sphere', '斗破苍穹年番'])
RUN_DESC = '◎片　名 Running Man◎年　代2010◎類　別真人秀◎簡　介嘉宾参加游戏，讨论类型：动画◎主　演刘在锡'
FIGHT_DESC = '片名：斗破苍穹年番 | 年代：2022 | 类别：动画/奇幻/冒险'


class ReviewTests(unittest.TestCase):
    def fixture(self, *shows):
        self.data = {d['id']: d for d in shows}
        self.log = Mock()
        self.read_detail = Mock(side_effect=lambda cid: self.data.get(cid))
        self.read_season = Mock(side_effect=self.season)
        self.search = Mock(side_effect=lambda name: list(self.data.values()))
        self.recognize = Mock(side_effect=lambda cid, title: self.media(cid))
        self.reviewer = RecognitionReviewer(collect_candidates=self.search,
            get_detail=self.read_detail, get_season=self.read_season,
            recognize_by_id=self.recognize, logger=self.log)

    def media(self, cid):
        d = self.data[cid]
        return N(tmdb_id=cid, title=d['name'], year=d['first_air_date'][:4])

    def season(self, cid, sn):
        summary = next((s for s in self.data[cid]['seasons'] if s['season_number'] == sn), None)
        if summary is None:
            return {}
        return dict(season_number=sn, episodes=[dict(episode_number=e, season_number=sn)
                    for e in range(1, summary['episode_count'] + 1)])

    def run_review(self, cid, *, season=1, eps=(827,), desc='', names=None):
        return self.reviewer.review(self.media(cid), names=names or [self.data[cid]['name']],
            season=season, episodes=eps, description=desc, query_title='offline resource')

    def test_structured_description_with_pt_spacing(self):
        genres, year, names = structured_evidence(RUN_DESC)
        self.assertEqual((genres, year, names), ({10764}, 2010, ['Running Man']))

    def test_continuous_traditional_and_simplified_fields_stop_at_synopsis(self):
        for desc in (
            '◎片　名 Running Man◎譯　名 跑男◎年　代2010◎類　別真人秀◎簡　介类型：动画',
            '◎片　　名 Running Man◎译　　名 跑男◎年　　代2010◎类　　别真人秀◎简　　介类型：动画',
            '◎片　名 Running Man◎譯　名 跑男◎年　份2010◎類　型真人秀◎簡介◎類型：動畫',
        ):
            with self.subTest(desc=desc):
                self.assertEqual(structured_evidence(desc), ({10764}, 2010, ['Running Man', '跑男']))

    def test_colon_concatenated_fields_and_fullwidth_pipe(self):
        for desc in ('片名：宝莲灯类型：动画年份：2026简介：参加真人秀类型：真人秀',
                     '片名：宝莲灯｜類型：動畫｜年份：2026｜簡介：参加真人秀',
                     '◎片名：宝莲灯◎类型：动画◎年份：2026◎简介：参加真人秀'):
            with self.subTest(desc=desc):
                self.assertEqual(structured_evidence(desc), ({16}, 2026, ['宝莲灯']))

    def test_title_stops_at_other_known_field_boundaries(self):
        self.assertEqual(structured_evidence('◎片名 宝莲灯◎导演 某某◎年代2026◎类别动画'),
                         ({16}, 2026, ['宝莲灯']))
        self.assertEqual(structured_evidence('片名：宝莲灯主演：某某年份：2026类型：动画'),
                         ({16}, 2026, ['宝莲灯']))

    def test_prose_fake_fields_after_synopsis_never_become_evidence(self):
        for desc in ('◎簡　介 这里提到類型：動畫年份：2010◎類別真人秀',
                     '简介：故事围绕类型：动画｜年份：2010',
                     '片名：样本简介：類型：動畫年份：2010'):
            with self.subTest(desc=desc):
                genres, year, names = structured_evidence(desc)
                self.assertEqual((genres, year), (set(), None))

    def test_episode_13_vs_12_with_matching_identity_warns_and_keeps(self):
        self.fixture(show(1, '动画样本', 2026, [16], [(1, 12, 2026)]))
        result = self.run_review(1, eps=(13,), desc='类别：动画年份：2026')
        self.assertFalse(result.blocked)
        self.assertFalse(result.changed)
        self.assertEqual((result.media.tmdb_id, result.season), (1, 1))
        self.search.assert_not_called()
        self.assertIn('RSS_RECOGNITION_REVIEW_SUSPECT', str(self.log.mock_calls))

    def test_cumulative_25_across_12_and_13_keeps_original_without_offset(self):
        self.fixture(show(1, '动画样本', 2025, [16], [(1, 12, 2025), (2, 13, 2026)]))
        result = self.run_review(1, eps=(25,), desc='类别：动画年份：2026')
        self.assertFalse(result.blocked)
        self.assertFalse(result.changed)
        self.assertEqual(result.season, 1)
        self.search.assert_not_called()
        self.assertIn('RSS_RECOGNITION_REVIEW_SUSPECT', str(self.log.mock_calls))

    def test_later_season_year_is_not_first_air_identity_conflict(self):
        self.fixture(FIGHT_RIGHT)
        result = self.run_review(79481, eps=range(1, 220), desc=FIGHT_DESC)
        self.assertFalse(result.blocked)
        self.assertFalse(result.changed)
        self.assertEqual(result.season, 1)
        self.search.assert_not_called()

    def test_capacity_and_reliable_year_start_repair_even_without_genres(self):
        self.fixture(RUN_WRONG, RUN_RIGHT)
        result = self.run_review(157765, desc='◎片名 Running Man◎年代2010◎简介 某节目')
        self.assertFalse(result.blocked)
        self.assertEqual(result.media.tmdb_id, 33238)
        self.assertTrue(result.changed)

    def test_year_alone_without_capacity_or_type_conflict_keeps_identity(self):
        self.fixture(RUN_WRONG, RUN_RIGHT)
        result = self.run_review(157765, eps=(1,), desc=RUN_DESC)
        self.assertFalse(result.blocked)
        self.assertFalse(result.changed)
        self.search.assert_not_called()

    def test_missing_season_year_does_not_prove_year_conflict(self):
        self.fixture(dict(RUN_WRONG, seasons=[dict(season_number=1, episode_count=48)]), RUN_RIGHT)
        result = self.run_review(157765, desc=RUN_DESC)
        self.assertFalse(result.blocked)
        self.assertFalse(result.changed)
        self.search.assert_not_called()

    def test_reidentified_genres_conflicting_with_candidate_are_rejected(self):
        self.fixture(RUN_WRONG, RUN_RIGHT)
        self.recognize.side_effect = lambda *args: N(tmdb_id=33238, year='2010', genre_ids=[16])
        self.assertTrue(self.run_review(157765, desc=RUN_DESC).blocked)

    def test_reidentified_genres_checked_even_without_description_category(self):
        self.fixture(RUN_WRONG, RUN_RIGHT)
        self.recognize.side_effect = lambda *args: N(tmdb_id=33238, year='2010', genre_ids=[16])
        self.assertTrue(self.run_review(157765, desc='年代：2010').blocked)

    def test_reidentified_animation_reality_genre_mismatch_is_rejected(self):
        self.fixture(FIGHT_WRONG, FIGHT_RIGHT)
        self.recognize.side_effect = lambda *args: N(tmdb_id=79481, year='2017', genre_ids=[10764])
        self.assertTrue(self.run_review(81500, eps=range(1, 220), desc=FIGHT_DESC).blocked)

    def test_reidentified_matching_genres_are_accepted(self):
        self.fixture(RUN_WRONG, RUN_RIGHT)
        self.recognize.side_effect = lambda *args: N(tmdb_id=33238, year='2010', genre_ids=[35, 10764])
        self.assertEqual(self.run_review(157765, desc=RUN_DESC).media.tmdb_id, 33238)

    def test_running_man_corrects_s01e827(self):
        self.fixture(RUN_WRONG, RUN_RIGHT)
        result = self.run_review(157765, desc=RUN_DESC)
        self.assertFalse(result.blocked)
        self.assertEqual((result.media.tmdb_id, result.season), (33238, 1))
        self.assertTrue(result.changed)

    def test_fights_break_sphere_maps_s01_to_s05(self):
        self.fixture(FIGHT_WRONG, FIGHT_RIGHT)
        result = self.run_review(81500, eps=range(1, 220), desc=FIGHT_DESC)
        self.assertFalse(result.blocked)
        self.assertEqual((result.media.tmdb_id, result.season), (79481, 5))
        meta = N(tmdbid=81500, begin_season=1, end_season=1, year='2022', total_season=1)
        apply_review(meta, result)
        self.assertEqual((meta.tmdbid, meta.begin_season, meta.year, meta.end_season),
                         (79481, 5, result.media.year, None))

    def test_short_animation_e827_only_capacity_is_suspect_not_blocked(self):
        self.fixture(show(1, '动画样本', 2010, [16], [(1, 12, 2010)]))
        result = self.run_review(1, desc='类别：动画')
        self.assertFalse(result.blocked)
        self.assertFalse(result.changed)
        self.read_season.assert_called_with(1, 1)
        self.search.assert_not_called()
        self.assertIn('RSS_RECOGNITION_REVIEW_SUSPECT', str(self.log.mock_calls))

    def test_long_animation_e827_not_limited_by_magic_number(self):
        self.fixture(show(1, '动画样本', 2010, [16], [(1, 900, 2010)]))
        self.assertFalse(self.run_review(1, desc='类别：动画').blocked)
        self.search.assert_not_called()

    def test_real_sparse_numbering_not_mistaken_for_count(self):
        self.fixture(show(1, '动画样本', 2010, [16], [(1, 12, 2010)]))
        self.read_season.side_effect = lambda *args: dict(season_number=1,
            episodes=[dict(episode_number=827, season_number=1)])
        self.assertFalse(self.run_review(1, desc='类别：动画').blocked)

    def test_summary_stale_but_real_episode_present_is_allowed(self):
        self.fixture(RUN_RIGHT)
        self.data[33238] = dict(RUN_RIGHT, seasons=[dict(season_number=1, episode_count=800)])
        self.read_season.side_effect = lambda *args: dict(season_number=1,
            episodes=[dict(episode_number=827)])
        self.assertFalse(self.run_review(33238, desc=RUN_DESC).blocked)

    def test_unknown_capacity_no_category_is_allowed(self):
        self.fixture(dict(RUN_WRONG, seasons=[]))
        self.assertFalse(self.run_review(157765).blocked)

    def test_unknown_remote_without_proven_conflict_is_allowed(self):
        self.fixture(RUN_WRONG)
        self.read_detail.side_effect = RuntimeError('sensitive data')
        self.assertFalse(self.run_review(157765, desc=RUN_DESC).blocked)
        self.log.warning.assert_not_called()

    def test_no_category_no_year_does_not_guess_new_identity(self):
        self.fixture(RUN_WRONG, RUN_RIGHT)
        result = self.run_review(157765)
        self.assertFalse(result.blocked)
        self.assertFalse(result.changed)
        self.assertEqual(result.media.tmdb_id, 157765)
        self.search.assert_not_called()
        self.assertIn('RSS_RECOGNITION_REVIEW_SUSPECT', str(self.log.mock_calls))

    def test_synopsis_animation_mention_does_not_override_reality(self):
        self.fixture(RUN_RIGHT)
        result = self.run_review(33238, desc='类别：真人秀\n简介：嘉宾讨论动画与电影。')
        self.assertFalse(result.blocked)
        self.search.assert_not_called()

    def test_synopsis_label_text_is_not_structured_field(self):
        self.assertEqual(structured_evidence('简介：故事围绕类型：动画展开。')[0], set())
        self.assertEqual(structured_evidence('标签：动画 | 简介：真人秀')[0], set())

    def test_ambiguous_same_name_candidates_block_even_if_one_is_popular(self):
        other = dict(RUN_RIGHT, id=44, vote_count=999999)
        self.fixture(RUN_WRONG, RUN_RIGHT, other)
        self.assertTrue(self.run_review(157765, desc=RUN_DESC).blocked)
        self.recognize.assert_not_called()

    def test_ambiguous_two_real_seasons_same_year_block(self):
        other_season = dict(season_number=6, episode_count=219, air_date='2022-10-01')
        self.fixture(FIGHT_WRONG, dict(FIGHT_RIGHT, seasons=FIGHT_RIGHT['seasons'] + [other_season]))
        self.assertTrue(self.run_review(81500, eps=range(1, 220), desc=FIGHT_DESC).blocked)

    def test_cumulative_numbers_not_guessed_as_season_mapping(self):
        self.fixture(FIGHT_WRONG, FIGHT_RIGHT)
        self.assertTrue(self.run_review(81500, eps=range(61, 220), desc=FIGHT_DESC).blocked)

    def test_cross_season_numbers_do_not_get_offset_mapping(self):
        self.fixture(FIGHT_WRONG, FIGHT_RIGHT)
        self.assertTrue(self.run_review(81500, eps=range(1, 280), desc=FIGHT_DESC).blocked)

    def test_partial_contiguous_pack_cannot_remap_to_different_season(self):
        self.fixture(FIGHT_WRONG, FIGHT_RIGHT)
        self.assertTrue(self.run_review(81500, eps=range(1, 101), desc=FIGHT_DESC).blocked)

    def test_reidentified_year_must_agree_with_candidate(self):
        self.fixture(RUN_WRONG, RUN_RIGHT)
        self.recognize.side_effect = lambda *args: N(tmdb_id=33238, year='2017')
        self.assertTrue(self.run_review(157765, desc=RUN_DESC).blocked)

    def test_type_conflict_with_small_episode_requires_real_mapping(self):
        self.fixture(FIGHT_WRONG, FIGHT_RIGHT)
        self.assertTrue(self.run_review(81500, eps=(1,), desc=FIGHT_DESC).blocked)

    def test_missing_year_cannot_remap_s01_to_s05(self):
        self.fixture(FIGHT_WRONG, FIGHT_RIGHT)
        self.assertTrue(self.run_review(81500, eps=range(1, 220), desc='类别：动画').blocked)

    def test_unavailable_real_season_blocks_proven_type_conflict(self):
        self.fixture(FIGHT_WRONG, FIGHT_RIGHT)
        self.read_season.side_effect = RuntimeError('sensitive-url')
        self.assertTrue(self.run_review(81500, eps=range(1, 220), desc=FIGHT_DESC).blocked)
        self.assertNotIn('sensitive', str(self.log.mock_calls))

    def test_search_failure_blocks_proven_capacity_conflict(self):
        self.fixture(RUN_WRONG, RUN_RIGHT)
        self.search.side_effect = RuntimeError('secret-url')
        self.assertTrue(self.run_review(157765, desc=RUN_DESC).blocked)
        self.assertNotIn('secret', str(self.log.mock_calls))

    def test_reidentification_wrong_id_is_blocked(self):
        self.fixture(RUN_WRONG, RUN_RIGHT)
        self.recognize.side_effect = lambda *args: self.media(157765)
        self.assertTrue(self.run_review(157765, desc=RUN_DESC).blocked)

    def test_reidentification_failure_is_blocked(self):
        self.fixture(RUN_WRONG, RUN_RIGHT)
        self.recognize.side_effect = RuntimeError('secret')
        self.assertTrue(self.run_review(157765, desc=RUN_DESC).blocked)

    def test_no_actual_episodes_does_not_remap_season_only_by_id(self):
        self.fixture(FIGHT_WRONG, FIGHT_RIGHT)
        self.assertTrue(self.run_review(81500, eps=(), desc=FIGHT_DESC).blocked)

    def test_disabled_reviewer_keeps_existing_behavior(self):
        self.fixture(RUN_WRONG, RUN_RIGHT)
        self.reviewer.enabled = False
        self.assertFalse(self.run_review(157765, desc=RUN_DESC).blocked)
        self.read_detail.assert_not_called()

    def test_remote_reads_cached_only_for_round(self):
        self.fixture(RUN_WRONG, RUN_RIGHT)
        for _ in range(2):
            self.assertEqual(self.run_review(157765, desc=RUN_DESC).media.tmdb_id, 33238)
        self.assertEqual(self.read_detail.call_count, 2)
        self.assertEqual(self.read_season.call_count, 2)


class ReviewFlowTests(unittest.TestCase):
    def setUp(self):
        from test_best_version_policy import PluginFlowTests
        self.flow = PluginFlowTests()
        self.flow.setUp()
        self.addCleanup(self.flow.doCleanups)
        self.logic = ReviewTests()
        self.contexts = []

    def prepare(self, wrong, right):
        self.logic.fixture(wrong, right)
        f = self.flow
        f.media = self.logic.media(wrong['id'])
        f.media.type = f.kind.TV
        f.media.original_title = wrong['name']
        f.media.title_year = wrong['name'] + ' (' + f.media.year + ')'
        f.media.overview = ''
        f.media.get_poster_image = lambda: ''
        replacement = self.logic.media(right['id'])
        replacement.type = f.kind.TV
        replacement.original_title = right['name']
        replacement.title_year = right['name'] + ' (' + replacement.year + ')'
        replacement.overview = ''
        replacement.get_poster_image = lambda: ''
        f.namespace['tmdb_review_detail'] = lambda cid, sn=None: (
            self.logic.season(cid, sn) if sn is not None else self.logic.data.get(cid))
        f.namespace['collect_tmdb_candidates'] = self.logic.search
        f.namespace['force_recognize_by_id'] = lambda *args: replacement
        submit = f.namespace['DownloadChain']().download_single
        def capture(**kwargs):
            self.contexts.append(kwargs['context'])
            return submit(**kwargs)
        download = f.namespace['DownloadChain']().download_torrent
        f.namespace['DownloadChain'] = lambda: N(download_torrent=download, download_single=capture)
        f.plugin.chain.media_exists = Mock(return_value=None)
        return f

    def assert_capacity_only_submitted_unchanged(self, ep, capacities, year):
        current = show(1, '动画样本', year, [16], capacities)
        f = self.prepare(current, current)
        f.run_round([f.release(f'S01E{ep}', eps=(ep,), description='类别：动画年份：2026')])
        self.assertEqual(len(self.contexts), 1)
        ctx = self.contexts[0]
        self.assertEqual((ctx.media_info.tmdb_id, ctx.meta_info.begin_season), (1, 1))
        self.assertEqual(ctx.meta_info._rss_actual_episodes, {ep})
        self.assertTrue(any('RSS_RECOGNITION_REVIEW_SUSPECT' in line for line in f.logs))

    def test_production_capacity_only_13_is_submitted_unchanged(self):
        self.assert_capacity_only_submitted_unchanged(13, [(1, 12, 2026)], 2026)

    def test_production_cumulative_25_is_submitted_without_offset(self):
        self.assert_capacity_only_submitted_unchanged(25, [(1, 12, 2025), (2, 13, 2026)], 2025)

    def test_production_reidentified_genre_conflict_never_submits(self):
        f = self.prepare(RUN_WRONG, RUN_RIGHT)
        replacement = f.namespace['force_recognize_by_id']()
        replacement.genre_ids = [16]
        f.run_round([f.release('S01E827', eps=(827,), description=RUN_DESC)])
        self.assertEqual(self.contexts, [])
        self.assertTrue(any('年份/类别不一致' in line for line in f.logs))

    def test_running_man_production_check_uses_correct_context(self):
        f = self.prepare(RUN_WRONG, RUN_RIGHT)
        f.run_round([f.release('S01E827', eps=(827,), description=RUN_DESC)])
        self.assertEqual(len(self.contexts), 1)
        ctx = self.contexts[0]
        self.assertEqual((ctx.meta_info.tmdbid, ctx.media_info.tmdb_id, ctx.meta_info.begin_season),
                         (33238, 33238, 1))
        self.assertEqual(f.saved['history'][0]['tmdbid'], 33238)
        f.plugin.chain.media_exists.assert_called_once_with(mediainfo=ctx.media_info)

    def test_fights_production_check_maps_before_library_guard_subscription_and_submit(self):
        from unittest.mock import Mock
        f = self.prepare(FIGHT_WRONG, FIGHT_RIGHT)
        f.plugin._action = 'download_subscribe'
        ensure = Mock()
        f.namespace['ensure_subscription'] = ensure
        f.run_round([f.release('S01', eps=range(1, 220), description=FIGHT_DESC)])
        self.assertEqual(len(self.contexts), 1)
        ctx = self.contexts[0]
        self.assertEqual((ctx.meta_info.tmdbid, ctx.media_info.tmdb_id, ctx.meta_info.begin_season),
                         (79481, 79481, 5))
        self.assertEqual(ctx.meta_info.year, ctx.media_info.year)
        self.assertEqual(ctx.meta_info._rss_actual_episodes, set(range(1, 220)))
        self.assertEqual(ensure.call_args.args[1:3], (ctx.media_info, ctx.meta_info))
        f.plugin.chain.media_exists.assert_called_once_with(mediainfo=ctx.media_info)

    def test_proven_conflict_does_not_subscribe_reserve_or_submit(self):
        f = self.prepare(FIGHT_WRONG, FIGHT_RIGHT)
        f.plugin._action = 'download_subscribe'
        ensure = Mock()
        f.namespace['ensure_subscription'] = ensure
        f.run_round([f.release('S01', eps=range(61, 220), description=FIGHT_DESC)])
        self.assertEqual(self.contexts, [])
        ensure.assert_not_called()
        f.plugin.chain.media_exists.assert_not_called()
        self.assertFalse(Path(f.temp.name, 'rss-download-pending.json').exists())
        self.assertEqual(f.saved.get('history'), [])

    def test_existing_hash_still_ensures_verified_subscription_without_resubmitting(self):
        f = self.prepare(RUN_WRONG, RUN_RIGHT)
        f.plugin._action = 'download_subscribe'
        ensure = Mock()
        f.namespace['ensure_subscription'] = ensure
        release = f.release('S01E827', eps=(827,), description=RUN_DESC)
        f.tasks.append({'hash': release['title']})
        f.run_round([release])
        self.assertEqual(self.contexts, [])
        self.assertEqual(ensure.call_args.args[1].tmdb_id, 33238)
        self.assertEqual(ensure.call_args.args[2].tmdbid, 33238)

    def test_actual_cross_season_files_are_not_remapped(self):
        f = self.prepare(FIGHT_WRONG, FIGHT_RIGHT)
        f.run_round([f.release('S01', files=['Show.S01E01.mkv', 'Show.S02E01.mkv'],
                               description=FIGHT_DESC)])
        self.assertEqual(self.contexts, [])
        self.assertTrue(any('RSS_EPISODE_DEFER' in line for line in f.logs))

    def test_resource_specific_correction_not_written_into_recognition_cache(self):
        f = self.prepare(FIGHT_WRONG, FIGHT_RIGHT)
        f.run_round([f.release('S01', size=500, eps=range(1, 220), description=FIGHT_DESC),
                     f.release('S01E01', size=100, eps=(1,))])
        self.assertEqual([c.media_info.tmdb_id for c in self.contexts], [79481, 81500])
        self.assertEqual([c.meta_info.begin_season for c in self.contexts], [5, 1])


if __name__ == '__main__':
    unittest.main()
