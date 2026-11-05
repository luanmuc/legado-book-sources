# -*- coding: utf-8 -*-
"""
autocollect_core 净化规则模块
采集大佬净化规则 / 分组优化 / 生成配套净化规则（单独文件，不写入书源）
"""

import json

from .config import CLEAN_RULES_FILE, DATA_SOURCES
from .utils import fetch_url, log


def collect_clean_rules():
    """采集各个大佬的净化规则"""
    log.info("=== 采集净化规则 ===")
    all_rules = []

    for source in DATA_SOURCES.get("clean_rules_sources", []):
        name = source["name"]
        url = source["url"]
        log.info(f"  采集 {name}...")

        resp = fetch_url(url, timeout=15)
        if resp and resp.status_code == 200:
            try:
                rules = resp.json()
                if isinstance(rules, list):
                    all_rules.extend(rules)
                    log.info(f"    成功: {len(rules)} 条")
            except Exception:
                log.warning(f"    格式错误")

    log.info(f"净化规则采集完成，共 {len(all_rules)} 条")
    return all_rules


def optimize_clean_rules(rules):
    """优化净化规则：分组简化、合并同类、按优先级排序"""
    # 分组映射表
    group_map = {
        "禁词": "禁词过滤",
        "广告": "广告净化",
        "错字": "错字修正",
        "和谐": "和谐还原",
        "标点": "标点修正",
        "标题": "标题净化",
        "英语": "英语翻译",
        "冗余": "冗余清理",
        "修正": "内容修正",
        "排版": "排版优化",
        "清理": "内容清理",
        "净化": "内容清理",
        "星号": "格式修正",
        "格式": "格式修正",
        "转化": "内容清理",
        "通用": "通用净化",
    }

    # 分组优先级（order越小越先执行）
    group_priority = {
        "格式修正": 10,
        "通用净化": 15,
        "广告净化": 20,
        "内容清理": 30,
        "冗余清理": 40,
        "排版优化": 50,
        "标点修正": 60,
        "错字修正": 70,
        "内容修正": 80,
        "和谐还原": 90,
        "禁词过滤": 100,
        "标题净化": 110,
        "英语翻译": 120,
    }

    # 简化分组名
    for r in rules:
        old_group = r.get("group", "")
        new_group = "其他"
        for key, target in group_map.items():
            if key in old_group:
                new_group = target
                break
        r["group"] = new_group

    # 按分组优先级排序
    rules.sort(key=lambda x: group_priority.get(x["group"], 500))

    # 重新编号id
    for i, r in enumerate(rules):
        r["id"] = i + 1

    return rules


def generate_clean_rules(sources, collected_rules=None):
    """生成配套净化规则：采集的 + 通用的，合并去重优化（单独文件，不写入书源）"""
    log.info("=== 生成配套净化规则 ===")

    # 通用规则（格式对齐官方）
    default_rules = [
        {
            "name": "通用-去除脚本标签",
            "group": "通用净化",
            "pattern": "<script[\\s\\S]*?</script>",
            "replacement": "",
            "isRegex": True,
            "isEnabled": True,
            "order": 1,
            "scopeContent": True,
            "scopeSource": False,
            "scopeTitle": False,
            "timeoutMillisecond": 3000
        },
        {
            "name": "通用-去除样式标签",
            "group": "通用净化",
            "pattern": "<style[\\s\\S]*?</style>",
            "replacement": "",
            "isRegex": True,
            "isEnabled": True,
            "order": 2,
            "scopeContent": True,
            "scopeSource": False,
            "scopeTitle": False,
            "timeoutMillisecond": 3000
        },
        {
            "name": "通用-去除广告文字",
            "group": "通用净化",
            "pattern": "下载APP|扫码阅读|关注公众号|点击加载全文|热门推荐|相关推荐|本章未完|点击下一章继续阅读",
            "replacement": "",
            "isRegex": True,
            "isEnabled": True,
            "order": 3,
            "scopeContent": True,
            "scopeSource": False,
            "scopeTitle": False,
            "timeoutMillisecond": 3000
        },
    ]

    # 合并采集的和默认的
    all_rules = []
    if collected_rules:
        all_rules.extend(collected_rules)
    all_rules.extend(default_rules)

    # 按pattern去重
    seen = set()
    unique_rules = []
    for r in all_rules:
        pattern = r.get("pattern", "")
        if pattern and pattern not in seen:
            seen.add(pattern)
            unique_rules.append(r)

    # 优化：分组简化、合并、排序
    optimized = optimize_clean_rules(unique_rules)

    # 保存
    with open(CLEAN_RULES_FILE, "w", encoding="utf-8") as f:
        json.dump(optimized, f, ensure_ascii=False, indent=2)

    log.info(f"净化规则生成完成，共 {len(optimized)} 条（采集{len(collected_rules or [])} + 通用{len(default_rules)}，去重优化后）")
    return optimized
