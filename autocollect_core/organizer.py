# -*- coding: utf-8 -*-
"""
autocollect_core 整理模块（第四阶段）
分组分类 / customOrder排序 / 大厂源保护

命名相关（生成名、自然排序、同族重编号）已拆到 naming.py：
  · naming.py 只管「源起什么名、尾号怎么连续」
  · organizer.py 只管「分几组、大厂怎么保护、customOrder 怎么分配」
"""

import re

from .config import ADULT_GROUP, BIG_SITES
from .utils import clean_url, get_domain, log
from .cleaner import is_big_site
from .naming import natural_name_key, generate_chinese_name, renumber_name_families


def classify_source(source):
    """分类：大厂/笔趣阁/玄幻/言情/成人/综合"""
    url = source.get("bookSourceUrl", "")
    name = source.get("bookSourceName", "")
    group = source.get("bookSourceGroup", "")

    if is_big_site(source):
        return "大厂正版"

    # 成人书源（filter_junk_sources 已统一打标记）
    if group == ADULT_GROUP:
        return ADULT_GROUP

    domain = get_domain(url)

    # 笔趣阁类
    biquge_keywords = ["biquge", "笔趣", "bqg", "藏花阁", "飘天文学", "小说阅读网"]
    for kw in biquge_keywords:
        if kw in domain.lower() or kw in name.lower():
            return "笔趣阁类"

    # 言情女频类
    romance_keywords = ["言情", "女频", "耽美", "晋江", "红袖", "潇湘", "花语女生"]
    for kw in romance_keywords:
        if kw in name.lower() or kw in group.lower() or kw in domain.lower():
            return "言情女频"

    # 玄幻武侠类
    xuanhuan_keywords = ["玄幻", "武侠", "修真", "修仙", "奇幻"]
    for kw in xuanhuan_keywords:
        if kw in name.lower() or kw in group.lower():
            return "玄幻武侠"

    return "综合其他"


def organize_sources(validated_sources, existing_sources):
    """整理：改名、分组、排序（大厂源强制保护，不被新采集覆盖）"""
    log.info("=== 开始整理 ===")

    # 0. 统一清理URL（防上游"已整理/已校验"等中文注释污染，覆盖 --stage/--publish-pending 全部路径）
    def _clean(src):
        # 兼容两种结构：校验输出为 {"source": {...}} 包装，正式版为裸源 dict
        item = src.get("source", src) if isinstance(src, dict) else src
        u = item.get("bookSourceUrl")
        if u:
            item["bookSourceUrl"] = clean_url(u)
        return src

    validated_sources = [_clean(s) for s in validated_sources]
    existing_sources = [_clean(s) for s in existing_sources]

    used_names = set()
    result = []
    custom_order = 1

    # 1. 大厂源：强制从现有仓库拿，新采集的一律跳过不覆盖
    big_sites = [s for s in existing_sources if is_big_site(s)]
    # 大厂顺序固定按 config.BIG_SITES（手动调好的顺序），不允许被名字排序或采集顺序覆盖
    def _big_key(x):
        u = (x.get("bookSourceUrl") or "").rstrip("/")
        for i, bt in enumerate(BIG_SITES):
            ou = bt["url"].rstrip("/")
            if u == ou or u.startswith(ou):
                return i
        return 99
    big_sites.sort(key=_big_key)
    log.info(f"大厂源: {len(big_sites)} 个（强制保护，保留手动调好的配置与顺序）")

    for s in big_sites:
        s["customOrder"] = custom_order
        custom_order += 1
        used_names.add(s.get("bookSourceName", ""))
        result.append(s)

    # 2. 其他源：新采集的，跳过所有大厂域名（避免重复）
    other_sources = []
    skipped_big = 0
    for r in validated_sources:
        s = r["source"]
        if is_big_site(s):
            skipped_big += 1
            continue
        other_sources.append(s)

    if skipped_big > 0:
        log.info(f"跳过新采集的大厂源: {skipped_big} 个（不覆盖手动调好的版本）")
    log.info(f"其他源: {len(other_sources)} 个")

    # 按分组排序（成人书源放最后）
    groups = {"笔趣阁类": [], "玄幻武侠": [], "言情女频": [], "综合其他": [], ADULT_GROUP: []}
    for s in other_sources:
        group = classify_source(s)
        if group in groups:
            groups[group].append(s)
        else:
            groups["综合其他"].append(s)

    for group_name in ["笔趣阁类", "玄幻武侠", "言情女频", "综合其他", ADULT_GROUP]:
        # 组内先按域名排序改名，保证名字-域名绑定稳定（序号分配不漂移）
        items = sorted(groups[group_name], key=lambda x: x.get("bookSourceUrl", ""))
        for s in items:
            # 规范化分组写回（覆盖原始乱分组/emoji/状态标记）
            s["bookSourceGroup"] = group_name
            if group_name == ADULT_GROUP:
                # 成人源豁免改名（2026-11-06 用户要求）：保留原名，仅重名时追加序号去重
                name = (s.get("bookSourceName") or "").strip() or "成人书源"
                if name in used_names:
                    i = 2
                    while f"{name}{i}" in used_names:
                        i += 1
                    name = f"{name}{i}"
                s["bookSourceName"] = name
                used_names.add(name)
            else:
                # 改名
                s["bookSourceName"] = generate_chinese_name(s, used_names, group_name)

        # 改名后按"名字族+数值"自然排序：同族名字（笔趣阁/笔趣阁2/...）聚合相邻，
        # 序号按数值递增（笔趣阁2 在 笔趣阁3 前，而非字典序 笔趣阁10<笔趣阁2）
        for s in sorted(items, key=natural_name_key):
            s["customOrder"] = custom_order
            custom_order += 1
            result.append(s)

    renumber_name_families(result)
    log.info(f"整理完成，共 {len(result)} 个源")
    return result
