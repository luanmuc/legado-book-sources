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

核心逻辑复用 autocollect_core.cleaner.filter_junk_sources（与主流程一致）
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autocollect_core.config import RAW_DIR
from autocollect_core.cleaner import filter_junk_sources
from autocollect_core.utils import log

VALIDATED_FILE = os.path.join(RAW_DIR, "validated.json")
CLEAN_FILE = os.path.join(RAW_DIR, "validated_clean.json")


def main():
    if not os.path.exists(VALIDATED_FILE):
        log.error(f"缺少 {VALIDATED_FILE}，请先运行 validate")
        sys.exit(1)

    with open(VALIDATED_FILE, "r", encoding="utf-8") as f:
        items = json.load(f)
    log.info(f"读取合格源: {len(items)} 个")

    kept = filter_junk_sources(items, keep_adult=True)

    with open(CLEAN_FILE, "w", encoding="utf-8") as f:
        json.dump(kept, f, ensure_ascii=False, indent=2)

    log.info(f"✅ 保留干净源 {len(kept)} 个 → {CLEAN_FILE}")


if __name__ == "__main__":
    main()
