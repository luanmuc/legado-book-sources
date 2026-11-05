# -*- coding: utf-8 -*-
"""Legado 书源规则轻量解析器 —— 用于可用性校验（判断规则能否真正解析出书籍）

支持常用子集（够判断"至少能解析出一本书"）：
- 选择器：class.x / tag.x / id.x / .x / #x / 标签名 / tag.N 索引
- 动作：@text @ownText @textNodes @html @href @src @attr.x / @data-x
- 多规则容错：||（取第一个非空）、##正则清理（忽略替换，只取前半）
- 不支持：@js:、@put:/@get:（返回空）
"""

import re

from bs4 import BeautifulSoup

try:
    from lxml import html as _lxml_html
except Exception:  # lxml 不可用时 XPath 规则按解析失败处理
    _lxml_html = None


_ACTION_WORDS = {
    "text", "ownText", "textNodes", "html", "all", "href", "src", "value",
    "title", "content", "alt", "data-src", "data-original",
}


def _strip_regex(rule):
    """去掉 ## 正则替换部分"""
    return (rule or "").split("##")[0].strip()


def _is_xpath(rule):
    """判断是否 XPath 规则（以 / 开头或以 .// 开头或规则体含 //）"""
    r = _strip_regex(rule)
    head = r.split("@")[0]
    return r.startswith("/") or r.startswith("./") or "//" in head


def _split_index(step):
    """'h4 a.0' → ('h4 a', 0)  'a.0' → ('a', 0)；无索引返回 None"""
    m = re.match(r"^(.*?)\s*([a-zA-Z][a-zA-Z0-9]*)[.](\d+)$", step.strip())
    if not m:
        return None
    parent = m.group(1).strip()
    tag = m.group(2)
    idx = int(m.group(3))
    return (parent + " " + tag if parent else tag), idx


def _convert_selector(sel):
    """Legado 简化选择器 → CSS 选择器"""
    sel = sel.strip()
    if not sel:
        return ""
    if sel.startswith("class."):
        return "." + sel[6:]
    if sel.startswith("tag."):
        return sel[4:]
    if sel.startswith("id."):
        return "#" + sel[3:]
    if sel.startswith("@css:"):
        return sel[5:]
    return sel


def _parse_rule(rule):
    """规则 → (steps[list[str] css], action[str|None])

    例："a.0@href" → (["a.0"], "href")；".result_ul@li" → ([".result_ul", "li"], None)
    """
    if not rule or not isinstance(rule, str):
        return [], None
    rule = rule.split("##")[0].strip()  # 去掉 ##正则替换
    steps, action = [], None
    for part in rule.split("@"):
        p = part.strip()
        if not p:
            continue
        low = p.lower()
        if low.startswith("js:") or low.startswith("put:") or low.startswith("get:"):
            continue  # 脚本类不支持，忽略（不影响解析判断）
        if low in _ACTION_WORDS or low.startswith("attr.") or low.startswith("data-"):
            action = p
            continue
        if re.match(r"^[a-zA-Z]+\.\d+$", p):  # a.0 / li.1 → 标签索引
            steps.append(p)
            continue
        css = _convert_selector(p)
        if css:
            steps.append(css)
    return steps, action


def _select_one(node, step):
    """按步骤选单个节点（支持 tag.N 索引与 'h4 a.0' 父+索引语法）"""
    si = _split_index(step)
    if si:
        css, idx = si
        els = node.select(css)
        return els[idx] if len(els) > idx else None
    els = node.select(step)
    return els[0] if els else None


def _select_all(node, step):
    """按步骤选全部节点（支持 tag.N 索引与 'h4 a.0' 父+索引语法）"""
    si = _split_index(step)
    if si:
        css, idx = si
        els = node.select(css)
        return [els[idx]] if len(els) > idx else []
    return node.select(step)


def _take_action(node, action):
    """对节点取动作值"""
    if node is None:
        return ""
    if not action:
        return node.get_text(" ", strip=True) if hasattr(node, "get_text") else ""
    a = action.lower()
    if a == "owntext":
        return "".join(node.find_all(string=True, recursive=False)).strip()
    if a in ("text", "textnodes", "all"):
        return node.get_text(" ", strip=True)
    if a == "html":
        return str(node)
    attr = None
    if a.startswith("attr."):
        attr = action[5:]
    elif a.startswith("data-"):
        attr = action
    else:
        attr = a
    try:
        v = node.get(attr)
        return (v or "").strip()
    except Exception:
        return ""


def _parse_candidate(root, rule):
    """解析单个候选规则 → (matched_elements, values)

    最后一个 step 用 select_all 得到元素列表，前面 step 逐级下降
    """
    steps, action = _parse_rule(rule)
    if not steps:
        return [], []
    node = root
    for step in steps[:-1]:
        node = _select_one(node, step)
        if node is None:
            return [], []
    elements = _select_all(node, steps[-1])
    values = [_take_action(el, action) for el in elements]
    return elements, values


def parse_rule_list(html_or_node, rule, max_check=10):
    """按规则解析出列表值（支持 || 多候选）

    返回 (matched_count, non_empty_values)
    """
    root = html_or_node
    if isinstance(html_or_node, str):
        root = BeautifulSoup(html_or_node, "html.parser")
    if not rule or not isinstance(rule, str):
        return 0, []
    for cand in rule.split("||"):
        cand = cand.strip()
        if not cand:
            continue
        elements, values = _parse_candidate(root, cand)
        non_empty = [v for v in values if v]
        if non_empty:
            return len(elements), non_empty[:max_check]
    return 0, []


def parse_book_list(html, rule_book_list, rule_name=None, rule_url=None, max_check=5):
    """解析书籍列表：bookList 找到条目，再用 name/bookUrl 规则取字段

    支持 bookList 的 || 多候选（逐个尝试，返回第一个成功的）
    返回 dict: {matched, books: [{name, url}], ok}
    ok = 至少一条能取到非空 name 或 url
    """
    if not rule_book_list or not isinstance(rule_book_list, str):
        return {"matched": 0, "books": [], "ok": False}
    candidates = [c.strip() for c in rule_book_list.split("||") if c.strip()] or [rule_book_list]
    last = {"matched": 0, "books": [], "ok": False}
    for cand in candidates:
        if _is_xpath(cand):
            r = _parse_book_list_xpath(html, cand, rule_name, rule_url, max_check)
        else:
            r = _parse_book_list_single(html, cand, rule_name, rule_url, max_check)
        if r["ok"]:
            return r
        if r["matched"] > last["matched"]:
            last = r
    return last


def _xpath_rel(rule):
    """XPath 转相对路径（item 上下文内执行）"""
    r = _strip_regex(rule)
    if r.startswith("/"):
        return "." + r
    return r


def _xpath_value(el, rule):
    """在 lxml 元素上按 XPath 取值（text()/属性/元素文本）"""
    if not rule:
        return ""
    r = _xpath_rel(rule)
    try:
        res = el.xpath(r)
    except Exception:
        return ""
    if not res:
        return ""
    v = res[0]
    if isinstance(v, str):
        return v.strip()
    try:
        return (v.text_content() or "").strip()
    except Exception:
        return ""


def _parse_book_list_xpath(html, book_list, name_rule=None, url_rule=None, max_check=5):
    """XPath 规则解析书籍列表（lxml 引擎）"""
    if _lxml_html is None:
        return {"matched": 0, "books": [], "ok": False}
    try:
        tree = _lxml_html.fromstring(html)
    except Exception:
        return {"matched": 0, "books": [], "ok": False}
    try:
        items = tree.xpath(_xpath_rel(book_list))
    except Exception:
        return {"matched": 0, "books": [], "ok": False}
    books = []
    for el in items[:max_check]:
        if isinstance(el, str):
            books.append({"name": el.strip(), "url": ""})
            continue
        books.append({"name": _xpath_value(el, name_rule), "url": _xpath_value(el, url_rule)})
    ok = any(b["name"] or b["url"] for b in books)
    return {"matched": len(items), "books": books, "ok": ok}


def _parse_book_list_single(html, rule_book_list, rule_name=None, rule_url=None, max_check=5):
    """单候选 bookList 解析（内部使用）"""
    soup = BeautifulSoup(html, "html.parser")
    try:
        steps, action = _parse_rule(rule_book_list or "")
        if not steps:
            return {"matched": 0, "books": [], "ok": False}
        node = soup
        for step in steps[:-1]:
            node = _select_one(node, step)
            if node is None:
                return {"matched": 0, "books": [], "ok": False}
        items = _select_all(node, steps[-1])
    except Exception:
        # CSS 语法不合法（如残留 | 等）→ 按解析失败处理
        return {"matched": 0, "books": [], "ok": False}
    books = []
    for el in items[:max_check]:
        name, url = "", ""
        try:
            if rule_name:
                _, vals = _parse_candidate(el, rule_name)
                name = next((v for v in vals if v), "")
            if rule_url:
                _, vals = _parse_candidate(el, rule_url)
                url = next((v for v in vals if v), "")
        except Exception:
            pass
        books.append({"name": name, "url": url})
    ok = any(b["name"] or b["url"] for b in books)
    return {"matched": len(items), "books": books, "ok": ok}


def parse_explore_entries(explore_url, limit=3):
    """解析 exploreUrl 为发现页入口列表 [{title, url}]

    支持两种格式：
    1) JSON 数组：[{"title":"玄幻","url":"/sort/1_{{page}}.html"}, ...]
    2) 多行字符串："玄幻::http://...\n武侠::/sort/2/{{page}}"
    """
    entries = []
    if not explore_url:
        return entries
    text = str(explore_url).strip()
    if text.startswith("["):
        import json
        try:
            arr = json.loads(text)
            for item in arr:
                if not isinstance(item, dict):
                    continue
                title = (item.get("title") or "").strip()
                url = (item.get("url") or "").strip()
                if url and not any(x in url.lower() for x in ("@js:", "login", "javascript:")):
                    entries.append({"title": title, "url": url})
        except Exception:
            pass
    else:
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if "::" in line:
                title, url = line.split("::", 1)
            else:
                title, url = "", line
            url = url.strip()
            if url and not any(x in url.lower() for x in ("@js:", "login", "javascript:")):
                entries.append({"title": title.strip(), "url": url})
    return entries[:limit]
