# -*- coding: utf-8 -*-
"""
autocollect_core 报告模块（第五阶段）
生成完整采集报告 collect_report.md
"""

from collections import Counter
from datetime import datetime

from .config import REPORT_FILE
from .utils import log


def generate_report(raw_count, deduped_count, dead_sources, final_count, big_count):
    """生成采集报告"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 统计淘汰原因
    reason_counter = Counter()
    for d in dead_sources:
        reason = d.get("reason", "未知")
        reason_counter[reason] += 1

    top_reasons = reason_counter.most_common(5)
    reasons_text = ""
    for reason, count in top_reasons:
        reasons_text += f"- {reason}: {count} 个\n"
    if not reasons_text:
        reasons_text = "- 无\n"

    report = f"""# 书源采集报告

**采集时间：** {now}

## 统计

| 阶段 | 数量 |
|------|------|
| 原始采集 | {raw_count} |
| 去重过滤后 | {deduped_count} |
| 校验淘汰 | {len(dead_sources)} |
| 最终入库 | {final_count} |
| 其中大厂源 | {big_count} |

## 淘汰原因Top 5

{reasons_text}
---
*本报告由 autocollect.py 自动生成*
"""

    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write(report)

    log.info(f"报告已生成: {REPORT_FILE}")
