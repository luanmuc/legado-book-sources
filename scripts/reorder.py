#!/usr/bin/env python3
"""整库顺序规整：大厂固定顺序 → 分组顺序 → 组内名字族自然排序，成人最末

用途：book.json 被任何批量操作（合并/剔除/改名）重排后，用它一键复原规范顺序。
大厂 12 个的顺序以 config.BIG_SITES 为准（手动调好的顺序，绝不能被名字排序覆盖）。

用法：
  python3 scripts/reorder.py            # 规整并保存
  python3 scripts/reorder.py --dry-run  # 只看变化
"""
import json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from autocollect_core.config import ADULT_GROUP, BIG_SITES, OUTPUT_FILE
from autocollect_core.utils import dump_json

GROUP_ORDER = ["大厂正版", "笔趣阁类", "玄幻武侠", "言情女频", "综合其他", ADULT_GROUP]


def _big_key(s):
    u = (s.get("bookSourceUrl") or "").rstrip("/")
    for i, x in enumerate(BIG_SITES):
        ou = x["url"].rstrip("/")
        if u == ou or u.startswith(ou):
            return i
    return 99


def _group_key(s):
    g = s.get("bookSourceGroup") or "综合其他"
    return GROUP_ORDER.index(g) if g in GROUP_ORDER else GROUP_ORDER.index("综合其他")


def _name_key(s):
    out = []
    for t in re.split(r"(\d+)", s.get("bookSourceName") or ""):
        out.append((0, int(t)) if (t.isascii() and t.isdigit()) else (1, t))
    return out


def reorder(sources):
    big = sorted([s for s in sources if s.get("bookSourceGroup") == "大厂正版"], key=_big_key)
    others = [s for s in sources if s.get("bookSourceGroup") != "大厂正版"]
    others.sort(key=lambda s: (_group_key(s), _name_key(s)))
    ordered = big + others
    for i, s in enumerate(ordered, 1):
        s["customOrder"] = i
    return ordered


def main():
    dry = "--dry-run" in sys.argv
    path = OUTPUT_FILE if os.path.isabs(OUTPUT_FILE) else os.path.join(ROOT, OUTPUT_FILE)
    data = json.load(open(path, encoding="utf-8"))
    before = {s.get("bookSourceUrl"): s.get("customOrder") for s in data}
    ordered = reorder(data)
    moved = sum(1 for s in ordered if before.get(s.get("bookSourceUrl")) != s.get("customOrder"))
    print(f"源数 {len(ordered)} | 顺序变动 {moved} 条")
    print("大厂顺序:", [s.get("bookSourceName") for s in ordered if s.get("bookSourceGroup") == "大厂正版"])
    adult = [s for s in ordered if s.get("bookSourceGroup") == ADULT_GROUP]
    if adult:
        print(f"成人组 {len(adult)} 个，位置 {adult[0]['customOrder']}-{adult[-1]['customOrder']}（最末）")
    if dry:
        print("dry-run，未写文件")
        return
    dump_json(ordered, path)  # 原子写
    print(f"✅ 已写入 {os.path.basename(path)}")


if __name__ == "__main__":
    main()
