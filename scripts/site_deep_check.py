#!/usr/bin/env python3
"""进站深查：抓首页的一本书 → 其详情/目录页的"最新章节"日期

为什么需要它：`site_health.py` 只看"门口"（首页 + sitemap + Last-Modified），
可判定率天花板 23%。更关键的是——**首页日期大量是假的**：

实测 `笔趣阁32`/`笔趣阁40`/`笔趣阁53` 首页日期**全是 2024-04-20**（同一天、模板日期），
进站后却是 2026-11-12 / 2026-11-14 / 2025-08-24，全都在上新书。
`潇湘书院` 首页挂 2026-02-03（那是公告），进站后书籍更新是今天。
`黑岩阅读` 首页挂 2019（版权年），进站后 2026-02-10。

所以首页/版权年/sitemap 只能筛"疑似"，**要判死必须进站看目录页**。

判据：详情页（或目录页）"最新章节 / 最近更新" 区块内的最大日期。
  ≤180 天 → 活站
  >180 天 → 僵尸
  拿不到 → 判不了（不删）

用法：
  python3 scripts/site_deep_check.py --input <health_result.json> \
      --verdicts 僵尸,疑似僵尸 --evidence home,home_suspect --workers 10
"""
import argparse
import datetime
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor

import requests
import urllib3
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin

urllib3.disable_warnings()

HEAD = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"}
TODAY = datetime.date.today()
DATE_RE = re.compile(r"(20\d{2})[-/年]\s?(\d{1,2})[-/月]\s?(\d{1,2})")
# 明显的静态资源、作者页、搜索页，不是"书"
SKIP_RE = re.compile(r"\.(css|js|png|jpe?g|gif|ico|svg|woff2?)|/people/|/author/|/search|/user/|"
                     r"login|register|/tags?/|/top/|/rank", re.I)
BOOK_RE = re.compile(r"(/book|/xs|/read|/novel|/biquge_|/txt|/info)[^\"']*?\d{3,}|/\d{3,}", re.I)
KW = ("最新章节", "最近更新", "最新更新", "最后更新", "更新列表", "目录")


def _session():
    s = requests.Session()
    s.headers.update(HEAD)
    return s


def dates_in(text, allow_future=False):
    ds = []
    for m in DATE_RE.finditer(text):
        try:
            d = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            continue
        if not allow_future and d > TODAY:
            continue
        ds.append(d)
    return max(ds) if ds else None


def _segment(text):
    """优先取"最新章节/最近更新"区块内的文本"""
    plain = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", text, flags=re.I)
    plain = re.sub(r"<[^>]+>", " ", plain)
    plain = re.sub(r"\s+", " ", plain)
    for kw in KW:
        i = plain.find(kw)
        if i >= 0:
            return plain[i:i + 1200]
    return plain


def check_site(item, sess_probe_pages=3, timeout=10):
    url = item.get("url") or ""
    out = {"name": item.get("name"), "url": url, "home_verdict": item.get("verdict"),
           "home_newest": item.get("newest"), "home_days": item.get("days"),
           "deep_date": None, "deep_days": None, "deep_url": None,
           "deep_verdict": "判不了", "note": ""}
    if not url.startswith("http"):
        out["note"] = "URL 缺失"
        return out
    s = _session()
    try:
        r = s.get(url, timeout=timeout, verify=False, allow_redirects=True)
        if r.status_code != 200 or len(r.text) < 500:
            out["deep_verdict"] = "不可达"
            out["note"] = f"首页 HTTP{r.status_code}"
            return out
        html = r.text
    except Exception as e:
        out["deep_verdict"] = "不可达"
        out["note"] = f"首页 {type(e).__name__}"
        return out

    links = []
    for m in re.finditer(r'href=["\']([^"\']+)["\']', html, re.I):
        c = m.group(1)
        if len(c) > 140 or SKIP_RE.search(c):
            continue
        if BOOK_RE.search(c) and c not in links:
            links.append(c)
    if not links:
        out["note"] = "首页找不到书链接"
        return out

    best, best_url = None, None
    tried = 0
    for c in links:
        if tried >= sess_probe_pages:
            break
        tried += 1
        try:
            u2 = urljoin(url, c)
            if not u2.startswith("http"):
                continue
            r2 = s.get(u2, timeout=timeout, verify=False, allow_redirects=True)
            if r2.status_code != 200:
                continue
            d = dates_in(_segment(r2.text))
            if d is None:
                lm = r2.headers.get("Last-Modified")
                if lm:
                    try:
                        dd = parsedate_to_datetime(lm).date()
                        if dd <= TODAY:
                            d = dd
                    except Exception:
                        pass
            if d and (best is None or d > best):
                best, best_url = d, u2
        except Exception:
            continue

    if best:
        out["deep_date"] = best.isoformat()
        out["deep_days"] = (TODAY - best).days
        out["deep_url"] = best_url
        out["deep_verdict"] = "活站" if out["deep_days"] <= 180 else "僵尸"
    else:
        out["note"] = "进站也没拿到日期"
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="site_health 产出的 JSON（含 results）")
    ap.add_argument("--output", default="")
    ap.add_argument("--verdicts", default="僵尸,疑似僵尸")
    ap.add_argument("--evidence", default="home,home_suspect,", help="逗号分隔，留空表示全部")
    ap.add_argument("--names", default="", help="逗号分隔，只查这些名字")
    ap.add_argument("--workers", type=int, default=10)
    args = ap.parse_args()

    data = json.load(open(args.input, encoding="utf-8"))
    res = data["results"] if isinstance(data, dict) else data
    vs = {x.strip() for x in args.verdicts.split(",") if x.strip()}
    ev = {x.strip() for x in args.evidence.split(",") if x.strip()}
    names = {x.strip() for x in args.names.split(",") if x.strip()}

    targets = [x for x in res
               if (not vs or x.get("verdict") in vs)
               and (not ev or (x.get("evidence") or "") in ev)
               and (not names or x.get("name") in names)]
    print(f"待深查 {len(targets)} 个")

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        outs = list(ex.map(check_site, targets))

    out_file = args.output or os.path.join(
        os.path.dirname(os.path.abspath(args.input)),
        f"deep_check_{datetime.datetime.now():%Y%m%d_%H%M%S}.json")
    json.dump(outs, open(out_file, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    import collections
    c = collections.Counter(o["deep_verdict"] for o in outs)
    print(f"\n=== 深查结果（{len(outs)} 个）===")
    for k, v in c.most_common():
        print(f"  {k}: {v}")
    alive = [o for o in outs if o["deep_verdict"] == "活站"]
    dead = [o for o in outs if o["deep_verdict"] == "僵尸"]
    print(f"\n进站判定活站（首页曾误判）{len(alive)} 个：")
    for o in sorted(alive, key=lambda z: z["deep_days"] or 9999):
        print(f"  {o['name'][:16]:18s} 首页{o['home_newest'] or '无'}({o['home_days']}) → 进站{o['deep_date']}({o['deep_days']}天)")
    print(f"\n进站判定僵尸 {len(dead)} 个：")
    for o in sorted(dead, key=lambda z: -(z["deep_days"] or 0)):
        print(f"  {o['name'][:16]:18s} 进站{o['deep_date']}({o['deep_days']}天)")
    print(f"\n产物: {out_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
