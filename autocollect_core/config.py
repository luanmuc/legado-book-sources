# -*- coding: utf-8 -*-
"""
autocollect_core 配置模块
所有常量、数据源、路径配置统一在这里维护
"""

import os

# ============================================================
# 大厂正版源列表（单独保护，不被自动更新覆盖）
# ============================================================
BIG_SITES = [
    {"name": "起点中文", "url": "https://www.qidian.com"},
    {"name": "番茄小说", "url": "https://fanqienovel.com"},
    {"name": "创世中文", "url": "http://chuangshi.qq.com"},
    {"name": "红袖添香", "url": "https://hongxiua.com"},
    {"name": "书旗小说", "url": "https://www.shuqi.com/"},
    {"name": "QQ阅读", "url": "https://ubook.reader.qq.com/"},
    {"name": "纵横中文", "url": "https://m.zongheng.com"},
    {"name": "潇湘书院", "url": "https://www.xxsy.net"},
    {"name": "晋江文学", "url": "https://www.jjwxc.net"},
    {"name": "磨铁中文", "url": "http://api.motie.com"},
    {"name": "黑岩阅读", "url": "https://www.heiyan.com"},
    {"name": "刺猬猫", "url": "https://mm.sfacg.com"},
]

# ============================================================
# 测试关键词池
# ============================================================
QUICK_TEST_KEYWORD = "凡人修仙传"  # 快速过滤用
FULL_TEST_KEYWORDS = [
    "凡人修仙传", "斗破苍穹", "遮天", "完美世界", "诡秘之主",
    "剑来", "射雕英雄传", "知否知否", "三生三世十里桃花", "东宫"
]

# ============================================================
# 数据源配置
# ============================================================
DATA_SOURCES = {
    "yckceo_list": {
        "name": "yckceo书源列表",
        "base_url": "https://www.yckceo.com/yuedu/shuyuan/index.html",
        "enabled": True
    },
    "yckceo_heji": {
        "name": "yckceo书源合集",
        "base_url": "https://www.yckceo.com/yuedu/shuyuans/index.html",
        "enabled": True
    },
    # 大佬仓库（直链JSON）
    "gurus": [
        {"name": "酷安三舞313", "url": "https://legado.aoaostar.com/sources/2a1f129b.json"},
        {"name": "关耳女频", "url": "https://legado.aoaostar.com/sources/e3e5d620.json"},
        {"name": "XIU2精品", "url": "https://legado.aoaostar.com/sources/71e564f.json"},
        {"name": "shidahuilang GitHub", "url": "https://raw.githubusercontent.com/shidahuilang/shuyuan/shuyuan/legado3.json"},
    ],
    # 净化规则数据源
    "clean_rules_sources": [
        {"name": "nyasama 1200条净化", "url": "https://shuyuan.nyasama.net/shuyuan/e4a6f3324f10443a0018deba816852b3.json"},
    ]
}

# ============================================================
# 过滤规则：非小说类关键词
# ============================================================
NON_NOVEL_KEYWORDS = [
    "漫画", "听书", "影视", "视频", "动漫", "电影", "电视剧",
    "吾爱破解", "52pojie", "豆瓣", "知乎", "B站", "bilibili",
    "音乐", "电台", "广播", "游戏", "动漫", "漫画柜", "漫画台"
]

# ============================================================
# 请求配置
# ============================================================
REQUEST_TIMEOUT = 10
REQUEST_RETRY = 2
CONCURRENCY = 8
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
REFERER = "https://www.google.com/"

# ============================================================
# 路径配置（BASE_DIR = 仓库根目录，即 autocollect_core 的上一级）
# ============================================================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(BASE_DIR, "raw", "autocollect")
OUTPUT_FILE = os.path.join(BASE_DIR, "books.json")
CLEAN_RULES_FILE = os.path.join(BASE_DIR, "clean_rules.json")
REPORT_FILE = os.path.join(BASE_DIR, "collect_report.md")
LOG_FILE = os.path.join(BASE_DIR, "autocollect.log")
