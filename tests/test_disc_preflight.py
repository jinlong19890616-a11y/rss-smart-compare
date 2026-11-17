import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'rsssubscribe_smart'))
from preflight import disc_format_reason


class DiscPreflightTests(unittest.TestCase):
    def test_cleaner_disc_extensions(self):
        for suffix in ('.iso', '.m2ts', '.vob', '.ifo', '.bup', '.bdmv', '.mpls', '.clpi'):
            with self.subTest(suffix=suffix):
                self.assertEqual(disc_format_reason(['movie/FILE' + suffix.upper()]), 'disc_format')

    def test_disc_directories_case_and_separator(self):
        for path in ('movie/BDMV/STREAM/data.bin', 'movie/video_ts/file.bin',
                     r'movie\bDmV\BACKUP\index.bin'):
            with self.subTest(path=path):
                self.assertTrue(disc_format_reason([path]))

    def test_bluray_remux_containers_allowed(self):
        self.assertIsNone(disc_format_reason([
            'Movie.2160p.BluRay.REMUX.mkv', 'extras/clip.mp4',
            'Movie.BDMV.release.mkv', 'subs/Chinese.srt']))

    def test_mixed_release_rejected(self):
        self.assertTrue(disc_format_reason(['movie.mkv', 'extras/VIDEO_TS/VTS_01_1.VOB']))

    def test_missing_list_not_classified_as_disc(self):
        self.assertIsNone(disc_format_reason(None))
        self.assertIsNone(disc_format_reason([]))

    def test_same_round_can_fall_back_to_non_disc(self):
        releases = [(['Movie/BDMV/index.bdmv'], 'disc'),
                    (['Movie.2160p.REMUX.mkv'], 'remux'),
                    (['Movie.1080p.mkv'], 'smaller')]
        submitted = []
        for files, label in releases:
            if disc_format_reason(files):
                continue
            if submitted:
                continue
            submitted.append(label)
        self.assertEqual(submitted, ['remux'])

    def test_wiring_before_submission_and_reservation(self):
        source = (ROOT / 'rsssubscribe_smart' / '__init__.py').read_text()
        start = source.index('if disc_format_reason(torrent_files):')
        self.assertLess(start, source.index('result = downloadchain.download_single('))
        body = source[start:source.index('if hash_exists(module, torrent_hash):', start)]
        self.assertIn('continue', body)
        self.assertNotIn('reserve(', body)
        self.assertNotIn('submitted_movie_keys.add', body)


if __name__ == '__main__':
    unittest.main()
