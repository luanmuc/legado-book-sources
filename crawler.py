#!/usr/bin/env python3
"""
书源自动抓取器 - 从 yckceo.com 抓取原始书源
原始数据存到 raw/ 目录，手动整理后的书源在根目录的 精选版书源.json

用法：
  python3 crawler.py --fetch-list          # 抓取全部书源列表（59页）
  python3 crawler.py --fetch-collection ID # 下载指定合集
  python3 crawler.py --fetch-all           # 抓列表+全部书源JSON
"""
import json, re, sys, urllib.request, urllib.parse, ssl, time, os

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0"
BASE = "https://www.yckceo.com/yuedu"
RAW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "raw")
os.makedirs(RAW_DIR, exist_ok=True)

def fetch(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        return r.read().decode("utf-8", errors="ignore")

def fetch_list(pages=59):
    """抓取书源列表页"""
    all_sources = []
    for p in range(1, pages + 1):
        try:
            html = fetch(f"{BASE}/shuyuan/index.html?page={p}")
            for m in re.finditer(r'/yuedu/shuyuan/json/id/(\d+)\.json', html):
                all_sources.append({"id": m.group(1), "page": p})
            if p % 10 == 0:
                print(f"  列表页 {p}/{pages}, 累计 {len(all_sources)} 条")
        except Exception as e:
            print(f"  第{p}页失败: {e}")
        time.sleep(0.3)
    out = os.path.join(RAW_DIR, "shuyuan_list.json")
    json.dump(all_sources, open(out, "w"), ensure_ascii=False)
    print(f"书源列表: {len(all_sources)} 条 -> {out}")
    return all_sources

def fetch_source(sid):
    try:
        return json.loads(fetch(f"{BASE}/shuyuan/json/id/{sid}.json"))
    except:
        return None

def fetch_collection(cid):
    try:
        req = urllib.request.Request(f"{BASE}/shuyuans/json/id/{cid}.json", headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
            data = json.loads(r.read().decode("utf-8", errors="ignore"))
        out = os.path.join(RAW_DIR, f"collection_{cid}.json")
        json.dump(data, open(out, "w"), ensure_ascii=False)
        print(f"合集{cid}: {len(data) if isinstance(data,list) else '对象'} 个源 -> {out}")
        return data
    except Exception as e:
        print(f"  合集{cid}失败: {e}")
        return None

def fetch_all_sources():
    """下载所有书源JSON，去重合并"""
    list_file = os.path.join(RAW_DIR, "shuyuan_list.json")
    if not os.path.exists(list_file):
        items = fetch_list()
    else:
        items = json.load(open(list_file))
    results = []
    seen_urls = set()
    for i, item in enumerate(items):
        s = fetch_source(item["id"])
        if s:
            url = s.get("bookSourceUrl", "").split("#")[0]
            if url not in seen_urls:
                seen_urls.add(url)
                results.append(s)
        if (i+1) % 100 == 0:
            print(f"  下载 {i+1}/{len(items)}, 去重后 {len(results)}")
        time.sleep(0.1)
    out = os.path.join(RAW_DIR, "采集池.json")
    json.dump(results, open(out, "w"), ensure_ascii=False)
    print(f"下载完成: {len(results)} 个去重书源 -> {out}")
    return results

if __name__ == "__main__":
    if "--fetch-list" in sys.argv:
        fetch_list()
    elif "--fetch-collection" in sys.argv:
        fetch_collection(sys.argv[sys.argv.index("--fetch-collection") + 1])
    elif "--fetch-all" in sys.argv:
        fetch_all_sources()
    else:
        print(__doc__)
