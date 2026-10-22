import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as N
import sys
sys.path.insert(0, str(Path(__file__).parents[1] / 'rsssubscribe_smart'))
from smart_guard import Guard, exclusive, selected_pairs

class Server:
    def __init__(self, tasks=None, files=None, error=False):
        self.tasks=tasks or []; self.files=files or []; self.error=error
    def get_torrents(self): return self.tasks, self.error
    def get_files(self, h): return self.files

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
        self.media=N(type=N(value='电视剧'),tmdb_id=123)
        self.meta=N(begin_season=1,season_list=[1],episode_list=[2])
    def tearDown(self): self.tmp.cleanup()
    def guard(self, tasks=None, files=None, row=None, error=False):
        server=Server(tasks,files,error)
        return Guard(self.root,N(get_instances=lambda:{'qb':server}),
                     N(get_by_hashes=lambda hs:{'abc':row} if row else {}),None)
    def task(self): return [{'hash':'abc','state':'downloading','tags':'MOVIEPILOT'}]
    def row(self): return N(type='电视剧',tmdbid=123,seasons='S01',downloader='qb')
    def file(self, ep=2, priority=1): return {'name':f'X.S01E{ep:02}.mkv','priority':priority}
    def test_empty_allows(self): self.assertEqual(self.guard().decide(self.media,self.meta,None),(None,None))
    def test_live_duplicate(self): self.assertTrue(self.guard(self.task(),[self.file()],self.row()).decide(self.media,self.meta,None)[0])
    def test_other_episode_allows(self): self.assertEqual(self.guard(self.task(),[self.file(3)],self.row()).decide(self.media,self.meta,None),(None,None))
    def test_partial_pack(self):
        self.meta.episode_list=[2,3]
        self.assertEqual(self.guard(self.task(),[self.file()],self.row()).decide(self.media,self.meta,None),(None,{3}))
    def test_unselected_not_covered(self): self.assertIsNone(selected_pairs([self.file(priority=0)]))
    def test_library_blocks(self): self.assertTrue(self.guard().decide(self.media,self.meta,N(seasons={1:[2]}))[0])
    def test_pending_then_expiry(self):
        g=self.guard();g.reserve(self.media,self.meta,'abc');self.assertTrue(g.decide(self.media,self.meta,None)[0])
        import json
        entries=json.loads(g.pending.read_text());entries[0]['time']-=121;g.pending.write_text(json.dumps(entries))
        self.assertEqual(g.decide(self.media,self.meta,None),(None,None))
    def test_query_failure_defers(self):
        with self.assertRaises(RuntimeError): self.guard(error=True).decide(self.media,self.meta,None)
    def test_missing_mapping_defers(self):
        with self.assertRaises(RuntimeError): self.guard(self.task()).decide(self.media,self.meta,None)
    def test_unknown_pack_overlap_defers(self):
        self.meta.episode_list=[]
        with self.assertRaises(RuntimeError): self.guard(self.task(),[self.file()],self.row()).decide(self.media,self.meta,None)
    def test_failed_task_allows_retry(self):
        t=self.task();t[0]['state']='error'
        self.assertEqual(self.guard(t,[self.file()],self.row()).decide(self.media,self.meta,None),(None,None))
    def test_movie(self):
        self.media.type.value='电影';r=self.row();r.type='电影'
        self.assertTrue(self.guard(self.task(),[],r).decide(self.media,self.meta,None)[0])
    def test_special_season_zero(self):
        self.meta.begin_season=0;self.meta.season_list=[0]
        self.assertTrue(self.guard().decide(self.media,self.meta,N(seasons={0:[2]}))[0])
    def test_exclusive_lock_timeout(self):
        with exclusive(self.root):
            with self.assertRaises(RuntimeError):
                with exclusive(self.root,timeout=0): pass
    def test_multiseason_defer(self):
        self.meta.season_list=[1,2]
        with self.assertRaises(RuntimeError): self.guard().decide(self.media,self.meta,None)

    def test_transferred_file_blocks_without_live_torrent_or_library(self):
        p=self.root/'Show.S01E02.mkv';p.write_bytes(b'video')
        g=self.guard();g.transferred=lambda ident,season:[N(dest=str(p))]
        self.assertTrue(g.decide(self.media,self.meta,None)[0])
    def test_stale_transfer_missing_file_allows(self):
        g=self.guard();g.transferred=lambda ident,season:[N(dest=str(self.root/'missing.S01E02.mkv'))]
        self.assertEqual(g.decide(self.media,self.meta,None),(None,None))
    def test_transferred_partial_pack(self):
        p=self.root/'Show.S01E02.mkv';p.write_bytes(b'video')
        g=self.guard();g.transferred=lambda ident,season:[N(dest=str(p))]
        self.meta.episode_list=[2,3]
        self.assertEqual(g.decide(self.media,self.meta,None),(None,{3}))
    def test_transferred_movie(self):
        p=self.root/'movie.mkv';p.write_bytes(b'video')
        g=self.guard();g.transferred=lambda ident,season:[N(dest=str(p))]
        self.media.type.value='电影'
        self.assertTrue(g.decide(self.media,self.meta,None)[0])
    def test_zero_size_transfer_not_trusted(self):
        p=self.root/'Show.S01E02.mkv';p.touch()
        g=self.guard();g.transferred=lambda ident,season:[N(dest=str(p))]
        self.assertEqual(g.decide(self.media,self.meta,None),(None,None))

    def test_2160_allows_after_1080_transfer(self):
        p=self.root/'Show.S01E02.1080p.mkv';p.write_bytes(b'video')
        g=self.guard();g.transferred=lambda ident,season:[N(dest=str(p))]
        self.meta._rss_resolution=2160
        self.assertEqual(g.decide(self.media,self.meta,N(seasons={1:[2]})),(None,None))
    def test_2160_blocks_after_2160_transfer(self):
        p=self.root/'Show.S01E02.2160p.mkv';p.write_bytes(b'video')
        g=self.guard();g.transferred=lambda ident,season:[N(dest=str(p))]
        self.meta._rss_resolution=2160
        self.assertTrue(g.decide(self.media,self.meta,None)[0])
    def test_1080_blocks_after_2160_transfer(self):
        p=self.root/'Show.S01E02.2160p.mkv';p.write_bytes(b'video')
        g=self.guard();g.transferred=lambda ident,season:[N(dest=str(p))]
        self.meta._rss_resolution=1080
        self.assertTrue(g.decide(self.media,self.meta,None)[0])
    def test_2160_allows_after_live1080(self):
        f=self.file();f['name']='Show.S01E02.1080p.mkv'
        g=self.guard(self.task(),[f],self.row());self.meta._rss_resolution=2160
        self.assertEqual(g.decide(self.media,self.meta,None),(None,None))
    def test_2160_blocks_after_live2160(self):
        f=self.file();f['name']='Show.S01E02.2160p.mkv'
        g=self.guard(self.task(),[f],self.row());self.meta._rss_resolution=2160
        self.assertTrue(g.decide(self.media,self.meta,None)[0])
    def test_pending1080_allows2160(self):
        g=self.guard();self.meta._rss_resolution=1080;g.reserve(self.media,self.meta,'abc')
        self.meta._rss_resolution=2160
        self.assertEqual(g.decide(self.media,self.meta,None),(None,None))
    def test_pending2160_blocks1080(self):
        g=self.guard();self.meta._rss_resolution=2160;g.reserve(self.media,self.meta,'abc')
        self.meta._rss_resolution=1080
        self.assertTrue(g.decide(self.media,self.meta,None)[0])
    def test_movie2160_allows1080_transfer(self):
        p=self.root/'Movie.1080p.mkv';p.write_bytes(b'video')
        g=self.guard();g.transferred=lambda ident,season:[N(dest=str(p))]
        self.media.type.value='电影';self.meta._rss_resolution=2160
        self.assertEqual(g.decide(self.media,self.meta,N()),(None,None))
    def test_unknown_resolution_not_upgrade_evidence(self):
        p=self.root/'Show.S01E02.mkv';p.write_bytes(b'video')
        g=self.guard();g.transferred=lambda ident,season:[N(dest=str(p))]
        self.meta._rss_resolution=2160
        self.assertTrue(g.decide(self.media,self.meta,None)[0])

if __name__=='__main__': unittest.main(verbosity=2)
