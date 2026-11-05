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
RELEASE_TAG = "v3.2"


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


def publish_release(token, final_count, rules_count):
    """发布/更新GitHub Release，上传 books.json 和 clean_rules.json 到发布页"""
    api = f"https://api.github.com/repos/{REPO}"
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}

    # 查找现有Release
    resp = requests.get(f"{api}/releases/tags/{RELEASE_TAG}", headers=headers, timeout=15)
    if resp.status_code == 200:
        release = resp.json()
        release_id = release["id"]
        log.info(f"找到现有Release {RELEASE_TAG} (ID {release_id})，更新文件")
        # 删除同名旧assets
        for asset in release.get("assets", []):
            if asset["name"] in ("books.json", "clean_rules.json"):
                d = requests.delete(f"{api}/releases/assets/{asset['id']}", headers=headers, timeout=15)
                log.info(f"  删除旧asset {asset['name']} (HTTP {d.status_code})")
    elif resp.status_code == 404:
        log.info(f"Release {RELEASE_TAG} 不存在，创建新Release")
        body = (f"全自动采集更新 {datetime.now().strftime('%Y-%m-%d')}\n"
                f"{final_count}个纯小说源 + {rules_count}条配套净化规则\n"
                f"- 12个大厂正版源\n"
                f"- 全自动采集脚本每周自动更新")
        r2 = requests.post(f"{api}/releases", headers=headers, timeout=15,
                           json={"tag_name": RELEASE_TAG, "name": RELEASE_TAG + " 稳定版",
                                 "body": body, "draft": False, "prerelease": False})
        if r2.status_code not in (200, 201):
            log.warning(f"创建Release失败: HTTP {r2.status_code} {r2.text[:200]}")
            return
        release_id = r2.json()["id"]
    else:
        log.warning(f"查询Release失败: HTTP {resp.status_code} {resp.text[:200]}")
        return

    # 上传assets（curl --data-binary 会报 size>=1，必须用requests）
    upload_headers = {"Authorization": f"token {token}", "Content-Type": "application/octet-stream"}
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
        else:
            log.warning(f"❌ 上传 {os.path.basename(fname)} 失败: HTTP {r3.status_code} {r3.text[:200]}")


def auto_publish(final_count, big_count):
    """自动提交并推送到GitHub，然后发布到发布页（Releases）"""
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
            # 推送
            subprocess.run(["git", "push", "origin", "main"], check=True, capture_output=True)
            log.info("✅ 推送 main 成功！")

        # 发布到发布页（Releases）
        token = get_github_token()
        rules_count = 0
        if os.path.exists(CLEAN_RULES_FILE):
            try:
                import json
                rules_count = len(json.load(open(CLEAN_RULES_FILE, encoding="utf-8")))
            except Exception:
                pass
        if token:
            publish_release(token, final_count, rules_count)
        else:
            log.warning("未找到GitHub token，跳过发布页更新")
    except Exception as e:
        log.warning(f"自动发布失败: {e}")
        log.warning("可以手动执行 git add && git commit && git push")
