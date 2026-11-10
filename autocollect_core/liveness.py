#!/usr/bin/env python3
"""存活探活：全管道唯一判死口径（每日增量入库 / 每月合并共用）

为什么单独抽出来：
- 两个入口各写一份 probe 逻辑，口径必然漂移（审计已经踩过这个坑）；
- 判死必须只认**确定性证据**。云端 Actions 走美国出口访问国内站，延迟与超时完全不可靠
  （历史实测：跨洋跑真实性阶梯校验，合格率从 72% 掉到 27%），所以超时、连接失败、
  5xx 一律不能当死站。

判死规则（只这两类）：
1. HTTP 404 / 410 —— 站点明确不存在，与网络质量无关，跨洋也稳定
2. 域名解析不出来 —— 域名本身不存在

保留（unknown，不算死）：
- 403 / 405（WAF 盾站，用户硬约束「WAF 403 类不淘汰」）
- 429（限流）、5xx（临时故障）
- 超时、SSL 错误、代理隧道失败
- 代理环境下连不上但域名能解析（说明站可能活着，只是链路问题）
"""
import logging
import socket
import urllib.parse
import urllib3
import requests

urllib3.disable_warnings()
log = logging.getLogger(__name__)

UA = "Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36"


def probe_alive(source, timeout=6):
    """返回 "ok" / "dead" / "unknown"。unknown 一律按保留处理。"""
    url = (source.get("bookSourceUrl") if isinstance(source, dict) else "") or ""
    if not url.startswith("http"):
        return "unknown"
    host = urllib.parse.urlparse(url).hostname or ""

    try:
        r = requests.get(url, timeout=timeout, allow_redirects=True, verify=False,
                         headers={"User-Agent": UA})
        if r.status_code in (404, 410):
            return "dead"
        if r.status_code >= 500 or r.status_code in (403, 405, 429):
            return "unknown"
        return "ok" if r.status_code < 400 else "unknown"
    except requests.exceptions.ProxyError:
        # Actions / 本地都走代理：连不上统一表现为 ProxyError 502，分不清「域名死了」和「代理抽风」。
        # 因此用域名解析当判据：解析不出=明确死站；能解析=保留
        return _dns_verdict(host)
    except requests.exceptions.ConnectionError as e:
        msg = str(e).lower()
        # 连接层「确定连不上」才判死：域名解析失败 / 端口拒绝 / 主机不可达
        if any(k in msg for k in ("name or service not known", "nodename nor servname",
                                  "nameresolutionerror", "failed to resolve",
                                  "getaddrinfo failed", "errno -2", "errno -3", "errno -5",
                                  "connection refused", "newconnectionerror",
                                  "failed to establish a new connection",
                                  "network is unreachable", "no route to host")):
            return "dead"
        return "unknown"
    except Exception:
        return "unknown"


def _dns_verdict(host):
    if not host:
        return "unknown"
    try:
        socket.getaddrinfo(host, None)
        return "unknown"
    except socket.gaierror:
        return "dead"
    except Exception:
        return "unknown"


def probe_many(sources, timeout=6, workers=20):
    """并发探活，返回 (ok_list, dead_list, unknown_list)"""
    from concurrent.futures import ThreadPoolExecutor
    ok, dead, unknown = [], [], []
    if not sources:
        return ok, dead, unknown
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for src, verdict in zip(sources, ex.map(lambda s: probe_alive(s, timeout), sources)):
            {"ok": ok, "dead": dead, "unknown": unknown}[verdict].append(src)
    return ok, dead, unknown
