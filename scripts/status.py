#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
状态自检（中断接续第一步：一条命令看清真实状态，不靠记忆、不重跑已完成步骤）

用法:
  python3 scripts/status.py            # 本地状态 + 发布页状态
  python3 scripts/status.py --local    # 只看本地（不联网）

输出:
  1. 正式版 books.json / 中间层 books_pending.json / clean_rules 的源数与分组
  2. 最新 cleaned_*.json（Actions 采集产物）
  3. 所有校验断点 ckpt_*.json（中断残留 → 重跑同一命令自动续）
  4. raw 分片数量与体积（采集进度）
  5. git 状态（未提交改动 / 未推送提交）
  6. 发布页最新版本 + assets 完整性（缺 asset = 上次发布中断，重跑会自动补齐）
  7. crontab 周任务是否在
"""

import argparse
import glob
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autocollect_core.config import (ADULT_GROUP, CLEAN_RULES_FILE, OUTPUT_FILE,
                                     PENDING_FILE, RAW_DIR)
from autocollect_core.cleaner import is_adult_source, is_big_site


def _load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _groups(sources):
    g = {}
    for s in sources:
        k = s.get("bookSourceGroup") or "未分组"
        g[k] = g.get(k, 0) + 1
    return dict(sorted(g.items(), key=lambda x: -x[1]))


def local_status():
    print("=" * 64)
    print("【本地状态】")

    for label, path in (("正式版 books.json", OUTPUT_FILE),
                        ("中间层 books_pending.json", PENDING_FILE)):
        data = _load(path)
        name = os.path.basename(path)
        if data is None:
            print(f"  {label}: 不存在或损坏")
            continue
        adults = len([s for s in data if s.get("bookSourceGroup") == ADULT_GROUP or is_adult_source(s)])
        print(f"  {label}: {len(data)} 源 | 成人 {adults} | 大厂 {len([s for s in data if is_big_site(s)])}")
        print(f"    分组: {_groups(data)}")
        if data and "customOrder" in data[0]:
            ok = all(data[i].get("customOrder") == i + 1 for i in range(len(data)))
            last_adult = max([i + 1 for i, s in enumerate(data)
                              if s.get("bookSourceGroup") == ADULT_GROUP] or [0])
            print(f"    customOrder 连续: {ok} | 成人组最末: {last_adult == len(data)}")

    rules = _load(CLEAN_RULES_FILE)
    print(f"  净化规则 clean_rules.json: {len(rules) if rules is not None else '缺失'} 条")

    cleaned = sorted(glob.glob(os.path.join(RAW_DIR, "cleaned_*.json")))
    if cleaned:
        d = _load(cleaned[-1])
        print(f"  最新清洗产物: {os.path.basename(cleaned[-1])} ({len(d) if d else '?'} 源)")
    else:
        print("  清洗产物: 无 cleaned_*.json")

    ckpts = sorted(glob.glob(os.path.join(RAW_DIR, "ckpt_*.json")))
    if ckpts:
        print(f"  校验断点（重跑同一命令自动续）: {len(ckpts)} 个")
        for c in ckpts:
            d = _load(c)
            n = len(d) if isinstance(d, (list, dict)) else 0
            print(f"    - {os.path.basename(c)}: {n} 条")
    else:
        print("  校验断点: 无")

    heji = glob.glob(os.path.join(RAW_DIR, "heji", "*.json"))
    raw = glob.glob(os.path.join(RAW_DIR, "raw_*.json"))
    print(f"  采集分片: heji {len(heji)} 个 + raw_*.json {len(raw)} 个")

    try:
        out = subprocess.run(["git", "status", "--short"], capture_output=True, text=True, timeout=10).stdout
        out = "\n".join(l for l in out.splitlines() if "backups" not in l)
        print(f"  git 未提交: {'无' if not out.strip() else ''}")
        if out.strip():
            for line in out.splitlines()[:8]:
                print(f"    {line}")
        ahead = subprocess.run(["git", "status", "-sb"], capture_output=True, text=True, timeout=10).stdout.splitlines()
        if ahead and "ahead" in ahead[0]:
            print(f"  未推送: {ahead[0]}")
    except Exception as e:
        print(f"  git 状态读取失败: {e}")

    try:
        cron = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=5).stdout
        print(f"  每日任务 crontab: {'已配置' if 'run_daily_collect' in cron else '未配置（跑 scripts/install_cron.sh 可重建）'}")
    except Exception:
        print("  每日任务 crontab: 无法读取（跑 scripts/install_cron.sh 可重建）")


def remote_status():
    print("=" * 64)
    print("【发布页状态】")
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from autocollect_core.publisher import get_github_token, get_latest_release, is_partial_release

    token = get_github_token()
    if not token:
        print("  未找到 GitHub token（检查 git remote 或 GITHUB_TOKEN 环境变量）")
        return
    rel = get_latest_release(token)
    if not rel:
        print("  读取失败（网络问题可稍后重试）")
        return
    print(f"  最新版本: {rel.get('tag_name')} | 发布 {rel.get('published_at', '')[:19]}")
    for a in rel.get("assets", []):
        print(f"    - {a['name']}: {a['size']:,} B")
    partial = is_partial_release(rel)
    print(f"  assets 完整性: {'⚠️ 不完整（上次发布中断）→ 重跑发布命令会自动复用该版本补齐' if partial else '✅ 完整'}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--local", action="store_true", help="只看本地，不联网")
    args = ap.parse_args()
    local_status()
    if not args.local:
        try:
            remote_status()
        except Exception as e:
            print(f"  发布页状态读取失败: {e}")
    print("=" * 64)
