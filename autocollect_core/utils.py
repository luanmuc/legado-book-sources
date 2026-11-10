# -*- coding: utf-8 -*-
"""
autocollect_core 工具模块
日志配置 + 通用工具函数
"""

import os
import re
import time
import logging
import requests
import urllib3
from urllib.parse import urlparse

from .config import (
    BASE_DIR, REQUEST_TIMEOUT, REQUEST_RETRY,
    USER_AGENT, REFERER,
)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)  # 关SSL警告

# ============================================================
# 日志配置（落 logs/ 目录，仓库根不再放 autocollect.log）
# ============================================================
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
_LOG_FILE = os.path.join(LOG_DIR, "autocollect.log")
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(_LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)


# ============================================================
# 通用工具
# ============================================================

def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def clean_url(url):
    """清理URL：去掉锚点、非URL字符（中文注释等）、首尾空格

    类型守卫：上游书源 JSON 是用户手工上传的，bookSourceUrl 可能是数字/对象/None。
    非字符串一律视为「无有效 URL」返回空串，避免一条脏数据把整条清洗链路打崩。
    """
    if not url or not isinstance(url, str):
        return ""
    # 去掉锚点后面的内容
    url = re.sub(r'[#＃].*$', '', url)
    # 去掉首尾空格
    url = url.strip()
    # 剔除URL中的非URL字符：中文注释/全角符号/emoji/装饰符等
    # （上游数据 url 尾部常被手打 "已整理"、🔞、✔️2025-11-2、♤pb、♦ 之类的标记）
    # 除原有中文/全角/emoji 外，补上 U+2600-27BF（杂项符号+dingbats，含 ✔ ♤ ♦ ★）、
    # U+2B00-2BFF、U+FE00-FE0F（变体选择符，✔️ 中的 ️）——否则 "https://a.com/x✔️2025-11-2"
    # 只会被截成 "https://a.com/x✔️2025-11-2"，同一站点出现两个 URL 变体，去重失效
    m = re.match(r'^(https?://[^\s\u4e00-\u9fff\uff00-\uffef\u2600-\u27bf\u2b00-\u2bff\ufe00-\ufe0f\U0001F300-\U0010FFFF]+)', url)
    if m:
        url = m.group(1)
    return url


def get_domain(url):
    """提取域名（去www、去端口、小写）"""
    try:
        url = clean_url(url)
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        return domain
    except Exception:
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
