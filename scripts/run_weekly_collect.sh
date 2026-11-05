#!/bin/bash
# ============================================================
# 每周自动采集书源（crontab 调用）
# 由系统 cron 每周日 02:00 执行，不依赖豆包定时任务/额度
# 流程: 采集 -> 清洗去重 -> 两级校验 -> 整理分组 -> 净化规则
#       -> 生成报告 -> git push main -> 更新 GitHub 发布页 Release
# 日志: logs/weekly_YYYYmmdd_HHMMSS.log（保留最近20份）
# ============================================================
set -o pipefail

REPO_DIR="/home/user/Doubao/chats/38450368417489154/book-sources"
LOG_DIR="${REPO_DIR}/logs"
PYTHON="/usr/bin/python3"
TS=$(date +%Y%m%d_%H%M%S)
LOG_FILE="${LOG_DIR}/weekly_${TS}.log"

mkdir -p "${LOG_DIR}"
cd "${REPO_DIR}" || { echo "[FATAL] 无法进入仓库目录 ${REPO_DIR}" >> "${LOG_FILE}"; exit 1; }

echo "===== 每周自动采集启动 $(date '+%Y-%m-%d %H:%M:%S') =====" >> "${LOG_FILE}"
echo "工作目录: ${REPO_DIR}" >> "${LOG_FILE}"

# 执行完整采集流程并自动发布（--publish 会 push main + 更新发布页 Release）
"${PYTHON}" autocollect.py --publish --months 2 >> "${LOG_FILE}" 2>&1
EXIT_CODE=$?

echo "===== 采集结束 exit=${EXIT_CODE} $(date '+%Y-%m-%d %H:%M:%S') =====" >> "${LOG_FILE}"

# 清理：只保留最近20份日志
ls -t "${LOG_DIR}"/weekly_*.log 2>/dev/null | tail -n +21 | xargs -r rm -f

exit "${EXIT_CODE}"
