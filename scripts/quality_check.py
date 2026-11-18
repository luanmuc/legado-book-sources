#!/usr/bin/env python3
"""源质量四层体检（2026-11-18）

与 validate_sources(mode="full") 的区别：
  full 校验靠「能不能用书源规则搜到书」，遇到反爬就判不了（实测 57% blocked）。
  本脚本不依赖搜索接口，分四层独立判定：URL 格式 → DNS → 端口 → 首页内容。

  第 4 层是唯一能解决「域名活着但已经不是小说站」的手段。

用法：
  python3 scripts/quality_check.py                  # 全量
  python3 scripts/quality_check.py --limit 200      # 抽样
  python3 scripts/quality_check.py --report out.json

输出：分类清单（脏URL/域名废弃/端口不通/非小说/死页/WAF保留/未知），
      并落盘到 raw/autocollect/tmp/ 供后续复核。

重要：网络层的初判**必须复核**——实测端口层误判率 56%、死页层 63%。
      --recheck 会对初判死亡项用 curl 直连多试一次。
"""
import argparse
import json
import os
import re
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from autocollect_core.utils import load_json, dump_json          # noqa: E402
from autocollect_core.cleaner import is_big_site                 # noqa: E402

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0 Safari/537.36")

HOST_RE = re.compile(r"^([a-z0-9]([-a-z0-9]*[a-z0-9])?\.)+[a-z]{2,}$", re.I)
IP_RE = re.compile(r"^(\d{1,3}\.){3}\d{1,3}$")

# 小说站特征词（首页前 2KB + title + keywords 里出现）
NOVEL_WORDS = ["小说", "阅读", "书城", "书屋", "书库", "文学", "章节", "完本",
               "玄幻", "修真", "都市", "言情", "武侠", "穿越", "重生", "修仙",
               "灵异", "历史", "军事", "网游", "科幻", "同人", "漫画", "动漫", "二次元"]
# 非小说特征词——命中这些说明站已经换了业务
ANTI_WORDS = ["彩票", "娱乐城", "博彩", "开户", "体育投注", "直播", "商城", "购物车",
              "招聘", "求职", "医院", "挂号", "学校", "招生", "培训", "旅游", "酒店",
              "机票", "论文", "文档", "PPT", "模板", "壁纸", "图库", "视频", "影视",
              "电影", "资源站", "网盘", "云盘", "加速器", "VPN", "软件下载",
              "APP下载", "企业官网", "加盟", "代理"]

# 反爬验证页的标题特征——这类是活站，绝不能删
WAF_TITLE_RE = re.compile(
    r"(verifying|just a moment|cloudflare|attention required|access denied|"
    r"checking your browser|ddos|captcha)", re.I)
# 死页/空壳标题特征
DEAD_TITLE_RE = re.compile(
    r"(404|not found|welcome to nginx|nginx|网页无法访问|已过期|停用|建设中)", re.I)


def host_of_loose(url):
    if "//" not in url:
        return ""
    return url.split("//")[-1].split("/")[0].split(":")[0].lower()


def layer1_url(url):
    """URL 格式：不联网，最硬的一层"""
    if not re.match(r"^https?://", url or "", re.I):
        return "BAD_SCHEME"
    h = host_of_loose(url)
    if HOST_RE.match(h) or IP_RE.match(h):
        return "OK"
    return "BAD_HOST"


def layer2_dns(host, timeout=5):
    """DNS：不受反爬影响。注意 getaddrinfo 不接受 timeout 参数。"""
    if not host:
        return "NO_HOST"
    old = socket.getdefaulttimeout()
    try:
        socket.setdefaulttimeout(timeout)
        socket.getaddrinfo(host, 443)
        return "OK"
    except socket.gaierror:
        return "NXDOMAIN"
    except Exception:
        return "ERROR"
    finally:
        socket.setdefaulttimeout(old)


def layer3_tcp(host, timeout=5):
    for port in (443, 80):
        try:
            s = socket.create_connection((host, port), timeout=timeout)
            s.close()
            return f"OK:{port}"
        except Exception:
            continue
    return "REFUSED"


def layer4_content(host):
    """抓首页判内容。不用 requests 是为了能强行绕代理。"""
    import requests
    requests.packages.urllib3.disable_warnings()
    sess = requests.Session()
    sess.trust_env = False          # 绕开环境代理，否则 ProxyError 会被当成站死
    for scheme in ("https://", "http://"):
        try:
            r = sess.get(scheme + host, headers={"User-Agent": UA}, timeout=10,
                         verify=False, allow_redirects=True)
            enc = r.apparent_encoding or "utf-8"
            try:
                html = r.content.decode(enc, "ignore")
            except Exception:
                html = r.content.decode("utf-8", "ignore")
        except Exception as e:
            last = type(e).__name__
            continue
        t = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
        title = (t.group(1) if t else "").strip()[:80]
        if WAF_TITLE_RE.search(title):
            return {"cls": "WAF保留", "title": title}
        if DEAD_TITLE_RE.search(title):
            return {"cls": "死页", "title": title}
        kw = ""
        m = re.search(r'name=["\'](?:keywords|description)["\'][^>]*content=["\']([^"\']*)',
                      html, re.I)
        if m:
            kw = m.group(1)[:120]
        head = html[:2000] + title + kw
        ns = sum(1 for w in NOVEL_WORDS if w in head)
        Anti = sum(1 for w in ANTI_WORDS if w in head)
        books = len(re.findall(r'href=["\'][^"\']*(?:/book/|/novel/|/read/|/txt/)', html, re.I))
        if ns >= 2 and ns > Anti:
            cls = "小说站"
        elif Anti >= 2 and Anti > ns:
            cls = "非小说"
        elif books >= 5:
            cls = "小说站"
        elif ns >= 1:
            cls = "疑似小说"
        else:
            cls = "未知"
        return {"cls": cls, "title": title, "kw": kw, "ns": ns, "anti": Anti, "books": books}
    return {"cls": "抓不到", "title": "", "err": last}


def curl_alive(url, host):
    """复核用：curl 直连、多协议、多次机会。返回 True 表示其实活着。"""
    for scheme in ("https://", "http://"):
        for _ in range(2):
            r = subprocess.run(
                ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}|%{size_download}",
                 "--max-time", "10", "--noproxy", "*", "-k", "-L", "-A", UA, scheme + host],
                capture_output=True)
            out = r.stdout.decode("utf-8", "ignore").strip()
            parts = (out.split("|") + ["0"])[:2]
            code, size = parts[0], parts[1]
            if code.isdigit() and 200 <= int(code) < 400 and int(size) > 300:
                return True, f"{code}/{size}B"
    return False, "FAIL"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="books.json")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=32)
    ap.add_argument("--recheck", action="store_true",
                    help="对初判死亡的项用 curl 直连复核（强烈建议开）")
    ap.add_argument("--report", default="raw/autocollect/tmp/quality_report.json")
    args = ap.parse_args()

    src = load_json(args.input, default=[])
    if args.limit:
        src = src[:args.limit]
    print(f"体检 {len(src)} 条  workers={args.workers}")

    rows = []

    def probe(item):
        url = (item.get("bookSourceUrl") or "").strip()
        host = host_of_loose(url)
        row = {"name": item.get("bookSourceName"), "url": url,
               "group": item.get("bookSourceGroup"), "big": is_big_site(item)}
        if row["big"]:
            row["verdict"] = "大厂豁免"
            return row
        l1 = layer1_url(url)
        if l1 != "OK":
            row["verdict"] = "脏URL"
            row["detail"] = l1
            return row
        l2 = layer2_dns(host)
        row["dns"] = l2
        if l2 == "NXDOMAIN":
            row["verdict"] = "域名废弃"
            return row
        l3 = layer3_tcp(host)
        row["tcp"] = l3
        if l3 == "REFUSED":
            row["verdict"] = "端口不通"
            return row
        c = layer4_content(host)
        row.update({f"c_{k}": v for k, v in c.items()})
        row["verdict"] = c["cls"]
        return row

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(probe, s) for s in src]
        for i, f in enumerate(as_completed(futs), 1):
            rows.append(f.result())
            if i % 200 == 0:
                print(f"  {i}/{len(src)}  ({time.time()-t0:.0f}s)")

    # 复核：端口不通 / 死页 这两层误判率高（实测 56%-63%）
    if args.recheck:
        risky = [r for r in rows if r["verdict"] in ("端口不通", "死页", "抓不到")]
        print(f"\n复核 {len(risky)} 条（端口/死页/抓不到）...")
        idx = {(r["url"]): r for r in risky}

        def rc(r):
            alive, detail = curl_alive(r["url"], host_of_loose(r["url"]))
            return r["url"], alive, detail

        with ThreadPoolExecutor(max_workers=16) as ex:
            futs = [ex.submit(rc, r) for r in risky]
            for f in as_completed(futs):
                u, alive, detail = f.result()
                r = idx[u]
                if alive:
                    r["verdict_before"] = r["verdict"]
                    r["verdict"] = "复核活着"
                    r["recheck"] = detail

    from collections import Counter
    c = Counter(r["verdict"] for r in rows)
    print(f"\n耗时 {time.time()-t0:.0f}s")
    for k, v in c.most_common():
        print(f"  {k}: {v}")
    dump_json(rows, args.report)
    print(f"\n明细已落盘 {args.report}")


if __name__ == "__main__":
    main()
