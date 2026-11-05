#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
阶段B: 批量下载书源合集（基于阶段A提取的ID清单）

- 从 raw/autocollect/heji_ids.json 读取合集ID清单
- 逐个下载，每个合集立即独立落盘 raw/autocollect/heji/{cid}.json
- 已下载过的自动跳过；中断后重跑只补缺失的（断点续传）
- 内存占用低（处理完即写盘），不易触发沙箱资源回收

用法：
  python3 scripts/collect_heji_batch.py                  # 全量下载
  python3 scripts/collect_heji_batch.py --from 500       # 从第500个ID开始（可选）
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autocollect_core.config import RAW_DIR
from autocollect_core.utils import ensure_dir, fetch_url, log

IDS_FILE = os.path.join(RAW_DIR, "heji_ids.json")
HEJI_DIR = os.path.join(RAW_DIR, "heji")


def download_heji(cid):
    """下载单个合集 JSON（302 自动跳 CDN）"""
    url = f"https://www.yckceo.com/yuedu/shuyuans/json/id/{cid}.json"
    resp = fetch_url(url, timeout=20)
    if not resp or resp.status_code != 200:
        return None
    try:
        return resp.json()
    except Exception:
        return None


def main():
    parser = argparse.ArgumentParser(description="批量下载合集（阶段B）")
    parser.add_argument("--from", dest="start_idx", type=int, default=0,
                        help="从第N个ID开始（可选，默认0）")
    args = parser.parse_args()

    if not os.path.exists(IDS_FILE):
        log.error(f"缺少ID清单 {IDS_FILE}，请先运行 scripts/collect_heji_ids.py")
        sys.exit(1)

    with open(IDS_FILE, "r", encoding="utf-8") as f:
        ids = json.load(f)
    total = len(ids)
    log.info(f"ID清单: {total} 个合集")

    ensure_dir(HEJI_DIR)
    done = skipped = failed = 0
    total_sources = 0
    idx = 0

    for i, cid in enumerate(ids):
        if i < args.start_idx:
            continue
        idx = i
        fpath = os.path.join(HEJI_DIR, f"{cid}.json")
        if os.path.exists(fpath):
            skipped += 1
            continue

        data = download_heji(cid)
        if data is None:
            failed += 1
            log.warning(f"  [{i+1}/{total}] 合集{cid} 下载失败")
            continue

        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        n = len(data) if isinstance(data, list) else 1
        total_sources += n
        done += 1

        if done % 20 == 0 or i == total - 1:
            log.info(f"  进度[{i+1}/{total}]: 新下载{done} 跳过{skipped} 失败{failed} 累计源{total_sources}")
        time.sleep(0.2)

    log.info(f"批量下载结束: 新下载{done} 跳过{skipped} 失败{failed} 累计源{total_sources}")


if __name__ == "__main__":
    main()
