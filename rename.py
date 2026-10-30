#!/usr/bin/env python3
"""给所有书源起四字名"""
import json

sources = json.load(open("books.json", encoding="utf-8"))

# 按域名匹配四字名
NAMES = {
    # 大厂
    "qidian.com": "起点读书",
    "wtzw.com": "七猫小说",
    "reader.qq.com": "企鹅阅读",
    "jjwxc.net": "晋江文学",
    "snssdk.com": "番茄小说",
    "shuqi.com": "书旗小说",
    "faloo.com": "飞卢小说",
    "douban.com": "豆瓣阅读",
    "zongheng.com": "纵横中文",
    "17k.com": "一七小说",
    "ciweimao.com": "刺猬猫",
    "sfacg.com": "菠萝包",
    "wenku8.net": "轻文文库",
    "gongzicp.com": "长佩文学",
    "readnovel.com": "小说阅读",
    
    # 精品站
    "3rzw.com": "三Z小说",
    "51read.org": "五一阅读",
    "69shuba": "六九书吧",
    "yiqushuku": "一曲书屋",
    "xkushu": "三五中文",
    "bifengzw": "东流小说",
    "jjjjxs": "久久小说",
    "52shuku": "五二书库",
    "shuyuan6": "书苑小说",
    "qbxs.net": "全本小说",
    "ishubao": "唔爱书包",
    "guodusy": "国度书院",
    "yeshuku": "夜书库",
    "wcxsw": "大文无错",
    "ttks.tw": "天天小说",
    "tianyibook": "天翼文学",
    "kankezw": "奇书网",
    "qsw.la": "奇书网",
    "qishuta": "奇书网络",
    "min-yuan": "小原文学",
    "czbooks": "小说狂人",
    "kxwx.org": "开心文学",
    "silukexsw": "思路客",
    "isiluke": "思路客网",
    "uuwx.la": "悠悠文学",
    "laiksw": "拉看书",
    "sou78": "搜小说",
    "sou.com": "搜小说网",
    "banshanren": "搬山人",
    "zhaishulou": "摘书楼",
    "xwenxuem": "文学",
    "juzixs": "文学迷",
    "youshu.me": "新优书网",
    "dxs.tw": "新读小说",
    "longtimebook": "新龙小说",
    "niuloong": "新龙小说",
    "wuxianxs": "无限小说",
    "aishuge": "明月小说",
    "ewentai": "易文台",
    "wangshugu": "望书阁",
    "mengyuanshucheng": "梦远书城",
    "qiuxiaoshuo": "求小说",
    "lianyiwx": "涟漪文学",
    "yuzhaiwen": "燕子书屋",
    "ixdzs8": "爱下电子",
    "alicesw": "爱丽丝书屋",
    "23hh.la": "爱尚小说",
    "hh.la": "爱尚小说",
    "shuwu.org": "琦书网",
    "101kanshu": "电线看书",
    "kanshushi": "看书室",
    "xiumb.com": "秀书网",
    "qiufengshuwu": "秋风书屋",
    "zuohs.com": "笔下文学",
    "damaoli": "笔书阁",
    "biwenzhai": "笔文斋",
    "dxsw.com": "第三小说",
    "jhsssd": "精华书阁",
    "jhssd": "精华书阁",
    "2ksk.org": "精华书阁",
    "richvv": "精华书阁",
    "jpxs123": "精品小说",
    "hongyebookzhai": "红叶书斋",
    "mayiwxw": "蚂蚁文学",
    "xiguashuwu": "西瓜书屋",
    "xs8.cn": "言情小说",
    "dukesk": "读客书库",
    "shellbook": "贝壳读书",
    "susuzw": "速速小说",
    "23qb.com": "铅笔小说",
    "jianpan": "键盘小说",
    "sunzw.com": "阳光中文",
    "lingdxsw": "零点小说",
    "pilisf": "霹雳书坊",
    "ffxs.info": "饭饭小说",
    
    # 免费站
    "gb84.com": "精品阅读",
    "1qxs.com": "一七小说",
    "31xs.com": "三一小说",
    "jjjxsw": "久久小说",
    "sangshixs": "九九藏书",
    "shubaowang": "书包网",
    "56zw.com": "五六中文",
    "67ks.com": "六七看书",
    "qfxs123": "千凡小说",
    "ybsws.com": "夜伴书屋",
    "miaoshuzhai": "妙书斋",
    "xiaxs.la": "手机小说",
    "wenxinge": "文心阁",
    "99mk.info": "晚班小说",
    "huilingtian": "格格党",
    "shatanxs": "沙滩小说",
    "aixiawx": "爱下书",
    "dfu7.com": "爱久久",
    "iwurexs": "爱电子书",
    "zzs5.com": "猪猪书网",
    "xuankuge": "玄幻阁子",
    "3diyibanzhu": "第一版主",
    "shufahouse": "红叶书斋",
    "cupfox7": "茶杯狐",
    "xmayitxt": "蚂蚁阅读",
    "yqxxs.com": "言情小说",
    "yeudusk": "阅读书库",
    "ldxsw.co": "零点书屋",
    "feiyanqing": "飞言情",
    "xiang5.com": "香网",
    
    # 笔趣阁类
    "biqugej": "笔趣快眼",
    "bswtan": "笔趣笔1",
    "biqusa": "笔趣小说",
    "biquw": "笔趣网吧",
    "biqg8": "笔趣阁",
    "abcbiquge": "笔趣阁",
    "xbiquge": "笔趣阁",
    "biqule": "笔趣阁",
    "biqugege": "笔趣阁",
    "bequgew": "笔趣阁",
    "conglianhao": "笔趣阁",
    "biquge.casa": "笔趣阁",
    "biquge.one": "笔趣阁",
    "qbiqus": "笔趣阁",
    "bqquge": "笔趣阁",
    "biqusan": "笔趣阁",
    "bigee.cc": "笔趣阁",
    "bequgexs": "笔趣阁",
    "biquges.com": "笔趣阁",
    "ibiquges": "香书小说",
}

from urllib.parse import urlparse
import re

def host(u):
    try:
        h = urlparse(u.replace("＃","#")).netloc.lower()
        h = h.split("@")[-1].split(":")[0]
        h = re.sub(r"^(m|www|wap|api|webapp|app|h5|mobile)\d*\.", "", h)
        return h
    except: return ""

used = set()
for s in sources:
    h = host(s["bookSourceUrl"])
    name = None
    for key, n in NAMES.items():
        if key in h:
            name = n
            break
    if not name:
        name = s["bookSourceName"][:4]  # 兜底取前4字
    # 去重
    base = name
    i = 2
    while name in used:
        name = f"{base}{i}"
        i += 1
    used.add(name)
    s["bookSourceName"] = name

# 按customOrder排序
sources.sort(key=lambda x: (-x.get("customOrder",0), x.get("bookSourceName","")))

json.dump(sources, open("books.json","w",encoding="utf-8"), ensure_ascii=False, indent=2)

# 输出
for i, s in enumerate(sources, 1):
    print(f"{i:3}. {s['bookSourceName']:6} | {s['bookSourceGroup']}")
