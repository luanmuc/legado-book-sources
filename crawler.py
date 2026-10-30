#!/usr/bin/env python3
"""
书源自动抓取器 - 从 yckceo.com 抓取书源
用法：
  python3 crawler.py --fetch-list          # 抓取全部书源列表
  python3 crawler.py --fetch-collection ID # 下载指定合集
  python3 crawler.py --fetch-all           # 抓列表+合集
"""
import json, re, sys, urllib.request, urllib.parse, ssl, time, os

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0"
BASE = "https://www.yckceo.com/yuedu"

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
            # 解析每个书源条目
            for m in re.finditer(r'/yuedu/shuyuan/json/id/(\d+)\.json', html):
                sid = m.group(1)
                all_sources.append({"id": sid, "page": p})
            if p % 10 == 0:
                print(f"  列表页 {p}/{pages}, 累计 {len(all_sources)} 条")
        except Exception as e:
            print(f"  第{p}页失败: {e}")
        time.sleep(0.3)
    json.dump(all_sources, open("shuyuan_list.json", "w"), ensure_ascii=False)
    print(f"书源列表: {len(all_sources)} 条")
    return all_sources

def fetch_source(sid):
    """下载单个书源JSON"""
    try:
        url = f"{BASE}/shuyuan/json/id/{sid}.json"
        data = json.loads(fetch(url))
        return data
    except:
        return None

def fetch_collection(cid):
    """下载合集JSON（跟随302跳转）"""
    try:
        url = f"{BASE}/shuyuans/json/id/{cid}.json"
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
            data = json.loads(r.read().decode("utf-8", errors="ignore"))
        return data
    except Exception as e:
        print(f"  合集{cid}失败: {e}")
        return None

def fetch_all_sources(list_file="shuyuan_list.json"):
    """下载所有书源JSON"""
    items = json.load(open(list_file))
    results = []
    for i, item in enumerate(items):
        s = fetch_source(item["id"])
        if s:
            results.append(s)
        if (i+1) % 100 == 0:
            print(f"  下载 {i+1}/{len(items)}, 成功 {len(results)}")
        time.sleep(0.1)
    json.dump(results, open("merged_sources.json", "w"), ensure_ascii=False)
    print(f"下载完成: {len(results)} 个书源")
    return results

if __name__ == "__main__":
    if "--fetch-list" in sys.argv:
        fetch_list()
    elif "--fetch-collection" in sys.argv:
        idx = sys.argv.index("--fetch-collection")
        cid = sys.argv[idx + 1]
        data = fetch_collection(cid)
        if data:
            json.dump(data, open(f"collection_{cid}.json", "w"), ensure_ascii=False)
            print(f"合集{cid}: {len(data) if isinstance(data,list) else '对象'} 个源")
    elif "--fetch-all" in sys.argv:
        items = fetch_list()
        fetch_all_sources()
    else:
        print(__doc__)
