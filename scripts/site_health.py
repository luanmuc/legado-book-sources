#!/usr/bin/env python3
"""站点健康度体检：只看"门口"的公开信息，不碰站内搜索接口

为什么这么做（2026-11-14 用户定调）：
  爬搜索接口的方案不可行——反爬主要就防这个，命中率只有 22-28%，
  判出来的"差"其实是我们爬不进去，不是站差。
  改成只读站点自己摆出来的公开信息，等于"人打开首页看一眼"：

    ① 首页能不能打开（HTTP 状态 + 内容长度）
    ② 首页上最新的更新日期（很多站首页就有"最近更新"）
    ③ robots.txt 声明的 sitemap → loc 数量（≈ 页面/书籍规模）、<lastmod>（≈ 最后更新时间）
    ④ 首页书链数量（/book/ /novel/ /read/ 这类链接去重计数）

  sitemap 本来就是写给搜索引擎看的，几乎不设防；首页对普通 UA 也很少拦。

判定：
  活跃  最新更新 ≤ 7 天
  正常  7~30 天
  迟缓  30~90 天
  僵尸  > 90 天没任何更新信号（书再多也别留）
  无信号 能打开但取不到任何日期（需人工看一眼）
  不可达 状态非 200 / 超时 / 证书错误

用法：
  python3 scripts/site_health.py --limit 200 --workers 12
  python3 scripts/site_health.py --all                     # 全量 2140
  python3 scripts/site_health.py --resume                  # 断点续跑
  python3 scripts/site_health.py --group 综合其他 --limit 50

产物（全在工作区）：
  raw/autocollect/research/site_health_<ts>.csv
  raw/autocollect/research/ckpt_site_health.json
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

import requests
import urllib3

urllib3.disable_warnings()

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOKS = os.path.join(ROOT, "books.json")
OUT_DIR = os.path.join(ROOT, "raw", "autocollect", "research")
CKPT = os.path.join(OUT_DIR, "ckpt_site_health.json")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
HEAD = {"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"}

DATE_RE = re.compile(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})")
LASTMOD_RE = re.compile(r"<lastmod>([^<]+)</lastmod>", re.I)
LOC_RE = re.compile(r"<loc>", re.I)
BOOKLINK_RE = re.compile(r'href="[^"]*(?:/book/|/novel/|/xiaoshuo/|/read/|/txt/)[^"]*"', re.I)

TIMEOUT_HOME = 10
TIMEOUT_SITEMAP = 8


def _newest_dates(text):
    """从文本里抠出所有日期，返回最大日期(date)"""
    best = None
    for m in DATE_RE.finditer(text or ""):
        try:
            d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            continue
        if 2000 <= d.year <= date.today().year + 1 and (best is None or d > best):
            best = d
    return best


def _fetch(url, timeout):
    """返回 (状态码, 正文, 响应头)。响应头用于取 Last-Modified——服务器给的文件修改时间，
    实测命中率约 20%，但准确度高（晋江 LM 显示 2 天前更新，正好证明它没死）。"""
    try:
        r = requests.get(url, headers=HEAD, timeout=timeout, verify=False, allow_redirects=True)
        r.encoding = r.apparent_encoding or "utf-8"
        return r.status_code, r.text or "", dict(r.headers)
    except Exception as e:
        return type(e).__name__, "", {}


def _find_sitemaps(base):
    """返回 (sitemap_url, loc_count, newest_lastmod, is_index)"""
    cands = []
    code, txt, _ = _fetch(base.rstrip("/") + "/robots.txt", TIMEOUT_SITEMAP)
    if code == 200:
        cands += re.findall(r"(?im)^sitemap:\s*(\S+)", txt)
    cands += [base.rstrip("/") + p for p in
              ("/sitemap.xml", "/sitemap_index.xml", "/sitemap/",
               "/baidu_sitemap.xml", "/sitemap.txt")]

    for c in cands[:5]:
        code, txt, _ = _fetch(c, TIMEOUT_SITEMAP)
        if code != 200 or "<" not in txt:
            continue
        is_index = "<sitemapindex" in txt.lower()
        locs = len(LOC_RE.findall(txt))
        lms = LASTMOD_RE.findall(txt)
        newest = _newest_dates(" ".join(lms)) if lms else None
        # 索引文件：取前 2 个子 sitemap 再数一层 loc 与 lastmod
        if is_index:
            subs = re.findall(r"<loc>([^<]+)</loc>", txt, re.I)
            # 规模：最多数 3 个子文件（避免请求爆炸）
            for sub in subs[:3]:
                code2, txt2, _ = _fetch(sub.strip(), TIMEOUT_SITEMAP)
                if code2 != 200:
                    continue
                locs += len(LOC_RE.findall(txt2))
            # 日期：索引自身的 <lastmod> 通常已覆盖全部子文件；
            # 个别站不写，此时递归末尾子文件补（通常按时间升序，末尾最新）
            if newest is None and subs:
                d2 = None
                for sub in subs[-2:]:
                    code2, txt2, _ = _fetch(sub.strip(), TIMEOUT_SITEMAP)
                    if code2 != 200:
                        continue
                    lms2 = LASTMOD_RE.findall(txt2)
                    if lms2:
                        dd = _newest_dates(" ".join(lms2))
                        if dd and (d2 is None or dd > d2):
                            d2 = dd
                newest = d2
        return c, locs, newest, is_index
    return "", 0, None, False


HOME_KW = ("最近更新", "最新更新", "刚刚更新", "最后更新", "最新章节", "更新列表")


def _home_date_smart(html):
    """首页日期。优先只在“最近更新/最新章节”区块内取——页面全文正则会把页脚版权年
    （实测多源同为 2015-02-14、某站为 2023-01-01）抓成“最后更新”，是误判主因。"""
    import re as _re
    txt = _re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", html, flags=_re.I)
    txt = _re.sub(r"<[^>]+>", " ", txt)
    txt = _re.sub(r"\s+", " ", txt)
    today = date.today()
    for kw in HOME_KW:
        i = txt.find(kw)
        if i >= 0:
            d = _newest_dates(txt[i:i + 900])
            if d and d <= today:
                return d
    d = _newest_dates(txt)
    if d and d > today:      # 未来日期不可信（实测出现过 2052-08-13）
        return None
    return d


def check_one(src):
    url = (src.get("bookSourceUrl") or "").strip()
    base = {"name": src.get("bookSourceName"), "url": url,
            "group": src.get("bookSourceGroup"), "type": src.get("bookSourceType", 0)}
    if not url.startswith("http"):
        return {**base, "reachable": False, "http": "无URL", "home_date": "",
                "sitemap_date": "", "newest": "", "days": None, "sitemap_urls": 0,
                "sitemap_kind": "", "book_links": 0, "evidence": "", "verdict": "不可达", "note": "URL 缺失"}

    t0 = time.time()
    code, html, hdrs = _fetch(url, TIMEOUT_HOME)
    rt = round(time.time() - t0, 1)
    reachable = (code == 200 and len(html) > 500)
    home_date = _home_date_smart(html) if reachable else None
    lm_date = None
    lm_raw = (hdrs or {}).get("Last-Modified")
    if lm_raw:
        try:
            from email.utils import parsedate_to_datetime
            lm_date = parsedate_to_datetime(lm_raw).date()
            if lm_date > date.today():      # 服务器时钟异常，不可信
                lm_date = None
        except Exception:
            lm_date = None
    book_links = len(set(BOOKLINK_RE.findall(html))) if reachable else 0

    sm_url, sm_locs, sm_date, is_idx = ("", 0, None, False)
    if reachable:
        sm_url, sm_locs, sm_date, is_idx = _find_sitemaps(url)

    # 证据分级：sitemap 的 <lastmod> 是站点自己写给搜索引擎的，可信度最高；
    # 首页日期常混版权声明年份（实测多个源同为 2015-02-14、某站为 2023-01-01），只作弱证据
    def _suspect(d):
        """疑似版权年/建站年：1 月 1 日、或早于 2015 年"""
        return d is not None and ((d.month == 1 and d.day == 1) or d.year < 2015)

    if sm_date:
        newest, evidence = sm_date, "sitemap"
    elif lm_date and not _suspect(lm_date):
        newest, evidence = lm_date, "lastmod"
    elif home_date and not _suspect(home_date):
        newest, evidence = home_date, "home"
    elif home_date:
        newest, evidence = home_date, "home_suspect"
    else:
        newest, evidence = None, ""
    days = (date.today() - newest).days if newest else None

    if not reachable:
        verdict, note = "不可达", f"HTTP {code}" if not str(code).startswith(("Read", "Proxy", "SSL", "Conn")) else str(code)
    elif days is None:
        verdict, note = "无信号", "能打开但首页与 sitemap 都没有日期"
    elif evidence == "home_suspect" and days > 90:
        verdict, note = "疑似僵尸", f"首页日期 {newest.isoformat()} 疑似版权/建站年，需人工确认"
    elif days <= 7:
        verdict, note = "活跃", ""
    elif days <= 30:
        verdict, note = "正常", ""
    elif days <= 90:
        verdict, note = "迟缓", ""
    else:
        verdict, note = "僵尸", f"最后更新距今 {days} 天"

    return {**base, "reachable": reachable, "http": code, "resp_s": rt,
            "home_date": home_date.isoformat() if home_date else "",
            "sitemap_date": sm_date.isoformat() if sm_date else "",
            "newest": newest.isoformat() if newest else "",
            "days": days, "sitemap_urls": sm_locs,
            "sitemap_kind": ("索引" if is_idx else ("单文件" if sm_url else "无")),
            "lm_date": lm_date.isoformat() if lm_date else "",
            "book_links": book_links, "evidence": evidence, "verdict": verdict, "note": note}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--all", action="store_true", help="全量跑")
    ap.add_argument("--group")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--seed", type=int, default=20261114)
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()

    books = json.load(open(BOOKS, encoding="utf-8"))
    pool = [s for s in books if args.group is None or s.get("bookSourceGroup") == args.group]
    if args.all or len(pool) <= args.limit:
        sample = pool
    else:
        random.seed(args.seed)
        sample = random.sample(pool, args.limit)
    sample.sort(key=lambda s: s.get("customOrder") or 0)

    done = {}
    if args.resume and os.path.exists(CKPT):
        done = {r["url"]: r for r in json.load(open(CKPT, encoding="utf-8")).get("results", [])}
        print(f"断点已有 {len(done)} 条")
    todo = [s for s in sample if s.get("bookSourceUrl") not in done]
    print(f"抽样 {len(sample)}，待跑 {len(todo)}，workers={args.workers}")

    def _run(s):
        try:
            return check_one(s)
        except Exception as e:
            return {"name": s.get("bookSourceName"), "url": s.get("bookSourceUrl"),
                    "group": s.get("bookSourceGroup"), "type": s.get("bookSourceType", 0),
                    "reachable": False, "http": type(e).__name__, "home_date": "",
                    "sitemap_date": "", "newest": "", "days": None, "sitemap_urls": 0,
                    "sitemap_kind": "", "book_links": 0, "evidence": "", "verdict": "不可达",
                    "note": f"未捕获 {type(e).__name__}"}

    t0 = time.time()
    results = list(done.values())
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for i, r in enumerate(ex.map(_run, todo), 1):
            results.append(r)
            if i % 50 == 0 or i == len(todo):
                print(f"  进度 {i}/{len(todo)}  {time.time()-t0:.0f}s")
                os.makedirs(OUT_DIR, exist_ok=True)
                json.dump({"updated": datetime.now().isoformat(), "results": results},
                          open(CKPT, "w", encoding="utf-8"), ensure_ascii=False)

    os.makedirs(OUT_DIR, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    csv_path = os.path.join(OUT_DIR, f"site_health_{ts}.csv")
    cols = ["name", "url", "group", "type", "reachable", "http", "resp_s", "home_date",
            "sitemap_date", "newest", "days", "sitemap_urls", "sitemap_kind",
            "book_links", "evidence", "verdict", "note"]
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(results)
    json.dump({"generated": datetime.now().isoformat(), "sample": len(sample),
               "results": results},
              open(os.path.join(OUT_DIR, f"site_health_{ts}.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

    print(f"\n=== 汇总（{len(results)} 源，{time.time()-t0:.0f}s）===")
    from collections import Counter
    for k, v in Counter(r["verdict"] for r in results).most_common():
        print(f"  {k}: {v}")
    print(f"CSV: {csv_path}")


if __name__ == "__main__":
    sys.exit(main())
