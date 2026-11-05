#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从已落盘分片恢复，跑完整下游流程（不重新采集，防中断可恢复）

用法：
  python3 scripts/run_from_fragments.py clean      # 合并分片+清洗去重 → raw/autocollect/cleaned_*.json
  python3 scripts/run_from_fragments.py validate   # 校验清洗结果（可 --from/--count 分批）
  python3 scripts/run_from_fragments.py final --publish  # 整理+净化规则+报告+push+发布页
"""

import argparse
import glob
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autocollect_core.config import OUTPUT_FILE, RAW_DIR
from autocollect_core.utils import log
from autocollect_core.cleaner import clean_and_dedup, is_big_site
from autocollect_core.validators import validate_sources
from autocollect_core.organizer import organize_sources
from autocollect_core.cleanrules import collect_clean_rules, generate_clean_rules
from autocollect_core.report import generate_report
from autocollect_core.publisher import auto_publish


def load_fragments():
    """合并所有分片：raw_list.json + raw_heji_*.json + heji/*.json + raw_gurus.json"""
    all_sources = []
    fragments = []

    list_file = os.path.join(RAW_DIR, "raw_list.json")
    if os.path.exists(list_file):
        with open(list_file, "r", encoding="utf-8") as f:
            all_sources.extend(json.load(f))
        fragments.append("raw_list.json")

    # 兼容两种采集路径：collect_staged.py(→raw_heji_s_e.json) 与 collect_heji_batch.py(→heji/*.json)
    for fpath in sorted(glob.glob(os.path.join(RAW_DIR, "raw_heji_*.json"))):
        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            all_sources.extend(data)
        fragments.append(os.path.basename(fpath))

    heji_dir = os.path.join(RAW_DIR, "heji")
    for fpath in sorted(glob.glob(os.path.join(heji_dir, "*.json"))):
        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            all_sources.extend(data)
        fragments.append(os.path.basename(fpath))

    gurus_file = os.path.join(RAW_DIR, "raw_gurus.json")
    if os.path.exists(gurus_file):
        with open(gurus_file, "r", encoding="utf-8") as f:
            all_sources.extend(json.load(f))
        fragments.append("raw_gurus.json")

    log.info(f"合并分片 {len(fragments)} 个 → 原始数据 {len(all_sources)} 个")
    return all_sources


def cmd_clean(args):
    """流式合并+清洗去重（逐文件处理、checkpoint 可恢复），落盘 cleaned 文件"""
    from autocollect_core.cleaner import is_non_novel, is_adult_source
    from autocollect_core.validators import check_rule_integrity
    from autocollect_core.utils import clean_url, get_domain

    domain_map = {}   # domain → 字段最完整的源
    tmp_file = os.path.join(RAW_DIR, "clean_tmp.json")

    # 断点恢复：上次中断的中间状态
    if os.path.exists(tmp_file):
        with open(tmp_file, "r", encoding="utf-8") as f:
            domain_map = json.load(f)
        log.info(f"从checkpoint恢复: 已处理 {len(domain_map)} 个域名")

    def checkpoint():
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(domain_map, f, ensure_ascii=False)
        log.info(f"  checkpoint: {len(domain_map)} 个域名")

    def add_sources(list_):
        for s in list_:
            if not isinstance(s, dict):
                continue
            url = s.get("bookSourceUrl", "")
            if not url:
                continue
            s["bookSourceUrl"] = clean_url(url)
            if not s.get("bookSourceName"):
                continue
            domain = get_domain(s["bookSourceUrl"])
            score = len([k for k, v in s.items() if v and v != ""])
            cur = domain_map.get(domain)
            if cur is None or score > len([k for k, v in cur.items() if v and v != ""]):
                domain_map[domain] = s

    def add_file(fpath, tag):
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            log.warning(f"  [{tag}] {os.path.basename(fpath)} JSON损坏，跳过: {str(e)[:60]}")
            return
        add_sources(data if isinstance(data, list) else [data])
        log.info(f"  [{tag}] {os.path.basename(fpath)}: {len(data) if isinstance(data, list) else 1} 个")

    fragments = 0

    list_file = os.path.join(RAW_DIR, "raw_list.json")
    if os.path.exists(list_file):
        add_file(list_file, "list")
        fragments += 1

    # 兼容两种采集路径（collect_staged → raw_heji_*.json；collect_heji_batch → heji/*.json）
    heji_staged = sorted(glob.glob(os.path.join(RAW_DIR, "raw_heji_*.json")))
    for i, fpath in enumerate(heji_staged):
        add_file(fpath, "heji")
        fragments += 1
        if (i + 1) % 10 == 0:
            checkpoint()

    heji_dir = os.path.join(RAW_DIR, "heji")
    heji_files = sorted(glob.glob(os.path.join(heji_dir, "*.json")))
    for i, fpath in enumerate(heji_files):
        add_file(fpath, "heji")
        fragments += 1
        if (i + 1) % 50 == 0:
            checkpoint()

    gurus_file = os.path.join(RAW_DIR, "raw_gurus.json")
    if os.path.exists(gurus_file):
        add_file(gurus_file, "gurus")
        fragments += 1

    log.info(f"合并分片 {fragments} 个 → 域名去重后 {len(domain_map)} 个")

    # 过滤非小说 + 规则完整性（成人内容豁免：成人漫画/影视等非小说类也保留）
    novel = [s for s in domain_map.values() if not is_non_novel(s) or is_adult_source(s)]
    log.info(f"过滤非小说后: {len(novel)} 个（成人内容已豁免保留）")
    valid = [s for s in novel if check_rule_integrity(s)]
    log.info(f"规则完整性: 通过 {len(valid)} 个")

    out = os.path.join(RAW_DIR, f"cleaned_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(valid, f, ensure_ascii=False, indent=2)
    if os.path.exists(tmp_file):
        os.remove(tmp_file)
    log.info(f"✅ 清洗完成 {len(valid)} 个 → {out}")


def cmd_validate(args):
    """校验最近的 cleaned 文件（可分批）"""
    cleaned_files = sorted(glob.glob(os.path.join(RAW_DIR, "cleaned_*.json")), reverse=True)
    if not cleaned_files:
        log.error("没有 cleaned_*.json，请先运行 clean")
        sys.exit(1)
    with open(cleaned_files[0], "r", encoding="utf-8") as f:
        sources = json.load(f)
    log.info(f"加载 {cleaned_files[0]}: {len(sources)} 个")

    # 分批：--from/--count 只处理一部分
    start = args.start
    end = min(len(sources), start + args.count) if args.count else len(sources)
    batch = sources[start:end]
    log.info(f"校验范围 [{start}:{end}]，共 {len(batch)} 个")

    mode = "full" if getattr(args, "full", False) else "quick"
    log.info(f"校验档位: {'完整真实性（搜索/发现至少一项可用）' if mode == 'full' else '快速存活（采集池）'}")
    validated, dead = validate_sources(batch, mode=mode)

    # 结果落盘（与已有合格源合并 + 按URL去重，支持分批追加）
    result_file = os.path.join(RAW_DIR, "validated.json")
    prev = []
    if os.path.exists(result_file):
        with open(result_file, "r", encoding="utf-8") as f:
            prev = json.load(f)
    merged = prev + validated

    def _src_url(item):
        # 兼容包装结构({source,...})与裸源dict（bookSourceUrl 顶层）
        if not isinstance(item, dict):
            return ""
        if "source" in item and isinstance(item["source"], dict):
            return item["source"].get("bookSourceUrl", "")
        return item.get("bookSourceUrl", "")

    seen = set()
    unique = []
    for s in merged:
        u = _src_url(s)
        if u and u in seen:
            continue
        if u:
            seen.add(u)
        unique.append(s)
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(unique, f, ensure_ascii=False, indent=2)
    log.info(f"✅ 本批合格 {len(validated)}，累计合格 {len(unique)} → {result_file}")

    # 淘汰源也落盘（供 final 报告统计淘汰原因）
    dead_file = os.path.join(RAW_DIR, "dead.json")
    prev_dead = []
    if os.path.exists(dead_file):
        with open(dead_file, "r", encoding="utf-8") as f:
            prev_dead = json.load(f)
    dead_by_url = {}
    for d in prev_dead:
        dead_by_url[_src_url(d)] = d
    for d in dead:
        dead_by_url[_src_url(d)] = d
    with open(dead_file, "w", encoding="utf-8") as f:
        json.dump(list(dead_by_url.values()), f, ensure_ascii=False, indent=2)
    log.info(f"累计淘汰 {len(dead_by_url)} 个 → {dead_file}")


def cmd_final(args):
    """整理+净化规则+报告+发布（基于合格源文件，可用过滤后的干净池）"""
    vfile = args.input or os.path.join(RAW_DIR, "validated.json")
    if not os.path.exists(vfile):
        log.error(f"缺少 {vfile}，请先运行 validate")
        sys.exit(1)
    with open(vfile, "r", encoding="utf-8") as f:
        validated = json.load(f)
    log.info(f"加载合格源 {len(validated)} 个")

    # 现有书源（大厂保护基准）
    existing = []
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            existing = json.load(f)
    log.info(f"现有书源 {len(existing)} 个")

    # 发布前完整校验（2026-11-06 用户要求：中间层合并到正式版发布时也要做一遍校验，一步不少）
    # 对 合格源 + 现有正式版（大厂保护） 的合并池执行真实性校验（搜索/发现至少一项可用）
    if args.publish:
        from autocollect_core.validators import validate_sources_with_checkpoint
        pool = list(existing) + [
            (v["source"] if isinstance(v, dict) and isinstance(v.get("source"), dict) else v)
            for v in validated
        ]  # 统一为裸源 dict（quick_validate/check_source_usable 都吃裸源）
        log.info(f"发布前完整校验: 合并池 {len(pool)} 个（现有 {len(existing)} + 新合格 {len(validated)}）")
        rechecked, dead2 = validate_sources_with_checkpoint(pool, "final_prepublish", batch=200, mode="full")
        if dead2:
            log.info(f"发布前校验淘汰: {len(dead2)} 个（大厂已保护）")
        validated = rechecked

    # 整理（大厂保护 + 改名 + 分组 + customOrder）
    final = organize_sources(validated, existing)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(final, f, ensure_ascii=False, indent=2)
    log.info(f"✅ 书源已整理保存: {len(final)} 个 → {OUTPUT_FILE}")

    # 净化规则
    collected = collect_clean_rules()
    generate_clean_rules(final, collected)

    # 报告（真实统计：分片原始量 / 清洗量 / 校验淘汰 / 入库量）
    raw_count = 0
    list_file = os.path.join(RAW_DIR, "raw_list.json")
    if os.path.exists(list_file):
        try:
            raw_count += len(json.load(open(list_file, encoding="utf-8")))
        except Exception:
            pass
    for fpath in glob.glob(os.path.join(RAW_DIR, "raw_heji_*.json")):
        try:
            raw_count += len(json.load(open(fpath, encoding="utf-8")))
        except Exception:
            pass
    heji_dir = os.path.join(RAW_DIR, "heji")
    for fpath in glob.glob(os.path.join(heji_dir, "*.json")):
        try:
            raw_count += len(json.load(open(fpath, encoding="utf-8")))
        except Exception:
            pass
    gurus_file = os.path.join(RAW_DIR, "raw_gurus.json")
    if os.path.exists(gurus_file):
        try:
            raw_count += len(json.load(open(gurus_file, encoding="utf-8")))
        except Exception:
            pass

    cleaned_files = sorted(glob.glob(os.path.join(RAW_DIR, "cleaned_*.json")), reverse=True)
    deduped_count = 0
    if cleaned_files:
        try:
            deduped_count = len(json.load(open(cleaned_files[0], encoding="utf-8")))
        except Exception:
            pass

    dead = []
    dead_file = os.path.join(RAW_DIR, "dead.json")
    if os.path.exists(dead_file):
        try:
            dead = json.load(open(dead_file, encoding="utf-8"))
        except Exception:
            dead = []
    if not dead:  # 无淘汰记录时按差值估算
        dead = [{"reason": "两级校验未通过"}] * max(0, deduped_count - len(validated))

    big_count = len([s for s in final if is_big_site(s)])
    generate_report(raw_count, deduped_count, dead, len(final), big_count)

    if args.publish:
        auto_publish(len(final), big_count)


def main():
    parser = argparse.ArgumentParser(description="从分片恢复跑下游")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("clean", help="合并分片+清洗去重落盘")
    p_v = sub.add_parser("validate", help="校验cleaned（可分批；默认快速存活，--full 完整真实性）")
    p_v.add_argument("--full", action="store_true", help="完整真实性校验（搜索/发现至少一项可用，发布前用）")
    p_v.add_argument("--start", type=int, default=0, help="起始索引")
    p_v.add_argument("--count", type=int, default=0, help="本批数量（0=全部）")
    p_f = sub.add_parser("final", help="整理+净化规则+报告+发布")
    p_f.add_argument("--publish", action="store_true", help="发布到GitHub")
    p_f.add_argument("--input", help="合格源文件路径（默认 validated.json）")

    args = parser.parse_args()
    if args.cmd == "clean":
        cmd_clean(args)
    elif args.cmd == "validate":
        cmd_validate(args)
    elif args.cmd == "final":
        cmd_final(args)


if __name__ == "__main__":
    main()
