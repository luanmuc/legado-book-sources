#!/bin/bash
# ============================================================
# 每周自动采集书源（crontab 调用）
# 由系统 cron 每周日 02:00 执行，不依赖豆包定时任务/额度
#
# 分步执行（每步独立落盘、可断点恢复，防沙箱重置/内存爆中断）:
#   A. 采集: 列表(--months过滤) + 合集(--months过滤) + 大佬仓库 → 分片JSON
#   B. 流式清洗: 合并分片 + 域名去重 + 非小说过滤 + 规则完整性 → cleaned_*.json
#   C. 两级校验: 全量分批真实搜索校验 → validated.json / dead.json
#   D. 垃圾过滤: 剔除失效/测试/非小说，成人内容单独分组 → validated_clean.json
#   E. 整理发布: 大厂保护 + 命名分组 + 净化规则 + 报告 + push + 发布页
#
# 用法:
#   bash scripts/run_weekly_collect.sh [月份数]   # 默认 2
# 日志: logs/weekly_YYYYmmdd_HHMMSS.log（保留最近20份）
# ============================================================
set -o pipefail

REPO_DIR="/home/user/Doubao/chats/38450368417489154/book-sources"
LOG_DIR="${REPO_DIR}/logs"
PYTHON="/usr/bin/python3"
TS=$(date +%Y%m%d_%H%M%S)
LOG_FILE="${LOG_DIR}/weekly_${TS}.log"
MONTHS=${1:-2}

mkdir -p "${LOG_DIR}"
cd "${REPO_DIR}" || { echo "[FATAL] 无法进入仓库目录 ${REPO_DIR}" >> "${LOG_FILE}"; exit 1; }

echo "===== 每周自动采集启动 $(date '+%Y-%m-%d %H:%M:%S') | months=${MONTHS} =====" >> "${LOG_FILE}"
echo "工作目录: ${REPO_DIR}" >> "${LOG_FILE}"

# ===== 阶段A: 采集（--months 按更新时间过滤，超范围自动停止）=====
echo "===== 阶段A: 采集 yckceo列表 + 合集 + 大佬仓库 =====" >> "${LOG_FILE}"
"${PYTHON}" scripts/collect_staged.py list --months "${MONTHS}" >> "${LOG_FILE}" 2>&1 || { echo "[FAIL] 列表采集失败" >> "${LOG_FILE}"; exit 1; }
"${PYTHON}" scripts/collect_staged.py heji 1 5 --months "${MONTHS}" >> "${LOG_FILE}" 2>&1 || { echo "[FAIL] 合集1-5页失败" >> "${LOG_FILE}"; exit 1; }
"${PYTHON}" scripts/collect_staged.py heji 6 10 --months "${MONTHS}" >> "${LOG_FILE}" 2>&1 || { echo "[FAIL] 合集6-10页失败" >> "${LOG_FILE}"; exit 1; }
"${PYTHON}" scripts/collect_staged.py gurus >> "${LOG_FILE}" 2>&1 || { echo "[FAIL] 大佬仓库失败" >> "${LOG_FILE}"; exit 1; }

# ===== 阶段B: 流式清洗（合并分片+去重+过滤，checkpoint可恢复）=====
echo "===== 阶段B: 流式清洗 =====" >> "${LOG_FILE}"
"${PYTHON}" scripts/run_from_fragments.py clean >> "${LOG_FILE}" 2>&1 || { echo "[FAIL] 清洗失败" >> "${LOG_FILE}"; exit 1; }

# ===== 阶段C: 两级校验（全量分批追加，每批1000）=====
echo "===== 阶段C: 两级校验（分批） =====" >> "${LOG_FILE}"
rm -f raw/autocollect/validated.json raw/autocollect/dead.json   # 每周全新校验，清掉上周结果
TOTAL=$("${PYTHON}" -c "
import glob, json, os, sys
sys.path.insert(0, os.getcwd())
from autocollect_core.config import RAW_DIR
fs = sorted(glob.glob(os.path.join(RAW_DIR, 'cleaned_*.json')), reverse=True)
print(len(json.load(open(fs[0], encoding='utf-8'))) if fs else 0)
")
echo "清洗后待校验: ${TOTAL} 个，分批(1000/批)执行" >> "${LOG_FILE}"
BATCH=1000
for ((start=0; start<TOTAL; start+=BATCH)); do
  echo "  校验批次 [${start}:$((start+BATCH))]" >> "${LOG_FILE}"
  "${PYTHON}" scripts/run_from_fragments.py validate --start ${start} --count ${BATCH} >> "${LOG_FILE}" 2>&1
done

# ===== 阶段D: 垃圾过滤（成人单独分组）=====
echo "===== 阶段D: 垃圾过滤 =====" >> "${LOG_FILE}"
"${PYTHON}" scripts/filter_junk_sources.py >> "${LOG_FILE}" 2>&1 || { echo "[FAIL] 垃圾过滤失败" >> "${LOG_FILE}"; exit 1; }

# ===== 阶段E: 整理+净化规则+报告+发布（push main + 发布页）=====
echo "===== 阶段E: 整理 + 净化规则 + 报告 + 发布 =====" >> "${LOG_FILE}"
"${PYTHON}" scripts/run_from_fragments.py final --input raw/autocollect/validated_clean.json --publish >> "${LOG_FILE}" 2>&1 || { echo "[FAIL] 整理发布失败" >> "${LOG_FILE}"; exit 1; }

echo "===== 采集结束 exit=0 $(date '+%Y-%m-%d %H:%M:%S') =====" >> "${LOG_FILE}"

# 清理：只保留最近20份日志
ls -t "${LOG_DIR}"/weekly_*.log 2>/dev/null | tail -n +21 | xargs -r rm -f

exit 0
