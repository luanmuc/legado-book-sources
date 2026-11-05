#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全自动书源采集脚本（主入口）
模块化结构，核心逻辑在 autocollect_core/ 包内

功能：从多个数据源采集书源 → 清洗去重 → 校验 → 整理 → 合并到仓库

用法：
  python3 autocollect.py              # 完整流程
  python3 autocollect.py --collect    # 只采集
  python3 autocollect.py --validate   # 只校验
  python3 autocollect.py --merge      # 只合并整理
  python3 autocollect.py --months 2   # 采集最近2个月的
  python3 autocollect.py --publish    # 跑完自动发布到GitHub发布页
"""

import argparse
import json
import os
from datetime import datetime

from autocollect_core.config import OUTPUT_FILE, RAW_DIR, PENDING_FILE
from autocollect_core.utils import log
from autocollect_core.collectors import collect_all
from autocollect_core.cleaner import clean_and_dedup, filter_junk_sources, is_big_site
from autocollect_core.validators import validate_sources
from autocollect_core.organizer import organize_sources
from autocollect_core.cleanrules import collect_clean_rules, generate_clean_rules
from autocollect_core.report import generate_report
from autocollect_core.publisher import auto_publish


def main():
    parser = argparse.ArgumentParser(description="全自动书源采集脚本")
    parser.add_argument("--collect", action="store_true", help="只执行采集")
    parser.add_argument("--validate", action="store_true", help="只执行校验")
    parser.add_argument("--merge", action="store_true", help="只执行合并整理")
    parser.add_argument("--publish", action="store_true", help="跑完自动发布到GitHub")
    parser.add_argument("--months", type=int, default=1, help="采集最近N个月的（默认1，可调大如2/3）")
    parser.add_argument("--collect-only", action="store_true",
                        help="只采集+清洗+规则校验，保存到 weekly/cleaned_*.json（GitHub Actions跨洋用，不做存活探测）")
    parser.add_argument("--from-cleaned", metavar="FILE",
                        help="从清洗结果继续：校验+垃圾过滤+整理（本地国内网络用，跳过采集/清洗）")
    parser.add_argument("--stage", action="store_true",
                        help="整理结果合并进中间层 books_pending.json，不发布（采集层→中间层，等你确认）")
    parser.add_argument("--publish-pending", action="store_true",
                        help="把中间层 books_pending.json 提升为正式版并保存（中间层→正式版；加 --publish 才更新Release）")
    args = parser.parse_args()

    log.info("=" * 50)
    log.info("全自动书源采集脚本 启动")
    log.info("=" * 50)

    # 加载现有书源
    existing = []
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            existing = json.load(f)
        log.info(f"加载现有书源: {len(existing)} 个")

    # ===== 模式0：只采集+清洗+规则校验（GitHub Actions 跨洋段） =====
    if args.collect_only:
        raw_sources = collect_all(months=args.months)
        cleaned = clean_and_dedup(raw_sources)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "weekly")
        os.makedirs(out_dir, exist_ok=True)
        out_file = os.path.join(out_dir, f"cleaned_{ts}.json")
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(cleaned, f, ensure_ascii=False, indent=2)
        log.info(f"采集+清洗完成: 原始 {len(raw_sources)} → 清洗后 {len(cleaned)}")
        log.info(f"保存到 {out_file}（由本地段继续校验+整理+发布）")
        return

    # ===== 模式0b：从清洗结果继续（本地国内网络段） =====
    if args.from_cleaned:
        if not os.path.exists(args.from_cleaned):
            log.error(f"找不到清洗结果文件: {args.from_cleaned}")
            return
        with open(args.from_cleaned, "r", encoding="utf-8") as f:
            cleaned = json.load(f)
        raw_sources = cleaned  # 报告统计用
        log.info(f"从清洗结果继续: {len(cleaned)} 个")
    else:
        cleaned = None

    # 第一阶段：采集
    if args.from_cleaned or args.publish_pending:
        pass  # --from-cleaned 已加载 / --publish-pending 直接用中间层，跳过采集
    elif not args.validate and not args.merge:
        raw_sources = collect_all(months=args.months)
    else:
        # 从raw目录加载最近的
        raw_files = sorted([f for f in os.listdir(RAW_DIR) if f.startswith("raw_")], reverse=True)
        if raw_files:
            with open(os.path.join(RAW_DIR, raw_files[0]), "r", encoding="utf-8") as f:
                raw_sources = json.load(f)
        else:
            raw_sources = []

    # 第二阶段：清洗去重
    if args.from_cleaned or args.publish_pending:
        pass  # cleaned 已加载 / publish-pending 不需要
    elif not args.validate and not args.merge:
        cleaned = clean_and_dedup(raw_sources)
    else:
        cleaned = raw_sources

    # 第三阶段：校验
    if args.publish_pending:
        validated = None
        dead = []
    elif not args.merge:
        validated, dead = validate_sources(cleaned)
    else:
        validated = [{"source": s, "pass_rate": 1.0} for s in cleaned]
        dead = []

    # 第三点五阶段：垃圾过滤（剔除非小说/测试/失效标记，成人内容保留归组）
    if not args.merge and not args.publish_pending:
        validated = filter_junk_sources(validated)

    # 第四阶段：整理合并
    if not args.collect and not args.validate:

        # ===== 中间层模式：合并进 books_pending.json，不发布（等你确认） =====
        if args.stage:
            pending_existing = []
            if os.path.exists(PENDING_FILE):
                with open(PENDING_FILE, "r", encoding="utf-8") as f:
                    pending_existing = json.load(f)
                log.info(f"加载中间层: {len(pending_existing)} 个")
            final_pending = organize_sources(validated, pending_existing)
            with open(PENDING_FILE, "w", encoding="utf-8") as f:
                json.dump(final_pending, f, ensure_ascii=False, indent=2)
            big_count = len([s for s in final_pending if is_big_site(s)])
            log.info("=" * 50)
            log.info(f"已并入中间层 books_pending.json: {len(final_pending)} 个（大厂 {big_count} 最顶保护）")
            log.info("正式版 books.json 未动。你确认后运行: python3 autocollect.py --publish-pending --publish")
            log.info("=" * 50)
            return

        # ===== 中间层提升正式版模式：books_pending.json → books.json =====
        if args.publish_pending:
            if not os.path.exists(PENDING_FILE):
                log.error("中间层 books_pending.json 不存在，先运行 --stage 合并采集结果")
                return
            with open(PENDING_FILE, "r", encoding="utf-8") as f:
                final_sources = json.load(f)
            log.info(f"中间层提升为正式版: {len(final_sources)} 个")
            with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
                json.dump(final_sources, f, ensure_ascii=False, indent=2)
            # 配套净化规则 + 报告
            collected_rules = collect_clean_rules()
            generate_clean_rules(final_sources, collected_rules)
            big_count = len([s for s in final_sources if is_big_site(s)])
            generate_report(len(final_sources), len(final_sources), [], len(final_sources), big_count)
            log.info(f"正式版已更新: {OUTPUT_FILE}（{len(final_sources)} 个）")
            if args.publish:
                auto_publish(len(final_sources), big_count)
            return

        final_sources = organize_sources(validated, existing)

        # 保存书源
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(final_sources, f, ensure_ascii=False, indent=2)

        # 采集大佬净化规则 + 生成配套净化规则
        collected_rules = collect_clean_rules()
        generate_clean_rules(final_sources, collected_rules)

        # 生成报告
        big_count = len([s for s in final_sources if is_big_site(s)])
        generate_report(len(raw_sources), len(cleaned), dead, len(final_sources), big_count)

        log.info("=" * 50)
        log.info(f"全部完成！最终书源: {len(final_sources)} 个")
        log.info(f"输出文件: {OUTPUT_FILE}")
        log.info("=" * 50)

        # 自动发布
        if args.publish:
            auto_publish(len(final_sources), big_count)


if __name__ == "__main__":
    main()
