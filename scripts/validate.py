#!/usr/bin/env python3
"""
书源校验器 - 测试书源是否可用
用法：
  python3 validate.py --test books.json
"""
import json, re, sys, ssl, time, urllib.request, urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0"

def host(u):
    try:
        h = urlparse(u.replace("＃", "#")).netloc.lower()
        return h.split("@")[-1].split(":")[0]
    except:
        return ""

def alive(url, timeout=8):
    """域名探活"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return r.status == 200
    except:
        return False

def search_test(source, keyword="剑来", timeout=12):
    """搜索接口测试"""
    book = source.get("bookSourceUrl", "").split("#")[0].rstrip("/")
    su = source.get("searchUrl", "")
    if not su:
        return False, "无searchUrl"
    method = "GET"
    body = None
    if "," in su and "{" in su:
        parts = su.split(",", 1)
        path = parts[0]
        try:
            cfg = json.loads(parts[1])
            method = cfg.get("method", "GET").upper()
            body = cfg.get("body", "")
        except:
            path = su
    else:
        path = su
    path = path.replace("{{key}}", urllib.parse.quote(keyword)).replace("{{page}}", "1")
    if path.startswith("http"):
        url = path
    else:
        url = book + "/" + path.lstrip("/")
    try:
        headers = {"User-Agent": UA, "Accept": "text/html,*/*"}
        data = None
        if method == "POST" and body:
            data = body.replace("{{key}}", keyword).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        req = urllib.request.Request(url, data=data, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            raw = r.read()
        return len(raw) > 500, f"{len(raw)}bytes"
    except Exception as e:
        return False, str(e)[:50]

def test_file(path):
    sources = json.load(open(path, encoding="utf-8"))
    print(f"测试 {len(sources)} 个书源...")
    results = {"alive": 0, "dead": 0, "search_ok": 0, "search_fail": 0, "details": []}
    
    with ThreadPoolExecutor(max_workers=15) as ex:
        futs = {ex.submit(alive, s["bookSourceUrl"]): s for s in sources}
        for fut in as_completed(futs):
            s = futs[fut]
            ok = fut.result()
            if ok:
                results["alive"] += 1
                sok, msg = search_test(s)
                if sok:
                    results["search_ok"] += 1
                else:
                    results["search_fail"] += 1
            else:
                results["dead"] += 1
            results["details"].append({"name": s["bookSourceName"], "alive": ok, "search": sok if ok else None})
    
    print(f"\n=== 校验结果 ===")
    print(f"域名存活: {results['alive']}/{len(sources)}")
    print(f"搜索可用: {results['search_ok']}/{results['alive']}")
    print(f"搜索失败: {results['search_fail']}")
    print(f"域名死亡: {results['dead']}")
    json.dump(results, open("validate_result.json", "w"), ensure_ascii=False, indent=2)

if __name__ == "__main__":
    if "--test" in sys.argv:
        idx = sys.argv.index("--test")
        test_file(sys.argv[idx + 1])
    else:
        print(__doc__)
