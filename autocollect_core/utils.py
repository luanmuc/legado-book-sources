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
    """清理URL：去掉锚点、非URL字符（中文注释等）、首尾空格"""
    if not url:
        return ""
    # 去掉锚点后面的内容
    url = re.sub(r'[#＃].*$', '', url)
    # 去掉首尾空格
    url = url.strip()
    # 剔除URL中的非URL字符：中文注释/全角符号等（如上游数据 url 尾部被手打"已整理"）
    m = re.match(r'^(https?://[^\s\u4e00-\u9fff\uff00-\uffef]+)', url)
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
