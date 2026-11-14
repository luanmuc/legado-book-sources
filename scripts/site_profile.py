#!/usr/bin/env python3
"""站点质量画像：抽样统计每个源的「完本率 / 更新活跃度 / 书目规模 / 字数」

定位：本地专项诊断工具，**不参与自动发布门禁**。
原因：2140 源 × 多次请求耗时过长，且 Actions 跑在美国节点，跨洋内容校验合格率仅 27%。

指标怎么来的（都有实测依据，不是估）：
  · 完本率  ← ruleSearch.kind 里的「完本/完结」vs「连载」（如「泡书吧小」直接给连载中/完本）
              无 kind 时用 lastChapter 正则兜底（「大结局/终章/全文完」）
  · 活跃度  ← kind 或 lastChapter 里的日期（如「落霞小说3」kind 直接是 2024-11-26 这种更新日期）
  · 条目数  ← 一次搜索能解析出多少本
  · 字数    ← ruleSearch.wordCount（24% 源有）

用法：
  python3 scripts/site_profile.py --limit 200 --workers 8
  python3 scripts/site_profile.py --limit 200 --resume        # 断点续跑
  python3 scripts/site_profile.py --group 笔趣阁类 --limit 50

产物（全部在工作区，禁用 /tmp）：
  raw/autocollect/research/site_profile_<ts>.csv
  raw/autocollect/research/ckpt_site_profile.json   ← 断点
"""
import argparse
import csv
import json
import os
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autocollect_core.validators import _build_search_request, _fetch_raw
from autocollect_core.legado_rules import parse_book_nodes, parse_rule_list, _xpath_value
from bs4 import BeautifulSoup

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOKS = os.path.join(ROOT, "books.json")
OUT_DIR = os.path.join(ROOT, "raw", "autocollect", "research")
CKPT = os.path.join(OUT_DIR, "ckpt_site_profile.json")

FIN_YES = re.compile(r"完本|完结|已完结|全本|全文完|大结局|终章")
FIN_NO = re.compile(r"连载|更新中|连在|未完")
DATE_RE = re.compile(r"(20\d{2})[-/年.](\d{1,2})[-/月.](\d{1,2})")
MONTHDAY_RE = re.compile(r"\b(\d{1,2})[-/](\d{1,2})\b")
SAMPLE_BOOKS = 10


def _guess_date(texts):
    """从 kind / lastChapter 文本里抠最近的更新日期，返回距今天数"""
    best = None
    for t in texts:
        if not t:
            continue
        for m in DATE_RE.finditer(str(t)):
            try:
                d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                if best is None or d > best:
                    best = d
            except ValueError:
                continue
    if best is None:
        return None, ""
    return (date.today() - best).days, best.isoformat()


def profile_one(src):
    """单个源画像，返回 dict"""
    rs = src.get("ruleSearch") or {}
    base = {
        "name": src.get("bookSourceName"),
        "url": src.get("bookSourceUrl"),
        "group": src.get("bookSourceGroup"),
        "type": src.get("bookSourceType", 0),
    }
    if not isinstance(rs, dict) or not rs.get("bookList"):
        return {**base, "ok": False, "books": 0, "finish_rate": None,
                "finish_known": 0, "activity_days": None, "last_update": "",
                "avg_wordcount": None, "note": "无 ruleSearch.bookList"}
    kw = str(src.get("checkKeyWord") or "").strip() or "我的"
    req = _build_search_request(src, kw)
    if not req:
        return {**base, "ok": False, "books": 0, "finish_rate": None,
                "finish_known": 0, "activity_days": None, "last_update": "",
                "avg_wordcount": None, "note": "无 searchUrl"}
    try:
        code, html = _fetch_raw(req, timeout=10)
    except Exception as e:
        return {**base, "ok": False, "books": 0, "finish_rate": None,
                "finish_known": 0, "activity_days": None, "last_update": "",
                "avg_wordcount": None, "note": f"请求异常 {type(e).__name__}"}
    if code != 200:
        return {**base, "ok": False, "books": 0, "finish_rate": None,
                "finish_known": 0, "activity_days": None, "last_update": "",
                "avg_wordcount": None, "note": f"HTTP {code}"}
    try:
        status, els, engine = parse_book_nodes(html, rs.get("bookList"), SAMPLE_BOOKS)
    except Exception as e:
        return {**base, "ok": False, "books": 0, "finish_rate": None,
                "finish_known": 0, "activity_days": None, "last_update": "",
                "avg_wordcount": None, "note": f"解析异常 {type(e).__name__}"}
    if status == "script":
        return {**base, "ok": False, "books": 0, "finish_rate": None,
                "finish_known": 0, "activity_days": None, "last_update": "",
                "avg_wordcount": None,
                "note": "JS/JsonPath 规则（静态无法解析，阅读器可跑）"}
    if not els:
        return {**base, "ok": False, "books": 0, "finish_rate": None,
                "finish_known": 0, "activity_days": None, "last_update": "",
                "avg_wordcount": None, "note": "搜索结果 0 条"}

    books, fin_yes, fin_no, dates, wcs = 0, 0, 0, [], []
    for el in els[:SAMPLE_BOOKS]:
        # 逐字段解析必须各自容错：单条字段规则写错（XPath 当 CSS / 含 js）不该让整源判失败
        def _val(rule):
            if not rule:
                return ""
            try:
                if engine == "xpath":
                    return _xpath_value(el, rule)
                return (parse_rule_list(el, rule, 1)[1] or [""])[0]
            except Exception:
                return ""
        nm = _val(rs.get("name"))
        kind = _val(rs.get("kind"))
        last = _val(rs.get("lastChapter"))
        wc = _val(rs.get("wordCount"))
        if not nm:
            continue
        books += 1
        if kind:
            if FIN_YES.search(str(kind)):
                fin_yes += 1
            elif FIN_NO.search(str(kind)):
                fin_no += 1
        elif last and FIN_YES.search(str(last)):
            fin_yes += 1  # 无 kind 时用「最新章=大结局」兜底
        d, ds = _guess_date([kind, last])
        if d is not None:
            dates.append((d, ds))
        if wc:
            m = re.search(r"(\d+(?:\.\d+)?)\s*万?字?", str(wc))
            if m:
                v = float(m.group(1)) * (10000 if "万" in str(wc) else 1)
                wcs.append(v)

    known = fin_yes + fin_no
    rate = round(fin_yes / known, 2) if known else None
    days, ds = (min(dates) if dates else (None, ""))
    note = []
    if books == 0:
        note.append("条目规则解析不出书名")
    if rate is None:
        note.append("kind/lastChapter 无完本线索")
    return {**base, "ok": books > 0, "books": books,
            "finish_rate": rate, "finish_known": known,
            "activity_days": days, "last_update": ds,
            "avg_wordcount": int(sum(wcs) / len(wcs)) if wcs else None,
            "note": "；".join(note)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--group", help="只抽某个分组")
    ap.add_argument("--seed", type=int, default=20261114)
    ap.add_argument("--resume", action="store_true", help="从断点续跑")
    args = ap.parse_args()

    books = json.load(open(BOOKS, encoding="utf-8"))
    pool = [s for s in books if args.group is None or s.get("bookSourceGroup") == args.group]
    # 成人段单独规则，默认不进画像（内容形态不同）
    if args.group is None:
        pool = [s for s in pool if s.get("bookSourceGroup") != "成人书源"]
    random.seed(args.seed)
    sample = pool if len(pool) <= args.limit else random.sample(pool, args.limit)
    sample.sort(key=lambda s: s.get("customOrder") or 0)

    done = {}
    if args.resume and os.path.exists(CKPT):
        done = {r["url"]: r for r in json.load(open(CKPT, encoding="utf-8")).get("results", [])}
        print(f"断点已有 {len(done)} 条")
    todo = [s for s in sample if s.get("bookSourceUrl") not in done]
    print(f"抽样 {len(sample)} 源，待跑 {len(todo)}，workers={args.workers}")

    def _run(s):
        try:
            return profile_one(s)
        except Exception as e:
            return {"name": s.get("bookSourceName"), "url": s.get("bookSourceUrl"),
                    "group": s.get("bookSourceGroup"), "type": s.get("bookSourceType", 0),
                    "ok": False, "books": 0, "finish_rate": None, "finish_known": 0,
                    "activity_days": None, "last_update": "", "avg_wordcount": None,
                    "note": f"未捕获 {type(e).__name__}"}

    t0 = time.time()
    results = list(done.values())
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for i, r in enumerate(ex.map(_run, todo), 1):
            results.append(r)
            if i % 20 == 0 or i == len(todo):
                print(f"  进度 {i}/{len(todo)}  用时 {time.time()-t0:.0f}s")
                os.makedirs(OUT_DIR, exist_ok=True)
                json.dump({"updated": datetime.now().isoformat(), "results": results},
                          open(CKPT, "w", encoding="utf-8"), ensure_ascii=False)

    os.makedirs(OUT_DIR, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    csv_path = os.path.join(OUT_DIR, f"site_profile_{ts}.csv")
    cols = ["name", "url", "group", "type", "ok", "books", "finish_rate",
            "finish_known", "activity_days", "last_update", "avg_wordcount", "note"]
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(results)
    json.dump({"generated": datetime.now().isoformat(), "sample": len(sample),
               "results": results}, open(os.path.join(OUT_DIR, f"site_profile_{ts}.json"),
                                         "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    okr = [r for r in results if r["ok"]]
    withfin = [r for r in okr if r["finish_rate"] is not None]
    print(f"\n=== 汇总（{len(results)} 源，用时 {time.time()-t0:.0f}s）===")
    print(f"可解析 {len(okr)} ({len(okr)/max(len(results),1)*100:.0f}%) | "
          f"能算出完本率 {len(withfin)} | 无完本线索 {len(okr)-len(withfin)}")
    print(f"CSV: {csv_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
