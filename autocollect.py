#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全自动书源采集脚本
功能：从多个数据源采集书源 → 清洗去重 → 校验 → 整理 → 合并到仓库

用法：
  python3 autocollect.py              # 完整流程
  python3 autocollect.py --collect    # 只采集
  python3 autocollect.py --validate   # 只校验
  python3 autocollect.py --merge      # 只合并整理
  python3 autocollect.py --months 2   # 采集最近2个月的
"""

import json
import os
import re
import sys
import time
import hashlib
import logging
import argparse
import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)  # 关SSL警告
from urllib.parse import urlparse
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============================================================
# 配置区
# ============================================================

# 大厂正版源列表（单独保护，不被自动更新覆盖）
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

# 测试关键词池
QUICK_TEST_KEYWORD = "凡人修仙传"  # 快速过滤用
FULL_TEST_KEYWORDS = [
    "凡人修仙传", "斗破苍穹", "遮天", "完美世界", "诡秘之主",
    "剑来", "射雕英雄传", "知否知否", "三生三世十里桃花", "东宫"
]

# 数据源配置
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

# 过滤规则：非小说类关键词
NON_NOVEL_KEYWORDS = [
    "漫画", "听书", "影视", "视频", "动漫", "电影", "电视剧",
    "吾爱破解", "52pojie", "豆瓣", "知乎", "B站", "bilibili",
    "音乐", "电台", "广播", "游戏", "动漫", "漫画柜", "漫画台"
]

# 请求配置
REQUEST_TIMEOUT = 10
REQUEST_RETRY = 2
CONCURRENCY = 8
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
REFERER = "https://www.google.com/"

# 路径配置
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.path.join(BASE_DIR, "raw", "autocollect")
OUTPUT_FILE = os.path.join(BASE_DIR, "books.json")
CLEAN_RULES_FILE = os.path.join(BASE_DIR, "clean_rules.json")
REPORT_FILE = os.path.join(BASE_DIR, "collect_report.md")

def collect_clean_rules():
    """采集各个大佬的净化规则"""
    log.info("=== 采集净化规则 ===")
    all_rules = []
    
    for source in DATA_SOURCES.get("clean_rules_sources", []):
        name = source["name"]
        url = source["url"]
        log.info(f"  采集 {name}...")
        
        resp = fetch_url(url, timeout=15)
        if resp and resp.status_code == 200:
            try:
                rules = resp.json()
                if isinstance(rules, list):
                    all_rules.extend(rules)
                    log.info(f"    成功: {len(rules)} 条")
            except:
                log.warning(f"    格式错误")
    
    log.info(f"净化规则采集完成，共 {len(all_rules)} 条")
    return all_rules

def optimize_clean_rules(rules):
    """优化净化规则：分组简化、合并同类、按优先级排序"""
    # 分组映射表
    group_map = {
        "禁词": "禁词过滤",
        "广告": "广告净化",
        "错字": "错字修正",
        "和谐": "和谐还原",
        "标点": "标点修正",
        "标题": "标题净化",
        "英语": "英语翻译",
        "冗余": "冗余清理",
        "修正": "内容修正",
        "排版": "排版优化",
        "清理": "内容清理",
        "净化": "内容清理",
        "星号": "格式修正",
        "格式": "格式修正",
        "转化": "内容清理",
        "通用": "通用净化",
    }
    
    # 分组优先级（order越小越先执行）
    group_priority = {
        "格式修正": 10,
        "广告净化": 20,
        "内容清理": 30,
        "冗余清理": 40,
        "排版优化": 50,
        "标点修正": 60,
        "错字修正": 70,
        "内容修正": 80,
        "和谐还原": 90,
        "禁词过滤": 100,
        "标题净化": 110,
        "英语翻译": 120,
        "通用净化": 15,
    }
    
    # 简化分组名
    for r in rules:
        old_group = r.get("group", "")
        new_group = "其他"
        for key, target in group_map.items():
            if key in old_group:
                new_group = target
                break
        r["group"] = new_group
    
    # 按分组优先级排序
    rules.sort(key=lambda x: group_priority.get(x["group"], 500))
    
    # 重新编号id
    for i, r in enumerate(rules):
        r["id"] = i + 1
    
    return rules

def generate_clean_rules(sources, collected_rules=None):
    """生成配套净化规则：采集的 + 通用的，合并去重优化"""
    log.info("=== 生成配套净化规则 ===")
    
    # 我自己写的通用规则（格式对齐官方）
    default_rules = [
        {
            "name": "通用-去除脚本标签",
            "group": "通用净化",
            "pattern": "<script[\\s\\S]*?</script>",
            "replacement": "",
            "isRegex": True,
            "isEnabled": True,
            "order": 1,
            "scopeContent": True,
            "scopeSource": False,
            "scopeTitle": False,
            "timeoutMillisecond": 3000
        },
        {
            "name": "通用-去除样式标签",
            "group": "通用净化",
            "pattern": "<style[\\s\\S]*?</style>",
            "replacement": "",
            "isRegex": True,
            "isEnabled": True,
            "order": 2,
            "scopeContent": True,
            "scopeSource": False,
            "scopeTitle": False,
            "timeoutMillisecond": 3000
        },
        {
            "name": "通用-去除广告文字",
            "group": "通用净化",
            "pattern": "下载APP|扫码阅读|关注公众号|点击加载全文|热门推荐|相关推荐|本章未完|点击下一章继续阅读",
            "replacement": "",
            "isRegex": True,
            "isEnabled": True,
            "order": 3,
            "scopeContent": True,
            "scopeSource": False,
            "scopeTitle": False,
            "timeoutMillisecond": 3000
        },
    ]
    
    # 合并采集的和默认的
    all_rules = []
    if collected_rules:
        all_rules.extend(collected_rules)
    all_rules.extend(default_rules)
    
    # 按pattern去重
    seen = set()
    unique_rules = []
    for r in all_rules:
        pattern = r.get("pattern", "")
        if pattern and pattern not in seen:
            seen.add(pattern)
            unique_rules.append(r)
    
    # 优化：分组简化、合并、排序
    optimized = optimize_clean_rules(unique_rules)
    
    # 保存
    with open(CLEAN_RULES_FILE, "w", encoding="utf-8") as f:
        json.dump(optimized, f, ensure_ascii=False, indent=2)
    
    log.info(f"净化规则生成完成，共 {len(optimized)} 条（采集{len(collected_rules or [])} + 通用{len(default_rules)}，去重优化后）")
    return optimized

# ============================================================
# 日志配置
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(BASE_DIR, "autocollect.log")),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ============================================================
# 工具函数
# ============================================================

def ensure_dir(path):
    os.makedirs(path, exist_ok=True)

def get_domain(url):
    """提取域名（去www、去端口、小写）"""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        return domain
    except:
        return url

def fetch_url(url, timeout=REQUEST_TIMEOUT, retry=REQUEST_RETRY):
    """带重试的请求，加反爬头"""
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": REFERER,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"
    }
    for i in range(retry + 1):
        try:
            resp = requests.get(url, headers=headers, timeout=timeout, verify=False)  # 跳过SSL验证，自签名证书不报错
            return resp
        except Exception as e:
            if i < retry:
                time.sleep(2)
            else:
                log.warning(f"请求失败: {url} - {e}")
                return None

def is_non_novel(source):
    """判断是否为非小说源"""
    name = source.get("bookSourceName", "").lower()
    url = source.get("bookSourceUrl", "").lower()
    for kw in NON_NOVEL_KEYWORDS:
        if kw.lower() in name or kw.lower() in url:
            return True
    return False

def is_big_site(source):
    """判断是否为大厂源（精确匹配，避免误判）"""
    url = source.get("bookSourceUrl", "")
    domain = get_domain(url)
    for big in BIG_SITES:
        big_domain = get_domain(big["url"])
        # 精确匹配 或者 是大厂域名的子域名
        if domain == big_domain or domain.endswith("." + big_domain):
            return True
    return False

# ============================================================
# 第一阶段：采集
# ============================================================

def get_target_months(months=2):
    """动态获取最近N个月的列表"""
    now = datetime.now()
    result = []
    for i in range(months):
        dt = now - timedelta(days=30 * i)
        result.append({
            "year": dt.year,
            "month": dt.month,
            "label": f"{dt.year}年{dt.month}月"
        })
    return result

def collect_yckceo_list(months=2):
    """采集yckceo书源列表：从列表页提取详情id，直接拼JSON链接下载"""
    log.info("=== 采集yckceo书源列表 ===")
    all_sources = []
    
    base_url = "https://www.yckceo.com/yuedu/shuyuan/index.html"
    page = 1
    max_pages = 20  # 爬前20页
    
    while page <= max_pages:
        try:
            resp = fetch_url(f"{base_url}?page={page}")
            if not resp or resp.status_code != 200:
                break
            
            html = resp.text
            # 从列表页提取详情页id：/yuedu/shuyuan/content/id/XXXX.html
            ids = re.findall(r'/yuedu/shuyuan/content/id/(\d+)\.html', html)
            if not ids:
                log.info(f"  第{page}页没有更多书源了")
                break
            
            log.info(f"  书源列表第{page}页，找到 {len(ids)} 个")
            
            # 直接拼接JSON链接下载（id是一样的）
            for sid in ids:
                json_url = f"https://www.yckceo.com/yuedu/shuyuan/json/id/{sid}.json"
                s_resp = fetch_url(json_url, timeout=8)
                if s_resp and s_resp.status_code == 200:
                    try:
                        data = s_resp.json()
                        if isinstance(data, list):
                            # 单个书源也是列表格式
                            for s in data:
                                if isinstance(s, dict) and s.get("bookSourceUrl"):
                                    all_sources.append(s)
                        elif isinstance(data, dict) and data.get("bookSourceUrl"):
                            all_sources.append(data)
                    except:
                        pass
                time.sleep(0.1)
            
            page += 1
            time.sleep(0.5)
            
        except Exception as e:
            log.warning(f"  第{page}页失败: {e}")
            break
    
    log.info(f"yckceo书源列表采集完成，共 {len(all_sources)} 个")
    return all_sources

def collect_yckceo_heji(months=2):
    """采集yckceo书源合集：从合集列表页提取id，下载合集JSON"""
    log.info("=== 采集yckceo书源合集 ===")
    all_sources = []
    
    base_url = "https://www.yckceo.com/yuedu/shuyuans/index.html"
    page = 1
    max_pages = 10  # 爬前10页合集
    
    while page <= max_pages:
        try:
            resp = fetch_url(f"{base_url}?page={page}")
            if not resp or resp.status_code != 200:
                break
            
            html = resp.text
            # 从合集列表页提取详情id：/yuedu/shuyuans/content/id/XXXX.html
            ids = re.findall(r'/yuedu/shuyuans/content/id/(\d+)\.html', html)
            if not ids:
                log.info(f"  第{page}页没有更多合集了")
                break
            
            log.info(f"  合集列表第{page}页，找到 {len(ids)} 个合集")
            
            # 下载每个合集（自动跟随302跳转到CDN）
            for cid in ids:
                json_url = f"https://www.yckceo.com/yuedu/shuyuans/json/id/{cid}.json"
                c_resp = fetch_url(json_url, timeout=15)
                if c_resp and c_resp.status_code == 200:
                    try:
                        sources = c_resp.json()
                        if isinstance(sources, list):
                            all_sources.extend(sources)
                            log.info(f"    合集{cid}: {len(sources)} 个")
                    except:
                        pass
                time.sleep(0.2)
            
            page += 1
            time.sleep(0.5)
            
        except Exception as e:
            log.warning(f"  合集列表第{page}页失败: {e}")
            break
    
    log.info(f"yckceo书源合集采集完成，共 {len(all_sources)} 个")
    return all_sources

def collect_gurus():
    """采集大佬仓库书源"""
    log.info("=== 采集大佬仓库 ===")
    all_sources = []
    for guru in DATA_SOURCES["gurus"]:
        if not guru["url"]:
            continue
        log.info(f"采集 {guru['name']}...")
        resp = fetch_url(guru["url"])
        if resp and resp.status_code == 200:
            try:
                data = resp.json()
                all_sources.extend(data)
                log.info(f"  {guru['name']}: {len(data)} 个")
            except:
                log.warning(f"  {guru['name']} 格式错误")
    log.info(f"大佬仓库采集完成，共 {len(all_sources)} 个")
    return all_sources

def collect_all(months=2):
    """采集所有启用的数据源"""
    ensure_dir(RAW_DIR)
    
    sources = []
    
    # yckceo书源列表
    if DATA_SOURCES.get("yckceo_list", {}).get("enabled", False):
        sources.extend(collect_yckceo_list(months))
    
    # yckceo书源合集
    if DATA_SOURCES.get("yckceo_heji", {}).get("enabled", False):
        sources.extend(collect_yckceo_heji(months))
    
    # 大佬仓库
    sources.extend(collect_gurus())
    
    # 保存原始数据
    raw_file = os.path.join(RAW_DIR, f"raw_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    with open(raw_file, "w", encoding="utf-8") as f:
        json.dump(sources, f, ensure_ascii=False, indent=2)
    
    log.info(f"采集完成，原始数据共 {len(sources)} 个源，保存到 {raw_file}")
    return sources

# ============================================================
# 第二阶段：清洗去重
# ============================================================

def clean_and_dedup(sources):
    """清洗和去重"""
    log.info("=== 开始清洗去重 ===")
    log.info(f"原始数据: {len(sources)} 个")
    
    # 1. 基础格式校验
    valid = []
    for s in sources:
        if not isinstance(s, dict):
            continue
        if not s.get("bookSourceUrl"):
            continue
        if not s.get("bookSourceName"):
            continue
        valid.append(s)
    log.info(f"格式校验通过: {len(valid)} 个")
    
    # 2. 按域名去重（保留字段最完整的）
    domain_map = {}
    for s in valid:
        domain = get_domain(s["bookSourceUrl"])
        # 计算字段完整度（字段越多越好）
        score = len([k for k, v in s.items() if v and v != ""])
        if domain not in domain_map or score > len([k for k, v in domain_map[domain].items() if v and v != ""]):
            domain_map[domain] = s
    
    deduped = list(domain_map.values())
    log.info(f"域名去重后: {len(deduped)} 个")
    
    # 3. 过滤非小说源
    novel_sources = [s for s in deduped if not is_non_novel(s)]
    log.info(f"过滤非小说后: {len(novel_sources)} 个")
    
    # 4. 规则完整性校验（按官方规范）
    valid_sources = []
    invalid_count = 0
    for s in novel_sources:
        if check_rule_integrity(s):
            valid_sources.append(s)
        else:
            invalid_count += 1
    log.info(f"规则完整性校验: 通过 {len(valid_sources)} 个，淘汰 {invalid_count} 个")
    
    return valid_sources

def check_rule_integrity(source):
    """按官方规范检查书源规则完整性"""
    # 必填字段检查
    required_fields = [
        "bookSourceUrl",
        "bookSourceName", 
        "searchUrl",
    ]
    for field in required_fields:
        if not source.get(field):
            return False
    
    # 规则对象检查
    rule_search = source.get("ruleSearch", {})
    rule_book_info = source.get("ruleBookInfo", {})
    rule_toc = source.get("ruleToc", {})
    rule_content = source.get("ruleContent", {})
    
    # 搜索规则必须有bookList和name
    if not rule_search.get("bookList"):
        return False
    if not rule_search.get("name"):
        return False
    
    # 详情规则必须有name和intro（至少有一个）
    if not rule_book_info.get("name") and not rule_book_info.get("intro"):
        return False
    
    # 目录规则必须有chapterList
    if not rule_toc.get("chapterList"):
        return False
    
    # 正文规则必须有content
    if not rule_content.get("content"):
        return False
    
    return True

# ============================================================
# 第三阶段：校验
# ============================================================

def quick_validate(source):
    """快速校验：首页可达性 + 搜索接口连通性"""
    url = source.get("bookSourceUrl", "")
    domain = get_domain(url)
    search_url = source.get("searchUrl", "")
    
    result = {
        "source": source,
        "domain": domain,
        "alive": False,
        "waf": False,
        "search_ok": False,
        "reason": ""
    }
    
    # 第一步：测试首页可达性
    try:
        resp = fetch_url(url, timeout=5)
        if resp is None:
            result["reason"] = "首页连接失败"
            return result
        
        if resp.status_code == 200:
            result["alive"] = True
        elif resp.status_code in [403, 405, 503]:
            result["waf"] = True  # WAF盾站，不淘汰
            result["alive"] = True
        elif resp.status_code == 404:
            result["reason"] = "首页404"
            return result
        else:
            result["alive"] = True
            
    except Exception as e:
        result["reason"] = f"首页请求异常"
        return result
    
    # 第二步：测试搜索接口连通性（简化版）
    if search_url and result["alive"]:
        try:
            # 从searchUrl提取实际请求地址
            # 格式通常是：/search?q=关键词 或者完整URL
            test_keyword = QUICK_TEST_KEYWORD
            
            # 构造测试URL
            if search_url.startswith("http"):
                test_url = search_url.replace("{{key}}", test_keyword).replace("searchKey", test_keyword)
            else:
                # 相对路径，拼接域名
                base = url.rstrip("/")
                path = search_url.split(",")[0]  # 取第一个逗号前的部分
                if path.startswith("/"):
                    test_url = base + path.replace("{{key}}", test_keyword)
                else:
                    test_url = base + "/" + path.replace("{{key}}", test_keyword)
            
            # 发测试请求
            s_resp = fetch_url(test_url, timeout=8)
            if s_resp and s_resp.status_code == 200:
                # 看看返回内容是不是正常（不是空的，不是错误页）
                content = s_resp.text
                if len(content) > 100:  # 至少有内容
                    result["search_ok"] = True
                else:
                    result["reason"] = "搜索返回内容太少"
            elif s_resp and s_resp.status_code in [403, 405]:
                result["search_ok"] = True  # WAF站搜索接口可能也被挡，但不淘汰
            else:
                result["reason"] = f"搜索接口{ s_resp.status_code if s_resp else '失败' }"
                
        except Exception as e:
            result["reason"] = f"搜索测试异常"
            # 搜索测试失败不直接淘汰，首页活着就留着
            result["search_ok"] = False
    else:
        result["search_ok"] = result["alive"]  # 没有searchUrl的，首页活着就算过
    
    return result

def full_validate(source):
    """完整校验：多关键词搜索测试"""
    search_url = source.get("searchUrl", "")
    url = source.get("bookSourceUrl", "")
    
    # 没有搜索规则的，直接不通过
    if not search_url:
        return {"source": source, "pass_rate": 0.0, "keywords_pass": 0}
    
    keywords_pass = 0
    test_keywords = FULL_TEST_KEYWORDS[:3]  # 先测3个关键词，够了
    
    for kw in test_keywords:
        try:
            # 构造搜索URL
            if search_url.startswith("http"):
                test_url = search_url.replace("{{key}}", kw).replace("searchKey", kw)
            else:
                base = url.rstrip("/")
                path = search_url.split(",")[0]
                if path.startswith("/"):
                    test_url = base + path.replace("{{key}}", kw)
                else:
                    test_url = base + "/" + path.replace("{{key}}", kw)
            
            resp = fetch_url(test_url, timeout=6)
            if resp and resp.status_code == 200 and len(resp.text) > 200:
                keywords_pass += 1
        except:
            pass
    
    pass_rate = keywords_pass / len(test_keywords) if test_keywords else 0
    return {
        "source": source,
        "pass_rate": pass_rate,
        "keywords_pass": keywords_pass
    }

def validate_sources(sources):
    """批量校验：两级过滤"""
    log.info("=== 开始校验 ===")
    log.info(f"待校验: {len(sources)} 个")
    
    # 第一遍：快速过滤
    log.info("第一遍：快速过滤（首页+搜索接口连通性）...")
    quick_results = []
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
        futures = {executor.submit(quick_validate, s): s for s in sources}
        for future in as_completed(futures):
            result = future.result()
            quick_results.append(result)
    
    alive_sources = [r for r in quick_results if r["alive"]]
    dead_sources = [r for r in quick_results if not r["alive"]]
    log.info(f"快速过滤: 存活 {len(alive_sources)} 个，淘汰 {len(dead_sources)} 个")
    
    # 第二遍：完整校验（多关键词搜索测试）
    log.info("第二遍：完整校验（3个关键词搜索测试）...")
    full_results = []
    low_pass = []
    for r in alive_sources:
        full_r = full_validate(r["source"])
        # 通过率低于30%的，标记为低质量
        if full_r["pass_rate"] >= 0.3:
            full_results.append(full_r)
        else:
            low_pass.append({"source": r["source"], "reason": f"搜索通过率低({full_r['pass_rate']*100:.0f}%)"})
    
    dead_sources.extend(low_pass)
    log.info(f"完整校验: 合格 {len(full_results)} 个，淘汰低质量 {len(low_pass)} 个")
    
    # 按通过率排序
    full_results.sort(key=lambda x: x["pass_rate"], reverse=True)
    
    return full_results, dead_sources

# ============================================================
# 第四阶段：整理（改名、分组、排序）
# ============================================================

def generate_chinese_name(source, used_names):
    """生成四字纯汉字名称"""
    original = source.get("bookSourceName", "")
    # 去掉表情和特殊字符
    clean = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9]', '', original)
    # 提取中文部分
    chinese = re.findall(r'[\u4e00-\u9fa5]+', clean)
    if chinese:
        name = "".join(chinese)[:4]
    else:
        # 没有中文就用域名首字母转拼音（简化处理）
        domain = get_domain(source.get("bookSourceUrl", ""))
        name = "书源" + domain[:2].upper()
    
    # 确保是纯汉字
    if not re.match(r'^[\u4e00-\u9fa5]+$', name):
        name = "小说站" + str(len(used_names) % 10)
    
    # 去重
    base_name = name
    i = 2
    while name in used_names:
        # 加一个字区分
        suffix = ["阁", "楼", "斋", "居", "轩", "苑", "堂", "馆"][len(used_names) % 8]
        name = base_name[:3] + suffix
        if name in used_names:
            name = base_name[:2] + suffix + str(i)
        i += 1
    
    used_names.add(name)
    return name

def classify_source(source):
    """分类：大厂/笔趣阁/玄幻/言情/综合"""
    url = source.get("bookSourceUrl", "")
    name = source.get("bookSourceName", "")
    group = source.get("bookSourceGroup", "")
    
    if is_big_site(source):
        return "大厂正版"
    
    domain = get_domain(url)
    
    # 笔趣阁类
    biquge_keywords = ["biquge", "笔趣", "bqg", "藏花阁", "飘天文学", "小说阅读网"]
    for kw in biquge_keywords:
        if kw in domain.lower() or kw in name.lower():
            return "笔趣阁类"
    
    # 言情女频类
    romance_keywords = ["言情", "女频", "耽美", "晋江", "红袖", "潇湘", "花语女生"]
    for kw in romance_keywords:
        if kw in name.lower() or kw in group.lower() or kw in domain.lower():
            return "言情女频"
    
    # 玄幻武侠类
    xuanhuan_keywords = ["玄幻", "武侠", "修真", "修仙", "奇幻"]
    for kw in xuanhuan_keywords:
        if kw in name.lower() or kw in group.lower():
            return "玄幻武侠"
    
    return "综合其他"

def organize_sources(validated_sources, existing_sources):
    """整理：改名、分组、排序（大厂源强制保护，不被新采集覆盖）"""
    log.info("=== 开始整理 ===")
    
    used_names = set()
    result = []
    custom_order = 1
    
    # 1. 大厂源：强制从现有仓库拿，新采集的一律跳过不覆盖
    big_sites = [s for s in existing_sources if is_big_site(s)]
    log.info(f"大厂源: {len(big_sites)} 个（强制保护，保留手动调好的配置）")
    
    for s in big_sites:
        s["customOrder"] = custom_order
        custom_order += 1
        used_names.add(s.get("bookSourceName", ""))
        result.append(s)
    
    # 2. 其他源：新采集的，跳过所有大厂域名（避免重复）
    other_sources = []
    skipped_big = 0
    for r in validated_sources:
        s = r["source"]
        if is_big_site(s):
            skipped_big += 1
            continue
        other_sources.append(s)
    
    if skipped_big > 0:
        log.info(f"跳过新采集的大厂源: {skipped_big} 个（不覆盖手动调好的版本）")
    log.info(f"其他源: {len(other_sources)} 个")
    
    # 按分组排序
    groups = {"笔趣阁类": [], "玄幻武侠": [], "言情女频": [], "综合其他": []}
    for s in other_sources:
        group = classify_source(s)
        if group in groups:
            groups[group].append(s)
        else:
            groups["综合其他"].append(s)
    
    for group_name in ["笔趣阁类", "玄幻武侠", "言情女频", "综合其他"]:
        for s in groups[group_name]:
            # 改名
            new_name = generate_chinese_name(s, used_names)
            s["bookSourceName"] = new_name
            s["customOrder"] = custom_order
            custom_order += 1
            result.append(s)
    
    log.info(f"整理完成，共 {len(result)} 个源")
    return result

# ============================================================
# 第五阶段：报告生成
# ============================================================

def generate_report(raw_count, deduped_count, dead_sources, final_count, big_count):
    """生成采集报告"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # 统计淘汰原因
    from collections import Counter
    reason_counter = Counter()
    for d in dead_sources:
        reason = d.get("reason", "未知")
        reason_counter[reason] += 1
    
    top_reasons = reason_counter.most_common(5)
    reasons_text = ""
    for reason, count in top_reasons:
        reasons_text += f"- {reason}: {count} 个\n"
    
    # 统计分组
    # 这里简化，后面可以加
    
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

# ============================================================
# 主流程
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="全自动书源采集脚本")
    parser.add_argument("--collect", action="store_true", help="只执行采集")
    parser.add_argument("--validate", action="store_true", help="只执行校验")
    parser.add_argument("--merge", action="store_true", help="只执行合并整理")
    parser.add_argument("--months", type=int, default=2, help="采集最近N个月的（默认2）")
    args = parser.parse_args()
    
    log.info("=" * 50)
    log.info("全自动书源采集脚本 启动")
    log.info("=" * 50)
    
    # 加载现有书源
    existing = []
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            existing = json.load(f)
        log.info(f"加载现有书源: {len(existing)} 个")
    
    # 第一阶段：采集
    if not args.validate and not args.merge:
        raw_sources = collect_all(months=args.months)
    else:
        # 从raw目录加载最近的
        raw_files = sorted([f for f in os.listdir(RAW_DIR) if f.startswith("raw_")], reverse=True)
        if raw_files:
            with open(os.path.join(RAW_DIR, raw_files[0]), "r", encoding="utf-8") as f:
                raw_sources = json.load(f)
        else:
            raw_sources = []
    
    # 第二阶段：清洗去重
    if not args.validate and not args.merge:
        cleaned = clean_and_dedup(raw_sources)
    else:
        cleaned = raw_sources
    
    # 第三阶段：校验
    if not args.merge:
        validated, dead = validate_sources(cleaned)
    else:
        validated = [{"source": s, "pass_rate": 1.0} for s in cleaned]
        dead = []
    
    # 第四阶段：整理合并
    if not args.collect and not args.validate:
        final_sources = organize_sources(validated, existing)
        
        # 保存书源
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(final_sources, f, ensure_ascii=False, indent=2)
        
        # 采集大佬净化规则 + 生成配套净化规则
        collected_rules = collect_clean_rules()
        generate_clean_rules(final_sources, collected_rules)
        
        # 生成报告
        big_count = len([s for s in final_sources if is_big_site(s)])
        generate_report(len(raw_sources), len(cleaned), dead, len(final_sources), big_count)
        
        log.info("=" * 50)
        log.info(f"全部完成！最终书源: {len(final_sources)} 个")
        log.info(f"输出文件: {OUTPUT_FILE}")
        log.info("=" * 50)

if __name__ == "__main__":
    main()
