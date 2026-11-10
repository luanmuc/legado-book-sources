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
import fcntl
import json
import logging
import os
import sys
from contextlib import contextmanager

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from autocollect_core.utils import clean_url  # noqa: E402
from autocollect_core.liveness import probe_many  # noqa: E402
from autocollect_core.cleaner import filter_junk_sources  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


@contextmanager
def pending_lock(pending_path):
    """中间层的排他写锁

    为什么需要：stage_daily 是「读 pending → 算新增 → 写 pending」的读改写，两个进程
    同时跑会互相覆盖（实测两组 20 条并发写 40 条，最后只剩 20 条）。
    探活用时很长，所以锁只包住最后的「重读 + 二次去重 + 写盘」临界区。
    """
    lock_path = pending_path + ".lock"
    fh = open(lock_path, "a+")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fh, fcntl.LOCK_UN)
        fh.close()


def load_json(path, default=None):
    """读 JSON；文件缺失/损坏都返回 default（由调用方决定是否致命）

    上游书源 JSON 是用户手工上传的，截断/半截文件很常见，不能让一个 json.load
    抛裸 traceback 就算失败——要么上层能降级，要么给出可读错误。
    """
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        log.error(f"JSON 解析失败（文件可能被截断）: {path} → {e}")
        return default


def main():
    ap = argparse.ArgumentParser(description="当天 cleaned 增量并入中间层（只新增、不复活）")
    ap.add_argument("--cleaned", required=True, help="当天清洗产物 weekly/cleaned_*.json")
    ap.add_argument("--formal", default=os.path.join(ROOT, "books.json"), help="正式版")
    ap.add_argument("--pending", default=os.path.join(ROOT, "books_pending.json"), help="中间层")
    ap.add_argument("--dry-run", action="store_true", help="只统计，不写盘")
    args = ap.parse_args()

    cleaned = load_json(args.cleaned)
    if not isinstance(cleaned, list) or not cleaned:
        log.error(f"cleaned 无效（不存在/损坏/不是数组）: {args.cleaned}")
        sys.exit(1)
    formal = load_json(args.formal, []) or []
    pending = load_json(args.pending, []) or []
    if not isinstance(formal, list) or not isinstance(pending, list):
        log.error("正式版或中间层不是数组结构，拒绝写入（避免把数据格式写坏）")
        sys.exit(1)

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
        # 临界区：加锁后重读一次 pending，按最新内容二次去重再写，
        # 避免另一个进程在我们探活期间已经写入了同一批源（读-改-写覆盖）
        with pending_lock(args.pending):
            fresh = load_json(args.pending, []) or []
            fresh_urls = {clean_url(x.get("bookSourceUrl") or "") for x in fresh}
            really_new = []
            for x in final_added:
                u = clean_url(x.get("bookSourceUrl") or "")
                if u and u not in fresh_urls:
                    fresh_urls.add(u)
                    really_new.append(x)
            with open(args.pending, "w", encoding="utf-8") as f:
                json.dump(list(fresh) + really_new, f, ensure_ascii=False, indent=2)
        result["pending_after"] = len(fresh) + len(really_new)
        result["added"] = len(really_new)
        log.info(f"中间层已更新: {len(fresh)} → {result['pending_after']}（本次 +{len(really_new)}）")

    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
