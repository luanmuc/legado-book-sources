# -*- coding: utf-8 -*-
"""
autocollect_core 采集模块（第一阶段）
yckceo书源列表 / yckceo书源合集 / 大佬仓库直链
"""

import json
import os
import re
import time
from datetime import datetime, timedelta

from .config import DATA_SOURCES, RAW_DIR
from .utils import ensure_dir, fetch_url, log


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
                    except Exception:
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
                    except Exception:
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
            except Exception:
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
