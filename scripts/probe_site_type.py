#!/usr/bin/env python3
"""站型探测：抓每个源首页 <title>，判断这个站到底是什么（小说/漫画/影视/PPT/档案馆…）

为什么需要它：删源和"只保留纯小说"的判定，不能靠名字猜。
实测反例：
  · 书城书库1（名字像书库）→ misskon.us，实为成人写真站
  · 刺猬猫（名字像小说、还在大厂名单里）→ mm.sfacg.com，实为漫画站
  · 优品幻灯（名字像书源）→ ypppt.com，实为 PPT 模板站

用法：
  python3 scripts/probe_site_type.py --non-text          # 只查 bookSourceType≠0 的源
  python3 scripts/probe_site_type.py --suspect           # 查名字含可疑词的源
  python3 scripts/probe_site_type.py --limit 20 --workers 8
  python3 scripts/probe_site_type.py --name 刺猬猫       # 单源排查

输出：控制台表格 + raw/autocollect/research/site_type_probe_<ts>.json（工作区永久目录）
注意：临时/中间产物一律写工作区（禁用 /tmp）。
"""
import argparse
import json
import os
import re
import sys
import time
import urllib3
import requests

urllib3.disable_warnings()

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOKS = os.path.join(ROOT, "books.json")
OUT_DIR = os.path.join(ROOT, "raw", "autocollect", "research")

H = {"User-Agent": ("Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36")}

# 站型特征：命中即归类。顺序有意义——先判明确无关，再判内容形态。
TYPE_RULES = [
    ("ppt",      r"PPT|幻灯片|模板.{0,6}下载|素材|范文|简历|表格模板"),
    ("archive",  r"archive\.org|档案馆|图书馆藏|互联网档案馆"),
    ("网盘",      r"网盘|pan\.baidu|cloud\.189|夸克|阿里云盘"),
    ("社交",      r"微博|weibo|抖音|贴吧|知乎|小红书"),
    ("音乐播客",  r"音乐|5sing|播客|podcast|荔枝fm|电台|musicBox"),
    ("有声",      r"有声|听书|广播剧|评书|FM|听姬|音声|ASMR|sound"),
    ("漫画",      r"漫画|漫畫|comic|manga|manhwa|webtoon|韩漫|日漫|彩漫|条漫|본子"),
    ("影视",      r"影视|电影|电视剧|短剧|剧集|netflix|动漫|在线观看|片多多|video"),
    ("小说",      r"小说|书库|书城|书屋|文学|阅读网|读物|txt|电子书|完本|全本|章节"),
]

REMOVE_TYPES = {"ppt", "archive", "网盘", "社交", "音乐播客"}  # 与阅读完全无关 → 不分段一律剔除


def classify(title, url):
    """返回 (站型, 命中证据)"""
    text = f"{title} {url}".lower()
    for label, pat in TYPE_RULES:
        if re.search(pat, text, re.I):
            if label in ("有声", "漫画", "影视"):
                return label, f"标题/域名命中「{label}」特征"
            return label, f"标题/域名命中「{label}」特征"
    return "未知", "未命中任何特征，需人工看"


def probe(item):
    idx, src = item
    url = src.get("bookSourceUrl") or ""
    title = ""
    try:
        r = requests.get(url, headers=H, timeout=12, verify=False, allow_redirects=True)
        r.encoding = r.apparent_encoding or "utf-8"
        m = re.search(r"<title[^>]*>(.*?)</title>", r.text, re.S | re.I)
        title = re.sub(r"\s+", " ", m.group(1)).strip()[:80] if m else ""
        code = r.status_code
    except Exception as e:
        code = type(e).__name__
    stype, why = classify(title, url)
    return {
        "index": idx,
        "name": src.get("bookSourceName"),
        "url": url,
        "group": src.get("bookSourceGroup"),
        "bookSourceType": src.get("bookSourceType", 0),
        "http": code,
        "title": title,
        "site_type": stype,
        "reason": why,
        "action": "剔除" if stype in REMOVE_TYPES else ("成人段保留" if stype in ("漫画", "影视", "有声") else "保留待人工"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--non-text", action="store_true", help="只查 bookSourceType≠0 的源")
    ap.add_argument("--suspect", action="store_true",
                    help="查名字含可疑词（幻灯/文档/网盘/漫画/影视/听/漫画…）的源")
    ap.add_argument("--name", help="按源名精确排查单个源")
    ap.add_argument("--limit", type=int, default=0, help="最多探测多少个（0=不限）")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    books = json.load(open(BOOKS, encoding="utf-8"))
    if args.name:
        targets = [(i, s) for i, s in enumerate(books) if s.get("bookSourceName") == args.name]
    elif args.non_text:
        targets = [(i, s) for i, s in enumerate(books) if s.get("bookSourceType", 0) != 0]
    elif args.suspect:
        kw = re.compile(r"幻灯|文档|网盘|漫画|漫畫|影视|剧场|听|FM|音乐|播客|archive|存档|百科|素材")
        targets = [(i, s) for i, s in enumerate(books)
                   if kw.search(str(s.get("bookSourceName")) + str(s.get("bookSourceUrl")))]
    else:
        ap.error("需要 --non-text / --suspect / --name 之一")

    if args.limit:
        targets = targets[: args.limit]
    print(f"待探测 {len(targets)} 个源，workers={args.workers}")

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        results = list(ex.map(probe, targets))

    print(f"\n{'idx':>5} {'名称':<14} {'type':>4} {'站型':<10} {'动作':<12} 标题")
    for r in sorted(results, key=lambda x: x["index"]):
        print(f"{r['index']:>5} {str(r['name'])[:13]:<14} {r['bookSourceType']:>4} "
              f"{r['site_type']:<10} {r['action']:<12} {r['title'][:52]}")

    summary = {}
    for r in results:
        summary.setdefault(r["site_type"], []).append(r["name"])
    print("\n=== 汇总 ===")
    for k, v in sorted(summary.items(), key=lambda x: -len(x[1])):
        print(f"  {k}: {len(v)} 个")

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, f"site_type_probe_{time.strftime('%Y%m%d_%H%M%S')}.json")
    json.dump({"probed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
               "total": len(books), "probed": len(results), "results": results},
              open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n结果已存: {out}")


if __name__ == "__main__":
    main()
