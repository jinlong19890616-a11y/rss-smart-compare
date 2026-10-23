import unittest
from pathlib import Path
from types import SimpleNamespace as N
import sys
sys.path.insert(0, str(Path(__file__).parents[1] / 'rsssubscribe_smart'))
from smart_guard import Guard, explicit_pairs, selected_pairs, rule_matches, has_chinese_subtitle, blocks, same_release

class Tests(unittest.TestCase):
    def setUp(self):
        self.media=N(type=N(value='电视剧'), tmdb_id=123)
        self.meta=N(begin_season=1, season_list=[1], episode_list=[1,2,3,4,5])
        self.g=Guard('/Volumes/mac资料盘/rss-smart-compare/test-runtime', N(get_instances=lambda:{'qb':N(get_torrents=lambda:([],False))}), N(get_by_hashes=lambda hashes:{}), None)
    def test_parse_single_and_pack(self):
        self.assertEqual(explicit_pairs('Show.S01E03.mkv'), (1,3))
        self.assertIsNone(explicit_pairs('Show.S01E01-E05'))
    def test_library_missing_episodes(self):
        reason, missing=self.g.decide(self.media,self.meta,N(seasons={1:[1,2,4]}))
        self.assertIsNone(reason); self.assertEqual(missing,{3,5})
    def test_library_complete_skips(self):
        reason,missing=self.g.decide(self.media,self.meta,N(seasons={1:[1,2,3,4,5]}))
        self.assertTrue(reason); self.assertIsNone(missing)
    def test_selected_pack_only_missing(self):
        files=[{'name':f'Show.S01E{i:02}.mkv','priority':1} for i in range(1,6)]
        self.assertEqual(selected_pairs(files), {(1,1),(1,2),(1,3),(1,4),(1,5)})
    def test_same_release_guard(self):
        self.assertTrue(same_release('Cycle Love 2024 S01 Complete 2160p WEB-DL', '[循环恋爱中].Cycle.Love.2024.S01.2160p.WEB-DL', 1))
        self.assertFalse(same_release('Great Performances S51E07 1080p PBS', 'Other Show S51E07 1080p', 51))

    def test_size_upgrade_guard(self):
        self.assertTrue(blocks(2160, 2160, 3 * 1024**3, 16 * 1024**3))
        self.assertFalse(blocks(2160, 2160, 16 * 1024**3, 3 * 1024**3))
        self.assertTrue(blocks(1080, 2160, 15 * 1024**3, 3 * 1024**3))
        self.assertFalse(blocks(2160, 1080, 3 * 1024**3, 15 * 1024**3))

    def test_media_rules(self):
        self.assertEqual(rule_matches('Show.S01E01.1080p.WEB-DL', 1080, 'any'), (True, ''))
        self.assertFalse(rule_matches('Show.S01E01.720p.WEB-DL', 1080, 'any')[0])
        self.assertTrue(rule_matches('Show.S01E01.1080p.中字', 1080, 'required')[0])
        self.assertFalse(rule_matches('Show.S01E01.1080p.WEB-DL', 1080, 'required')[0])
        self.assertTrue(has_chinese_subtitle('Movie.1080p.CHS'))
        self.assertTrue(has_chinese_subtitle('Movie.1080p.内封中字'))
        self.assertTrue(has_chinese_subtitle('Movie.1080p.&amp;#x4E2D;&amp;#x5B57;'))
        self.assertTrue(has_chinese_subtitle('字幕素材：简体中文字幕'))
        self.assertTrue(has_chinese_subtitle('外挂中文软字幕'))
        self.assertFalse(has_chinese_subtitle('国语 粤语 双音轨'))

if __name__=='__main__': unittest.main(verbosity=2)
