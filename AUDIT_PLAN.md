# 巡检管道审计计划（AUDIT_PLAN.md）

审计对象：**每日采集 → 中间层 → 每月自动合并发布** 全自动巡检管道
审计方式：脚本化只读核查（`scripts/audit_pipeline.py`）+ 逐条回读源码定性
最近执行：2026-11-07　结论：**23 / 23 PASS**

---

## 1. 审计方法与证据分级

不按「功能是否实现」审，按「运行时会不会被走到、走到会怎样」审。每个检查点必须给出证据，证据分四级：

| 级别 | 含义 | 采信标准 |
|---|---|---|
| 端到端 | 真实跑过 Workflow / 脚本并看到产物 | 最高，可直接判 PASS |
| 产物 | 对落盘数据（books.json、report、ckpt）做结构断言 | 可判 PASS |
| 结构契约 | 代码里存在明确的参数/分支/保护逻辑，且调用链闭合 | 可判 PASS，但需标注"静态" |
| 静态线索 | 只读到函数定义，未确认被调用或实际执行 | 只算"疑似"，不判 PASS |

**规矩**：静态扫描的命中一律先回读源码再定级。本轮两次假阳性就是这条规矩救回来的（见 §4）。

---

## 2. 检查点清单（23 项）

### A. 调度与触发（4 项）

| ID | 检查点 | 判定标准 | 结论 | 证据 |
|---|---|---|---|---|
| A1 | cron 与预期时区一致 | 每日 `7 17 * * *`(UTC)=北京 01:07；每月 `0 20 1 * *`(UTC)=北京 2 号 04:00 | PASS | 两处 cron 实测解析一致 |
| A2 | schedule 触发时 inputs 为空可兜底 | shell 必须写 `${VAR:-默认值}`，不能假定 inputs 有值 | PASS | 两处均 `MONTHS="${INPUT_MONTHS:-1}"` |
| A3 | 写权限声明 | 建 release + 推代码需 `contents: write` | PASS | 两个 workflow 均为 write |
| A4 | 并发互斥 | 两个 workflow 都会 push main，需 concurrency 或 rebase 重试 | PASS | 两处均加 concurrency（daily-collect / monthly-release）+ monthly 另有 rebase 重试 |

### B. 采集层（2 项）

| ID | 检查点 | 判定标准 | 结论 | 证据 |
|---|---|---|---|---|
| B1 | 数据源配置可达性 | 源地址集中声明在 config，不散落代码 | PASS | config 内 `yckceo_list` / `yckceo_heji` / `gurus` 三源声明 |
| B2 | 清洗去重键稳定 | `clean_url` 为唯一键，且剔除中文/emoji 污染 | PASS | 函数存在且含污染处理 |

### C. 中间层语义（2 项）

| ID | 检查点 | 判定标准 | 结论 | 证据 |
|---|---|---|---|---|
| C1 | pending 消费后状态可辨 | 已并入正式版后应归档清空，否则下次 stage 重复处理 | PASS | 1323 条已归档 `raw/autocollect/books_pending_archived_20261107.json`，pending 置空 |
| C2 | 历史淘汰源不被复活 | 月度合并不得读历史 cleaned/artifact 汇总 | PASS | 月度脚本只做新采集，无 artifact 下载路径 |

### D. 校验层（3 项）

| ID | 检查点 | 判定标准 | 结论 | 证据 |
|---|---|---|---|---|
| D1 | 三态判定完整 | 搜索/发现各返回 ok\|bad\|blocked\|None，任一 ok 即可用 | PASS | `check_search_parsed` / `check_explore_parsed` / `check_source_usable` 均在，含 blocked 分支 |
| D2 | 成人豁免不看 group | `is_adult_source` 只用 name/url/comment，group 是判定结果不能当输入 | PASS | AST 剥离文档串后确认可执行代码只取三字段（原实现 bug 已修，55中文网/592书库 不再锁死） |
| D3 | quick/full 档位可区分 | `validate_sources` 支持 mode，断点按 mode 分名 | PASS | mode 参数与 ckpt 分名齐备 |

### E. 排序组织（2 项）

| ID | 检查点 | 判定标准 | 结论 | 证据 |
|---|---|---|---|---|
| E1 | 大厂顺序不被名字排序覆盖 | `organize_sources` 用 BIG_SITES 序做 `_big_key` 保护 | PASS | `_big_key` + BIG_SITES 均在 |
| E2 | 正式版结构自洽 | customOrder 连续、分组段连续、成人最末 | PASS | 1538 条连续；分组 6 段；成人 1345-1538 且末位=1538 |

### F. 发布层（5 项）

| ID | 检查点 | 判定标准 | 结论 | 证据 |
|---|---|---|---|---|
| F1 | 版本号递增不覆盖 | `get_next_release_tag` 取最新 vX.Y.Z patch+1 | PASS | 函数存在（静态） |
| F2 | 中断残留复用 | `is_partial_release` 命中则补齐同 tag，不新开版本 | PASS | 复用判断已接入发布主流程（静态） |
| F3 | asset 上传端点正确 | 必须 `uploads.github.com`，api.github.com 会 404 | PASS | 上传用 uploads 端点 |
| F4 | 自动/手动版可区分 | 标题前缀 + 说明标注校验口径，下载可自行选择 | PASS | `build_release_meta`(auto/manual) 已接入，月度脚本用 `mode="auto"` |
| F5 | Actions 内不重复 git push | 内部 push 与 workflow 提交冲突需跳过 | PASS | 检测 `GITHUB_ACTIONS` 跳过内部推送 |

### G. 幂等与恢复（2 项）

| ID | 检查点 | 判定标准 | 结论 | 证据 |
|---|---|---|---|---|
| G1 | 断点按档位分名 | ckpt 文件名含 mode，避免 quick/full 串用 | PASS | ckpt 名含 mode |
| G2 | 重跑不重复发版 | 内容无变化时跳过发布 | PASS | 有 no-change 短路 |

### H. 文档一致性（3 项）

| ID | 检查点 | 判定标准 | 结论 | 证据 |
|---|---|---|---|---|
| H1 | README 源数与实际一致 | 文档总数 = books.json 条数 | PASS | README 1538 = 实际 1538 |
| H2 | 模块表覆盖新脚本 | DEVELOPMENT 模块表登记 monthly_release/audit_pipeline/reorder | PASS | 已登记（本轮补） |
| H3 | 过期口径清理 | 现行描述不得残留「每周采集」（历史更新日志除外） | PASS | 现行描述 0 处（历史条目保留，属事实记录） |

---

## 3. 本轮发现与修复

| # | 级别 | 问题 | 改前 | 改后 |
|---|---|---|---|---|
| 1 | 中 | 日更 workflow 无并发互斥，与月度/手动推送可能抢 main | `concurrency` 缺失，push 直接失败 | 加 `concurrency: daily-collect`；月度另加 rebase 重试 3 次 |
| 2 | 中 | 中间层已消费未清空，下次 stage 会重复处理 1323 条 | pending 1323 条其中 1208 已并入正式版 | 归档 `books_pending_archived_20261107.json`，pending 置空 |
| 3 | 低 | DEVELOPMENT 模块表未登记新脚本，且残留 `run_weekly_collect.sh` | 模块表缺 3 个脚本，脚本改名未同步 | 补 `monthly_release.py` / `audit_pipeline.py` / `reorder.py`，`run_weekly`→`run_daily`，crontab 说明改每日 |
| 4 | 低 | README 现行描述仍写「每周采集」6 处 | 与每日采集改造不符 | 现行描述清零（更新日志历史条目保留） |

---

## 4. 审计工具自身的假阳性（已修，记录备查）

| # | 假阳性 | 成因 | 修法 |
|---|---|---|---|
| 1 | D2 判「成人判定仍读 group」 | 函数 docstring 里写了 `bookSourceGroup` 说明文字，被字符串匹配命中 | 改 AST 解析：按「函数体首条 Expr」定位 docstring 常量并排除（`get_docstring` 会 clean 缩进，字符串比较不可靠） |
| 2 | B1 判「数据源未声明」 | config 用小写键 `yckceo_list`，检查用大写 `YCKCEO` | 检查改小写不敏感 |
| 3 | H3 判「仍有每周残留」 | 更新日志历史条目含「每周」，属历史事实 | 排除以 `- v` 开头的历史行 |

---

## 5. 未验证项（只拿到静态证据，需下次真实运行确认）

| 项 | 缺什么证据 | 如何补 |
|---|---|---|
| F4 自动通道 | `mode="auto"` 只跑过 dry-run，没真正建过 release | 下一次月度自动发布后，核对标题前缀是否为【自动】、说明是否含"只判域名存活" |
| F1/F2 | 版本递增与中断复用未在真实发布中触发 | 发布后查 `releases/tags/<tag>` 与 asset 完整性 |
| G1/G2 | 断点复用与 no-change 短路未实测 | 删 ckpt 重跑一次、内容不变再跑一次 |
| 云端 vs 本地判定差异 | 同一批源云端保留 530 / 本地 650，差 178 未逐条归因 | 抽样 20 个差异源，对比两端 HTTP 状态 |

---

## 6. 回归方式

```bash
# 全套审计（只读，不改任何数据）
python3 scripts/audit_pipeline.py

# 机器可读，便于流水线断言
python3 scripts/audit_pipeline.py --json

# 结构断言单独复核
python3 scripts/reorder.py --dry-run
```

判据：`FAIL = 0` 才允许发版；`WARN` 需在本次发布说明里登记原因。
