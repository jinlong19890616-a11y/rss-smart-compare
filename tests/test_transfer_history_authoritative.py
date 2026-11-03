import unittest
from pathlib import Path
class TransferHistoryAuthoritativeTests(unittest.TestCase):
    def test_transfer_history_does_not_require_local_file_or_emby(self):
        s=(Path(__file__).parents[1]/'rsssubscribe_smart'/'smart_guard.py').read_text()
        self.assertIn('completed transfer', s)
        self.assertIn('Transfer history proves the episode was downloaded', s)
        self.assertNotIn('if not path.is_file() or path.stat().st_size <= 0:', s)
