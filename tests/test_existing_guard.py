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

    def quality_meta(self, episodes, size=100, resolution=2160):
        self.meta.episode_list = episodes
        mark = f'S01E{episodes[0]:02}' if len(episodes) == 1 else 'S01.Complete'
        self.meta.org_string = f'Cycle.Love.{mark}.{resolution}p.WEB-DL'
        self.meta._rss_resolution = resolution
        self.meta._rss_size = size

    def quality_task(self, resolution=2160):
        tasks = self.task()
        tasks[0].update(name=f'Cycle.Love.S01.Complete.{resolution}p.WEB-DL', size=1000)
        return tasks

    def quality_files(self, resolution=2160):
        return [{'name': f'Cycle.Love.S01E{ep:02}.{resolution}p.mkv',
                 'priority': 1, 'size': 10} for ep in (2, 3)]

    def test_pack_total_does_not_upgrade_live_episode_files(self):
        self.quality_meta([2, 3])
        g = self.guard(self.quality_task(), self.quality_files(), self.row())
        self.assertTrue(g.decide(self.media, self.meta, None)[0])

    def test_unknown_pack_total_does_not_upgrade_live_episode_files(self):
        self.quality_meta([])
        g = self.guard(self.quality_task(), self.quality_files(), self.row())
        with self.assertRaises(RuntimeError):
            g.decide(self.media, self.meta, None)

    def test_pack_total_does_not_upgrade_transferred_episode_files(self):
        self.quality_meta([2, 3])
        p = self.root / 'Cycle.Love.S01E02.2160p.mkv'
        p.write_bytes(b'0123456789')
        g = self.guard()
        g.transferred = lambda ident, season: [N(dest=str(p))]
        self.assertEqual(g.decide(self.media, self.meta, None), (None, {3}))

    def test_pack_selected_subset_does_not_turn_total_into_episode_size(self):
        self.quality_meta([2])
        self.meta.org_string = 'Cycle.Love.S01.Complete.2160p.WEB-DL'
        g = self.guard(self.quality_task(), self.quality_files(), self.row())
        self.assertTrue(g.decide(self.media, self.meta, None)[0])

    def test_same_title_disabled_episode_not_covered(self):
        self.quality_meta([2, 3])
        files = self.quality_files()
        files[1]['priority'] = 0
        g = self.guard(self.quality_task(), files, self.row())
        self.assertEqual(g.decide(self.media, self.meta, None), (None, {3}))

    def test_same_title_all_disabled_does_not_cover(self):
        self.quality_meta([2, 3])
        files = self.quality_files()
        for f in files:
            f['priority'] = 0
        g = self.guard(self.quality_task(), files, self.row())
        self.assertEqual(g.decide(self.media, self.meta, None), (None, None))

    def test_selected_archive_still_defers_unknown_coverage(self):
        self.quality_meta([2, 3])
        files = [{'name': 'Cycle.Love.S01.Complete.rar', 'priority': 1}]
        g = self.guard(self.quality_task(), files, self.row())
        with self.assertRaises(RuntimeError):
            g.decide(self.media, self.meta, None)

    def test_same_title_different_resolution_allows_upgrade(self):
        self.quality_meta([2, 3])
        g = self.guard(self.quality_task(1080), self.quality_files(1080), self.row())
        self.assertEqual(g.decide(self.media, self.meta, None), (None, None))

    def test_same_title_single_episode_size_upgrade_uses_file_not_pack_total(self):
        self.quality_meta([2])
        g = self.guard(self.quality_task(), self.quality_files(), self.row())
        self.assertEqual(g.decide(self.media, self.meta, None), (None, None))

    def test_missing_file_size_does_not_fall_back_to_torrent_total(self):
        self.quality_meta([2])
        files = self.quality_files()
        for f in files:
            del f['size']
        tasks = self.quality_task()
        tasks[0]['size'] = 1
        g = self.guard(tasks, files, self.row())
        self.assertTrue(g.decide(self.media, self.meta, None)[0])

    def test_pack_pending_total_is_never_episode_size(self):
        self.quality_meta([2, 3], size=10)
        g = self.guard()
        g.reserve(self.media, self.meta, 'abc', selected={2})
        self.quality_meta([2], size=100)
        self.assertTrue(g.decide(self.media, self.meta, None)[0])

    def test_single_episode_pending_size_upgrade(self):
        self.quality_meta([2], size=10)
        g = self.guard()
        g.reserve(self.media, self.meta, 'abc')
        self.meta._rss_size = 100
        self.assertEqual(g.decide(self.media, self.meta, None), (None, None))

    def test_legacy_pending_total_not_used_for_episode_size(self):
        import json
        self.quality_meta([2], size=10)
        g = self.guard()
        g.reserve(self.media, self.meta, 'abc')
        entries = json.loads(g.pending.read_text())
        del entries[0]['size_episode']
        g.pending.write_text(json.dumps(entries))
        self.meta._rss_size = 100
        self.assertTrue(g.decide(self.media, self.meta, None)[0])

    def test_same_title_movie_different_quality_not_fuzzy_blocked(self):
        self.quality_meta([2], size=2000)
        self.media.type.value = '电影'
        row = self.row()
        row.type = '电影'
        g = self.guard(self.quality_task(1080), [], row)
        self.assertEqual(g.decide(self.media, self.meta, None), (None, None))

    def test_smaller_2160_episode_does_not_replace_larger_1080(self):
        self.quality_meta([2], size=5)
        g = self.guard(self.quality_task(1080), self.quality_files(1080), self.row())
        self.assertTrue(g.decide(self.media, self.meta, None)[0])

    def test_resolution_upgrade_not_broadened_in_guard(self):
        for old, new in ((720, 1080), (720, 2160), (2160, 4320)):
            with self.subTest(old=old, new=new):
                self.quality_meta([2], resolution=new)
                g = self.guard(self.quality_task(old), self.quality_files(old), self.row())
                self.assertTrue(g.decide(self.media, self.meta, None)[0])

    def test_movie_low_copy_does_not_override_existing_high_copy(self):
        self.media.type.value = '电影'
        self.quality_meta([2], size=100)
        low = self.root / 'Movie.1080p.mkv'
        high = self.root / 'Movie.2160p.mkv'
        low.write_bytes(b'0123456789')
        high.write_bytes(b'x' * 200)
        for paths in ((low, high), (high, low)):
            with self.subTest(paths=paths):
                g = self.guard()
                g.transferred = lambda ident, season: [N(dest=str(p)) for p in paths]
                self.assertTrue(g.decide(self.media, self.meta, N())[0])

    def test_episode_low_copy_does_not_override_existing_high_copy(self):
        self.quality_meta([2], size=100)
        low = self.root / 'Show.S01E02.1080p.mkv'
        high = self.root / 'Show.S01E02.2160p.mkv'
        low.write_bytes(b'0123456789')
        high.write_bytes(b'x' * 200)
        for paths in ((low, high), (high, low)):
            with self.subTest(paths=paths):
                g = self.guard()
                g.transferred = lambda ident, season: [N(dest=str(p)) for p in paths]
                self.assertTrue(g.decide(self.media, self.meta, N(seasons={1:[2]}))[0])

    def test_strm_transfer_is_not_quality_evidence(self):
        self.quality_meta([2])
        p = self.root / 'Cycle.Love.S01E02.2160p.strm'
        p.write_bytes(b'https://example.invalid/video')
        g = self.guard()
        g.transferred = lambda ident, season: [N(dest=str(p))]
        self.assertEqual(g.decide(self.media, self.meta, None), (None, None))

if __name__=='__main__': unittest.main(verbosity=2)
