#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
垃圾源过滤：剔除非小说/测试占位/失效标记源，成人内容保留归组

输入: raw/autocollect/validated.json（包装结构: {source, pass_rate, ...}）
输出: raw/autocollect/validated_clean.json（同结构）

剔除规则：
  1. 非小说类：漫画/听书/影视/视频/动漫/音乐/广播/游戏/图库/写真等
  2. 测试占位：test/测试/示例/占位/demo/localhost等
  3. 失效标记：搜索失效/正文失效/目录失效/网站失效/校验超时/BAD等

保留规则：
  成人内容（涩涩/瑟瑟/18+/皇叔/刘备/海棠/🔞等）**不剔除**，
  统一打标记 bookSourceGroup="成人书源"，由 organize 单独分组。
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autocollect_core.config import RAW_DIR
from autocollect_core.utils import log

VALIDATED_FILE = os.path.join(RAW_DIR, "validated.json")
CLEAN_FILE = os.path.join(RAW_DIR, "validated_clean.json")

NON_NOVEL_KW = [
    "漫画", "听书", "影视", "视频", "动漫", "电影", "电视剧", "动画", "综艺",
    "音乐", "电台", "广播", "游戏", "图解", "图库", "写真", "壁纸",
]
ADULT_KW = [
    "涩涩", "瑟瑟", "18加", "18+", "成人", "皇叔", "刘备", "不可描述",
    "R18", "r18", "黄书", "色情", "黄色", "🔞", "🚬", "海废", "po18", "po文",
    "老司机", "绅士", "耽美", "海棠", "禁验", "禁阅", "肉漫", "肉文", "香艳",
]
TEST_KW = [
    "test", "测试", "示例", "example", "占位", "demo", "localhost",
    "127.0.0.1", "请勿检验", "验证码", "测试站",
]
DEAD_KW = [
    "失效", "已死", "网站失效", "校验超时", "BAD", "搜不到书",
    "搜索目录失效", "发现目录失效", "搜索正文失效", "发现正文失效",
]


ADULT_GROUP = "成人书源"  # 成人源统一归入此分组


def is_junk(s):
    name = (s.get("bookSourceName") or "")
    url = (s.get("bookSourceUrl") or "")
    group = (s.get("bookSourceGroup") or "")
    blob = (name + " " + url + " " + group).lower()

    if any(k.lower() in blob for k in NON_NOVEL_KW):
        return "非小说"
    if any(k.lower() in blob for k in TEST_KW):
        return "测试占位"
    if any(k in blob for k in DEAD_KW):
        return "失效标记"
    return None


def is_adult(s):
    name = (s.get("bookSourceName") or "")
    url = (s.get("bookSourceUrl") or "")
    group = (s.get("bookSourceGroup") or "")
    blob = (name + " " + url + " " + group).lower()
    return any(k in blob for k in ADULT_KW)


def main():
    if not os.path.exists(VALIDATED_FILE):
        log.error(f"缺少 {VALIDATED_FILE}，请先运行 validate")
        sys.exit(1)

    with open(VALIDATED_FILE, "r", encoding="utf-8") as f:
        items = json.load(f)
    log.info(f"读取合格源: {len(items)} 个")

    junk_counts = {}
    adult_count = 0
    kept = []
    for item in items:
        s = item.get("source", item) if isinstance(item, dict) else item
        reason = is_junk(s)
        if reason:
            junk_counts[reason] = junk_counts.get(reason, 0) + 1
            continue
        # 成人内容保留，统一归入"成人书源"分组
        if is_adult(s):
            s["bookSourceGroup"] = ADULT_GROUP
            adult_count += 1
        kept.append(item)

    with open(CLEAN_FILE, "w", encoding="utf-8") as f:
        json.dump(kept, f, ensure_ascii=False, indent=2)

    log.info(f"✅ 剔除垃圾源 {sum(junk_counts.values())} 个: {junk_counts}")
    log.info(f"✅ 成人内容保留 {adult_count} 个（归入{ADULT_GROUP}分组）")
    log.info(f"✅ 保留干净源 {len(kept)} 个 → {CLEAN_FILE}")


if __name__ == "__main__":
    main()
