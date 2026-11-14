import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as N
sys.path.insert(0, str(Path(__file__).parents[1] / 'rsssubscribe_smart'))
from identity import identity_title_candidates, is_ambiguous_english_title
class IdentityAmbiguityTests(unittest.TestCase):
    def test_generic_wrong_year_defers(self):
        self.assertTrue(is_ambiguous_english_title('Wonderland',N(year='2018'),N(year='2026')))
    def test_generic_matching_year_allowed(self):
        self.assertFalse(is_ambiguous_english_title('Wonderland',N(year='2026'),N(year='2026')))
    def test_specific_english_allowed(self):
        self.assertFalse(is_ambiguous_english_title('The Last of Us',N(year='2023'),N(year='2023')))
    def test_explicit_chinese_field(self):
        self.assertIn('五十公里桃花坞',identity_title_candidates('Wonderland 2026','中文名：五十公里桃花坞 | 类型：综艺'))
