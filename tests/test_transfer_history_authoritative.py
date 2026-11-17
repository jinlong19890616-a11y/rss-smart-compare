import unittest
from pathlib import Path
class TransferHistoryAuthoritativeTests(unittest.TestCase):
    def test_transfer_history_does_not_require_local_file_or_emby(self):
        s=(Path(__file__).parents[1]/'rsssubscribe_smart'/'smart_guard.py').read_text()
        self.assertIn('status is the authoritative completed-download fact', s)
        self.assertIn('covered.add(pair[1])', s)
        self.assertNotIn('if not path.is_file() or path.stat().st_size <= 0:', s)
