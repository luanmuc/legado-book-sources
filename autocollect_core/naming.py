# -*- coding: utf-8 -*-
"""
命名模块：同族源名字生成、自然排序键、同族尾号连续重编

与 organizer.py 的分工：
  · naming.py 只管「给源起什么名、名字怎么排、尾号怎么连续」
  · organizer.py 只管「分几个组、大厂怎么保护、customOrder 怎么分配」
"""

import re

from .config import ADULT_GROUP
from .utils import log


SUFFIX_CHARS = ["书屋", "阅读", "小说", "书城", "书库", "书轩", "书斋", "书苑"]


def natural_name_key(source):
    """名字自然排序键：同族前缀聚合，尾部数字按数值比较（笔趣阁2 < 笔趣阁3 < ... < 笔趣阁146）"""
    name = source.get("bookSourceName", "") or ""
    m = re.match(r"^(.*?)(\d+)$", name)
    if m:
        return (m.group(1), int(m.group(2)))
    return (name, 0)


def generate_chinese_name(source, used_names, group):
    """生成名字：笔趣阁类统一「笔趣阁+数字」；其他类四字纯汉字，重名加数字"""
    original = source.get("bookSourceName", "")
    clean = re.sub(r'[^\u4e00-\u9fa5]', '', original)

    if group == "笔趣阁类":
        base = "笔趣阁"  # 批量同名的统一基底，用数字排序区分
    else:
        chinese = clean[:4]
        if len(chinese) < 4:  # 不足4字，循环补足到正好4字
            pad_idx = len(used_names) % len(SUFFIX_CHARS)
            while len(chinese) < 4:
                pad_word = SUFFIX_CHARS[pad_idx % len(SUFFIX_CHARS)]
                chinese += pad_word[: 4 - len(chinese)]
                pad_idx += 1
        base = chinese

    # 唯一性：base 或 base+N
    if base not in used_names:
        used_names.add(base)
        return base
    n = 2
    while f"{base}{n}" in used_names:
        n += 1
    name = f"{base}{n}"
    used_names.add(name)
    return name


def renumber_name_families(sources):
    """发布前统一给「同族源」重编连续尾号（2026-11-10 用户要求）

    问题：名字里的数字两个来源都不连续——
      · 笔趣阁类由 generate_chinese_name 生成，第一个叫「笔趣阁」（无号），后续从 2 开始；
      · 其他组保留上游原名，写着「第一版主11 / 14 / 17」「新御书屋7 / 42」这种断号。
    结果导入后同一站点看到 2、5、8 跳号，用户明确要求「每次发布从 1 开始重新排，要连续号」。

    规则：
      · 成人组、大厂组不动（成人原名原样是硬约束，大厂名字手动调过）
      · 族键 = 去掉尾部数字的名字；带数字的源与同名本体算同族
      · 族内按当前顺序（customOrder）从 1 连续编号（本体也补 1）
      · 只有 1 个成员的族保持原样（单站不该被强行加号）
      · 前缀去空格后 <2 字符跳过（避免「书1」误并）
    """
    families = {}
    for s in sources:
        group = s.get("bookSourceGroup")
        if group in (ADULT_GROUP, "大厂正版"):
            continue
        name = (s.get("bookSourceName") or "").strip()
        if not name:
            continue
        m = re.match(r"^(.+?)(\d+)$", name)
        prefix = m.group(1) if m else name
        if len(prefix.strip()) < 2:
            continue
        families.setdefault(prefix, []).append((s, bool(m)))

    renamed = 0
    for prefix, members in families.items():
        if len(members) < 2:
            continue
        members.sort(key=lambda t: t[0].get("customOrder", 0))
        n = 1
        for s, _ in members:
            new_name = f"{prefix}{n}"
            if s.get("bookSourceName") != new_name:
                s["bookSourceName"] = new_name
                renamed += 1
            n += 1
    log.info(f"同族尾号重编: {renamed} 个源（{len(families)} 个族，仅非成人/非大厂）")
    return sources
