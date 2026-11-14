#!/usr/bin/env python3
"""新源健康门槛：把"半死不活"的站点挡在中间层之外

接入位置：`.github/workflows/auto-update.yml` 的「当天增量并入中间层」之前。
只处理**本次新采到的候选**（几十条），绝不对全量 2140 跑——那会把每日 workflow 拖垮。

判定口径（刻意为"宁可放过、不可错杀"，因为云端在美西节点，跨洋取不到 sitemap 是常态）：
  · hard_zombie  仅当 sitemap 的 <lastmod> 明确存在且距今 > 180 天 → 剔除
                 （sitemap 是站点主动写给搜索引擎的，是这个站"自己说"什么时候更新的）
  · 其余全部放行：不可达、无信号、首页日期、甚至首页显示很久没更新——
                 跨洋网络下这些都可能是"我们取不到"，不能当证据

用法：
  python3 scripts/health_gate.py --input weekly/cleaned_xxx.json --output weekly/cleaned_gated.json \
      --max 120 --drop-hard-zombie

退出码：恒为 0（采集流水线不该因为预筛失败而中断），除非参数错误。
"""
import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from site_health import check_one  # 复用同一套判定

HARD_ZOMBIE_DAYS = 180


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--max", type=int, default=120, help="最多体检多少条（超出部分直接放行）")
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--drop-hard-zombie", action="store_true", help="剔除硬证据僵尸")
    ap.add_argument("--budget", type=int, default=180, help="整体时间预算（秒），超时即停止体检并全部放行")
    args = ap.parse_args()

    data = json.load(open(args.input, encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("sources") or data.get("books") or []
    print(f"输入 {len(data)} 条，最多体检 {args.max} 条")

    t0 = time.time()
    probe = data[: args.max]
    rest = data[args.max:]

    def _run(s):
        try:
            return check_one(s)
        except Exception as e:
            return {"url": s.get("bookSourceUrl"), "name": s.get("bookSourceName"),
                    "verdict": "不可达", "evidence": "", "days": None,
                    "sitemap_urls": 0, "note": f"未捕获 {type(e).__name__}"}

    results = []
    timed_out = False
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(_run, s) for s in probe]
        for f in futs:
            if time.time() - t0 > args.budget:
                timed_out = True
                break
            try:
                results.append(f.result(timeout=15))
            except Exception:
                continue
    if timed_out:
        print(f"⚠️ 超出 {args.budget}s 时间预算，剩余体检取消（全部放行）")

    by_url = {r.get("url"): r for r in results}
    hard_zombies, kept = [], []
    for s in probe:   # 只处理体检过的这一段，rest 原样追加（否则会重复计数）
        r = by_url.get(s.get("bookSourceUrl"))
        if (r and r.get("evidence") == "sitemap"
                and r.get("days") is not None and r["days"] > HARD_ZOMBIE_DAYS):
            if args.drop_hard_zombie:
                hard_zombies.append({"name": s.get("bookSourceName"),
                                     "url": s.get("bookSourceUrl"),
                                     "lastmod": r.get("newest"), "days": r["days"],
                                     "sitemap_urls": r.get("sitemap_urls")})
                continue
        if r:
            s = dict(s)
            s.setdefault("comment", "")
            tag = f"// 健康度:{r.get('verdict')}" + (f" 最后更新{r['newest']}" if r.get("newest") else "")
            if "健康度:" not in (s.get("comment") or ""):
                s["comment"] = (s.get("comment") + " " + tag).strip()
        kept.append(s)

    os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".", exist_ok=True)
    json.dump(kept + rest, open(args.output, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    n_reach = sum(1 for r in results if r.get("reachable"))
    n_sm = sum(1 for r in results if r.get("sitemap_urls"))
    print(f"体检 {len(results)} 条：可达 {n_reach} / 有 sitemap {n_sm} / 硬僵尸 {len(hard_zombies)}")
    print(f"输出 {len(kept)+len(rest)} 条 → {args.output}")
    for z in hard_zombies[:20]:
        print(f"  剔除 {z['name']}  {z['url']}  最后更新 {z['lastmod']} ({z['days']}天前)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
