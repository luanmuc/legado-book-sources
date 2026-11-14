# -*- coding: utf-8 -*-
"""
autocollect_core 校验模块（第三阶段）
规则完整性检查 / 快速校验 / 完整校验 / 批量两级过滤
"""

from concurrent.futures import ThreadPoolExecutor, as_completed

from .legado_rules import parse_rule_list, parse_first_attr

from .config import (CONCURRENCY, FULL_TEST_KEYWORDS, GENERIC_TEST_KEYWORDS,
                     QUICK_TEST_KEYWORD)
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

    # 第一步：首页可达性 —— 必须复用全管道唯一判死口径（liveness.probe_alive）
    # 2026-11-10 修：原来这里用 fetch_url(timeout=4, retry=0)，任何超时/代理失败都当死站。
    # 实测：648 源经此判死 407 条，抽样 20 条复测 0 条真死（5 条站是活的、15 条无法判定），
    # 等于把「代理抽风」当「站没了」，一次发布误杀 400+ 源。判死只认 404/410 与域名不存在。
    from .liveness import probe_alive

    verdict = probe_alive(source, timeout=6)
    if verdict == "dead":
        result["reason"] = "确定性死站（404/410 或域名解析不出）"
        return result
    result["alive"] = True
    result["reason"] = "" if verdict == "ok" else "链路不稳/无法判定，保留"

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


def validate_sources(sources, mode="quick"):
    """批量校验，分两档（2026-11-06 用户明确要求分级）

    档位由调用阶段决定：
      mode="quick"（采集池第一遍，量级大）：只做存活校验——首页可达性 + WAF 识别，
                    快速剔除死站，不解析规则（1345+ 源也能几分钟跑完）
      mode="full"（发布前，一步不少）：存活校验 + 真实性校验
                    （搜索/发现至少一项能用规则解析出书才算可用）

    full 档判定：
      - usable=True   → 合格 pass_rate=1.0
      - usable=None   → 网络/反爬无法判定（blocked）→ 保留待验 pass_rate=0.6
      - usable=False  → 搜索和发现都解析不出（内容已换/规则失效）→ 淘汰
      - 大厂源（BIG_SITES）永不淘汰（本机网络/反爬环境判定不可靠，阅读器端可用）
    """
    from .cleaner import is_big_site

    log.info("=== 开始校验 ===")
    log.info(f"待校验: {len(sources)} 个 | 档位: {'快速存活（采集池）' if mode == 'quick' else '完整真实性（发布前）'}")

    # 第一遍：快速过滤（两档共用）
    log.info("第一遍：快速过滤（首页连通性/WAF 识别）...")
    quick_results = []
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
        futures = {executor.submit(quick_validate, s): s for s in sources}
        for future in as_completed(futures):
            result = future.result()
            quick_results.append(result)

    alive_sources = [r for r in quick_results if r["alive"]]
    dead_sources = [r for r in quick_results if not r["alive"]]
    log.info(f"快速过滤: 存活 {len(alive_sources)} 个，淘汰 {len(dead_sources)} 个")

    # 快速档：采集池第一遍到此为止（量大，只做存活）
    if mode == "quick":
        results = [{"source": r["source"], "pass_rate": 1.0, "alive": True} for r in alive_sources]
        log.info(f"快速存活校验完成: 合格 {len(results)} 个（规则真实性校验留到发布前）")
        return results, dead_sources

    # 完整档：真实可用性校验（搜索/发现至少一项能解析出书）
    log.info("第二遍：真实规则解析校验（搜索/发现至少一项可用；大厂保护不淘汰）...")
    full_results = []
    low_pass = []
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
        futures = {executor.submit(check_source_usable, r["source"]): r for r in alive_sources}
        for future in as_completed(futures):
            base = futures[future]
            src = base["source"]
            try:
                r = future.result()
            except Exception as e:
                r = {"usable": None, "search": "error", "explore": None,
                     "detail": f"校验异常 {type(e).__name__}"}
            usable = r.get("usable")
            is_big = is_big_site(src)
            if usable is True:
                item = {"source": src, "pass_rate": 1.0,
                        "usable": True, "detail": r.get("detail", "")}
                if r.get("relaxed_adult"):
                    item["relaxed_adult"] = True
                full_results.append(item)
            elif usable is None:
                # blocked（网络异常/反爬/WAF）：无法判定，保留；大厂直接按合格处理
                full_results.append({"source": src, "pass_rate": 1.0 if is_big else 0.6,
                                     "usable": None,
                                     "big_protected": is_big,
                                     "detail": r.get("detail", "")})
            else:  # usable is False
                if is_big:
                    # 大厂永不淘汰
                    full_results.append({"source": src, "pass_rate": 0.5,
                                         "usable": False, "big_protected": True,
                                         "detail": r.get("detail", "")})
                else:
                    low_pass.append({"source": src,
                                     "reason": f"搜索/发现均失效: {r.get('detail', '')[:100]}"})

    dead_sources.extend(low_pass)
    log.info(f"可用性校验: 合格 {len(full_results)} 个（其中无法判定保留 "
             f"{len([x for x in full_results if x.get('usable') is None])}、"
             f"成人宽松豁免 {len([x for x in full_results if x.get('relaxed_adult')])}、"
             f"大厂保护 {len([x for x in full_results if x.get('big_protected')])}），"
             f"淘汰失效 {len(low_pass)} 个")

    # 按通过率排序
    full_results.sort(key=lambda x: x["pass_rate"], reverse=True)

    return full_results, dead_sources


def validate_sources_with_checkpoint(sources, tag, batch=300, mode="quick"):
    """两级校验 + 断点续传（主流程 --stage/--publish/--publish-pending 使用）

    每批校验结果立即落盘 raw/autocollect/ckpt_{tag}_validated.json / ckpt_{tag}_dead.json；
    重启时读取已验URL自动跳过（真正断点续传，不用从头重跑）；
    全部校验完成后删除checkpoint文件，下次同一tag从头开始。

    tag: 输入标识（如 cleaned文件名、pending），输入不同tag不同，互不干扰。
    mode: "quick"=只存活（采集池第一遍，量大快筛）| "full"=存活+真实性（发布前一步不少）
          两种档位 checkpoint 文件自动分名（ckpt_{tag}_{mode}_*.json），互不覆盖。
    """
    import json
    import os

    from .config import RAW_DIR

    def _url(item):
        # 兼容裸源 dict（bookSourceUrl 顶层）与包装结构（{source: {...}}）
        if not isinstance(item, dict):
            return ""
        if "source" in item and isinstance(item["source"], dict):
            return item["source"].get("bookSourceUrl", "")
        return item.get("bookSourceUrl", "")

    vfile = os.path.join(RAW_DIR, f"ckpt_{tag}_{mode}_validated.json")
    dfile = os.path.join(RAW_DIR, f"ckpt_{tag}_{mode}_dead.json")
    os.makedirs(RAW_DIR, exist_ok=True)

    validated, dead_acc = [], []
    done = set()
    if os.path.exists(vfile):
        try:
            with open(vfile, encoding="utf-8") as f:
                validated = json.load(f)
            done = {_url(v) for v in validated if _url(v)}
            log.info(f"断点续传: 已校验 {len(validated)} 个（{vfile}）")
        except Exception as e:
            log.warning(f"checkpoint损坏，从头校验: {e}")
            validated = []
    if os.path.exists(dfile):
        try:
            with open(dfile, encoding="utf-8") as f:
                dead_acc = json.load(f)
            done |= {_url(d) for d in dead_acc if _url(d)}  # 已淘汰的源同样不重跑
        except Exception:
            dead_acc = []

    todo = [s for s in sources if _url(s) and _url(s) not in done]
    log.info(f"校验断点: 共 {len(sources)} 个，已验 {len(validated)}，待验 {len(todo)}")
    if not todo:
        log.info("全部已校验，直接复用结果")
    for i in range(0, len(todo), batch):
        batch_sources = todo[i:i + batch]
        v, d = validate_sources(batch_sources, mode=mode)
        validated.extend(v)
        dead_acc.extend(d)
        with open(vfile, "w", encoding="utf-8") as f:
            json.dump(validated, f, ensure_ascii=False, indent=2)
        with open(dfile, "w", encoding="utf-8") as f:
            json.dump(dead_acc, f, ensure_ascii=False, indent=2)
        log.info(f"  批次 [{i}:{i + len(batch_sources)}] 完成: 合格 {len(validated)} 累计，淘汰 {len(dead_acc)} 累计")

    for f in (vfile, dfile):
        if os.path.exists(f):
            os.remove(f)
    log.info(f"✅ 校验完成[{mode}]: 合格 {len(validated)}，淘汰 {len(dead_acc)}（checkpoint已清理）")
    return validated, dead_acc


# ==================== 真实规则解析校验（2026-11-06） ====================
# 背景：用户指出"网站活着 ≠ 书源有效"——域名还在但内容已换、搜索接口返回 200
# 也可能是无关页面。旧校验只判 HTTP 200 + 内容长度，无法识别此类失效。
# 新校验：用书源自身规则真正解析 HTML，至少解析出一本书才算可用。

import json as _json
import re as _re

import requests as _requests

from .legado_rules import is_script_rule, parse_book_list, parse_explore_entries


def _parse_lenient_json(text):
    """宽松解析书源配置 JSON

    实测大量书源 searchUrl 尾部配置用单引号（{'charset':'gbk','method':'POST'}），
    标准 json.loads 直接失败 → method/body/charset 全丢，POST 变 GET、编码失效。
    依次尝试：标准 JSON → 单引号转双引号 → 正则抠 method/body/charset。
    """
    if not text:
        return {}
    try:
        v = _json.loads(text)
        return v if isinstance(v, dict) else {}
    except Exception:
        pass
    try:
        v = _json.loads(text.replace("'", '"'))
        return v if isinstance(v, dict) else {}
    except Exception:
        pass
    out = {}
    for key in ("method", "body", "charset", "headers"):
        mm = _re.search(r"[\"']?%s[\"']?\s*:\s*[\"']([^\"']*)[\"']" % key, text)
        if mm:
            out[key] = mm.group(1)
    return out


def _build_search_request(source, keyword):
    """解析 searchUrl 为请求参数（支持 GET / POST + charset + JSON 配置）"""
    search_url = (source.get("searchUrl") or "").strip()
    base = (source.get("bookSourceUrl") or "").strip().rstrip("/")
    if not search_url:
        return None
    cfg = {}
    m = _re.search(r",\s*(\{.*\})\s*$", search_url, _re.S)
    if m:
        raw_cfg = m.group(1)
        cfg = _parse_lenient_json(raw_cfg)
        search_url = search_url[:m.start()].strip()
    if search_url.startswith("http"):
        url = search_url
    else:
        url = base + ("" if search_url.startswith(("/", "?")) else "/") + search_url
    method = (cfg.get("method") or "GET").upper()
    body = cfg.get("body")
    charset = cfg.get("charset")
    def _fill(t):
        # 先替换带花括号的完整占位符，再处理裸 searchKey（顺序错会把 {{searchKey}} 弄成 {{词}}）
        return (t.replace("{{searchKey}}", keyword).replace("{{key}}", keyword)
                 .replace("{{page}}", "1").replace("{{pageNo}}", "1")
                 .replace("searchKey", keyword))

    if body:
        body = _fill(body)
    url = _fill(url)
    return {"url": url, "method": method, "body": body, "charset": charset}


def _fetch_raw(req, timeout=8):
    """按请求参数发请求，返回 (status_code, html_text)

    编码策略：显式 charset > HTTP header > meta charset > apparent_encoding(chardet) > utf-8
    中文小站大量是 GBK/GB2312，requests 默认猜成 ISO-8859-1 会乱码导致规则解析失败。
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    if req["method"] == "POST":
        post_headers = dict(headers)
        post_headers["Content-Type"] = "application/x-www-form-urlencoded"
        resp = _requests.post(req["url"], data=(req["body"] or ""), headers=post_headers,
                              timeout=timeout, verify=False)
    else:
        resp = _requests.get(req["url"], headers=headers, timeout=timeout, verify=False)

    # 编码候选打分（实测大量站点 header/meta 声明与实际不符，直接信任会乱码致解析全灭）
    cands = []
    if req.get("charset"):
        cands.append(req["charset"])
    ctype = (resp.headers.get("Content-Type") or "").lower()
    m = _re.search(r"charset=([a-zA-Z0-9_\-]+)", ctype)
    if m:
        cands.append(m.group(1))
    m = _re.search(rb"charset=[\"']?([a-zA-Z0-9_\-]+)", resp.content[:3000])
    if m:
        cands.append(m.group(1).decode("ascii", errors="ignore"))
    try:
        cands.append(resp.apparent_encoding)
    except Exception:
        pass
    cands += ["utf-8", "gb18030"]

    seen, score_best, text_best = set(), -1, ""
    for enc in cands:
        if not enc:
            continue
        e = enc.lower()
        if e in seen or e in ("iso-8859-1", "ascii", "latin-1"):
            continue
        seen.add(e)
        try:
            t = resp.content.decode(enc, errors="ignore")
        except Exception:
            continue
        # 打分：常见汉字命中数 - 乱码替换字符惩罚
        score = sum(t.count(ch) for ch in "的一是在了有和人这中大为上个国我以要他时来用们")
        score -= t.count("\ufffd") * 5
        # GBK 误解码特征（UTF-8 内容按 GBK 解出会出现这些字）
        score -= sum(t.count(ch) for ch in "鍚鎺鍛闃銆绔欎") * 2
        if score > score_best:
            score_best, text_best = score, t
    if text_best:
        return resp.status_code, text_best
    return resp.status_code, resp.text


def _search_once(source, keyword):
    """单关键词搜索解析（内部使用）

    返回 (status: 'ok'|'bad'|'blocked', detail: str)
    """
    rule_search = source.get("ruleSearch") or {}
    if not isinstance(rule_search, dict):
        return "bad", "ruleSearch 非对象"
    book_list = rule_search.get("bookList")
    if not book_list:
        return "bad", "无 ruleSearch.bookList"
    req = _build_search_request(source, keyword)
    if not req:
        return "bad", "无 searchUrl"
    try:
        code, html = _fetch_raw(req)
    except Exception as e:
        return "blocked", f"请求异常 {type(e).__name__}"
    if code != 200:
        return "blocked", f"HTTP {code}"
    # 纯前端渲染页（React/Vue SPA）：静态 HTML 里没有结果，但阅读器 WebView 能渲染 → 不判失效
    low_html = html.lower()
    if len(html) < 4000 and any(k in low_html for k in (
            "you need to enable javascript", "enable javascript to run this app",
            "please enable javascript", "requires javascript")):
        return "blocked", "纯JS渲染页（静态无内容，WebView可渲染，不判失效）"
    try:
        r = parse_book_list(html, book_list, rule_search.get("name"), rule_search.get("bookUrl"))
    except Exception as e:
        return "bad", f"规则解析异常 {type(e).__name__}"
    if r["ok"]:
        sample = [(b["name"], b["url"]) for b in r["books"] if b["name"] or b["url"]][:2]
        # 官方校验会用 bookUrlPattern 判断「搜到的是不是书籍详情页」。
        # 559/2169 个源带该字段：解析出结果但 URL 全不匹配 → 很可能是搜索页/分类页被误当书，
        # 判 blocked（保留待验）而不是 bad（淘汰），宁滥勿缺。
        pattern = str(source.get("bookUrlPattern") or "").strip()
        if pattern:
            import re as _re
            urls = [b["url"] for b in r["books"] if b.get("url")]
            try:
                if urls and not any(_re.search(pattern, u) for u in urls):
                    return "blocked", (f"解析到 {len(urls)} 条但 URL 均不匹配 bookUrlPattern"
                                       f"（可能搜到的不是书籍详情页）")
            except _re.error:
                pass  # pattern 本身写错，不据此判死
        return "ok", f"解析成功 matched={r['matched']} 样例={sample}"

    # POST 配置过时回退（实测大量老源 method 写 POST，站点实际只认 GET）
    if req["method"] == "POST" and req.get("body"):
        try:
            q = req["body"].replace("{{key}}", keyword).replace("searchKey", keyword)
            sep = "&" if "?" in req["url"] else "?"
            g = {"url": req["url"] + sep + q, "method": "GET", "body": None,
                 "charset": req.get("charset")}
            code2, html2 = _fetch_raw(g)
            if code2 == 200:
                r2 = parse_book_list(html2, book_list, rule_search.get("name"),
                                     rule_search.get("bookUrl"))
                if r2["ok"]:
                    sample = [(b["name"], b["url"]) for b in r2["books"] if b["name"] or b["url"]][:2]
                    return "ok", f"POST空→GET回退成功 matched={r2['matched']} 样例={sample}"
        except Exception:
            pass

    return "bad", f"解析不出书籍 matched={r['matched']}"


def check_search_parsed(source, keywords=None, max_try=3):
    """真实搜索解析校验（通用关键词轮试，2026-11-06 用户要求用关键字而非书名）

    - 默认关键词池 GENERIC_TEST_KEYWORDS：["我的","天下","重生","总裁","王爷","系统","都市","修仙","神","爱"]
    - 每源最多试 max_try 个关键词，任一个解析出书即 ok（降低"该书本站没有"造成的误判）
    - 关键词逐一尝试：任一 ok → ok；有任一词返回 200 但解析不出、最终仍无 ok → bad；
      全部网络异常/非200 → blocked

    返回 (status: 'ok'|'bad'|'blocked', detail: str)
      ok      至少一个关键词解析出一本带 name 或 url 的书（规则真正可用）
      bad     有接口返回 200 但所有关键词都解析不出（网站内容已换 / 规则失效）——淘汰依据
      blocked 网络异常 / 非 200（反爬、WAF、代理）——不淘汰，需人工或换网络复验
    """
    # 规则依赖脚本/JSONPath → 静态解析无法复现，不判失效（保留待验）
    rule = source.get("ruleSearch") if isinstance(source.get("ruleSearch"), dict) else {}
    if is_script_rule(rule.get("bookList")):
        return "blocked", "搜索规则依赖脚本/JSONPath（静态无法解析，不判失效）"

    # 官方 BookSource.getCheckKeyword(default)：源自带 checkKeyWord 时优先用它，
    # 否则回落默认关键词。实测 481/2169 个源（起点/番茄/红袖/书旗/QQ阅读等）带此字段，
    # 用通用词去搜会被这些站判定成空结果 → 误杀。
    ck = str(rule.get("checkKeyWord") or "").strip()
    base = [k for k in (keywords or GENERIC_TEST_KEYWORDS) if k]
    if ck:
        keywords = ([ck] + [k for k in base if k != ck])[:max_try] if keywords else [ck]
    else:
        keywords = base[:max_try]
    if not keywords:
        keywords = [QUICK_TEST_KEYWORD]
    tried = []
    any_200 = False
    for kw in keywords:
        status, detail = _search_once(source, kw)
        if status == "ok":
            return "ok", f"关键词[{kw}] {detail}"
        if status == "bad":
            any_200 = True
        tried.append(f"[{kw}]{status}:{detail}")
    joined = " | ".join(tried)[:160]
    n_bad = sum(1 for k in tried if ":bad:" in k)
    n_blk = sum(1 for k in tried if ":blocked:" in k)
    # 证据分层，避免网络抖动误杀：
    #  ≥2 个关键词都拿到 200 却解析不出 → 内容确实变了 → bad
    #  只 1 个关键词 200 + 其余超时/异常 → 证据不足 → blocked（待验保留）
    if n_bad >= 2 or (n_bad == 1 and n_blk == 0):
        return "bad", f"{len(keywords)} 个关键词均解析不出书籍 {joined}"
    return "blocked", f"关键词请求多数异常，无法判定（200但解析不出 {n_bad} 个 / 异常 {n_blk} 个）{joined}"


def check_explore_parsed(source, max_entries=3, timeout=8):
    """发现页校验：exploreUrl 至少一个入口能用规则解析出书

    返回 (status: 'ok'|'bad'|'blocked'|None, detail: str)
      ok      至少 1 个入口解析成功（"发现页按钮有一个能用"）
      bad     所有入口返回 200 但都解析不出（发现页规则失效/内容已变）
      blocked 所有入口都网络异常/非 200（反爬/WAF，无法判定）
      None    无发现页配置（不适用，跳过该检查）
    """
    entries = parse_explore_entries(source.get("exploreUrl"))
    rule = source.get("ruleExplore") or {}
    if not isinstance(rule, dict):
        rule = {}
    book_list = rule.get("bookList")
    if not entries or not book_list:
        return None, "无发现页配置" if not entries else "无 ruleExplore.bookList"
    if is_script_rule(book_list):
        return "blocked", "发现规则依赖脚本/JSONPath（静态无法解析，不判失效）"
    base = (source.get("bookSourceUrl") or "").strip().rstrip("/")
    tried = []
    got_200 = False
    for e in entries[:max_entries]:
        u = (e["url"] or "").replace("{{page}}", "1").replace("{{pageNo}}", "1")
        if not u:
            continue
        if not u.startswith("http"):
            u = base + ("" if u.startswith("/") else "/") + u
        tried.append(e["title"] or u)
        try:
            code, html = _fetch_raw({"url": u, "method": "GET", "body": None, "charset": None},
                                    timeout=timeout)
        except Exception:
            continue
        if code != 200:
            continue
        got_200 = True
        try:
            r = parse_book_list(html, book_list, rule.get("name"), rule.get("bookUrl"))
        except Exception:
            continue
        if r["ok"]:
            sample = [(b["name"], b["url"]) for b in r["books"] if b["name"] or b["url"]][:2]
            return "ok", f"入口[{e['title']}]解析成功 样例={sample}"
    if got_200:
        return "bad", f"{len(tried)} 个入口用规则全部解析失败 {tried}"
    return "blocked", f"{len(tried)} 个入口网络异常/非200 {tried}"


def check_adult_content_ready(source):
    """成人源"能否取内容"宽松校验（用户要求：成人源按实际情况校验，不拿书籍解析标准硬卡）

    背景：成人组里混有漫画/短剧/影视/图片/听书站，它们的规则本就是解析图片、视频、
    章节列表，用 ruleSearch.bookList 去要求"解析出书名"必然失败，会把能用的源误杀。

    改用"至少有一条能取内容的规则链"作为可用判据（不要求书名/封面解析）：
      - 正文规则 ruleContent（能取正文/图片列表）
      - 目录规则 ruleToc.bookList 或 chapterList
      - 搜索规则 ruleSearch.bookList
      - 发现规则 ruleExplore.bookList 或 exploreUrl
    四条只要有任意一条非空且格式正确 → 阅读器端可用，保留。
    四条全空 → 空壳规则（阅读器也读不出内容），淘汰。

    返回 (ready: bool, detail: str)
    """
    def _ok(v):
        return bool(v) and isinstance(v, (str, dict)) and str(v).strip() not in ("", "{}", "[]")

    checks = []
    r_info = source.get("ruleBookInfo") if isinstance(source.get("ruleBookInfo"), dict) else {}
    r_toc = source.get("ruleToc") if isinstance(source.get("ruleToc"), dict) else {}
    r_content = source.get("ruleContent") if isinstance(source.get("ruleContent"), dict) else {}
    r_search = source.get("ruleSearch") if isinstance(source.get("ruleSearch"), dict) else {}
    r_explore = source.get("ruleExplore") if isinstance(source.get("ruleExplore"), dict) else {}

    checks.append(("正文", _ok(r_content.get("content")) or _ok(source.get("ruleContentUrl"))))
    checks.append(("目录", _ok(r_toc.get("bookList")) or _ok(r_toc.get("chapterList")) or _ok(source.get("ruleTocUrl"))))
    checks.append(("搜索", _ok(r_search.get("bookList"))))
    checks.append(("发现", _ok(r_explore.get("bookList")) or _ok(source.get("exploreUrl"))))

    hits = [n for n, ok in checks if ok]
    if hits:
        return True, f"成人源宽松校验通过（可用规则: {'/'.join(hits)}）"
    return False, "成人源规则空壳（正文/目录/搜索/发现四条规则全无）"


# ============================================================
# 详情 → 目录 → 正文 三级链路校验（2026-11-14 按社区口径补）
# ============================================================
# 背景：社区对书源的校验分四项——搜索 / 详情 / 目录 / 正文，失败结果里
# 「详情失效」「目录失效」「正文失效」各占一类。原实现只校验搜索与发现的**解析**，
# 对详情/目录/正文仅检查「规则字符串非空」，等于一个源搜索能出书、正文打不开也放过去，
# 用户导入后照样读不了。这里按官方字段真实走一遍链路。

def _abs_url(url, source):
    """把相对 URL 补成绝对（书源里大量 /book/123 这种写法）"""
    u = str(url or "").strip()
    if not u:
        return ""
    if u.startswith("http"):
        return u
    base = str(source.get("bookSourceUrl") or "").strip().rstrip("/")
    if u.startswith("//"):
        return "https:" + u
    return base + ("" if u.startswith(("/", "?")) else "/") + u


def _pick_first_value(html, rule):
    """按单条规则取第一个非空值

    只吞「脏规则导致的解析异常」（上游书源常有 `[property~=las?test_chapter_name]`
    这种非法选择器）。NameError/ImportError 是自身代码缺陷，必须暴露，不能静默当成
    「解析不出」——上一版就是被宽 catch 吞掉，把好源误判成详情失效。
    """
    try:
        n, vals = parse_rule_list(html, rule, max_check=3)
        return vals[0] if vals else ""
    except (NameError, ImportError):
        raise
    except Exception:
        return ""


def check_detail_parsed(source, book, timeout=8):
    """详情页校验：要么按 ruleBookInfo 解析出字段，要么能拿到目录页 URL"""
    rule_info = source.get("ruleBookInfo") if isinstance(source.get("ruleBookInfo"), dict) else {}
    url = _abs_url(book.get("url"), source)
    if not url:
        return "bad", "搜索未返回书籍 URL"
    req = {"url": url, "method": "GET", "body": None, "charset": None}
    try:
        code, html = _fetch_raw(req, timeout=timeout)
    except Exception as e:
        return "blocked", f"详情请求异常 {type(e).__name__}"
    if code != 200:
        return "blocked", f"详情 HTTP {code}"

    toc_url = _pick_first_value(html, rule_info.get("tocUrl"))
    names = []
    for key in ("name", "author", "lastChapter"):
        v = _pick_first_value(html, rule_info.get(key))
        if v:
            names.append(f"{key}={v[:16]}")
    if toc_url or names:
        extra = f" tocUrl={toc_url[:60]}" if toc_url else ""
        return "ok", "详情解析到 " + (";".join(names) if names else "目录链接") + extra
    # 规则为空时不算失效：很多源的详情字段留空靠阅读器默认逻辑
    if not any(str(rule_info.get(k) or "").strip() for k in ("name", "author", "tocUrl")):
        return "blocked", "无详情规则（留空由阅读器默认处理，不判失效）"
    return "bad", "详情页字段全部解析不出"


def check_toc_parsed(source, book, detail_html=None, timeout=8):
    """目录页校验：ruleToc 至少解析出 1 章"""
    rule_toc = source.get("ruleToc") if isinstance(source.get("ruleToc"), dict) else {}
    rule_info = source.get("ruleBookInfo") if isinstance(source.get("ruleBookInfo"), dict) else {}
    url = _abs_url(book.get("url"), source)
    toc_url = ""
    if detail_html:
        toc_url = _pick_first_value(detail_html, rule_info.get("tocUrl"))
    toc_url = _abs_url(toc_url, source) if toc_url else url

    req = {"url": toc_url, "method": "GET", "body": None, "charset": None}
    try:
        code, html = _fetch_raw(req, timeout=timeout)
    except Exception as e:
        return "blocked", f"目录请求异常 {type(e).__name__}"

    book_list = rule_toc.get("bookList") or rule_toc.get("chapterList")
    if not book_list:
        return "blocked", "无目录规则（留空由阅读器默认处理，不判失效）"
    try:
        n, vals = parse_rule_list(html, book_list, max_check=3)
    except Exception as e:
        return "bad", f"目录规则解析异常 {type(e).__name__}"
    if vals:
        return "ok", f"目录解析到 {n} 项 首项={str(vals[0])[:24]}"
    return "bad", "目录页解析不出章节"


def check_content_parsed(source, chapter_url, timeout=8):
    """正文页校验：ruleContent.content 能取到实际内容（文本长度或图片数）"""
    rule_content = source.get("ruleContent") if isinstance(source.get("ruleContent"), dict) else {}
    content_rule = rule_content.get("content") or source.get("ruleContentUrl")
    if not content_rule:
        return "blocked", "无正文规则（留空由阅读器默认处理，不判失效）"
    url = _abs_url(chapter_url, source)
    if not url:
        return "bad", "无章节 URL"
    req = {"url": url, "method": "GET", "body": None, "charset": None}
    try:
        code, html = _fetch_raw(req, timeout=timeout)
    except Exception as e:
        return "blocked", f"正文请求异常 {type(e).__name__}"
    if code != 200:
        return "blocked", f"正文 HTTP {code}"
    try:
        n, vals = parse_rule_list(html, content_rule, max_check=20)
    except Exception as e:
        return "bad", f"正文规则解析异常 {type(e).__name__}"
    text = "".join(vals)
    if len(text) >= 30 or len(vals) >= 1:
        return "ok", f"正文解析到 {len(vals)} 段 / {len(text)} 字符"
    return "bad", "正文解析为空"


def check_chain_usable(source, book, timeout=8):
    """三级链路：详情 → 目录 → 正文。返回 dict(chain_ok, detail/toc/content)"""
    d_status, d_detail = check_detail_parsed(source, book, timeout=timeout)
    detail_html = None
    if d_status == "ok":
        try:
            req = {"url": _abs_url(book.get("url"), source), "method": "GET",
                   "body": None, "charset": None}
            code, detail_html = _fetch_raw(req, timeout=timeout)
        except Exception:
            detail_html = None

    t_status, t_detail = check_toc_parsed(source, book, detail_html=detail_html, timeout=timeout)

    c_status, c_detail = "blocked", "未取到章节"
    chapter_url = ""
    if t_status == "ok":
        try:
            rule_toc = source.get("ruleToc") if isinstance(source.get("ruleToc"), dict) else {}
            bl = rule_toc.get("bookList") or rule_toc.get("chapterList")
            src_html = detail_html
            if src_html is None:
                req = {"url": _abs_url(book.get("url"), source), "method": "GET",
                       "body": None, "charset": None}
                _, src_html = _fetch_raw(req, timeout=timeout)
            first_cand = str(bl).split("||")[0]
            # 老格式 bookList 自带 @href → parse_rule_list 直接给 URL；
            # 新格式 chapterList 只选元素，URL 要按 chapterUrl 规则再取
            vals = parse_rule_list(src_html, first_cand, max_check=3)[1]
            if vals and str(vals[0]).strip().startswith(("http://", "https://", "/", "//")):
                chapter_url = str(vals[0]).strip()
            else:
                url_rule = rule_toc.get("chapterUrl") or "href"
                chapter_url = parse_first_attr(src_html, first_cand, url_rule)
        except Exception:
            chapter_url = ""
        if chapter_url:
            c_status, c_detail = check_content_parsed(source, chapter_url, timeout=timeout)

    # 链路判定：正文 ok 才算全通；全 blocked 视为无法判定；任一环节明确 bad 则链路不通
    statuses = [d_status, t_status, c_status]
    if c_status == "ok":
        chain_ok = True
    elif all(x == "blocked" for x in statuses):
        chain_ok = None
    elif "bad" in statuses:
        chain_ok = False
    else:
        chain_ok = None
    return {"chain_ok": chain_ok, "detail": d_status, "toc": t_status,
            "content": c_status, "detail_text": d_detail, "toc_text": t_detail,
            "content_text": c_detail}

def check_source_usable(source, keywords=None, relax_adult=True, deep=False):
    """可用性判定（用户标准：搜索、发现最起码有一个能用才算可用源）

    relax_adult=True（默认）：成人源不跑书籍解析（内容形态含漫画/短剧/图片，解析不可靠），
    改走 check_adult_content_ready 宽松判定（至少一条能取内容的规则链即可）。
    check_usable.py 专项排查可传 relax_adult=False 做纯解析对照。

    返回 dict:
      usable=True   至少一项（搜索/发现）解析出书 → 源可用；成人源宽松校验通过也算
      usable=False  搜索和发现都解析不出（且无网络阻断）→ 内容已变/规则失效，淘汰
      usable=None   存在无法判定项（网络异常/反爬/WAF blocked）→ 保留待人工
    """
    if relax_adult:
        try:
            from .cleaner import is_adult_source
            if is_adult_source(source):
                ready, detail = check_adult_content_ready(source)
                return {"usable": ready, "search": "adult_relaxed", "explore": "adult_relaxed",
                        "detail": detail, "relaxed_adult": True}
        except Exception:
            pass

    s_status, s_detail = check_search_parsed(source, keywords)
    e_status, e_detail = check_explore_parsed(source)
    detail = f"搜索[{s_status}]{s_detail} | 发现[{e_status}]{e_detail}"
    if s_status == "ok" or e_status == "ok":
        result = {"usable": True, "search": s_status, "explore": e_status, "detail": detail}
        # deep：搜索能出书后再走 详情→目录→正文。发布前校验用得上——
        # 「搜索能搜到、正文打不开」的源对用户等于废源，必须在发布口拦住。
        if deep and s_status == "ok":
            book = {}
            m = _re.search(r"样例=\[\('(.+?)', '(.+?)'\)", s_detail)
            if m:
                book = {"name": m.group(1), "url": m.group(2)}
            if book.get("url"):
                ch = check_chain_usable(source, book)
                result["chain"] = ch
                result["detail"] = (detail + f" | 链路[详情{ch['detail']}/目录{ch['toc']}"
                                    f"/正文{ch['content']}]")
                if ch["chain_ok"] is False:
                    result["usable"] = False
                elif ch["chain_ok"] is None and result["usable"] is True:
                    result["usable"] = None
        return result
    if s_status == "blocked" or e_status == "blocked":
        return {"usable": None, "search": s_status, "explore": e_status, "detail": detail}
    return {"usable": False, "search": s_status, "explore": e_status, "detail": detail}
