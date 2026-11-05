#!/bin/bash
# ============================================================
# 每周自动采集书源（crontab 调用）—— 三层架构版（2026-11）
# 由系统 cron 每周日 02:00 执行，不依赖豆包定时任务/额度
#
# 核心原则（用户硬约束）：
#   1. 采集池第一遍量太大 → 只做【快速存活校验】（quick），不跑真实性解析
#   2. 所有需求（真实性/关键词/成人豁免/排序）在【发布前】一步不少（full）
#   3. 采集结果只并入【中间层 books_pending.json】，正式版发布必须用户确认
#
# 分步执行（每步独立落盘、可断点恢复，防沙箱重置/内存爆中断）:
#   A. 采集: 列表(--months过滤) + 合集(--months过滤) + 大佬仓库 → 分片JSON
#   B. 流式清洗: 合并分片 + 域名去重 + 非小说过滤 + 规则完整性 → cleaned_*.json
#   C. 并入中间层: 快速存活校验(quick) + 垃圾过滤(成人豁免) + 整理 → books_pending.json
#      （不发布！正式版 books.json 纹丝不动）
#
# 发布（用户确认后手动执行，发布前自动跑完整真实性校验 full + 发新版本）:
#   python3 autocollect.py --publish-pending --publish
#
# 用法:
#   bash scripts/run_weekly_collect.sh [月份数]   # 默认 1（只采集最近1个月，用户偏好）
# 日志: logs/weekly_YYYYmmdd_HHMMSS.log（保留最近20份）
# ============================================================
set -o pipefail

REPO_DIR="/home/user/Doubao/chats/38450368417489154/book-sources"
LOG_DIR="${REPO_DIR}/logs"
PYTHON="/usr/bin/python3"
TS=$(date +%Y%m%d_%H%M%S)
LOG_FILE="${LOG_DIR}/weekly_${TS}.log"
MONTHS=${1:-1}   # 默认只采集最近1个月（用户偏好），可传参调大

mkdir -p "${LOG_DIR}"
cd "${REPO_DIR}" || { echo "[FATAL] 无法进入仓库目录 ${REPO_DIR}" >> "${LOG_FILE}"; exit 1; }

echo "===== 每周自动采集启动 $(date '+%Y-%m-%d %H:%M:%S') | months=${MONTHS} =====" >> "${LOG_FILE}"
echo "工作目录: ${REPO_DIR}" >> "${LOG_FILE}"

# ===== 阶段A: 采集（列表前10页 + 合集第1页，--months 按更新时间过滤）=====
echo "===== 阶段A: 采集 yckceo列表 + 合集 + 大佬仓库 =====" >> "${LOG_FILE}"
"${PYTHON}" scripts/collect_staged.py list --months "${MONTHS}" >> "${LOG_FILE}" 2>&1 || { echo "[FAIL] 列表采集失败" >> "${LOG_FILE}"; exit 1; }
"${PYTHON}" scripts/collect_staged.py heji 1 1 --months "${MONTHS}" >> "${LOG_FILE}" 2>&1 || { echo "[FAIL] 合集前30个失败" >> "${LOG_FILE}"; exit 1; }
"${PYTHON}" scripts/collect_staged.py gurus >> "${LOG_FILE}" 2>&1 || { echo "[FAIL] 大佬仓库失败" >> "${LOG_FILE}"; exit 1; }

# ===== 阶段B: 流式清洗（合并分片+去重+过滤，checkpoint可恢复）=====
echo "===== 阶段B: 流式清洗 =====" >> "${LOG_FILE}"
"${PYTHON}" scripts/run_from_fragments.py clean >> "${LOG_FILE}" 2>&1 || { echo "[FAIL] 清洗失败" >> "${LOG_FILE}"; exit 1; }

# ===== 阶段C: 并入中间层（快速存活校验 quick + 垃圾过滤成人豁免 + 整理）=====
# 说明：quick = 只判首页存活/WAF，量大也能跑完；真实性校验留到 --publish-pending 发布前
echo "===== 阶段C: 并入中间层（quick 存活校验，不发布） =====" >> "${LOG_FILE}"
LATEST=$("${PYTHON}" -c "
import glob, os, sys
sys.path.insert(0, os.getcwd())
from autocollect_core.config import RAW_DIR
fs = sorted(glob.glob(os.path.join(RAW_DIR, 'cleaned_*.json')), reverse=True)
print(fs[0] if fs else '')
")
if [ -z "${LATEST}" ]; then
  echo "[FAIL] 未找到 cleaned_*.json" >> "${LOG_FILE}"
  exit 1
fi
echo "中间层合并输入: ${LATEST}" >> "${LOG_FILE}"
"${PYTHON}" autocollect.py --from-cleaned "${LATEST}" --stage >> "${LOG_FILE}" 2>&1 || { echo "[FAIL] 并入中间层失败" >> "${LOG_FILE}"; exit 1; }

echo "===== 采集结束 exit=0 $(date '+%Y-%m-%d %H:%M:%S') =====" >> "${LOG_FILE}"
echo "提示：正式版未动。确认中间层后执行:" >> "${LOG_FILE}"
echo "  python3 autocollect.py --publish-pending --publish   # 发布前完整校验(full) + 发新版" >> "${LOG_FILE}"

# 清理：只保留最近20份日志
ls -t "${LOG_DIR}"/weekly_*.log 2>/dev/null | tail -n +21 | xargs -r rm -f

exit 0
