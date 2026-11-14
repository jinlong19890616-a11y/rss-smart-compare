import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / 'rsssubscribe_smart'))
from preflight import (DeferCache, looks_like_torrent,
                       torrent_payload_diagnostic)


class TorrentPayloadTests(unittest.TestCase):
    def test_bencoded_torrent_accepted(self):
        self.assertTrue(looks_like_torrent(b'd8:announce4:infod6:lengthi1e4:name1:aee'))

    def test_site_error_pages_rejected(self):
        for payload in (b'{"error":"rate limited"}', b'<html>login</html>',
                        None, 'd8:announce', b'd'):
            self.assertFalse(looks_like_torrent(payload), payload)

    def test_diagnostic_redacts_link_credentials(self):
        raw = b'{"url":"https://site/rss?sign=SECRET&uid=42&t=123","error":"x"}'
        message = torrent_payload_diagnostic(raw)
        self.assertNotIn('SECRET', message)
        self.assertIn('redacted', message)
        self.assertIn('len=', message)


class DeferCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = self.temp.name

    def tearDown(self):
        self.temp.cleanup()

    def test_unseen_resource_is_not_deferred(self):
        cache = DeferCache(self.root)
        cache.begin_round()
        self.assertFalse(cache.is_deferred(('Movie 2026', '12345')))

    def test_marked_resource_survives_reload(self):
        cache = DeferCache(self.root)
        cache.mark(('Movie 2026', '12345'), 'non-torrent payload')
        DeferCache(self.root).begin_round()
        reloaded = DeferCache(self.root)
        reloaded.begin_round()
        self.assertTrue(reloaded.is_deferred(('Movie 2026', '12345')))

    def test_other_resources_are_not_suppressed(self):
        cache = DeferCache(self.root)
        cache.mark(('Movie 2026', '12345'), 'non-torrent payload')
        cache.begin_round()
        self.assertFalse(cache.is_deferred(('Better Release 2026', '99999')))

    def test_rotating_link_signature_still_hits_backoff(self):
        """M-Team signs download links per poll; backoff must key on title+size."""
        cache = DeferCache(self.root)
        releases = [
            ('Aswang 1994 1080p BluRay', '32487000000',
             'https://rss.example/dlv2?sign=AAA&t=1794610800&tid=1&uid=2'),
            ('Aswang 1994 1080p BluRay', '32487000000',
             'https://rss.example/dlv2?sign=BBB&t=1794625200&tid=1&uid=2'),
        ]
        self.assertNotEqual(releases[0][2], releases[1][2])
        for index, (title, size, url) in enumerate(releases):
            cache.begin_round()
            stable_key = (title, size)
            if index == 0:
                self.assertFalse(cache.is_deferred(stable_key))
                cache.mark(stable_key, 'non-torrent payload')
            else:
                self.assertTrue(cache.is_deferred(stable_key))

    def test_expired_entries_are_dropped(self):
        cache = DeferCache(self.root, ttl_seconds=1)
        cache.mark(('Movie', '1'), 'x')
        time.sleep(1.1)
        cache.begin_round()
        self.assertFalse(cache.is_deferred(('Movie', '1')))

    def test_cache_is_bounded(self):
        cache = DeferCache(self.root, max_entries=3)
        for i in range(6):
            cache.mark((f'item{i}', str(i)), 'r')
        cache.begin_round()
        self.assertEqual(len(cache._round), 3)


if __name__ == '__main__':
    unittest.main()
