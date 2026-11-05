#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分段采集脚本（防沙箱重置中断）

把完整采集拆成多个可独立落盘的阶段，每段跑完立即保存分片 JSON；
中断后只需重跑当前段，已完成的段直接从分片恢复。

用法：
  python3 scripts/collect_staged.py list              # 段1: yckceo列表 前10页 → raw_list.json
  python3 scripts/collect_staged.py heji 1 3         # 段2: 合集 1-3页 → raw_heji_1_3.json（--limit 前N个）
  python3 scripts/collect_staged.py gurus            # 段5: 大佬仓库 → raw_gurus.json
  python3 scripts/collect_staged.py merge            # 段6: 合并采集分片 → raw_all_YYYYMMDD.json
"""

import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autocollect_core.collectors import collect_gurus, collect_yckceo_heji, collect_yckceo_list
from autocollect_core.config import RAW_DIR
from autocollect_core.utils import ensure_dir, log


def save(fragment_name, sources):
    """保存分片到 raw/autocollect/"""
    ensure_dir(RAW_DIR)
    path = os.path.join(RAW_DIR, fragment_name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sources, f, ensure_ascii=False, indent=2)
    log.info(f"✅ 已落盘 {fragment_name}: {len(sources)} 个 → {path}")


def cmd_list(args):
    log.info(f"段1: yckceo书源列表 前10页（最近{args.months}个月）")
    sources = collect_yckceo_list(months=args.months, page_start=1, page_end=10)
    save("raw_list.json", sources)


def cmd_heji(args):
    start, end = args.start, args.end
    log.info(f"段: yckceo书源合集 {start}-{end}页（最近{args.months}个月，前{args.limit}个合集）")
    sources = collect_yckceo_heji(months=args.months, page_start=start, page_end=end, limit=args.limit)
    save(f"raw_heji_{start}_{end}.json", sources)


def cmd_gurus(args):
    log.info("段: 4个大佬仓库直链")
    sources = collect_gurus()
    save("raw_gurus.json", sources)


def cmd_merge(args):
    """合并采集分片（仅 raw_list/raw_heji_*/raw_gurus，不含 cleaned/validated/dead 等中间产物）"""
    ensure_dir(RAW_DIR)
    all_sources = []
    fragments = []
    prefixes = ("raw_list.json", "raw_heji_", "raw_gurus.json")
    for fname in sorted(os.listdir(RAW_DIR)):
        if not fname.endswith(".json"):
            continue
        if not any(fname == p or fname.startswith(p) for p in prefixes):
            continue
        path = os.path.join(RAW_DIR, fname)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            log.warning(f"  跳过无法读取的分片 {fname}: {e}")
            continue
        all_sources.extend(data)
        fragments.append(fname)

    log.info(f"合并分片: {fragments}")
    log.info(f"合并后原始数据: {len(all_sources)} 个")

    out = os.path.join(RAW_DIR, f"raw_all_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(all_sources, f, ensure_ascii=False, indent=2)
    log.info(f"✅ 已落盘 {out}")
    return out


def main():
    parser = argparse.ArgumentParser(description="分段采集脚本")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="采集yckceo列表20页 → raw_list.json")
    p_list.add_argument("--months", type=int, default=1, help="只采集最近N个月（默认1）")
    p_heji = sub.add_parser("heji", help="采集合集指定页范围 → raw_heji_s_e.json")
    p_heji.add_argument("start", type=int)
    p_heji.add_argument("end", type=int)
    p_heji.add_argument("--months", type=int, default=1, help="只采集最近N个月（默认1）")
    p_heji.add_argument("--limit", type=int, default=30, help="只采集列表前N个合集（默认30）")
    sub.add_parser("gurus", help="采集4个大佬仓库 → raw_gurus.json")
    sub.add_parser("merge", help="合并所有分片 → raw_all_*.json")

    args = parser.parse_args()

    if args.cmd == "list":
        cmd_list(args)
    elif args.cmd == "heji":
        cmd_heji(args)
    elif args.cmd == "gurus":
        cmd_gurus(args)
    elif args.cmd == "merge":
        cmd_merge(args)


if __name__ == "__main__":
    main()
