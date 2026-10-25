import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import Mock
sys.path.insert(0, str(Path(__file__).parents[1] / 'rsssubscribe_smart'))
from subscription_flow import ensure_subscription

class SubscriptionTests(unittest.TestCase):
    def setUp(self):
        self.media=N(tmdb_id=42, title='Show', title_year='Show (2026)',year='2026',type='电视剧')
        self.meta=N(begin_season=1, season_list=[1])
        self.logger=Mock()
        self.chain=Mock()
        self.chain.exists.return_value=False
    def test_success_checks_return_id(self):
        self.chain.add.return_value=(12, '')
        self.assertTrue(ensure_subscription(self.chain,self.media,self.meta,self.logger))
        self.chain.add.assert_called_once()
    def test_failed_add_is_not_reported_success_and_retries(self):
        self.chain.add.return_value=(None, 'failed')
        for _ in range(2):
            self.assertFalse(ensure_subscription(self.chain,self.media,self.meta,self.logger))
        self.assertEqual(self.chain.add.call_count,2)
        self.logger.info.assert_not_called()
    def test_existing_does_not_add(self):
        self.chain.exists.return_value=True
        self.assertTrue(ensure_subscription(self.chain,self.media,self.meta,self.logger))
        self.chain.add.assert_not_called()
    def test_exception_does_not_block_download_caller(self):
        self.chain.add.side_effect=RuntimeError('private api payload')
        self.assertFalse(ensure_subscription(self.chain,self.media,self.meta,self.logger))
        self.assertNotIn('private',str(self.logger.warning.call_args))
    def test_cross_season_rejected(self):
        self.meta.season_list=[1,2]
        self.assertFalse(ensure_subscription(self.chain,self.media,self.meta,self.logger))
        self.chain.add.assert_not_called()
    def test_subscription_precedes_download_and_guard(self):
        source=(Path(__file__).parents[1]/'rsssubscribe_smart'/'__init__.py').read_text()
        self.assertLess(source.index('ensure_subscription(subscribechain'),source.index('guard.decide('))
        self.assertLess(source.index('ensure_subscription(subscribechain'),source.index('downloadchain.download_single('))
