# -*- coding: utf-8 -*-
"""
autocollect_core 整理模块（第四阶段）
四字纯汉字改名 / 分组分类 / customOrder排序 / 大厂源保护
"""

import re

from .utils import get_domain, log
from .cleaner import is_big_site


def generate_chinese_name(source, used_names):
    """生成四字纯汉字名称"""
    original = source.get("bookSourceName", "")
    # 去掉表情和特殊字符
    clean = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9]', '', original)
    # 提取中文部分
    chinese = re.findall(r'[\u4e00-\u9fa5]+', clean)
    if chinese:
        name = "".join(chinese)[:4]
    else:
        # 没有中文就用域名首字母转拼音（简化处理）
        domain = get_domain(source.get("bookSourceUrl", ""))
        name = "书源" + domain[:2].upper()

    # 确保是纯汉字
    if not re.match(r'^[\u4e00-\u9fa5]+$', name):
        name = "小说站" + str(len(used_names) % 10)

    # 去重
    base_name = name
    i = 2
    while name in used_names:
        # 加一个字区分
        suffix = ["阁", "楼", "斋", "居", "轩", "苑", "堂", "馆"][len(used_names) % 8]
        name = base_name[:3] + suffix
        if name in used_names:
            name = base_name[:2] + suffix + str(i)
        i += 1

    used_names.add(name)
    return name


def classify_source(source):
    """分类：大厂/笔趣阁/玄幻/言情/综合"""
    url = source.get("bookSourceUrl", "")
    name = source.get("bookSourceName", "")
    group = source.get("bookSourceGroup", "")

    if is_big_site(source):
        return "大厂正版"

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

    used_names = set()
    result = []
    custom_order = 1

    # 1. 大厂源：强制从现有仓库拿，新采集的一律跳过不覆盖
    big_sites = [s for s in existing_sources if is_big_site(s)]
    log.info(f"大厂源: {len(big_sites)} 个（强制保护，保留手动调好的配置）")

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

    # 按分组排序
    groups = {"笔趣阁类": [], "玄幻武侠": [], "言情女频": [], "综合其他": []}
    for s in other_sources:
        group = classify_source(s)
        if group in groups:
            groups[group].append(s)
        else:
            groups["综合其他"].append(s)

    for group_name in ["笔趣阁类", "玄幻武侠", "言情女频", "综合其他"]:
        for s in groups[group_name]:
            # 改名
            new_name = generate_chinese_name(s, used_names)
            s["bookSourceName"] = new_name
            s["customOrder"] = custom_order
            custom_order += 1
            result.append(s)

    log.info(f"整理完成，共 {len(result)} 个源")
    return result
