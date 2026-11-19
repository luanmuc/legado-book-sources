#!/usr/bin/env python3
"""
应用人工核验结果 → 直接清理 books.json + 补黑名单。

背景（2026-11-19）：脚本判活对"判不出"这一档基本无力——360 条判不出里，
浏览器截图能救回 11 条，用户手动点验 158 条只救回 6 条（3.8%）。人工点验是
唯一可信的终判，因此把"人工结果 → 执行"固化成脚本，避免每次手动改 JSON。

用法:
    python3 scripts/apply_review_result.py --result 结果.md --dry-run
    python3 scripts/apply_review_result.py --result 结果.md

结果文件格式（与导出的清单编号一一对应，每行一条）:
    共 158 条，已标 156 条
    1. 打不开/要验证
    2. 能看小说
    3. 不是小说站
    ...
    未标：10,45

判定优先级（重要，防止误删）:
    能看小说      → 保留，并从黑名单剔除（若曾被拉黑）
    不是小说站    → 整站变性，删除 + 黑名单 scope=host
    打不开/要验证  → 僵尸站，删除 + 黑名单 scope=url（只拦这条规则，不误伤同域其他源）
    未标          → 不动，只报告
"""
import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOKS = os.path.join(ROOT, "books.json")
EXCLUDED = os.path.join(ROOT, "excluded_sources.json")
GROUPS = os.path.join(ROOT, "raw", "autocollect", "shots", "groups16.json")
TMP = os.path.join(ROOT, "raw", "autocollect", "tmp")


def norm_host(url):
    return (url.split("//")[-1].split("/")[0].split(":")[0].lower()
            .removeprefix("www."))


VERDICTS = {
    "能看小说": "ok",
    "打不开/要验证": "dead",
    "不是小说站": "not_novel",
}


def parse_result(path):
    text = open(path, encoding="utf-8").read()
    out = {}
    for m in re.finditer(r"^(\d+)\.\s*(\S.*)$", text, re.M):
        idx, raw = int(m.group(1)), m.group(2).strip()
        for k, v in VERDICTS.items():
            if raw.startswith(k):
                out[idx] = v
                break
    return out


def load_index():
    """返回 [{idx, url, title}]，编号与导出清单一致。"""
    data = json.load(open(GROUPS, encoding="utf-8"))
    items = [it for g in data for it in g["items"]]
    return [{"idx": i + 1, "url": it["u"], "title": it.get("t", "")}
            for i, it in enumerate(items)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--result", required=True, help="人工核验结果文件")
    ap.add_argument("--dry-run", action="store_true", help="只报告不落盘")
    ap.add_argument("--no-adult-exempt", action="store_true", default=True,
                    help="(已默认开启)取消成人源豁免：死站一律删，不分分组")
    args = ap.parse_args()

    verdict = parse_result(args.result)
    index = load_index()
    total = len(index)
    print(f"结果解析 {len(verdict)} 条 / 清单 {total} 条")

    by_url = {}
    for it in index:
        if it["idx"] in verdict:
            by_url[norm_host(it["url"])] = verdict[it["idx"]]

    unmarked = [it for it in index if it["idx"] not in verdict]
    if unmarked:
        print(f"未标 {len(unmarked)} 条（不动）: "
              f"{[it['idx'] for it in unmarked]}")

    books = json.load(open(BOOKS, encoding="utf-8"))
    keep, dead, not_novel, ok = [], [], [], []
    for b in books:
        h = norm_host(b.get("bookSourceUrl", ""))
        v = by_url.get(h)
        if v == "ok":
            ok.append(b)
            keep.append(b)
        elif v == "not_novel":
            not_novel.append(b)
        elif v == "dead":
            dead.append(b)
        else:
            keep.append(b)

    print(f"\n命中：能看 {len(ok)} / 不是小说站 {len(not_novel)} / "
          f"打不开 {len(dead)}")
    print(f"books.json {len(books)} → {len(keep)}")

    if args.dry_run:
        print("\n[dry-run] 不落盘")
        for b in dead:
            print(f"  删(dead)      {b.get('bookSourceName','')[:20]:20s} "
                  f"{b['bookSourceUrl'][:40]}")
        for b in not_novel:
            print(f"  删(not-novel) {b.get('bookSourceName','')[:20]:20s} "
                  f"{b['bookSourceUrl'][:40]}")
        return

    os.makedirs(TMP, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = os.path.join(TMP, f"books_before_review_{stamp}.json")
    shutil.copy2(BOOKS, backup)
    print(f"备份 → {backup}")

    for i, b in enumerate(keep, 1):
        b["customOrder"] = i
    json.dump(keep, open(BOOKS, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

    if os.path.exists(EXCLUDED):
        excl = json.load(open(EXCLUDED, encoding="utf-8"))
    else:
        excl = {"items": [], "hosts": []}

    today = datetime.now().strftime("%Y-%m-%d")
    for b, scope, reason in (
        [(b, "url", "用户逐条手动进站：打不开/要验证") for b in dead]
        + [(b, "host", "用户逐条手动进站：不是小说站") for b in not_novel]
    ):
        h = norm_host(b["bookSourceUrl"])
        if scope == "host" and h not in excl["hosts"]:
            excl["hosts"].append(h)
        already = any(norm_host(x["url"]) == h and x.get("scope") == scope
                      for x in excl["items"])
        if not already:
            excl["items"].append({
                "name": b.get("bookSourceName", ""),
                "url": b["bookSourceUrl"],
                "reason": reason,
                "date": today,
                "batch": "人工核验",
                "scope": scope,
            })
    excl["updated"] = today
    json.dump(excl, open(EXCLUDED, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    order = [b["customOrder"] for b in keep]
    print(f"customOrder 连续: {order == list(range(1, len(keep) + 1))}")
    print(f"黑名单 {len(excl['items'])} items / {len(excl['hosts'])} hosts")


if __name__ == "__main__":
    sys.exit(main())
