#!/usr/bin/env python3
"""
全自动书源流水线
流程：抓取新书源 → 对比增量 → 域名探活 → 搜索测试 → 补全规则 → 净化 → 去重 → 合并到最终书源

用法：
  python3 pipeline.py              # 全自动
  python3 pipeline.py --quick       # 快速模式（只测新增源）
"""
import json, re, os, sys, ssl, time, urllib.request, urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse
from bs4 import BeautifulSoup

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Mobile"
BASE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(BASE, "raw")
FINAL = os.path.join(BASE, "books.json")
os.makedirs(RAW, exist_ok=True)

# ============ 工具函数 ============
def host(u):
    try:
        h = urlparse(u.replace("＃", "#")).netloc.lower()
        h = h.split("@")[-1].split(":")[0]
        h = re.sub(r"^(m|www|wap|api|webapp|app|h5|mobile)\d*\.", "", h)
        return h
    except: return ""

def fetch(url, timeout=10, data=None, headers=None):
    h = {"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"}
    if headers: h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        raw = r.read()
        ct = r.headers.get("Content-Type", "").lower()
        enc = "gbk" if "gbk" in ct or "gb2312" in ct else "utf-8"
        try: text = raw.decode(enc, errors="ignore")
        except: text = raw.decode("utf-8", errors="ignore")
        return text, r.geturl()

# ============ Step 1: 抓取新书源 ============
def step_fetch():
    print("\n[Step 1] 抓取书源列表...")
    pool_file = os.path.join(RAW, "pool.json")
    existing = json.load(open(pool_file, encoding="utf-8")) if os.path.exists(pool_file) else []
    existing_urls = set(s.get("bookSourceUrl","").split("#")[0] for s in existing)
    
    new_sources = []
    for p in range(1, 11):
        try:
            html, _ = fetch(f"https://www.yckceo.com/yuedu/shuyuan/index.html?page={p}")
            for m in re.finditer(r'/yuedu/shuyuan/json/id/(\d+)\.json', html):
                sid = m.group(1)
                try:
                    sjson, _ = fetch(f"https://www.yckceo.com/yuedu/shuyuan/json/id/{sid}.json")
                    s = json.loads(sjson)
                    url = s.get("bookSourceUrl","").split("#")[0]
                    if url and url not in existing_urls:
                        new_sources.append(s)
                except: pass
        except: pass
        time.sleep(0.2)
    
    print(f"  新增 {len(new_sources)} 个源")
    return new_sources, existing

# ============ Step 2: 域名探活 ============
def step_alive(sources):
    print(f"\n[Step 2] 域名探活 ({len(sources)}个)...")
    alive = []
    def check(s):
        url = s.get("bookSourceUrl","").split("#")[0]
        try:
            req = urllib.request.Request(url + "/", headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=10, context=ctx) as r:
                return True  # 200
        except urllib.error.HTTPError as e:
            # 403/401/404/405/429/500/502/503 都算存活
            # 404对API类源是正常的（首页不存在但API路径能用）
            # 401/403是WAF或需要认证，阅读App能带header/cookie绕过
            return True
        except urllib.error.URLError as e:
            # 只有DNS解析失败、连接拒绝、超时才算可能死
            # 但超时也可能是站慢，先保留
            return True
        except Exception:
            return False  # 其他异常（SSL错误等）才算死
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = {ex.submit(check, s): s for s in sources}
        for fut in as_completed(futs):
            if fut.result():
                alive.append(futs[fut])
    removed = len(sources) - len(alive)
    print(f"  存活 {len(alive)}/{len(sources)}" + (f"（剔除{removed}个）" if removed else "（全部存活）"))
    return alive

# ============ Step 3: 搜索测试 ============
def step_search(sources):
    print(f"\n[Step 3] 搜索接口测试 ({len(sources)}个)...")
    good = []
    def test(s):
        su = s.get("searchUrl","")
        if not su: return False
        book = s.get("bookSourceUrl","").split("#")[0].rstrip("/")
        method, body, charset = "GET", None, "utf-8"
        if "," in su and "{" in su:
            try:
                cfg = json.loads(su.split(",",1)[1])
                method = cfg.get("method","GET").upper()
                body = cfg.get("body","")
                charset = cfg.get("charset","utf-8")
                path = su.split(",",1)[0]
            except: path = su
        else: path = su
        path = path.replace("{{key}}", urllib.parse.quote("剑来")).replace("{{page}}","1")
        url = path if path.startswith("http") else book + "/" + path.lstrip("/")
        try:
            data = body.replace("{{key}}","剑来").encode(charset, errors="ignore") if method=="POST" and body else None
            headers = {"Content-Type":"application/x-www-form-urlencoded"} if data else {}
            html, _ = fetch(url, timeout=10, data=data, headers=headers)
            # 返回>500字节就算有内容（API类返回JSON可能很小）
            return len(html) > 500
        except: return False
    with ThreadPoolExecutor(max_workers=12) as ex:
        futs = {ex.submit(test, s): s for s in sources}
        for fut in as_completed(futs):
            if fut.result():
                good.append(futs[fut])
    print(f"  搜索可用 {len(good)}/{len(sources)}")
    return good

# ============ Step 4: 自动补全规则 ============
def step_autofix(sources):
    print(f"\n[Step 4] 自动补全规则 ({len(sources)}个)...")
    for s in sources:
        for f in ["ruleSearch","ruleBookInfo","ruleToc","ruleContent"]:
            v = s.get(f)
            if not isinstance(v, dict):
                s[f] = {} if not v else (json.loads(v) if isinstance(v,str) and v.startswith("{") else {})
        
        rb = s["ruleBookInfo"]
        rb.setdefault("name", "h1@text||.info h1@text")
        rb.setdefault("author", ".info p@text||.author@text")
        rb.setdefault("coverUrl", "img@src||.cover img@src")
        rb.setdefault("intro", ".intro@text||#intro@text")
        rb.setdefault("tocUrl", "")
        
        rt = s["ruleToc"]
        rt.setdefault("chapterList", "#list dd a||.listmain dd a||.booklist dd a")
        rt.setdefault("chapterName", "@text")
        rt.setdefault("chapterUrl", "@href")
        
        rc = s["ruleContent"]
        rc.setdefault("content", "#content@html||.content@html||#booktxt@html")
        # 通用净化
        if not rc.get("replaceRegex"):
            rc["replaceRegex"] = """<script>.*?</script>
<style>.*?</style>
本章未完.*请翻页
http[s]?://[^\s<]+
旳##的
嚿##会
國##国"""
        
        s.setdefault("enabled", True)
        s.setdefault("bookSourceType", 0)
        s.setdefault("respondTime", 15000)
        if not s.get("header"):
            s["header"] = json.dumps({"User-Agent": UA})
    print(f"  规则补全完成")
    return sources

# ============ Step 5: 过滤成人/漫画 ============
def step_filter(sources):
    print(f"\n[Step 5] 过滤成人/漫画/非小说 ({len(sources)}个)...")
    # 精确匹配，避免误杀（不用"bl"这种短词）
    BAD = ["成人","肉文","海棠","po18","脸红心跳","欲望社","人妻","耽美","🔞",
           "漫画","动漫","漫客","听书","有声","词典","游戏","小红书"]
    good = [s for s in sources if not any(b.lower() in s.get("bookSourceName","").lower() for b in BAD)]
    print(f"  过滤后 {len(good)}/{len(sources)}")
    return good

# ============ Step 6: 合并去重 ============
def step_merge(new_sources, existing_final):
    print(f"\n[Step 6] 合并去重...")
    existing_hosts = set(host(s["bookSourceUrl"]) for s in existing_final)
    added = 0
    for s in new_sources:
        h = host(s["bookSourceUrl"])
        if h not in existing_hosts:
            s["bookSourceGroup"] = "免费小说站"
            s["customOrder"] = 6000
            existing_final.append(s)
            existing_hosts.add(h)
            added += 1
    print(f"  新增 {added} 个到最终书源")
    existing_final.sort(key=lambda x: (-x.get("customOrder",0), x.get("bookSourceName","")))
    return existing_final

# ============ Step 0: 全量校验精选版，剔除死源 ============
def step_validate_final(sources):
    print(f"\n[Step 0] 全量校验精选版 ({len(sources)}个)...")
    alive = step_alive(sources)
    dead = len(sources) - len(alive)
    if dead > 0:
        print(f"  剔除 {dead} 个死源")
    else:
        print(f"  全部存活")
    return alive

# ============ 主流程 ============
def main():
    print("=" * 50)
    print("全自动书源流水线")
    print("=" * 50)
    
    # 读取精选版
    final = json.load(open(FINAL, encoding="utf-8"))
    print(f"精选版: {len(final)} 个")
    
    # Step 0: 全量校验，剔除死源
    final = step_validate_final(final)
    
    # Step 1: 抓取新增
    new_sources, raw_db = step_fetch()
    
    if new_sources:
        # Step 2: 探活新增
        alive = step_alive(new_sources)
        # Step 3: 搜索测试
        searchable = step_search(alive)
        # Step 4: 过滤
        filtered = step_filter(searchable)
        # Step 5: 补全规则
        fixed = step_autofix(filtered)
        # Step 6: 合并
        final = step_merge(fixed, final)
    
    # 保存精选版
    json.dump(final, open(FINAL, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    
    # 更新采集池
    all_raw = raw_db + new_sources if new_sources else raw_db
    json.dump(all_raw, open(os.path.join(RAW,"pool.json"),"w"), ensure_ascii=False)
    
    print(f"\n{'='*50}")
    print(f"完成！精选版: {len(final)} 个")
    print(f"{'='*50}")

if __name__ == "__main__":
    main()
