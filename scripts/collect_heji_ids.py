#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
阶段A: 批量提取书源合集链接（轻量，只爬列表页提取ID）

只抓合集列表页（默认前10页），提取每个合集的 ID 并落盘，
不下载任何合集内容。之后用 collect_heji_batch.py 批量下载。

用法：
  python3 scripts/collect_heji_ids.py                 # 提取 1-10 页合集ID
  python3 scripts/collect_heji_ids.py --pages 1 5     # 只提取 1-5 页
输出：raw/autocollect/heji_ids.json
"""

import argparse
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autocollect_core.config import RAW_DIR
from autocollect_core.utils import ensure_dir, fetch_url, log

IDS_FILE = os.path.join(RAW_DIR, "heji_ids.json")


def main():
    parser = argparse.ArgumentParser(description="提取合集链接（阶段A）")
    parser.add_argument("--pages", type=int, nargs=2, default=[1, 10],
                        help="合集页范围，如 --pages 1 5")
    args = parser.parse_args()

    ensure_dir(RAW_DIR)
    start, end = args.pages

    # 断点续传：已有ID清单加载去重，中断后重跑只补缺失页
    all_ids = []
    if os.path.exists(IDS_FILE):
        try:
            with open(IDS_FILE, "r", encoding="utf-8") as f:
                all_ids = json.load(f)
            log.info(f"断点续传: 已有 {len(all_ids)} 个ID，只补缺失页")
        except Exception:
            all_ids = []
    seen = set(all_ids)

    for page in range(start, end + 1):
        url = f"https://www.yckceo.com/yuedu/shuyuans/index.html?page={page}"
        resp = fetch_url(url, timeout=15)
        if not resp or resp.status_code != 200:
            log.warning(f"  第{page}页请求失败，停止")
            break
        ids = re.findall(r'/yuedu/shuyuans/content/id/(\d+)\.html', resp.text)
        if not ids:
            log.info(f"  第{page}页没有更多合集了，停止")
            break
        new_ids = [i for i in ids if i not in seen]
        log.info(f"  合集列表第{page}页: {len(ids)} 个合集（新增 {len(new_ids)}）")
        all_ids.extend(new_ids)
        seen.update(new_ids)
        # 每页立即落盘（中断后从文件恢复，只补缺失页）
        with open(IDS_FILE, "w", encoding="utf-8") as f:
            json.dump(all_ids, f, ensure_ascii=False, indent=2)
        time.sleep(0.5)

    log.info(f"共提取合集链接 {len(all_ids)} 个")
    log.info(f"✅ 已落盘 {IDS_FILE}")


if __name__ == "__main__":
    main()
