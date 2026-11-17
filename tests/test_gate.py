# -*- coding: utf-8 -*-
"""门槛剔除判定单测（不联网）

这里测的是"什么情况下**不许**删站"，因为删站是不可逆的，而且线上真的删错过：

- 2026-11-14 深查后误删 34 个活站（占当时删除量的 52%）
- 2026-11-16 红袖移动版被当普通站判死（host 归一化不一致）
- 2026-11-17 6 条候选被删，全部 `home_days=None`——根因是判定写成了
  `if hd is not None and hd <= 180`，**取不到首页证据时条件不成立，直接落进删除分支**，
  把"证据不足"当成"没有矛盾证据"。实测其中 4 个站 HTTP 200、页面几十 KB 仍在服务。

跑法：python3 -m unittest discover -s tests -v
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

ZOMBIE_DAYS = 180


def should_drop(rec, big=lambda u: False, static=lambda n, u="": False, drop_enabled=True):
    """复刻 deep_gate 的剔除判定，用于回归测试。

    真实实现是 scripts/deep_gate.py 里的内联循环；这里保持同构，
    改动判定时两边必须一起改（否则测试会变成假绿灯）。
    """
    if big(rec.get("url")):
        return False
    if static(rec.get("name"), rec.get("url")):
        return False
    d = rec.get("deep_days") or 0
    if d <= ZOMBIE_DAYS:
        return False
    hd = rec.get("home_days")
    # 双证据同向才允许删：首页证据必须存在，且也要超过阈值
    if hd is None or hd <= ZOMBIE_DAYS:
        return False
    return drop_enabled


class TestDeepGateDropRule(unittest.TestCase):
    # ---------- 不该删 ----------

    def test_home_days_missing_means_not_proven(self):
        """首页日期取不到 = 只有进站一个信号，证据不足，必须放行

        这是 2026-11-17 那 6 条被误删的根因。修复前本用例 FAIL。
        """
        rec = {"name": "知音漫客（优+）", "url": "https://m.zymk.cn/",
               "deep_days": 1382, "home_days": None}
        self.assertFalse(should_drop(rec))

    def test_home_days_contradicts_deep(self):
        """首页说新、进站说老 → 数据矛盾，放行"""
        rec = {"name": "某站", "url": "https://a.com", "deep_days": 900, "home_days": 30}
        self.assertFalse(should_drop(rec))

    def test_deep_days_within_threshold(self):
        rec = {"name": "某站", "url": "https://a.com", "deep_days": 100, "home_days": 900}
        self.assertFalse(should_drop(rec))

    def test_big_site_exempt(self):
        """大厂一律豁免（黑岩进站 277 天但仍在运营）"""
        rec = {"name": "黑岩", "url": "https://www.hongyanshu.com", "deep_days": 277, "home_days": 900}
        self.assertFalse(should_drop(rec, big=lambda u: "hongyanshu" in u))

    def test_static_site_exempt(self):
        """古籍/国学站内容固定，永不更新是常态"""
        rec = {"name": "国学汉籍", "url": "https://www.gxhj.com/", "deep_days": 999, "home_days": 1200}
        self.assertFalse(should_drop(rec, static=lambda n, u="": "国学" in n))

    def test_dry_run_never_drops(self):
        rec = {"name": "某站", "url": "https://a.com", "deep_days": 900, "home_days": 900}
        self.assertFalse(should_drop(rec, drop_enabled=False))

    # ---------- 该删的必须能删 ----------

    def test_both_evidence_old_drops(self):
        """双证据同向变老才算僵尸——这是唯一允许删的情形"""
        rec = {"name": "笔趣阁某站", "url": "https://biquge-xx.com", "deep_days": 900, "home_days": 800}
        self.assertTrue(should_drop(rec))

    def test_dropping_disabled_by_flag(self):
        """不带 --drop-zombie 时只出报告不改数据"""
        rec = {"name": "某站", "url": "https://a.com", "deep_days": 900, "home_days": 800}
        self.assertFalse(should_drop(rec, drop_enabled=False))


class TestTemplateDate(unittest.TestCase):
    """sitemap lastmod 的模板假数据识别

    单站看 lastmod 完全看不出问题，必须横向比同批。实测 2026-11-17 health 挡掉
    7 条里有 4 个爱丽丝书屋镜像共用 2024-08-19，而 4 个站都 HTTP 200 在正常服务。
    """

    def setUp(self):
        from scripts.health_gate import detect_template_dates
        self.detect = detect_template_dates

    def test_mirror_sites_sharing_date(self):
        rs = [{"evidence": "sitemap", "newest": "2024-08-19"}] * 4
        self.assertEqual(self.detect(rs), {"2024-08-19"})

    def test_single_date_not_flagged(self):
        rs = [{"evidence": "sitemap", "newest": "2026-09-01"}]
        self.assertEqual(self.detect(rs), set())

    def test_two_occurrences_not_enough(self):
        # 阈值 3：只有两个站撞日期时可能是巧合，不足以认定模板
        rs = [{"evidence": "sitemap", "newest": "2024-08-19"}] * 2
        self.assertEqual(self.detect(rs), set())

    def test_only_sitemap_evidence_counts(self):
        # 首页证据不参与这条判据（首页日期另有 _suspect 过滤）
        rs = [{"evidence": "home", "newest": "2024-08-19"}] * 5
        self.assertEqual(self.detect(rs), set())

    def test_empty_and_missing_newest(self):
        rs = [{"evidence": "sitemap", "newest": None}, {"evidence": "sitemap"}]
        self.assertEqual(self.detect(rs), set())
        self.assertEqual(self.detect([]), set())


if __name__ == "__main__":
    unittest.main(verbosity=2)
