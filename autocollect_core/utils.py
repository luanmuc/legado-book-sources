# -*- coding: utf-8 -*-
"""
autocollect_core 工具模块
日志配置 + 通用工具函数
"""

import os
import re
import time
import json
import logging
import threading
import requests
import urllib3
from urllib.parse import urlparse

from .config import (
    BASE_DIR, REQUEST_TIMEOUT, REQUEST_RETRY, CONNECT_TIMEOUT,
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


# ============================================================
# 连接复用 + 绕过环境代理（2026-11-18 全仓审计后修）
# ============================================================
# 为什么必须 trust_env=False：云主机/Actions 环境普遍设了 HTTP_PROXY/HTTPS_PROXY，
# requests 默认读环境变量→所有请求经代理中转。而代理会：
#   1. 把国内小说站的大量请求拦成 404/超时（实测同一站 curl --noproxy 拿 200/8393B，
#      requests 走代理拿 404/138B —— 直接导致"连不上"误判率 56%）
#   2. 每次多一跳中转，实测批量请求慢 2.2 倍（10 站 8.5s vs 3.9s）
# GitHub API 已在 no_proxy 里，置 False 后仍走直连，不影响发版。
#
# 为什么用线程局部 Session：连接复用避免每次重新 TLS 握手。批量校验时
# 同一 host 会被反复请求（首页/搜索/详情/目录/正文），复用收益明显。

_thread_local = threading.local()


def _get_session():
    """每线程一个 Session（requests.Session 非线程安全，不能跨线程共享）"""
    sess = getattr(_thread_local, "session", None)
    if sess is None:
        sess = requests.Session()
        sess.trust_env = False                     # 绕开环境代理
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=32, pool_maxsize=64, max_retries=0)
        sess.mount("http://", adapter)
        sess.mount("https://", adapter)
        _thread_local.session = sess
    return sess


def fetch_url(url, timeout=REQUEST_TIMEOUT, retry=REQUEST_RETRY, session=None, headers=None):
    """带重试的请求，加反爬头；默认复用线程局部 Session（连接池 + 不读环境代理）

    session: 传入外部 Session（多 UA 轮试场景可自行控池）；None 用线程局部默认池
    headers: 覆盖默认头（换 UA 突破反爬时用）

    超时拆成 (connect, read)：连不上/域名不通的站在 3 秒内快速失败，
    不再空等整个 timeout。批量探活时死站占比很高（本次实测 120 条里 25%+），
    这一项能砍掉整轮相当大一块等待时间。
    """
    hdr = {
        "User-Agent": USER_AGENT,
        "Referer": REFERER,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"
    }
    if headers:
        hdr.update(headers)
    sess = session or _get_session()
    tmo = (CONNECT_TIMEOUT, timeout) if isinstance(timeout, (int, float)) else timeout
    for i in range(retry + 1):
        try:
            resp = sess.get(url, headers=hdr, timeout=tmo, verify=False)  # 跳过SSL验证，自签名证书不报错
            return resp
        except Exception as e:
            if i < retry:
                time.sleep(2)
            else:
                log.warning(f"请求失败: {url} - {e}")
                return None


# ============================================================
# JSON 落盘（统一 ensure_ascii=False + indent=2 + 原子写）
# ============================================================
# 全仓曾有 24 处重复 json.dump(..., ensure_ascii=False, indent=2)，
# 且都是「直接覆盖写」：写一半进程被杀会留下截断的 books.json。
# books.json 12.4MB，被 stage_daily / publish_flow / monthly_release / reorder
# 多处写入，一旦写坏，下游 json.load 全部崩（历史上已踩过一次）。

def load_json(path, default=None):
    """读 JSON：文件不存在或内容损坏都返回 default，不让一条坏文件打断链路"""
    if not path or not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        log.warning(f"JSON 损坏，按默认值处理: {path} - {e}")
        return default


def host_of(u):
    """域名归一化：去掉协议、路径、端口和移动版前缀。

    必须只有一份实现。历史上 health_gate/deep_gate 只去 www.，stage_daily 还去
    m/wap/mobile，导致 m.hongxiu.com 在门槛视图是 m.hongxiu.com（大厂豁免集合里
    是 hongxiu.com，匹配不上 → 被当普通站判死），在黑名单视图却是 hongxiu.com。
    红袖移动版就是这么被误删的。
    """
    h = (u or "").strip().split("//")[-1].split("/")[0].split("?")[0].lower()
    h = h.split(":")[0]
    return re.sub(r"^(www|m|wap|mobile)\.", "", h)


def dump_json(data, path, atomic=True, indent=2):
    """写 JSON：中文不转义 + 原子替换（先写 .tmp、fsync、再 rename）

    原子写保证「要么是旧完整文件，要么是新完整文件」，不会出现半截 JSON。
    流水线里被 kill / 磁盘打满时，普通 open("w") 会留下半截文件，下游 load_json
    直接抛错把整条链路带断——所以所有产物与断点都必须走这里。
    fsync 是必要的：rename 只保证目录项原子，不保证数据已刷到盘。
    """
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    body = json.dumps(data, ensure_ascii=False, indent=indent)
    if not atomic:
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
        return path
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(body)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)  # 同盘 rename 是原子操作
    return path


# ===== 上游合集的校验标记保留 =====

# 上游合集作者自己会做题、把结果写在分组名里：`校验可用`、`2026年11月07日搜索校验`、
# `🌹已检26.10.15`、`校验超时`、`【❌❌】搜索正文失-效`。这是别人拿真书试过的结论，
# 免费的质量信号。但整理阶段会按自己的规则重写 bookSourceGroup，这些标记一进正式版就没了。
# 实测 11-17 的 cleaned 里带标记的有 700+ 条，而 books.json 里一条都查不到——白扔了。
UPSTREAM_MARK_RE = re.compile(r"校验|验证|已检|失效|超时|❌")


def extract_upstream_marks(group):
    """从上游原始分组名里抽出校验/失效标记，最多 3 个（别把 comment 塞满）

    分组名长这样：`通常书源 📂,快速书源 ⚡`、`校验可用`、`【❌❌】搜索正文失-效,校验超时`
    按逗号/分号切开逐段判断，命中即整段保留（"2026年11月07日搜索校验"这种带日期的也要留住
    日期，不能只留"校验"两个字）。
    """
    if not group:
        return []
    marks = []
    for part in re.split(r"[,;，；]", str(group)):
        p = part.strip()
        if not p or not UPSTREAM_MARK_RE.search(p):
            continue
        if p not in marks:
            marks.append(p)
        if len(marks) >= 3:
            break
    return marks


def tag_upstream_marks(source):
    """把上游校验标记写进 comment，幂等（重复调用不会叠加）

    comment 已经是"源身上带说明"的公共通道（健康度门槛也往这里写 `// 健康度:xxx`），
    复用同一条通道，不新增字段，避免动 Legado 的书源结构。
    """
    marks = extract_upstream_marks(source.get("bookSourceGroup") or "")
    if not marks:
        return source
    tag = "// 上游:" + "|".join(marks)
    c = source.get("comment") or ""
    if tag in c:
        return source
    source["comment"] = (c + " " + tag).strip() if c.strip() else tag
    return source


def url_key(url):
    """比对用的 URL 归一化：在 clean_url 基础上抹平尾斜杠与大小写差异

    专用于「这两个 URL 是不是同一个源」的判断，不改变库里存的原始 URL。

    为什么需要：clean_url 只剔锚点/注释/非法字符，**不动尾斜杠**——
    `https://www.shuqi.com` 与 `https://www.shuqi.com/` 归一化后仍是两个值，
    于是同一个站能被当成两个源各进一次中间层。实测 2026-11-18 中间层 370 条
    里有 120 条（32%）的 URL 其实已在正式版，根因就是这里。
    """
    u = clean_url(url)
    if not u:
        return ""
    # 协议和 host 大小写不敏感；路径大小写敏感，不能整体 lower
    m = re.match(r"^(https?://)([^/]*)(.*)$", u, re.I)
    if m:
        scheme, netloc, rest = m.group(1).lower(), m.group(2).lower(), m.group(3)
        u = f"{scheme}{netloc}{rest}"
    return u.rstrip("/")
