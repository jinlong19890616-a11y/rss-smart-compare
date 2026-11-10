import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as N
sys.path.insert(0, str(Path(__file__).parents[1] / 'rsssubscribe_smart'))
from preflight import actual_episodes, hash_exists
import test_existing_guard as fixtures

class PreflightTests(unittest.TestCase):
    def test_incomplete_season_has_only_real_episodes(self):
        self.assertEqual(actual_episodes(['X.S01E01.mkv','X.S01E03.mkv','readme.txt'],1),{1,3})
    def test_cross_season_rejected(self):
        with self.assertRaises(ValueError): actual_episodes(['X.S02E01.mkv'],1)
    def test_unknown_rejected(self):
        with self.assertRaises(ValueError): actual_episodes(['movie.mkv'],1)
    def test_multi_episode_file_rejected(self):
        with self.assertRaises(ValueError): actual_episodes(['X.S01E01-E03.mkv'],1)
    def test_existing_hash_case_insensitive(self):
        m=N(get_instances=lambda:{'qb':N(get_torrents=lambda:([{'hash':'ABC'}],False))})
        self.assertTrue(hash_exists(m,'abc'))
        self.assertFalse(hash_exists(m,'def'))
    def test_query_failure_does_not_allow(self):
        m=N(get_instances=lambda:{'qb':N(get_torrents=lambda:(None,True))})
        with self.assertRaises(RuntimeError): hash_exists(m,'abc')

class ActualScopeTests(fixtures.Tests):
    def test_actual_episodes_override_inferred_full_season(self):
        self.meta.episode_list=list(range(1,41));self.meta._rss_actual_episodes={1,2}
        self.assertTrue(self.guard().decide(self.media,self.meta,N(seasons={1:[1,2]}))[0])
    def test_full_pack_cap_excludes_only_capped_episode(self):
        self.meta.episode_list=[2,3];self.meta._rss_resolution=2160
        tasks=[{'hash':'a','name':'X.1080p','state':'downloading'}, {'hash':'b','name':'X.1080p','state':'downloading'}]
        row=self.row()
        servers={h:N(get_torrents=lambda t=t:([t],False),get_files=lambda h:[{'name':'X.S01E02.1080p.mkv','size':10 if h=='a' else 20,'priority':1}]) for h,t in zip(['a','b'],tasks)}
        from smart_guard import Guard
        g=Guard(self.root,N(get_instances=lambda:servers),N(get_by_hashes=lambda hs:{h:N(type='电视剧',tmdbid=123,seasons='S01',downloader=h) for h in hs}),None)
        self.assertEqual(g.decide(self.media,self.meta,None),(None,{3}))
