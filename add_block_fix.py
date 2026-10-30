#!/usr/bin/env python3
"""加拆字/异体字屏蔽修复规则"""
import json

sources = json.load(open("阅读书源_最终可用.json", encoding="utf-8"))

# 常见拆字/形近字屏蔽修复
# 这些是某些盗版站对敏感字的处理方式，可以反向修复
BLOCK_FIX = """囗##国
囸##日
囝##女
囡##女
図##田
圀##国
压##压
墚##杀
弑##杀
戳##杀
兦##亡
亾##亡
叾##句
囙##因
囜##女
団##团
囤##屯
囥##亢
囦##水
囧##明
囨##不
囩##云
囪##囱
囫##狐
囬##回
园##元
囮##化
囯##国
囲##井
図##野
围##韦
囵##仑
囶##国
囷##禾
囸##日
囹##令
固##古
囻##反
囼##台
图##图
囿##有
圀##国
圁##言
圂##溷
圃##甫
圄##吾
圅##函
圆##员
圇##亶
圈##卷
圉##幸
圊##青
国##国
圌##垂
圍##韦
圎##员
圏##拳
圐##枯
圑##甫
園##袁
圓##员
圔##聿
圕##点
圖##图
團##專
圗##古
團##專
圙##掠
圚##回
圛##隶
圝##栾
圞##栾"""

# 去掉已经有的（避免重复）
added = 0
for s in sources:
    rc = s.get("ruleContent", {})
    if not isinstance(rc, dict):
        rc = {}
    existing = rc.get("replaceRegex", "")
    if BLOCK_FIX not in existing:
        rc["replaceRegex"] = existing + "\n" + BLOCK_FIX
        s["ruleContent"] = rc
        added += 1

json.dump(sources, open("阅读书源_最终可用.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"已给 {added} 个源加了拆字屏蔽修复规则")
