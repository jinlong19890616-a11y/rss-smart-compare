import unittest
from pathlib import Path
import sys
import types
import importlib.util
ROOT = Path(__file__).parents[1]
pkg = types.ModuleType('rsssubscribe_smart')
pkg.__path__ = [str(ROOT / 'rsssubscribe_smart')]
sys.modules['rsssubscribe_smart'] = pkg
spec = importlib.util.spec_from_file_location('rsssubscribe_smart.qbittorrent_adapter', ROOT / 'rsssubscribe_smart/qbittorrent_adapter.py')
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
add_and_plan = module.add_and_plan

class FakeQbit:
    def __init__(self, files):
        self.files=files
        self.calls=[]
    def add_torrent(self, torrent_url, save_path=None):
        self.calls.append(('add',torrent_url,save_path)); return 'abc123'
    def get_files(self, torrent_hash):
        self.calls.append(('files',torrent_hash)); return self.files
    def set_file_priority(self, torrent_hash, file_ids, priority):
        self.calls.append(('priority',torrent_hash,sorted(file_ids),priority))

class AdapterTests(unittest.TestCase):
    def test_partial_pack_applies_priorities(self):
        q=FakeQbit([{'index':i,'name':f'Show.S01E{i+1:02}.mkv'} for i in range(5)])
        result=add_and_plan(q,'magnet:?xt=urn:test',1,{1,2,4},'/downloads')
        self.assertEqual(result.status,'apply')
        self.assertEqual(result.skipped_ids,[0,1,3])
        self.assertEqual(result.download_ids,[2,4])
        self.assertIn(('priority','abc123',[0,1,3],0),q.calls)
        self.assertIn(('priority','abc123',[2,4],1),q.calls)

    def test_complete_pack_skips_without_download_priority(self):
        q=FakeQbit([{'index':i,'name':f'Show.S01E{i+1:02}.mkv'} for i in range(2)])
        result=add_and_plan(q,'magnet:?xt=urn:test',1,{1,2})
        self.assertEqual(result.status,'skip')
        self.assertEqual(result.skipped_ids,[0,1])
        self.assertNotIn(('priority','abc123',[0,1],1),q.calls)

    def test_unknown_file_never_applies(self):
        q=FakeQbit([{'index':0,'name':'Show.S01E01.mkv'},{'index':1,'name':'Show-cover.mkv'}])
        result=add_and_plan(q,'magnet:?xt=urn:test',1,{1})
        self.assertEqual(result.status,'defer')
        self.assertFalse(any(call[0]=='priority' for call in q.calls))

if __name__=='__main__': unittest.main(verbosity=2)
