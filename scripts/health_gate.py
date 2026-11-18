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
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

log = logging.getLogger("gate")
if not log.handlers:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from site_health import check_one  # 复用同一套判定
from autocollect_core.utils import dump_json, host_of
try:
    from autocollect_core.config import BIG_SITES, STATIC_SITE_KEYWORDS, STATIC_SITE_HOSTS
except Exception:
    BIG_SITES = []
    STATIC_SITE_KEYWORDS = ()
    STATIC_SITE_HOSTS = ()


def detect_template_dates(results, min_count=3, min_days=None):
    """找出疑似模板假日期：同一批里同一个 sitemap lastmod 出现 ≥ min_count 次。

    min_days：只统计"已经超过这个天数"的日期。模板判定的唯一目的是**防误删**，
    而 days 很小的日期根本不可能触发删除，标成模板没有意义，还会把报告弄脏
    （实测 2026-11-18 就有 2026-11-17 / 2026-11-18 两个新鲜日期被标进来）。


    sitemap 的 <lastmod> 未必是真实更新时间。实测：爱丽丝书屋 4 个镜像域名共用
    2024-08-19，而这 4 个站 HTTP 200、66KB 内容照常在服务；历史上还见过
    2024-04-20 被七八个笔趣阁分站共享。单站看 lastmod 完全看不出这件事，
    必须横向比——所以这条判据只能在本批里做，不能落到单站函数里。
    """
    cnt = {}
    for r in results:
        if r.get("evidence") != "sitemap" or not r.get("newest"):
            continue
        if min_days is not None:
            d = r.get("days")
            if d is None or d <= min_days:
                continue          # 这个日期不可能触发删除，不参与模板判定
        cnt[r["newest"]] = cnt.get(r["newest"], 0) + 1
    return {d for d, n in cnt.items() if n >= min_count}


def _host(u):
    return host_of(u)   # 唯一实现在 utils.host_of


# 大厂豁免：晋江 sitemap 停在 2020、黑岩首页挂 2019 版权年、潇湘首页是公告日期，
# 但它们都活得好好的。大厂站点人工维护、有反爬，禁止靠自动信号判死。
_BIG_HOSTS = {_host(b.get("url")) for b in BIG_SITES}


def is_big_site(url):
    h = _host(url)
    return any(h == b or h.endswith("." + b) for b in _BIG_HOSTS if b)

HARD_ZOMBIE_DAYS = 180



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
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--report", default="", help="门槛报告 JSON（供每日摘要统计用）")
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
            return check_one(s, deadline=t0 + args.budget)
        except Exception as e:
            return {"url": s.get("bookSourceUrl"), "name": s.get("bookSourceName"),
                    "verdict": "不可达", "evidence": "", "days": None,
                    "sitemap_urls": 0, "note": f"未捕获 {type(e).__name__}"}

    results = []
    timed_out = False
    # 预算必须是硬上限。原先用 `with` 包 ThreadPoolExecutor：break 之后 with 退出
    # 会 shutdown(wait=True)，把已提交的任务全部等完，--budget 180s 实际能跑到 240s+。
    # 现在手动 shutdown(wait=False, cancel_futures=True)，并改用 as_completed 取结果
    # （原先是按提交顺序 f.result，前面一条慢的会把后面已完成的卡住、白占 worker）。
    ex = ThreadPoolExecutor(max_workers=args.workers)
    futs = [ex.submit(_run, s) for s in probe]
    try:
        for f in as_completed(futs):
            if time.time() - t0 > args.budget:
                timed_out = True
                print(f"⚠️ 超出 {args.budget}s 时间预算，剩余体检取消（全部放行）")
                break
            try:
                results.append(f.result())
            except Exception as e:
                log.warning(f"体检异常（该源按放行处理）: {e}")
    finally:
        ex.shutdown(wait=False, cancel_futures=True)

    by_url = {r.get("url"): r for r in results}

    template_dates = detect_template_dates(results, min_days=HARD_ZOMBIE_DAYS)
    if template_dates:
        log.warning(f"疑似模板日期（同批 ≥3 次，整组放行）：{sorted(template_dates)}")

    hard_zombies, kept = [], []
    for s in probe:   # 只处理体检过的这一段，rest 原样追加（否则会重复计数）
        r = by_url.get(s.get("bookSourceUrl"))
        big = is_big_site(s.get("bookSourceUrl"))
        if (r and not big and r.get("evidence") == "sitemap"
                and r.get("days") is not None and r["days"] > HARD_ZOMBIE_DAYS
                and r.get("newest") not in template_dates):
            if args.drop_hard_zombie and not is_static(s.get("bookSourceName"), s.get("bookSourceUrl")):
                hard_zombies.append({"name": s.get("bookSourceName"),
                                     "url": s.get("bookSourceUrl"),
                                     "lastmod": r.get("newest"), "days": r["days"],
                                     "sitemap_urls": r.get("sitemap_urls")})
                continue
        if r:
            s = dict(s)
            s.setdefault("comment", "")
            tag = f"// 健康度:{r.get('verdict')}" + (f" 最后更新{r['newest']}" if r.get("newest") else "")
            if big:
                tag += " 大厂豁免"
            if "健康度:" not in (s.get("comment") or ""):
                s["comment"] = (s.get("comment") + " " + tag).strip()
        kept.append(s)

    os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".", exist_ok=True)
    dump_json(kept + rest, args.output)

    n_reach = sum(1 for r in results if r.get("reachable"))
    n_sm = sum(1 for r in results if r.get("sitemap_urls"))
    print(f"体检 {len(results)} 条：可达 {n_reach} / 有 sitemap {n_sm} / 硬僵尸 {len(hard_zombies)}")
    print(f"输出 {len(kept)+len(rest)} 条 → {args.output}")

    report = {
        "gate": "health",
        "input": len(data),
        "checked": len(results),
        "reachable": n_reach,
        "with_sitemap": n_sm,
        "hard_zombie": len(hard_zombies),
        "template_dates": sorted(template_dates),   # 疑似模板日期，已整组放行
        "dropped": len(hard_zombies),
        "output": len(kept) + len(rest),
        "dropped_items": [{"name": z["name"], "url": z["url"],
                           "lastmod": z.get("lastmod"), "days": z.get("days")}
                          for z in hard_zombies],
    }
    rp = args.report or os.path.join(os.path.dirname(os.path.abspath(args.output)) or ".",
                                     "health_gate_report.json")
    dump_json(report, rp)
    print(f"报告: {rp}")
    for z in hard_zombies[:20]:
        print(f"  剔除 {z['name']}  {z['url']}  最后更新 {z['lastmod']} ({z['days']}天前)")
    if timed_out:
        # 超预算时不再等线程池里那几个正在跑的请求（单站最坏 42s，10 worker 能把
        # 180s 预算拖成 240s+）。产物已落盘，直接跳过解释器退出时的线程 join。
        sys.stdout.flush(); sys.stderr.flush()
        os._exit(0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
