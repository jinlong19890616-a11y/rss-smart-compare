import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parents[1] / 'rsssubscribe_smart'))
from file_selection_plan import build_plan, file_pair

class FilePlanTests(unittest.TestCase):
    def test_pair(self):
        self.assertEqual(file_pair('Season 1/Show.S01E03.mkv'), (1,3))
        self.assertIsNone(file_pair('Show.S01E01-E05.mkv'))
        self.assertIsNone(file_pair('Show.S01E03.nfo'))

    def test_partial_season_plan(self):
        files=[
            {'index':0,'name':'Show.S01E01.mkv'},
            {'index':1,'name':'Show.S01E02.mkv'},
            {'index':2,'name':'Show.S01E03.mkv'},
            {'index':3,'name':'Show.S01E04.mkv'},
        ]
        p=build_plan(files,1,{1,2,4})
        self.assertEqual(p['status'],'apply')
        self.assertEqual([x['episode'] for x in p['decisions'] if x['action']=='download'],[3])
        self.assertEqual([x['priority'] for x in p['decisions'] if x['action']=='skip'],[0,0,0])

    def test_complete_season_skips(self):
        files=[{'index':0,'name':'Show.S01E01.mkv'},{'index':1,'name':'Show.S01E02.mkv'}]
        p=build_plan(files,1,{1,2})
        self.assertEqual(p['status'],'skip')

    def test_unknown_file_defers(self):
        files=[{'index':0,'name':'Show.S01E01.mkv'},{'index':1,'name':'Show-special.mkv'}]
        self.assertEqual(build_plan(files,1,{1})['status'],'defer')

    def test_archive_defers(self):
        files=[{'index':0,'name':'Show.S01E01.zip'}]
        self.assertEqual(build_plan(files,1,set())['status'],'defer')

if __name__ == '__main__': unittest.main(verbosity=2)
