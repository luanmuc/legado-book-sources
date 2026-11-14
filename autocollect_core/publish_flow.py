# -*- coding: utf-8 -*-
"""
发布流程：中间层 → 正式版（--publish-pending 路径）

从 autocollect.py 抽出，让 CLI 入口只做参数解析与调度，业务逻辑在核心库。

流程：
  1. 读 books_pending.json（中间层候选）+ books.json（现有正式版）
  2. 大厂从正式版强制保护，新采集的大厂源跳过
  3. 对中间层待校验源跑 full 校验（存活 + 真实性，一步不少）
  4. 垃圾过滤（成人保留归组）
  5. 与现有正式版按 URL 去重合并
  6. organize_sources 整理（分组 + 命名 + 同族重编号 + customOrder）
  7. 写 books.json + 生成 clean_rules + 报告
  8. do_publish=True 时调 auto_publish 发 Release
"""

import json
import os

from .config import PENDING_FILE, OUTPUT_FILE
from .utils import log, load_json, dump_json
from .cleaner import is_big_site, filter_junk_sources
from .validators import validate_sources_with_checkpoint
from .organizer import organize_sources
from .cleanrules import collect_clean_rules, generate_clean_rules
from .report import generate_report
from .publisher import auto_publish


def publish_pending_flow(pending_file=None, output_file=None, do_publish=False):
    """中间层提升正式版。返回 (final_count, big_count, added, dead_count)。"""
    pending_file = pending_file or PENDING_FILE
    output_file = output_file or OUTPUT_FILE

    if not os.path.exists(pending_file):
        log.error(f"中间层 {pending_file} 不存在，先运行 --stage 合并采集结果")
        return None

    pending_sources = load_json(pending_file, default=[])

    # 读取现有正式版作为合并基准：大厂保护 + 既有源全部保留（增量合并，不替换正式版）
    current_sources = load_json(output_file, default=[])

    big_sites = [s for s in current_sources if is_big_site(s)]
    rest_pending = [s for s in pending_sources if not is_big_site(s)]
    log.info(f"发布前完整校验: 中间层 {len(pending_sources)} 个 + 正式版 {len(current_sources)} 个"
             f"（大厂保护 {len(big_sites)}，中间层待校验 {len(rest_pending)}）")

    # 发布前完整校验：存活 + 真实性（搜索/发现至少一项可用），一步不少
    validated, dead = validate_sources_with_checkpoint(
        rest_pending, "pending", batch=200, mode="full"
    )
    validated = filter_junk_sources(validated)

    # 合并：正式版全部保留 + 校验合格新源按 bookSourceUrl 去重追加
    existing_urls = {s.get("bookSourceUrl") for s in current_sources}
    merged = [{"source": s, "pass_rate": 1.0} for s in current_sources]
    added = 0
    for v in validated:
        if v.get("source", {}).get("bookSourceUrl") not in existing_urls:
            merged.append(v)
            added += 1

    final_sources = organize_sources(merged, current_sources)
    log.info(f"发布合并完成: 正式版 {len(current_sources)} → {len(final_sources)}"
             f"（新增 {added}，发布校验淘汰 {len(dead)}）")

    dump_json(final_sources, output_file)  # 原子写

    # 配套净化规则 + 报告
    collected_rules = collect_clean_rules()
    generate_clean_rules(final_sources, collected_rules)
    big_count = len([s for s in final_sources if is_big_site(s)])
    generate_report(len(pending_sources), len(pending_sources), dead, len(final_sources), big_count)
    log.info(f"正式版已更新: {output_file}（{len(final_sources)} 个，大厂 {big_count}，发布校验淘汰 {len(dead)}）")

    if do_publish:
        auto_publish(len(final_sources), big_count)

    return len(final_sources), big_count, added, len(dead)
