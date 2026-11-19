#!/usr/bin/env python3
"""
导出人工核验清单（可直接点击的 Markdown 链接）。

背景（2026-11-19 用户反馈）："你别做成文档，文档我咋点？你发到对话里边，
我直接点链接。" —— 大清单不要做成 HTML/文件，直接在对话里给 Markdown 链接，
点开即跳转，比打开文档再复制粘贴快得多。

用法:
    # 从截图批次里导出（默认读 groups16.json）
    python3 scripts/export_review_list.py --from-shots --group-size 10

    # 从 books.json 里按分组/关键词挑一批盲区源
    python3 scripts/export_review_list.py --from-books --hosts-file 待验.txt

输出:
    raw/autocollect/shots/groups<N>.json   含编号→URL 映射（供 apply_review_result 用）
    以及 stdout 的 Markdown 文本（直接粘到对话里）
"""
import argparse
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOTS = os.path.join(ROOT, "raw", "autocollect", "shots")
BOOKS = os.path.join(ROOT, "books.json")


def link(idx, url):
    disp = url.replace("https://", "").replace("http://", "").rstrip("/")
    return f"{idx}. [{disp}]({url})"


def emit(items, group_size, out_name):
    groups, cur = [], []
    for i, it in enumerate(items, 1):
        cur.append({"idx": i, **it})
        if len(cur) == group_size:
            groups.append({"g": len(groups) + 1, "items": cur})
            cur = []
    if cur:
        groups.append({"g": len(groups) + 1, "items": cur})

    os.makedirs(SHOTS, exist_ok=True)
    path = os.path.join(SHOTS, out_name)
    json.dump(groups, open(path, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"映射已存 → {path}（{len(items)} 条 / {len(groups)} 组）\n")

    lines = []
    for g in groups:
        lines.append(f"### 第 {g['g']} 组")
        for it in g["items"]:
            lines.append(link(it["idx"], it["url"]))
        lines.append("")
    print("\n".join(lines))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-shots", action="store_true")
    ap.add_argument("--from-books", metavar="PATTERN", nargs="?", const="*",
                    help="从 books.json 按分组/关键词名挑（默认全部）")
    ap.add_argument("--hosts-file", help="每行一个 URL 或域名")
    ap.add_argument("--group-size", type=int, default=10)
    ap.add_argument("--out", default="groups_review.json")
    args = ap.parse_args()

    if args.from_shots:
        p = os.path.join(SHOTS, "groups16.json")
        data = json.load(open(p, encoding="utf-8"))
        items = [{"url": it["u"], "t": it.get("t", "")}
                 for g in data for it in g["items"]]
        emit(items, args.group_size, args.out)
        return
    if args.from_books is not None:
        books = json.load(open(BOOKS, encoding="utf-8"))
        items = []
        if args.hosts_file:
            raw = [l.strip() for l in open(args.hosts_file, encoding="utf-8")
                   if l.strip() and not l.startswith("#")]
            keys = {k.split("//")[-1].split("/")[0].lower().removeprefix("www.")
                    for k in raw}
            items = [{"url": b["bookSourceUrl"],
                      "t": b.get("bookSourceName", "")} for b in books
                     if b["bookSourceUrl"].split("//")[-1].split("/")[0]
                     .lower().removeprefix("www.") in keys]
        else:
            pat = "" if args.from_books == "*" else args.from_books
            items = [{"url": b["bookSourceUrl"],
                      "t": b.get("bookSourceName", "")} for b in books
                     if pat in (b.get("bookSourceGroup") or "")]
        emit(items, args.group_size, args.out)
        return
    ap.error("需要 --from-shots 或 --from-books")


if __name__ == "__main__":
    main()
