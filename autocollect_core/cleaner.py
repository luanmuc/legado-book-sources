# -*- coding: utf-8 -*-
"""
autocollect_core 清洗去重模块（第二阶段）
格式校验 / URL清理 / 域名去重 / 非小说过滤 / 规则完整性过滤
"""

from .config import (ADULT_GROUP, BIG_SITES, JUNK_DEAD_KW, JUNK_ADULT_KW,
                     JUNK_NON_NOVEL_KW, JUNK_TEST_KW, NON_NOVEL_KEYWORDS)
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

    # 3. 过滤非小说源（成人内容豁免：成人漫画/影视等非小说类也保留）
    novel_sources = [s for s in deduped if not is_non_novel(s) or is_adult_source(s)]
    log.info(f"过滤非小说后: {len(novel_sources)} 个（成人内容已豁免保留）")

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


def _source_blob(s):
    name = s.get("bookSourceName") or ""
    url = s.get("bookSourceUrl") or ""
    group = s.get("bookSourceGroup") or ""
    return (name + " " + url + " " + group).lower()


def classify_junk(s):
    """垃圾源分类：返回 非小说/测试占位/失效标记，干净源返回 None"""
    blob = _source_blob(s)
    if any(k.lower() in blob for k in JUNK_NON_NOVEL_KW):
        return "非小说"
    if any(k.lower() in blob for k in JUNK_TEST_KW):
        return "测试占位"
    if any(k.lower() in blob for k in JUNK_DEAD_KW):  # blob已小写，关键词统一lower避免大小写漏判
        return "失效标记"
    return None


def is_adult_source(s):
    """是否为成人内容源"""
    blob = _source_blob(s)
    return any(k.lower() in blob for k in JUNK_ADULT_KW)


def filter_junk_sources(items, keep_adult=True):
    """垃圾过滤（集成到主流程）：剔除垃圾，成人内容保留并归入ADULT_GROUP分组
    items: 校验合格列表（包装结构 {source, pass_rate} 或裸源 dict 均可，原样返回）

    规则优先级（2026-11-06 用户要求：所有过滤保留成人内容，除了失效的不保留；
    不单单保留书源，成人漫画/影视等非小说类也保留）：
    1. 失效标记 / 测试占位：一律剔除（成人内容也不例外）
    2. 成人内容：无条件保留（含成人漫画/影视/游戏等非小说类）
    3. 其余非小说：剔除
    """
    junk_counts = {}
    adult_count = 0
    kept = []
    for item in items:
        s = item.get("source", item) if isinstance(item, dict) else item
        blob = _source_blob(s)
        # 1. 失效/测试：无条件剔除（优先于成人判断——"除了失效的不保留"）
        if any(k.lower() in blob for k in JUNK_DEAD_KW):
            junk_counts["失效标记"] = junk_counts.get("失效标记", 0) + 1
            continue
        if any(k.lower() in blob for k in JUNK_TEST_KW):
            junk_counts["测试占位"] = junk_counts.get("测试占位", 0) + 1
            continue
        # 2. 成人内容：无条件保留（即使名字含"漫画/影视"等非小说词也不当垃圾剔）
        if keep_adult and is_adult_source(s):
            s["bookSourceGroup"] = ADULT_GROUP  # 成人源统一归组，organize 单独分组（排序最末）
            adult_count += 1
            kept.append(item)
            continue
        # 3. 其余非小说 → 剔除
        reason = classify_junk(s)
        if reason:
            junk_counts[reason] = junk_counts.get(reason, 0) + 1
            continue
        kept.append(item)

    log.info(f"垃圾过滤: 剔除 {sum(junk_counts.values())} 个 {junk_counts}")
    log.info(f"成人内容保留 {adult_count} 个（归入{ADULT_GROUP}分组，排序最末）")
    log.info(f"过滤后干净源 {len(kept)} 个")
    return kept
