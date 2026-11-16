# -*- coding: utf-8 -*-
"""核心纯函数单测（不联网、不读仓库数据）

45 项审计只检查"某段字符串是否还在文件里"，函数改名成 _disabled_xxx 也能 PASS。
这里补上真正跑逻辑的测试，覆盖历史上真实踩过的三个坑：

1. `_split_index` 对 `class.xxx.N` 的拆分——曾把 `class.书名.0` 拆成
   css=`class.书名` 索引=0，导致 1756/2169 个源的选择器全错。
2. host 归一化——`m.hongxiu.com` 在门槛视图没归一到 `hongxiu.com`，
   大厂豁免匹配不上，红袖移动版被误判成僵尸删掉。
3. 静态站豁免——古籍/国学站"最后更新停在建站时"是常态，不能判死。

跑法：python3 -m unittest discover -s tests -v
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from autocollect_core.utils import host_of                      # noqa: E402
from autocollect_core.legado_rules import _split_index         # noqa: E402


class TestHostOf(unittest.TestCase):
    """域名归一化只有一份实现，三处脚本共用"""

    def test_strips_scheme_and_path(self):
        self.assertEqual(host_of("https://www.example.com/a/b?c=1"), "example.com")

    def test_mobile_prefix_same_as_desktop(self):
        # 这是红袖移动版被误删的根因：两者必须归一成同一个 host
        self.assertEqual(host_of("https://m.hongxiu.com"), "hongxiu.com")
        self.assertEqual(host_of("https://www.hongxiu.com"), "hongxiu.com")
        self.assertEqual(host_of("https://wap.ciweimao.com"), "ciweimao.com")
        self.assertEqual(host_of("https://mobile.a.com"), "a.com")

    def test_port_stripped(self):
        self.assertEqual(host_of("http://a.com:8080/x"), "a.com")

    def test_bare_host_and_empty(self):
        self.assertEqual(host_of("a.com/path"), "a.com")
        self.assertEqual(host_of(""), "")
        self.assertEqual(host_of(None), "")

    def test_subdomain_not_collapsed(self):
        # book.xxx.com 不是移动版前缀，不能被当成主域
        self.assertEqual(host_of("http://book.xxx.com"), "book.xxx.com")


class TestSplitIndex(unittest.TestCase):
    """Legado 索引语法解析"""

    def test_plain_index(self):
        self.assertEqual(_split_index("a.0"), ("a", "index", 0))

    def test_negative_index(self):
        self.assertEqual(_split_index("a.-1"), ("a", "index", -1))

    def test_exclude(self):
        self.assertEqual(_split_index("tag.tr!0"), ("tr", "exclude", 0))
        self.assertEqual(_split_index("tag.tr!-1"), ("tr", "exclude", -1))

    def test_slice(self):
        self.assertEqual(_split_index("a[0:10]"), ("a", "slice", (0, 10)))
        self.assertEqual(_split_index("a[1:]"), ("a", "slice", (1, None)))

    def test_parent_selector_kept(self):
        self.assertEqual(_split_index("h4 a.0"), ("h4 a", "index", 0))

    def test_class_prefix_not_mistaken_for_index(self):
        # 回归：class.a 曾被误判成 css='class' + 索引，导致 .a 选择器丢失
        self.assertIsNone(_split_index("class.a"))
        self.assertIsNone(_split_index("plain"))


class TestStaticExempt(unittest.TestCase):
    """静态内容站豁免：古籍/国学/诗词/典籍"""

    def setUp(self):
        from scripts.deep_gate import is_static
        self.is_static = is_static

    def test_hits_static_site(self):
        self.assertTrue(self.is_static("中华诗词", "https://m.zhonghuashici.com/"))
        self.assertTrue(self.is_static("国学汉籍", "https://www.gxhj.com/"))
        self.assertTrue(self.is_static("国学经典", "https://guoxue.wunpu.com/"))

    def test_normal_novel_site_not_exempt(self):
        # 普通小说站不能被这条豁免漏过去，否则僵尸站永远删不掉
        self.assertFalse(self.is_static("笔趣阁32", "https://www.biquge32.com/"))
        self.assertFalse(self.is_static("刺猬猫", "https://www.ciweimao.com/"))
        self.assertFalse(self.is_static("红袖添香", "https://m.hongxiu.com"))

    def test_exempt_by_url_only(self):
        # 域名白名单兜底：站名被清空/改名后仍然豁免（gxhj.com 域名本身不含关键词）
        self.assertTrue(self.is_static("", "https://www.gxhj.com/"))
        self.assertTrue(self.is_static("某古籍站改名后", "https://guoxue.wunpu.com/"))
        # 白名单是精确匹配，不能把普通站带进来
        self.assertFalse(self.is_static("", "https://www.gxhj.com.cn/"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
