# -*- coding: utf-8 -*-
"""
autocollect_core 清洗去重模块（第二阶段）
格式校验 / URL清理 / 域名去重 / 非小说过滤 / 规则完整性过滤
"""

from .config import BIG_SITES, NON_NOVEL_KEYWORDS
from .utils import clean_url, get_domain, log
from .validators import check_rule_integrity


def is_non_novel(source):
    """判断是否为非小说源"""
    name = source.get("bookSourceName", "").lower()
    url = source.get("bookSourceUrl", "").lower()
    for kw in NON_NOVEL_KEYWORDS:
        if kw.lower() in name or kw.lower() in url:
            return True
    return False


def is_big_site(source):
    """判断是否为大厂源（精确匹配，避免误判）"""
    url = source.get("bookSourceUrl", "")
    domain = get_domain(url)
    for big in BIG_SITES:
        big_domain = get_domain(big["url"])
        # 精确匹配 或者 是大厂域名的子域名
        if domain == big_domain or domain.endswith("." + big_domain):
            return True
    return False


def clean_and_dedup(sources):
    """清洗和去重"""
    log.info("=== 开始清洗去重 ===")
    log.info(f"原始数据: {len(sources)} 个")

    # 1. 基础格式校验 + URL清理
    valid = []
    for s in sources:
        if not isinstance(s, dict):
            continue
        url = s.get("bookSourceUrl", "")
        if not url:
            continue
        # 清理URL
        s["bookSourceUrl"] = clean_url(url)
        if not s.get("bookSourceName"):
            continue
        valid.append(s)
    log.info(f"格式校验通过: {len(valid)} 个")

    # 2. 按域名去重（保留字段最完整的）
    domain_map = {}
    for s in valid:
        domain = get_domain(s["bookSourceUrl"])
        # 计算字段完整度（字段越多越好）
        score = len([k for k, v in s.items() if v and v != ""])
        if domain not in domain_map or score > len([k for k, v in domain_map[domain].items() if v and v != ""]):
            domain_map[domain] = s

    deduped = list(domain_map.values())
    log.info(f"域名去重后: {len(deduped)} 个")

    # 3. 过滤非小说源
    novel_sources = [s for s in deduped if not is_non_novel(s)]
    log.info(f"过滤非小说后: {len(novel_sources)} 个")

    # 4. 规则完整性校验（按官方规范）
    valid_sources = []
    invalid_count = 0
    for s in novel_sources:
        if check_rule_integrity(s):
            valid_sources.append(s)
        else:
            invalid_count += 1
    log.info(f"规则完整性校验: 通过 {len(valid_sources)} 个，淘汰 {invalid_count} 个")

    return valid_sources
