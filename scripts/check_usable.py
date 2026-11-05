# -*- coding: utf-8 -*-
"""全量可用性检测：搜索/发现至少一个能用才算可用源（带断点续传）

用法：
  python3 scripts/check_usable.py            # 全量检测 books.json
  python3 scripts/check_usable.py --limit 50 # 只测前 N 个（抽样）
输出：raw/autocollect/usable_report_<ts>.json + 控制台统计
断点：raw/autocollect/ckpt_usable.json（已处理 URL 集合，中断重跑自动跳过）
"""
import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autocollect_core.cleaner import is_big_site
from autocollect_core.validators import check_source_usable

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOKS = os.path.join(ROOT, "books.json")
OUT_DIR = os.path.join(ROOT, "raw", "autocollect")
CKPT = os.path.join(OUT_DIR, "ckpt_usable.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只测前 N 个源（0=全量）")
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--batch", type=int, default=200, help="每批落盘数")
    args = ap.parse_args()

    sources = json.load(open(BOOKS, encoding="utf-8"))
    if args.limit:
        sources = sources[: args.limit]
    total = len(sources)

    done = {}
    if os.path.exists(CKPT):
        try:
            done = json.load(open(CKPT, encoding="utf-8"))
        except Exception:
            done = {}
    print(f"共 {total} 个源，已完成 {len(done)} 个（断点）")

    todo = [s for s in sources if (s.get("bookSourceUrl") or "") not in done]
    print(f"待检测 {len(todo)} 个")

    report = {}
    for url, r in done.items():
        report[url] = r

    def one(s):
        url = s.get("bookSourceUrl") or ""
        try:
            r = check_source_usable(s)
        except Exception as e:
            r = {"usable": None, "search": "error", "explore": None,
                 "detail": f"异常 {type(e).__name__}"}
        return url, {
            "name": s.get("bookSourceName", ""),
            "group": s.get("bookSourceGroup", ""),
            "big": is_big_site(s),
            "usable": r["usable"],
            "search": r["search"],
            "explore": r["explore"],
            "detail": r["detail"],
        }

    t0 = time.time()
    n_done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(one, s): s for s in todo}
        for fut in as_completed(futs):
            url, r = fut.result()
            report[url] = r
            n_done += 1
            if n_done % args.batch == 0:
                json.dump(report, open(CKPT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
                el = time.time() - t0
                print(f"  进度 {n_done}/{len(todo)} 用时 {el:.0f}s", flush=True)

    json.dump(report, open(CKPT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    ts = time.strftime("%Y%m%d_%H%M%S")
    out = os.path.join(OUT_DIR, f"usable_report_{ts}.json")
    json.dump(report, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    # 统计
    stat = {"可用": 0, "失效": 0, "待验": 0}
    big_fail = []
    fail_list = []
    for url, r in report.items():
        k = "可用" if r["usable"] is True else ("失效" if r["usable"] is False else "待验")
        stat[k] += 1
        if r["usable"] is False:
            (big_fail if r["big"] else fail_list).append(r["name"])
    print()
    print(f"=== 结果 {len(report)} 源 ===")
    print(f"可用: {stat['可用']} | 失效: {stat['失效']} | 待验(网络/反爬): {stat['待验']}")
    print(f"大厂失效(不淘汰): {len(big_fail)} {big_fail}")
    print(f"报告: {out}")
    print(f"失效明细前20: {fail_list[:20]}")


if __name__ == "__main__":
    main()
