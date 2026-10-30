#!/usr/bin/env python3
"""给所有书源加正文错别字/异体字修复规则"""
import json

sources = json.load(open("阅读书源_最终可用.json", encoding="utf-8"))

# 常见盗版书错别字/异体字修复对（格式：原字##正确字）
TYPO_FIX = """旳##的
嚿##会
咾##了
脿##脸
哋##地
丅##下
丄##上
骼##胳
鞡##拉
歩##步
県##县
図##图
圧##压
収##收
仮##假
抜##拔
両##两
剣##剑
剰##剩
勧##劝
営##营
広##广
弾##弹
総##总
様##样
桜##樱
処##处
関##关
険##险"""

for s in sources:
    rc = s.get("ruleContent", {})
    if not isinstance(rc, dict):
        rc = {}
    existing = rc.get("replaceRegex", "")
    if TYPO_FIX not in existing:
        rc["replaceRegex"] = existing + "\n" + TYPO_FIX
    s["ruleContent"] = rc

json.dump(sources, open("阅读书源_最终可用.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"已给 {len(sources)} 个源加了错别字修复规则")
print(f"共 {len(TYPO_FIX.split(chr(10)))} 组替换对")
