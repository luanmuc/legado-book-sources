#!/usr/bin/env python3
"""每日增量入库：把当天 cleaned 里「正式版与中间层都没有的新源」并入 books_pending.json

设计约束（用户明确要求）：
- 严格只新增、不复活：只读当天这一份 cleaned，绝不汇总历史池（历史池里含已淘汰的源）
- 只取 URL 既不在 books.json（正式版）也不在 books_pending.json（中间层）的源
- 采集池第一遍只做存活校验（quick）：只淘汰 404/410 与域名解析失败的明确死站；
  403/405（WAF 盾站）、429（限流）、5xx（临时故障）、超时/SSL 一律保留
- 中间层只追加、不重排：顺序整理与完整校验留到发布前一步

用法：
    python3 scripts/stage_daily.py --cleaned weekly/cleaned_20261110_004022.json
    python3 scripts/stage_daily.py --cleaned <file> --dry-run     # 只看会加多少，不写盘
"""
import argparse
import json
import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from autocollect_core.utils import clean_url  # noqa: E402
from autocollect_core.liveness import probe_many  # noqa: E402
from autocollect_core.cleaner import filter_junk_sources  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser(description="当天 cleaned 增量并入中间层（只新增、不复活）")
    ap.add_argument("--cleaned", required=True, help="当天清洗产物 weekly/cleaned_*.json")
    ap.add_argument("--formal", default=os.path.join(ROOT, "books.json"), help="正式版")
    ap.add_argument("--pending", default=os.path.join(ROOT, "books_pending.json"), help="中间层")
    ap.add_argument("--dry-run", action="store_true", help="只统计，不写盘")
    args = ap.parse_args()

    cleaned = load_json(args.cleaned)
    if not cleaned:
        log.error(f"cleaned 为空或不存在: {args.cleaned}")
        sys.exit(1)
    formal = load_json(args.formal, []) or []
    pending = load_json(args.pending, []) or []

    formal_urls = {clean_url(s.get("bookSourceUrl") or "") for s in formal}
    pending_urls = {clean_url(s.get("bookSourceUrl") or "") for s in pending}
    log.info(f"输入 cleaned {len(cleaned)} | 正式版 {len(formal)} | 中间层 {len(pending)}")

    # 1. 只留两份库里都没有的 URL（这是「不复活」的唯一闸门）
    new = []
    seen = set()
    for s in cleaned:
        u = clean_url(s.get("bookSourceUrl") or "")
        if not u or u in formal_urls or u in pending_urls or u in seen:
            continue
        seen.add(u)
        new.append(s)
    log.info(f"当天真正新增候选: {len(new)}")

    result = {
        "cleaned": len(cleaned),
        "formal": len(formal),
        "pending_before": len(pending),
        "new_candidates": len(new),
        "alive": 0,
        "added": 0,
        "dead": 0,
        "waf_or_unstable": 0,
        "junk": 0,
        "pending_after": len(pending),
    }
    if not new:
        print(json.dumps(result, ensure_ascii=False))
        return

    # 2. 采集池第一遍：只做存活校验。用统一判死口径（只淘汰 404/410 与域名不存在），
    #    不用 validators.quick —— 那套在云端跨洋网络下会把 403/超时全当死站（实测合格率掉到 27%）
    ok, dead, unknown = probe_many(new, timeout=6, workers=20)
    validated = ok + unknown
    result["alive"] = len(validated)
    result["dead"] = len(dead)
    result["waf_or_unstable"] = len(unknown)
    log.info(f"存活校验: 保留 {len(validated)}（其中 WAF/不稳定 {len(unknown)}）/ 明确死站 {len(dead)}")

    # 3. 垃圾过滤（只对新增源，绝不回头过滤中间层里已有的源）
    kept = filter_junk_sources(validated)
    result["junk"] = len(validated) - len(kept)

    # 4. 追加进中间层（保留原顺序，不打乱已有条目）
    added = [item.get("source", item) if isinstance(item, dict) else item for item in kept]
    existing_urls = {clean_url(s.get("bookSourceUrl") or "") for s in pending}
    final_added = []
    for s in added:
        u = clean_url(s.get("bookSourceUrl") or "")
        if u and u not in existing_urls:
            existing_urls.add(u)
            final_added.append(s)
    result["added"] = len(final_added)
    result["pending_after"] = len(pending) + len(final_added)

    if args.dry_run:
        log.info(f"[dry-run] 会新增 {len(final_added)} 个，中间层 {len(pending)} → {result['pending_after']}")
    else:
        with open(args.pending, "w", encoding="utf-8") as f:
            json.dump(pending + final_added, f, ensure_ascii=False, indent=2)
        log.info(f"中间层已更新: {len(pending)} → {result['pending_after']}（本次 +{len(final_added)}）")

    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
