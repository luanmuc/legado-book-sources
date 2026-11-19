#!/usr/bin/env python3
"""
推送即发版：读当前 books.json / clean_rules.json，直接建 Release。

背景（2026-11-19）：仓库的两个 workflow 原本只有 schedule + workflow_dispatch，
推送不会触发任何流程，导致改了 books.json 后 Release 一直落后于仓库
（实测 v3.2.34 发版前 Release 停在 v3.2.33 / 1887 源，而仓库已是 1735 源）。
本脚本由 .github/workflows/auto-release.yml 在 books.json 变更时调用。

幂等：publisher.auto_publish 内部先比内容指纹，没变化直接跳过。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autocollect_core.publisher import auto_publish  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    books = json.load(open(os.path.join(ROOT, "books.json"), encoding="utf-8"))
    rules_path = os.path.join(ROOT, "clean_rules.json")
    rules = json.load(open(rules_path, encoding="utf-8")) if os.path.exists(rules_path) else []

    big = len([b for b in books if b.get("bookSourceGroup") == "大厂正版"])
    print(f"源 {len(books)} | 规则 {len(rules)} | 大厂 {big}")

    ok = auto_publish(len(books), big, mode="auto",
                      stats={"来源": "push 触发", "源数": len(books)})
    if not ok:
        print("::error::发版未完成（Release 未建成或 asset 不齐）")
        return 1
    print("发版完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
