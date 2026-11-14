#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每日采集的统计与摘要（从 auto-update.yml 的内联 heredoc 抽出）

原来这段逻辑写在 workflow 的 `python3 - <<'EOF'` 里，既不能本地测、也不能复用。
抽出来后：本地可跑、可加断言、workflow 只保留一行调用。

用法：
  python3 scripts/daily_summary.py stats     # 打印 raw 分片 + cleaned 统计（纯观测，不写盘）
  python3 scripts/daily_summary.py append    # 生成 weekly/daily_summary.json + 追加 history
"""
import glob
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    from autocollect_core.utils import dump_json, load_json
except ImportError:
    dump_json = load_json = None

# runner 是 UTC，直接用 now() 会差一天；统一用北京时间
CST = timezone(timedelta(hours=8))
HISTORY_KEEP = 120  # 历史行只保留最近 120 天


def _count_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return len(data) if isinstance(data, list) else None
    except Exception:
        return None


def stats():
    """打印 raw 合集分片与 weekly/cleaned 各文件的源数（不写盘）"""
    total = 0
    for f in sorted(glob.glob(os.path.join(ROOT, "raw", "autocollect", "heji", "*.json"))):
        n = _count_json(f)
        if n:
            total += n
    print(f"  合集分片合计: {total}")

    for f in sorted(glob.glob(os.path.join(ROOT, "weekly", "cleaned_*.json"))):
        n = _count_json(f)
        label = os.path.basename(f)
        print(f"  {label}: {n} 个清洗后源" if n is not None else f"  {label}: 读取失败")


def _domain(url):
    """从 URL 取域名，失败返回 None（上游 URL 常带装饰符，不能裸 split 崩）"""
    try:
        host = (url or "").split("//")[1].split("/")[0]
        return host or None
    except Exception:
        return None


def append():
    """生成 weekly/daily_summary.json，并追加一行到 daily_history.jsonl"""
    files = sorted(glob.glob(os.path.join(ROOT, "weekly", "cleaned_*.json")))
    if not files:
        print("没有 cleaned 产物，跳过摘要")
        return

    latest = files[-1]
    data = load_json(latest, default=None) if load_json else None
    if data is None:
        try:
            with open(latest, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"读取失败: {latest} - {e}")
            return

    groups = Counter((s.get("bookSourceGroup") or "未分组") for s in data)
    domains = Counter()
    for s in data:
        d = _domain(s.get("bookSourceUrl"))
        if d:
            domains[d] += 1

    summary = {
        "date": datetime.now(CST).strftime("%Y-%m-%d"),
        "file": os.path.basename(latest),
        "cleaned": len(data),
        "groups": dict(groups),
        "domains": len(domains),
    }

    out = os.path.join(ROOT, "weekly", "daily_summary.json")
    if dump_json:
        dump_json(summary, out)
    else:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

    hist = os.path.join(ROOT, "weekly", "daily_history.jsonl")
    os.makedirs(os.path.dirname(hist), exist_ok=True)
    with open(hist, "a", encoding="utf-8") as f:
        f.write(json.dumps({"date": summary["date"], "cleaned": summary["cleaned"],
                            "domains": summary["domains"]}, ensure_ascii=False) + "\n")

    # 裁掉超过 120 天的历史
    with open(hist, encoding="utf-8") as f:
        lines = [x for x in f.read().strip().split("\n") if x]
    if len(lines) > HISTORY_KEEP:
        with open(hist, "w", encoding="utf-8") as f:
            f.write("\n".join(lines[-HISTORY_KEEP:]) + "\n")

    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"
    if cmd == "stats":
        stats()
    elif cmd == "append":
        append()
    else:
        print(f"未知命令: {cmd}（可选 stats / append）")
        sys.exit(2)


if __name__ == "__main__":
    main()
