# -*- coding: utf-8 -*-
"""
autocollect_core 发布模块
git提交推送 + GitHub Release发布页更新
"""

import os
import re
import subprocess
from datetime import datetime

import requests

from .config import CLEAN_RULES_FILE, OUTPUT_FILE, REPORT_FILE
from .utils import log


REPO = "luanmuc/legado-book-sources"


def get_next_release_tag(token):
    """从GitHub现有Releases取最新 vX.Y.Z tag，patch+1 作为新版本号（v3.2.7 → v3.2.8）

    用户要求（2026-11-05）：每次发布都到发布页发布一个新版本，不再覆盖旧tag。
    """
    api = f"https://api.github.com/repos/{REPO}/releases"
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}
    try:
        resp = requests.get(api, headers=headers, timeout=15)
        if resp.status_code == 200:
            tags = [r["tag_name"] for r in resp.json()
                    if re.match(r"^v\d+\.\d+\.\d+$", r.get("tag_name", ""))]
            if tags:
                latest = sorted(tags, key=lambda t: [int(x) for x in t[1:].split(".")])[-1]
                major, minor, patch = [int(x) for x in latest[1:].split(".")]
                return f"v{major}.{minor}.{patch + 1}"
    except Exception as e:
        log.warning(f"读取最新Release失败，回退 v1.0.0: {e}")
    return "v1.0.0"


def get_latest_release(token):
    """取最新 Release（用于中断恢复判定）"""
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}
    try:
        r = requests.get(f"https://api.github.com/repos/{REPO}/releases/latest",
                         headers=headers, timeout=15)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        log.warning(f"读取最新Release失败: {e}")
    return None


def is_partial_release(release):
    """判断最新 Release 是否为上一次发布中断的残留（用户要求：所有中断都能接上）

    中断特征：books.json / clean_rules.json 任一缺失，或存在但大小为 0（上传未完成）。
    命中则复用该版本补齐 assets，而不是再开一个新版本（避免产生空壳版本）。
    """
    if not release:
        return False
    assets = {a.get("name"): a for a in release.get("assets", [])}
    for name in ("books.json", "clean_rules.json"):
        a = assets.get(name)
        if not a or int(a.get("size") or 0) <= 1:
            return True
    return False


def get_github_token():
    """获取GitHub token：优先环境变量，其次从git remote提取（不写死在代码里）"""
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        return token
    try:
        r = subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True, text=True)
        m = re.search(r"https://[^:]+:([^@]+)@", r.stdout)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


def build_release_meta(tag, final_count, rules_count, mode="manual", stats=None):
    """生成发布页标题与说明：自动版 / 手动版明确区分，便于下载时自行选择"""
    stats = stats or {}
    if mode == "auto":
        title = f"【自动】{tag} · {final_count} 源"
        body = (f"**自动发布**（云端定时任务，{datetime.now().strftime('%Y-%m-%d')}）\n\n"
                f"- 书源总数：**{final_count}** 个纯小说源\n"
                f"- 净化规则：{rules_count} 条\n"
                f"- 大厂正版：{stats.get('big_sites', 12)} 个（顺序固定）\n\n"
                f"**校验口径：只判域名存活**\n"
                f"明确死站（DNS 失败 / 连接被拒 / 4xx / 5xx）已剔除；"
                f"响应超时与代理异常的源一律保留。\n"
                f"内容真实性（搜索/发现能否解析出书）**未校验**——这一步只有国内网络能判。\n\n"
                f"如果你要的是已验证可用的源，请选标题不带【自动】的版本。")
    else:
        title = f"{tag} · {final_count} 源（完整校验）"
        body = (f"**手动发布**（国内网络完整校验，{datetime.now().strftime('%Y-%m-%d')}）\n\n"
                f"- 书源总数：**{final_count}** 个纯小说源\n"
                f"- 净化规则：{rules_count} 条\n"
                f"- 大厂正版：{stats.get('big_sites', 12)} 个（顺序固定）\n\n"
                f"**校验口径：域名存活 + 内容真实性**\n"
                f"每个源用 3 个通用关键词真实请求，搜索或发现至少一项能解析出书才保留；"
                f"连续两个关键词 200 却解析不出才判失效，单次 200 其余超时按待验保留。")
    if stats.get("note"):
        body += f"\n\n{stats['note']}"
    if stats:
        lines = []
        for k, label in (("raw", "采集原始"), ("cleaned", "清洗后"), ("candidates", "去重候选"),
                         ("dead_removed", "死站剔除"), ("net_added", "净增")):
            if stats.get(k) is not None:
                lines.append(f"- {label}：{stats[k]}")
        if lines:
            body += "\n\n**本批统计**\n" + "\n".join(lines)
    return title, body


def publish_release(token, final_count, rules_count, mode="manual", stats=None):
    """发布/更新GitHub Release，上传 books.json 和 clean_rules.json 到发布页

    版本策略（用户要求 2026-11-05）：每次发布都创建新版本 tag（vX.Y.Z patch+1），
    不再覆盖旧tag；若目标tag恰好存在则更新其assets（历史tag内容保持最新）。

    发布来源区分（用户要求 2026-11-07）：mode="auto" 为云端定时自动发布（只做域名存活
    校验），mode="manual" 为本地国内网络完整校验后手动发布。标题前缀与说明正文都会
    标注，下载时按需选择。
    """
    api = f"https://api.github.com/repos/{REPO}"
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}

    # 中断恢复优先：最新 Release 是上次发布留下的残缺版本 → 复用补齐，不再新开版本
    latest = get_latest_release(token)
    if is_partial_release(latest):
        tag = latest["tag_name"]
        log.info(f"检测到上次发布中断残留（{tag} assets 不完整），复用该版本补齐上传")
    else:
        tag = get_next_release_tag(token)
        log.info(f"本次发布版本: {tag}")

    # 查找现有Release
    resp = requests.get(f"{api}/releases/tags/{tag}", headers=headers, timeout=15)
    if resp.status_code == 200:
        release = resp.json()
        release_id = release["id"]
        log.info(f"找到现有Release {tag} (ID {release_id})，更新文件")
        # 删除同名旧assets
        for asset in release.get("assets", []):
            if asset["name"] in ("books.json", "clean_rules.json"):
                d = requests.delete(f"{api}/releases/assets/{asset['id']}", headers=headers, timeout=15)
                log.info(f"  删除旧asset {asset['name']} (HTTP {d.status_code})")
    elif resp.status_code == 404:
        log.info(f"Release {tag} 不存在，创建新Release")
        title, body = build_release_meta(tag, final_count, rules_count, mode, stats)
        r2 = requests.post(f"{api}/releases", headers=headers, timeout=15,
                           json={"tag_name": tag, "name": title,
                                 "body": body, "draft": False, "prerelease": False})
        if r2.status_code not in (200, 201):
            log.warning(f"创建Release失败: HTTP {r2.status_code} {r2.text[:200]}")
            return False
        release_id = r2.json()["id"]
    else:
        log.warning(f"查询Release失败: HTTP {resp.status_code} {resp.text[:200]}")
        return False

    # 上传assets（curl --data-binary 会报 size>=1，必须用requests）
    upload_headers = {"Authorization": f"token {token}", "Content-Type": "application/octet-stream"}
    uploaded = []
    for fname in (OUTPUT_FILE, CLEAN_RULES_FILE):
        if not os.path.exists(fname):
            log.warning(f"  {os.path.basename(fname)} 不存在，跳过上传")
            continue
        with open(fname, "rb") as f:
            r3 = requests.post(
                f"https://uploads.github.com/repos/{REPO}/releases/{release_id}/assets?name={os.path.basename(fname)}",
                headers=upload_headers, data=f, timeout=180)
        if r3.status_code == 201:
            log.info(f"✅ 上传 {os.path.basename(fname)} 到发布页成功")
            uploaded.append(os.path.basename(fname))
        else:
            log.warning(f"❌ 上传 {os.path.basename(fname)} 失败: HTTP {r3.status_code} {r3.text[:200]}")

    # 完整性自检：两个 asset 都在才算发布成功；缺的重新跑同一命令会自动复用本版本补齐
    if len(uploaded) == 2:
        log.info(f"✅ 发布页 {tag} 完整（books.json + clean_rules.json 均已上传）")
        return True
    log.warning(f"⚠️ 发布页 {tag} 不完整（成功上传 {len(uploaded)}/2），"
                f"重跑发布命令会自动复用 {tag} 补齐，不会新开版本")
    return False


def auto_publish(final_count, big_count, mode="manual", stats=None):
    """自动提交并推送到GitHub，然后发布到发布页（Releases）

    返回 True 表示 release 已创建且两个 asset 齐全；False 表示发布未完成（调用方应据此失败退出，
    避免 CI 显示成功但发布页没更新）。
    """
    log.info("=== 自动发布到GitHub ===")

    try:
        # 配置git用户
        subprocess.run(["git", "config", "user.name", "autocollect-bot"], check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "bot@autocollect.com"], check=True, capture_output=True)

        # 加文件（只添加确实存在的文件）
        for fname in (OUTPUT_FILE, CLEAN_RULES_FILE, REPORT_FILE):
            if os.path.exists(fname):
                subprocess.run(["git", "add", fname], check=True, capture_output=True)

        # 提交
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        commit_msg = f"chore: 自动更新 {now}\n\n- 书源总数: {final_count}\n- 大厂正版: {big_count}"
        result = subprocess.run(["git", "commit", "-m", commit_msg], capture_output=True, text=True)
        if "nothing to commit" in result.stdout:
            log.info("没有更新内容，不需要发布")
        else:
            # 推送（Actions 环境由 workflow 负责提交，跳过）
            if os.environ.get("GITHUB_ACTIONS") != "true":
                subprocess.run(["git", "push", "origin", "main"], check=True, capture_output=True)
                log.info("✅ 推送 main 成功！")
            else:
                log.info("Actions 环境：跳过 git push，由 workflow 提交")

        # 发布到发布页（Releases）
        token = get_github_token()
        rules_count = 0
        if os.path.exists(CLEAN_RULES_FILE):
            try:
                import json
                rules_count = len(json.load(open(CLEAN_RULES_FILE, encoding="utf-8")))
            except Exception:
                pass
        if not token:
            log.warning("未找到GitHub token，跳过发布页更新")
            return False
        return bool(publish_release(token, final_count, rules_count, mode=mode, stats=stats))
    except Exception as e:
        log.warning(f"自动发布失败: {e}")
        log.warning("可以手动执行 git add && git commit && git push")
        return False
