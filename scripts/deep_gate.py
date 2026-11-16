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
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

log = logging.getLogger("gate")
if not log.handlers:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from site_deep_check import check_site  # 复用进站判定
from autocollect_core.utils import dump_json, host_of
try:
    from autocollect_core.config import STATIC_SITE_KEYWORDS, STATIC_SITE_HOSTS, BIG_SITES
except Exception:
    BIG_SITES = []

ZOMBIE_DAYS = 180


def _host(u):
    return host_of(u)   # 唯一实现在 utils.host_of


_BIG = {_host(b.get("url")) for b in BIG_SITES}


def is_big(u):
    h = _host(u)
    return any(h == b or h.endswith("." + b) for b in _BIG if b)


def is_static(name, u=""):
    """静态内容站豁免：古籍/国学/诗词/典籍类站点内容固定，
    "最后更新停在建站时"是常态而非失活，不能用更新日期判死。

    两条判据取并集：站名关键词命中，或域名在 STATIC_SITE_HOSTS 白名单里。
    只认站名是不够的——gxhj.com / guoxue.wunpu.com 的域名完全不含关键词，
    站名一旦被清理或改名，真古籍站就会被当僵尸删掉。
    """
    text = (name or "") + " " + (u or "")
    if any(k in text for k in STATIC_SITE_KEYWORDS):
        return True
    return host_of(u) in STATIC_SITE_HOSTS


def _guarded_check(it, deadline):
    """预算硬截断：排队任务在预算耗尽后不再发起进站请求。
    单个进站最坏 4s×3 页×多请求，不截断会把 --budget 拖成 2 倍。"""
    if time.time() > deadline:
        return {**it, "verdict": "超预算", "newest": None, "days": None}
    try:
        return check_site(it)
    except Exception as e:
        log.warning(f"进站深查异常（按保留处理）: {e}")
        return {**it, "verdict": "判不了", "newest": None, "days": None}


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
    # 预算必须是硬上限：原 `with ThreadPoolExecutor()` 在 break 后退出时
    # shutdown(wait=True)，会把已提交的进站任务全部等完，--budget 名不副实。
    ex = ThreadPoolExecutor(max_workers=args.workers)
    futs = [ex.submit(_guarded_check, it, t0 + args.budget) for it in items]
    timed_out = False
    try:
        for f in as_completed(futs):
            if time.time() - t0 > args.budget:
                timed_out = True
                print(f"⚠️ 超出 {args.budget}s 预算，剩余深查取消（全部保留）")
                break
            try:
                results.append(f.result(timeout=25))
            except Exception as e:
                log.warning(f"进站深查异常（该源按保留处理）: {e}")

    finally:
        ex.shutdown(wait=False, cancel_futures=True)

    alive = [r for r in results if r["deep_verdict"] == "活站"]
    zombie = [r for r in results if r["deep_verdict"] == "僵尸"]
    unknown = [r for r in results if r["deep_verdict"] in ("判不了", "不可达")]

    drop_urls = set()
    dropped = []
    for r in zombie:
        if is_big(r["url"]):
            continue          # 大厂豁免（黑岩进站 277 天但仍在运营）
        if is_static(r.get("name"), r.get("url")):
            continue          # 静态内容站豁免（古籍/国学站永不更新是正常的）
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
    dump_json(out, args.output)

    report = {"checked": len(results), "alive": len(alive), "zombie": len(zombie),
              "unknown": len(unknown), "dropped": len(dropped),
              "dropped_items": [{k: r[k] for k in ("name", "url", "deep_date", "deep_days")} for r in dropped]}
    rp = args.report or os.path.join(os.path.dirname(os.path.abspath(args.output)),
                                     "deep_gate_report.json")
    dump_json(report, rp)

    print(f"深查 {len(results)} 条：活站 {len(alive)} / 僵尸 {len(zombie)} / 判不了+不可达 {len(unknown)}")
    print(f"实际剔除 {len(dropped)} 条 → 输出 {len(out)} 条")
    for r in dropped[:15]:
        print(f"  剔除 {r['name']} {r['url']} 进站 {r['deep_date']}({r['deep_days']}天)")
    print(f"报告: {rp}")
    if timed_out:
        # 同上：预算耗尽后不再等已发起的进站请求跑完
        sys.stdout.flush(); sys.stderr.flush()
        os._exit(0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
