#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每月自动合并 + 发布（GitHub Actions 定时调用）

为什么不是「汇总每日 artifact」：每日产出的 cleaned 是**未筛的原始池**，其中包含
已经被历史校验淘汰的源；按月从 artifact 汇总会把淘汰源重新捞回来（实测一次会把
1538 条顶到 2139 条）。所以每月走「重新采集一次」模式：采集 → 明确死站剔除 →
垃圾过滤 → 与正式版合并 → 自动发版。不存在历史回捞，也不受 artifact 保留期限制。

校验取舍：跨洋网络做不了内容真实性校验（实测误杀 72%→27%），本脚本只剔「明确死站」
（DNS 失败 / 连接被拒 / 4xx / 5xx），超时与代理异常一律保留，宁滥勿缺。

用法：
  python3 scripts/monthly_release.py                  # 采集(1月) + 合并 + 发布
  python3 scripts/monthly_release.py --months 2       # 采集近 2 月
  python3 scripts/monthly_release.py --dry-run        # 只合并不写盘不发布
"""
import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import socket
import urllib.parse
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from autocollect_core.cleaner import clean_and_dedup, filter_junk_sources, is_big_site
from autocollect_core.collectors import collect_all
from autocollect_core.config import OUTPUT_FILE
from autocollect_core.organizer import organize_sources
from autocollect_core.utils import clean_url, log


def probe_alive(source, timeout=6):
    """只认明确死站：404/410 或连接层明确失败；403/405(WAF)、429(限流)、5xx(临时)、超时、SSL、代理异常一律 unknown 保留"""
    url = source.get("bookSourceUrl") or ""
    if not url.startswith("http"):
        return "unknown"
    try:
        r = requests.get(url, timeout=timeout, allow_redirects=True, verify=False,
                         headers={"User-Agent": "Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36"})
        # 404/410 才是「站点明确不存在」；403/405 是 WAF 盾站（用户硬约束：不淘汰），
        # 429 是限流、5xx 是临时故障，都不足以判死，按 unknown 保留
        if r.status_code in (404, 410):
            return "dead"
        if r.status_code >= 500 or r.status_code in (403, 405, 429):
            return "unknown"
        return "ok" if r.status_code < 400 else "unknown"
    except requests.exceptions.ProxyError as e:
        # 本机/Actions 都走代理：连不上时统一表现为 ProxyError 502，无法区分「域名死了」和「代理抽风」。
        # 因此改用域名解析做判据：域名解析不出来 = 明确死站；能解析 = 站可能活着，只记 unknown
        host = urllib.parse.urlparse(url).hostname
        try:
            socket.getaddrinfo(host, None)
            return "unknown"
        except socket.gaierror:
            return "dead"
        except Exception:
            return "unknown"
    except requests.exceptions.ConnectionError as e:
        # 连接层「确定连不上」才判死：域名解析失败 / 端口拒绝 / 主机不可达
        # （urllib3 各版本文案不同，实测需要同时认 failed to resolve 与 NameResolutionError）
        msg = str(e).lower()
        if any(k in msg for k in ("name or service not known", "nodename nor servname",
                                  "nameresolutionerror", "failed to resolve",
                                  "getaddrinfo failed", "errno -2", "errno -3", "errno -5",
                                  "connection refused", "newconnectionerror",
                                  "failed to establish a new connection",
                                  "network is unreachable", "no route to host")):
            return "dead"
        return "unknown"
    except Exception:
        return "unknown"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", type=int, default=1, help="采集最近 N 个月的更新")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    requests.packages.urllib3.disable_warnings()

    books_path = OUTPUT_FILE if os.path.isabs(OUTPUT_FILE) else os.path.join(ROOT, OUTPUT_FILE)
    existing = json.load(open(books_path, encoding="utf-8")) if os.path.exists(books_path) else []
    log.info(f"现有正式版: {len(existing)} 个源")

    # 1. 采集 + 清洗
    raw = collect_all(months=args.months)
    cleaned = clean_and_dedup(raw)
    log.info(f"采集清洗: 原始 {len(raw)} → 清洗后 {len(cleaned)}")

    # 2. 与正式版去重
    seen = {clean_url(s.get("bookSourceUrl") or "") for s in existing}
    uniq = []
    for s in cleaned:
        u = clean_url(s.get("bookSourceUrl") or "")
        if u and u not in seen:
            seen.add(u)
            uniq.append(s)
    log.info(f"与正式版去重后候选: {len(uniq)}")

    # 3. 明确死站剔除
    alive, dead = [], []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(probe_alive, s): s for s in uniq}
        for f in as_completed(futs):
            s = futs[f]
            (dead if f.result() == "dead" else alive).append(s)
    log.info(f"明确死站剔除 {len(dead)}，保留 {len(alive)}（超时/代理异常按保留处理）")

    # 4. 候选 = 存活新源 + 现有非大厂源（organize 只从候选取，existing 仅用于大厂保护）
    #    新源才走垃圾过滤；现有源已过历史校验，重过滤会误删（实测 badaoge.la 因 URL 含 "bad"
    #    命中 JUNK_DEAD_KW 被删），所以现有源原样进入候选
    existing_non_big = [s for s in existing if not is_big_site(s)]
    validated = filter_junk_sources([{"source": s, "pass_rate": 1.0} for s in alive])
    validated += [{"source": s, "pass_rate": 1.0} for s in existing_non_big]

    # 5. 合并整理
    final = organize_sources(validated, existing)
    big_count = len([s for s in final if is_big_site(s)])
    before = len(existing)
    log.info(f"合并结果: {before} → {len(final)}（大厂 {big_count} 保护，净增 {len(final) - before}）")

    if args.dry_run:
        log.info("dry-run：不写盘、不发布")
        return

    json.dump(final, open(books_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    report = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "months": args.months,
        "raw": len(raw),
        "cleaned": len(cleaned),
        "candidates": len(uniq),
        "dead_removed": len(dead),
        "merged_total": len(final),
        "net_added": len(final) - before,
        "big_sites": big_count,
        "note": "跨洋只做明确死站剔除，内容真实性未校验",
    }
    os.makedirs(os.path.join(ROOT, "raw", "autocollect"), exist_ok=True)
    json.dump(report, open(os.path.join(ROOT, "raw", "autocollect", "monthly_report.json"),
                           "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    log.info(f"报告: {json.dumps(report, ensure_ascii=False)}")

    from autocollect_core.publisher import auto_publish
    if not auto_publish(len(final), big_count, mode="auto", stats=report):
        log.error("❌ 发布未完成（release 未建成 asset 不齐），books.json 已写盘但未发版")
        sys.exit(1)
    log.info("✅ 每月合并 + 发布完成")


if __name__ == "__main__":
    main()
