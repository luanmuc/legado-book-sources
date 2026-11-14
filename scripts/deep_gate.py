#!/usr/bin/env python3
"""进站深查门槛：把"确认在更新"作为唯一判活依据

为什么不能用门口信号：`site_health.py` 只读首页/sitemap/Last-Modified，
但实测这些经常是模板假数据——`2024-04-20` 被七八个站共享、`2015-02-14` 被四个站共享，
进站后全是最近几天在更新。用它判死会误删一半。

本脚本进站：抓首页的一本书 → 详情/目录页 → 读"最新章节"区块的日期。
  ≤180 天 → 活站（保留）
  >180 天 → 僵尸（可剔除）
  拿不到 / 打不开 → 保留（"我们看不到"不等于"站死了"）

用法：
  # 每日：只查新候选里被标了"疑似"的
  python3 scripts/deep_gate.py --input weekly/cleaned_gated.json \
      --output weekly/cleaned_deep.json --max 40 --only-suspect --drop-zombie

  # 月度：对正式版抽样清存量
  python3 scripts/deep_gate.py --input books.json \
      --output books_deep.json --max 150 --drop-zombie

退出码恒为 0（不阻断采集/发布），只有参数错误才非 0。
"""
import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from site_deep_check import check_site  # 复用进站判定
try:
    from autocollect_core.config import BIG_SITES
except Exception:
    BIG_SITES = []

ZOMBIE_DAYS = 180


def _host(u):
    return (u or "").split("//")[-1].split("/")[0].lower().replace("www.", "")


_BIG = {_host(b.get("url")) for b in BIG_SITES}


def is_big(u):
    h = _host(u)
    return any(h == b or h.endswith("." + b) for b in _BIG if b)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--max", type=int, default=150)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--only-suspect", action="store_true",
                    help="只查 comment 里已被门口筛标为疑似/僵尸的（每日用，省时间）")
    ap.add_argument("--drop-zombie", action="store_true")
    ap.add_argument("--budget", type=int, default=300, help="整体时间预算（秒）")
    ap.add_argument("--report", default="", help="报告 JSON 输出路径")
    args = ap.parse_args()

    data = json.load(open(args.input, encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("sources") or data.get("books") or []
    print(f"输入 {len(data)} 条")

    pool = data
    if args.only_suspect:
        pool = [s for s in data
                if any(k in (s.get("comment") or "") for k in ("疑似", "僵尸", "无信号", "迟缓"))]
        print(f"其中被门口筛标记为可疑的 {len(pool)} 条")

    probe = pool[: args.max]
    rest = data
    print(f"进站深查 {len(probe)} 条（上限 {args.max}）")

    t0 = time.time()
    items = [{"name": s.get("bookSourceName"), "url": s.get("bookSourceUrl"),
              "verdict": "未知", "newest": None, "days": None} for s in probe]

    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(check_site, it) for it in items]
        for f in futs:
            if time.time() - t0 > args.budget:
                print(f"⚠️ 超出 {args.budget}s 预算，剩余深查取消（全部保留）")
                break
            try:
                results.append(f.result(timeout=25))
            except Exception:
                continue

    alive = [r for r in results if r["deep_verdict"] == "活站"]
    zombie = [r for r in results if r["deep_verdict"] == "僵尸"]
    unknown = [r for r in results if r["deep_verdict"] in ("判不了", "不可达")]

    drop_urls = set()
    dropped = []
    for r in zombie:
        if is_big(r["url"]):
            continue          # 大厂豁免（黑岩进站 277 天但仍在运营）
        d = r.get("deep_days") or 0
        if d <= ZOMBIE_DAYS:
            continue
        hd = r.get("home_days")
        if hd is not None and hd <= 180:
            continue          # 首页说新、进站说老，数据矛盾 → 不删
        if args.drop_zombie:
            drop_urls.add((r["url"] or "").rstrip("/"))
            dropped.append(r)

    out = []
    for s in rest:
        if (s.get("bookSourceUrl") or "").rstrip("/") in drop_urls:
            continue
        out.append(s)

    os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".", exist_ok=True)
    json.dump(out, open(args.output, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    report = {"checked": len(results), "alive": len(alive), "zombie": len(zombie),
              "unknown": len(unknown), "dropped": len(dropped),
              "dropped_items": [{k: r[k] for k in ("name", "url", "deep_date", "deep_days")} for r in dropped]}
    rp = args.report or os.path.join(os.path.dirname(os.path.abspath(args.output)),
                                     "deep_gate_report.json")
    json.dump(report, open(rp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print(f"深查 {len(results)} 条：活站 {len(alive)} / 僵尸 {len(zombie)} / 判不了+不可达 {len(unknown)}")
    print(f"实际剔除 {len(dropped)} 条 → 输出 {len(out)} 条")
    for r in dropped[:15]:
        print(f"  剔除 {r['name']} {r['url']} 进站 {r['deep_date']}({r['deep_days']}天)")
    print(f"报告: {rp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
