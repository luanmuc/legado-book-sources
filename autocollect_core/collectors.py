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


def parse_update_time(txt, now=None):
    """解析yckceo列表/合集页条目的更新时间（相对/绝对）为绝对时间；无法解析返回None"""
    now = now or datetime.now()
    txt = (txt or "").strip()
    m = re.match(r"(\d+)\s*分钟前", txt)
    if m:
        return now - timedelta(minutes=int(m.group(1)))
    m = re.match(r"(\d+)\s*小时前", txt)
    if m:
        return now - timedelta(hours=int(m.group(1)))
    m = re.match(r"(\d+)\s*天前", txt)
    if m:
        return now - timedelta(days=int(m.group(1)))
    m = re.match(r"(\d+)\s*个月前", txt)
    if m:
        return now - timedelta(days=30 * int(m.group(1)))
    m = re.match(r"(\d{1,2})/(\d{1,2})\s+(\d{1,2}):(\d{2})", txt)
    if m:
        mm, dd = int(m.group(1)), int(m.group(2))
        year = now.year
        if (mm, dd) > (now.month, now.day):  # 跨年边界：倒序列表不会出现未来日期
            year -= 1
        return datetime(year, mm, dd, int(m.group(3)), int(m.group(4)))
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", txt)
    if m:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def extract_update_times(html):
    """提取列表页每个条目的更新时间（顺序与id提取结果一一对应）"""
    return re.findall(r'<p class="m-right"[^>]*>([^<]+)</p>', html)


def filter_by_months(ids, times, months, now, label):
    """按更新时间过滤最近N个月内的条目；返回(保留ids, 是否整页均超范围)"""
    if months <= 0:
        return ids, False
    cutoff = now - timedelta(days=30 * months)
    kept, all_old = [], True
    for i, sid in enumerate(ids):
        dt = parse_update_time(times[i] if i < len(times) else "", now)
        if dt is None:
            kept.append(sid)  # 时间解析失败不误杀，保留
            continue
        if dt >= cutoff:
            kept.append(sid)
            all_old = False
    log.info(f"  {label}: 最近{months}个月过滤 {len(ids)}→{len(kept)} 个")
    return kept, all_old


def collect_yckceo_list(months=1, page_start=1, page_end=10):
    """采集yckceo书源列表：从列表页提取详情id，直接拼JSON链接下载
    page_start/page_end: 支持分段采集（默认只采前10页，用户指定范围）
    months: 只采集最近N个月内更新的书源（按更新时间过滤，超范围自动停止）
    """
    log.info("=== 采集yckceo书源列表 ===")
    if months > 0:
        log.info(f"目标月份范围: {' / '.join(m['label'] for m in get_target_months(months))}")
    all_sources = []

    base_url = "https://www.yckceo.com/yuedu/shuyuan/index.html"
    page = page_start
    max_pages = page_end
    now = datetime.now()

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

            # 按更新时间过滤最近N个月
            times = extract_update_times(html)
            kept_ids, all_old = filter_by_months(ids, times, months, now, f"列表第{page}页")
            if all_old:
                log.info(f"  第{page}页书源全部超过最近{months}个月，停止翻页")
                break
            if not kept_ids:
                break

            # 直接拼接JSON链接下载（id是一样的）
            for sid in kept_ids:
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


def collect_yckceo_heji(months=1, page_start=1, page_end=1):
    """采集yckceo书源合集：从合集列表页提取id，下载合集JSON
    page_start/page_end: 支持分段采集（默认只采第1页=最新100个合集，用户指定范围）
    months: 只采集最近N个月内更新的合集（按更新时间过滤，超范围自动停止）
    """
    log.info("=== 采集yckceo书源合集 ===")
    if months > 0:
        log.info(f"目标月份范围: {' / '.join(m['label'] for m in get_target_months(months))}")
    all_sources = []

    base_url = "https://www.yckceo.com/yuedu/shuyuans/index.html"
    page = page_start
    max_pages = page_end
    now = datetime.now()

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

            # 按更新时间过滤最近N个月
            times = extract_update_times(html)
            kept_ids, all_old = filter_by_months(ids, times, months, now, f"合集第{page}页")
            if all_old:
                log.info(f"  第{page}页合集全部超过最近{months}个月，停止翻页")
                break
            if not kept_ids:
                break

            # 下载每个合集（自动跟随302跳转到CDN）
            for cid in kept_ids:
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
