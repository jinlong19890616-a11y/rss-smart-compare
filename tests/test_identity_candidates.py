import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / 'rsssubscribe_smart'))
from identity import identity_title_candidates

class IdentityCandidateTests(unittest.TestCase):
    def test_explicit_chinese_description_fallback(self):
        got=identity_title_candidates('Lotus Lantern Fan Xin Wen Tian 2026 2160p', '宝莲灯凡心问天 | 类型：动作 动画 奇幻')
        self.assertEqual(got[0], 'Lotus Lantern Fan Xin Wen Tian 2026 2160p')
        self.assertIn('宝莲灯凡心问天', got)
    def test_explicit_field(self):
        self.assertIn('宝莲灯凡心问天', identity_title_candidates('English 2026', '片名：宝莲灯凡心问天 | 类型：电影'))
    def test_bracket_title(self):
        self.assertIn('宝莲灯凡心问天', identity_title_candidates('[宝莲灯凡心问天] English 2026', ''))
    def test_synopsis_not_used(self):
        self.assertNotIn('这是一个普通故事', identity_title_candidates('English 2026', '这是一个普通故事，讲述英雄的冒险'))
