#!/bin/bash
# ============================================================
# 一键重建「每周自动采集」crontab
# 用途：VM 环境重置导致 crontab 丢失后，重跑本脚本即可恢复
#   每天 UTC 17:07（北京次日 01:07）执行 run_daily_collect.sh 全链路
# 幂等：重复执行不会产生重复行
# ============================================================
set -e

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="${REPO_DIR}/scripts/run_daily_collect.sh"
# UTC 17:07 = 北京次日 01:07，与 GitHub Actions 每日采集同一时段
CRON_LINE="7 17 * * * cd ${REPO_DIR} && bash ${SCRIPT} >/dev/null 2>&1"

echo "仓库目录: ${REPO_DIR}"

# ---- 自检 ----
[ -f "${SCRIPT}" ] || { echo "[FATAL] 找不到 ${SCRIPT}"; exit 1; }
chmod +x "${SCRIPT}"
command -v python3 >/dev/null || { echo "[FATAL] 需要 python3"; exit 1; }

# ---- 幂等写入：先剔除旧行，再追加 ----
crontab -l 2>/dev/null | grep -v "run_daily_collect.sh" | crontab -
( crontab -l 2>/dev/null; echo "${CRON_LINE}" ) | crontab -

echo "✅ crontab 已重建，当前生效任务："
crontab -l | grep -E "run_daily_collect|^#?" || echo "（无相关任务！）"

echo ""
echo "下次触发：每周日 02:00（北京时间）"
echo "日志：${REPO_DIR}/logs/weekly_*.log（脚本自动创建）"
