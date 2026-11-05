# -*- coding: utf-8 -*-
"""
autocollect_core 校验模块（第三阶段）
规则完整性检查 / 快速校验 / 完整校验 / 批量两级过滤
"""

from concurrent.futures import ThreadPoolExecutor, as_completed

from .config import CONCURRENCY, FULL_TEST_KEYWORDS, QUICK_TEST_KEYWORD
from .utils import fetch_url, get_domain, log


def check_rule_integrity(source):
    """按官方规范检查书源规则完整性"""
    # 必填字段检查
    required_fields = [
        "bookSourceUrl",
        "bookSourceName",
        "searchUrl",
    ]
    for field in required_fields:
        if not source.get(field):
            return False

    # 规则对象检查（防御异常格式：可能是list/str等）
    rule_search = source.get("ruleSearch", {})
    rule_book_info = source.get("ruleBookInfo", {})
    rule_toc = source.get("ruleToc", {})
    rule_content = source.get("ruleContent", {})
    if not isinstance(rule_search, dict):
        rule_search = {}
    if not isinstance(rule_book_info, dict):
        rule_book_info = {}
    if not isinstance(rule_toc, dict):
        rule_toc = {}
    if not isinstance(rule_content, dict):
        rule_content = {}

    # 搜索规则必须有bookList和name
    if not rule_search.get("bookList"):
        return False
    if not rule_search.get("name"):
        return False

    # 详情规则必须有name和intro（至少有一个）
    if not rule_book_info.get("name") and not rule_book_info.get("intro"):
        return False

    # 目录规则必须有chapterList
    if not rule_toc.get("chapterList"):
        return False

    # 正文规则必须有content
    if not rule_content.get("content"):
        return False

    return True


def quick_validate(source):
    """快速校验：首页可达性 + 搜索接口连通性"""
    url = source.get("bookSourceUrl", "")
    domain = get_domain(url)
    search_url = source.get("searchUrl", "")

    result = {
        "source": source,
        "domain": domain,
        "alive": False,
        "waf": False,
        "search_ok": False,
        "reason": ""
    }

    # 第一步：测试首页可达性（探测场景不重试，死站直接判死提速）
    try:
        resp = fetch_url(url, timeout=4, retry=0)
        if resp is None:
            result["reason"] = "首页连接失败"
            return result

        if resp.status_code == 200:
            result["alive"] = True
        elif resp.status_code in [403, 405, 503]:
            result["waf"] = True  # WAF盾站，不淘汰
            result["alive"] = True
        elif resp.status_code == 404:
            result["reason"] = "首页404"
            return result
        else:
            result["alive"] = True

    except Exception as e:
        result["reason"] = "首页请求异常"
        return result

    # 第二步：测试搜索接口连通性（简化版）
    if search_url and result["alive"]:
        try:
            # 从searchUrl提取实际请求地址
            test_keyword = QUICK_TEST_KEYWORD

            # 构造测试URL
            if search_url.startswith("http"):
                test_url = search_url.replace("{{key}}", test_keyword).replace("searchKey", test_keyword)
            else:
                # 相对路径，拼接域名
                base = url.rstrip("/")
                path = search_url.split(",")[0]  # 取第一个逗号前的部分
                if path.startswith("/"):
                    test_url = base + path.replace("{{key}}", test_keyword)
                else:
                    test_url = base + "/" + path.replace("{{key}}", test_keyword)

            # 发测试请求（不重试）
            s_resp = fetch_url(test_url, timeout=6, retry=0)
            if s_resp and s_resp.status_code == 200:
                # 看看返回内容是不是正常（不是空的，不是错误页）
                content = s_resp.text
                if len(content) > 100:  # 至少有内容
                    result["search_ok"] = True
                else:
                    result["reason"] = "搜索返回内容太少"
            elif s_resp and s_resp.status_code in [403, 405]:
                result["search_ok"] = True  # WAF站搜索接口可能也被挡，但不淘汰
            else:
                result["reason"] = f"搜索接口{s_resp.status_code if s_resp else '失败'}"

        except Exception as e:
            result["reason"] = "搜索测试异常"
            # 搜索测试失败不直接淘汰，首页活着就留着
            result["search_ok"] = False
    else:
        result["search_ok"] = result["alive"]  # 没有searchUrl的，首页活着就算过

    return result


def full_validate(source):
    """完整校验：多关键词搜索测试"""
    search_url = source.get("searchUrl", "")
    url = source.get("bookSourceUrl", "")

    # 没有搜索规则的，直接不通过
    if not search_url:
        return {"source": source, "pass_rate": 0.0, "keywords_pass": 0}

    keywords_pass = 0
    test_keywords = FULL_TEST_KEYWORDS[:3]  # 先测3个关键词，够了

    for kw in test_keywords:
        try:
            # 构造搜索URL
            if search_url.startswith("http"):
                test_url = search_url.replace("{{key}}", kw).replace("searchKey", kw)
            else:
                base = url.rstrip("/")
                path = search_url.split(",")[0]
                if path.startswith("/"):
                    test_url = base + path.replace("{{key}}", kw)
                else:
                    test_url = base + "/" + path.replace("{{key}}", kw)

            resp = fetch_url(test_url, timeout=5, retry=0)
            if resp and resp.status_code == 200 and len(resp.text) > 200:
                keywords_pass += 1
        except Exception:
            pass

    pass_rate = keywords_pass / len(test_keywords) if test_keywords else 0
    return {
        "source": source,
        "pass_rate": pass_rate,
        "keywords_pass": keywords_pass
    }


def validate_sources(sources):
    """批量校验：两级过滤"""
    log.info("=== 开始校验 ===")
    log.info(f"待校验: {len(sources)} 个")

    # 第一遍：快速过滤
    log.info("第一遍：快速过滤（首页+搜索接口连通性）...")
    quick_results = []
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
        futures = {executor.submit(quick_validate, s): s for s in sources}
        for future in as_completed(futures):
            result = future.result()
            quick_results.append(result)

    alive_sources = [r for r in quick_results if r["alive"]]
    dead_sources = [r for r in quick_results if not r["alive"]]
    log.info(f"快速过滤: 存活 {len(alive_sources)} 个，淘汰 {len(dead_sources)} 个")

    # 第二遍：完整校验（多关键词搜索测试，并发执行）
    log.info("第二遍：完整校验（3个关键词搜索测试）...")
    full_results = []
    low_pass = []
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
        futures = {executor.submit(full_validate, r["source"]): r for r in alive_sources}
        for future in as_completed(futures):
            r = futures[future]
            full_r = future.result()
            # 通过率低于30%的，标记为低质量
            if full_r["pass_rate"] >= 0.3:
                full_results.append(full_r)
            else:
                low_pass.append({"source": r["source"], "reason": f"搜索通过率低({full_r['pass_rate']*100:.0f}%)"})

    dead_sources.extend(low_pass)
    log.info(f"完整校验: 合格 {len(full_results)} 个，淘汰低质量 {len(low_pass)} 个")

    # 按通过率排序
    full_results.sort(key=lambda x: x["pass_rate"], reverse=True)

    return full_results, dead_sources
