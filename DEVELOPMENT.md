# 开发文档（DEVELOPMENT.md）

> 中断恢复（对话中断/额度耗尽/沙箱重置/发布传入一半）见 **[RESUME.md](RESUME.md)**；
> 接续第一步永远是 `python3 scripts/status.py`（本地+发布页真实状态一条命令看清）。

> Legado 阅读书源仓库自动采集系统的架构、数据流、CLI、发布与故障排查说明。
> 维护者视角的完整手册。用户文档见 [README.md](README.md)。

---

## 1. 系统架构：三层隔离

```
┌─ 采集层（GitHub Actions 每周日自动，无人值守）─────────────────────────┐
│ .github/workflows/auto-update.yml                                     │
│   → collect_staged 逻辑（collectors.py）                               │
│   → yckceo列表(前10页) + 合集(前30个) + 大佬仓库(2个存活)              │
│   → clean_and_dedup（流式清洗/域名去重/规则完整性）                    │
│   → 产物 weekly/cleaned_YYYYMMDD_HHMMSS.json 自动 commit+push          │
└──────────────────────────────────────────────────────────────────────┘
                              ▼ git pull（国内网络）
┌─ 中间层（本地执行，正式版不受影响）───────────────────────────────────┐
│ python3 autocollect.py --from-cleaned weekly/cleaned_X.json --stage    │
│   → validate_sources（两级校验）                                       │
│   → filter_junk_sources（垃圾过滤，成人归组）                          │
│   → organize_sources（整理/改名/排序，大厂保护）                       │
│   → 合并进 books_pending.json（多次采集累积）                          │
└──────────────────────────────────────────────────────────────────────┘
                              ▼ 用户确认「发布」
┌─ 正式版（发布动作，校验一步不少）─────────────────────────────────────┐
│ python3 autocollect.py --publish-pending --publish                     │
│   → 大厂12原样保护                                                     │
│   → 其余全部重新走两级校验 + 垃圾过滤（发布前完整校验）                 │
│   → 提升为 books.json + clean_rules.json + collect_report.md           │
│   → auto_publish：git commit+push + 发布页开新版本（见"发布版本策略"）  │
└──────────────────────────────────────────────────────────────────────┘
```

**发布版本策略（2026-11-05 用户要求）**：每次发布都到发布页发布**新版本**，不再只覆盖旧 tag。
`publisher.get_next_release_tag()` 读现有 Releases 最新 `vX.Y.Z` tag，patch+1（v3.2.7→v3.2.8）；
目标 tag 不存在则创建新 Release，已存在则更新其 assets（历史 tag 内容保持最新）。
合并路径已防污染：`organizer.organize_sources` 入口对全部源统一 `clean_url`（兼容校验输出包装结构与正式版裸结构）。

**为什么采集与校验分离**：GitHub Actions 免费 runner 在美国，跨洋访问国内站点
采集可行（实测列表页 3.3s / JSON 2.2s / CDN 1.9s），但存活/搜索校验针对国内书源站
跨洋大量误判（合格率 72% → 27%）。因此：**采集在 Actions，校验必须国内网络**。

**断点续传矩阵（2026-11-05 补全，豆包对话/沙箱中断均可持续）**：

| 环节 | 断点机制 | 中断后 |
|------|----------|--------|
| 采集分片（collect_staged） | 每段独立落盘 raw_list/raw_heji_*/raw_gurus.json | 重跑当前段即可，已完成段不动 |
| 合集ID提取（collect_heji_ids） | 每页落盘 heji_ids.json + 已有ID续爬 | 只补缺失页 |
| 合集批量下载（collect_heji_batch） | heji/{cid}.json 已存在跳过 | 只补缺失合集 |
| 流式清洗（run_from_fragments clean） | clean_tmp.json checkpoint（每10/50分片） | 从checkpoint继续 |
| 分批校验（run_from_fragments validate） | validated.json/dead.json 每批追加+URL去重 | 从 --start 继续 |
| **两级校验（--stage/--publish/--publish-pending）** | **ckpt_{tag}_{validated,dead}.json 每批落盘（batch=300/200）** | **重启跳过已验源（含已淘汰），只补未验** |
| 整理/过滤/报告 | 秒级操作 | 无需断点 |

---

## 2. 模块职责

### autocollect_core/（10 模块，核心逻辑单一数据源）

| 模块 | 职责 | 关键函数 |
|------|------|----------|
| `config.py` | 常量：大厂12清单、垃圾/成人关键词表、数据源URL、路径、请求参数 | `BIG_SITE_*`、`JUNK_*`、`ADULT_GROUP`、`GENERIC_TEST_KEYWORDS`（我的/天下/重生…）、`REQUEST_TIMEOUT/RETRY/CONCURRENCY`（支持 `YCKCEO_*` 环境变量覆盖） |
| `utils.py` | 日志、反爬请求、域名工具 | `fetch_url(url, timeout, retry)`（UA+Referer+verify=False）、`clean_url`、`get_domain` |
| `collectors.py` | 采集三路数据源 | `collect_yckceo_list(months, page_start, page_end)`、`collect_yckceo_heji(months, page_start, page_end, limit)`、`collect_gurus()`、`collect_all(months)`；`parse_update_time`/`extract_update_times`/`filter_by_months`（时间过滤） |
| `cleaner.py` | 清洗去重 + 分类判定 | `clean_and_dedup(raw)`（流式+checkpoint）、`is_big_site`、`classify_junk`/`is_adult_source`/`filter_junk_sources`（失效/测试先剔→成人无条件保留→其余非小说剔） |
| `legado_rules.py` | **Legado 规则解析引擎**（真实性校验用） | `parse_book_list(html, bookList, name, url)`（CSS+XPath 双引擎、`||` 多候选）、`parse_explore_entries(exploreUrl)`（JSON数组/`标题::URL` 两种格式） |
| `validators.py` | 两级校验 + 真实性校验 | `check_rule_integrity`、`quick_validate`（首页连通性，WAF 不淘汰）、`check_search_parsed`（通用关键词轮试+规则解析，三态 ok/bad/blocked）、`check_explore_parsed`（发现页前3入口轮试至少1个解析出书）、`check_source_usable`（搜索/发现至少一项可用）、`validate_sources(cleaned)` → `(validated, dead)`（大厂保护） |
| `organizer.py` | 整理输出 | `organize_sources(validated, existing)`（大厂保护最顶 + 四字改名 + **成人豁免改名/符号清理** + 名字族自然排序 + customOrder） |
| `cleanrules.py` | 净化规则 | `collect_clean_rules()`（nyasama 包）、`generate_clean_rules(final, rules)`（去重优化输出） |
| `report.py` | 采集报告 | `generate_report(raw, cleaned, dead, final, big_count)`（真实统计） |
| `publisher.py` | 发布 | `publish_release()`（**每次发新版 vX.Y.Z**，patch+1）、`auto_publish(final_count, big_count)`（git→push→Release→assets 上传 uploads.github.com） |

### scripts/（分步执行，断点恢复友好）

| 脚本 | 用途 |
|------|------|
| `run_daily_collect.sh` | 一键分步全流程（MONTHS 参数，默认 1；A 采集→B 清洗→C 分批校验→D 垃圾过滤→E 整理发布），本地 crontab 每日触发 |
| `monthly_release.py` | 每月自动合并发布（Actions auto 通道）：重新采集 → 明确死站剔除 → 垃圾过滤 → 合并 → `auto_publish(mode="auto")` |
| `audit_pipeline.py` | 巡检管道审计（只读）：23 个检查点覆盖调度/采集/中间层/校验/排序/发布/恢复/文档，输出 PASS/WARN/FAIL + 证据 |
| `reorder.py` | 整库顺序规整（`--dry-run` 可先看）：大厂固定序 → 分组序 → 族名自然序 → 成人最末 |
| `collect_staged.py` | 分段采集：`list`（前10页）/ `heji start end`（--limit 默认30）/ `gurus` |
| `collect_heji_ids.py` | 提取合集列表全部 id → `heji_ids.json` |
| `collect_heji_batch.py` | 逐合集独立落盘下载（断点续传，中断零损失） |
| `run_from_fragments.py` | 分片恢复：`clean`（合并分片+清洗+成人豁免，兼容 raw_heji_*.json 与 heji/*.json 两种路径）/ `validate --start --count`（分批）/ `final --input --publish` |
| `filter_junk_sources.py` | 垃圾过滤+成人归组（复用 cleaner 核心函数） |
| `check_usable.py` | 真实性专项检测：全量/抽样跑 `check_source_usable`，输出 usable_report + 断点 ckpt_usable.json |
| `status.py` | **状态自检**：正式版/中间层源数与分组、最新 cleaned、校验断点、采集分片、git 状态、发布页最新版本与 assets 完整性、crontab 是否在（中断接续第一步） |
| `install_cron.sh` | 一键重建本地 crontab（每日采集时段，VM 重置后恢复用） |

---

## 3. 数据流与产物

```
原始采集（流式，防内存爆）        清洗（checkpoint）        校验（分批）
raw/autocollect/                  cleaned_*.json           validated.json
├─ raw_list.json (列表前10页)       （域名去重 13,713→        （两级校验 1,422 合格，
├─ raw_heji_1_1.json (合集前30)     6,867→规则完整通过）      淘汰落盘 dead.json）
├─ raw_gurus.json (大佬1640)                               ↓
└─ heji/*.json (批量下载分片)      垃圾过滤                整理发布
                                  validated_clean.json →  books.json(929)
                                                        →  clean_rules.json(1176)
                                                        →  collect_report.md
三层模式下：
  weekly/cleaned_*.json（Actions 产物，已 push 仓库）
  books_pending.json（中间层，待确认）
```

---

## 4. CLI 参数全集

### autocollect.py

| 参数 | 说明 |
|------|------|
| `--collect` | 只执行采集 |
| `--validate` | 只执行校验 |
| `--merge` | 只执行合并整理 |
| `--publish` | 跑完自动发布（git push + Release assets 更新） |
| `--months N` | 采集最近 N 个月（默认 1；按更新时间过滤，整页超范围自动停止翻页） |
| `--collect-only` | **Actions 用**：采集+清洗+规则校验 → `weekly/cleaned_*.json`，不做存活探测 |
| `--from-cleaned FILE` | **本地用**：从清洗结果继续（校验+过滤+整理），跳过采集/清洗 |
| `--stage` | 整理结果合并进 `books_pending.json`（中间层），不发布 |
| `--publish-pending` | 中间层提升正式版：**发布前完整校验**（大厂保护+两级校验+垃圾过滤），加 `--publish` 才更新 Release |

### scripts/collect_staged.py

| 命令 | 参数 | 说明 |
|------|------|------|
| `list` | `--months N` | 采集列表前 10 页 → `raw_list.json` |
| `heji start end` | `--months N`、`--limit K` | 采集合集页范围 → `raw_heji_s_e.json`，取列表前 K 个（默认 30） |
| `gurus` | - | 4 个大佬仓库直链 → `raw_gurus.json` |

### scripts/run_from_fragments.py

| 命令 | 参数 | 说明 |
|------|------|------|
| `clean` | - | 合并分片（list + raw_heji_*.json + heji/*.json + gurus）→ 流式清洗（checkpoint） |
| `validate` | `--start` `--count` | 分批两级校验（每批 1000，追加 validated.json，dead.json 落淘汰原因） |
| `final` | `--input FILE` `--publish` | 整理+报告+可选发布 |

### 环境变量（跨洋优化）

| 变量 | 默认 | 说明 |
|------|------|------|
| `YCKCEO_TIMEOUT` | 10 | 单请求超时秒数（Actions 设 30） |
| `YCKCEO_RETRY` | 2 | 失败重试次数（Actions 设 3） |
| `YCKCEO_CONCURRENCY` | 20 | 批量下载/校验并发 |

---

## 5. 校验体系（发布前一步不少）

> **分档原则（2026-11 用户明确要求）**：采集池第一遍量太大，只做存活校验（quick）；
> 所有需求（真实性/关键词/成人规则/排序）在**发布前**完整执行（full），一步不少。
> - `validate_sources(sources, mode="quick"|"full")`，默认 quick
> - `validate_sources_with_checkpoint(..., mode=)`，两种档位 ckpt 文件自动分名，互不覆盖
> - quick 档：首页可达性 + WAF 识别（死站直接淘汰，pass_rate=1.0）
> - full 档：quick + 真实性校验（下文第 4 条）
> - 接入点：`autocollect.py` 采集校验=quick，`--publish-pending`=full；`run_from_fragments.py` `validate`=quick（`--full` 可切），`final --publish` 自动跑发布前 full 复检；`scripts/check_usable.py` 专项全量检测

1. **格式校验**：必填字段（bookSourceUrl/searchUrl）、JSON 结构
2. **规则完整性**：ruleBookInfo/ruleSearch/ruleDetail/ruleContent 等非空、类型正确（dict 防御）
3. **快速存活过滤**：首页连通性；**WAF（403/405/503）不淘汰**（能搜出书就保留）
4. **真实性校验（核心，2026-11 新增）**：`validators.check_source_usable()`
   - **搜索**：`check_search_parsed()` —— 构造 searchUrl 请求（支持 GET/POST/charset/JSON 配置），编码探测（charset header/meta/apparent_encoding，修复 GBK 小站乱码），用 `ruleSearch.bookList` + `name`/`bookUrl` 规则真实解析 HTML
     - 通用关键词轮试（`config.GENERIC_TEST_KEYWORDS`：我的/天下/重生/总裁/王爷/系统/都市/修仙/神/爱），每源最多试 3 个，任一解析出书即 ok
     - 用关键字而非具体书名——降低"该书本站没有"造成的误判（对齐 Legado 官方校验默认词"我的"）
   - **发现**：`check_explore_parsed()` —— `exploreUrl`（支持 JSON 数组 / `标题::URL` 多行两种格式）前 3 个入口轮试（`{{page}}` 替换为 1），用 `ruleExplore.bookList` 解析，**至少 1 个入口解析出书才算可用**
   - **判定（用户标准）**：搜索、发现**最起码有一个能用**才算可用源
     | 搜索 | 发现 | 结论 |
     |---|---|---|
     | ok | 任意 | ✓ 可用 pass_rate=1.0 |
     | bad/无配置 | ok | ✓ 可用 pass_rate=1.0 |
     | bad | bad | ✗ 淘汰（内容已换/域名挂售/规则失效） |
     | blocked（网络/反爬） | 任意 | ? 保留待验 pass_rate=0.6 |
     | 任意 | blocked | ? 保留待验 pass_rate=0.6 |
   - **成人源宽松豁免**：`check_adult_content_ready()` —— 成人组含漫画/短剧/影视/图片/听书站，用 `ruleSearch.bookList` 要求"解析出书名"必然失败。改为判"至少一条能取内容的规则链"（`ruleContent.content` / `ruleToc.bookList|chapterList` / `ruleSearch.bookList` / `ruleExplore.bookList|exploreUrl`）任一非空即可用，四条全空才算空壳淘汰；**死站仍由第一遍存活校验淘汰（成人也不豁免失效）**
   - **大厂保护**：12 个 BIG_SITES 永不淘汰（即使 usable=False 也保留，标记 big_protected）
   - 三态返回：`ok` / `bad`（200 但解析不出，淘汰依据）/ `blocked`（非 200/异常，不淘汰）
5. **垃圾过滤**：非小说/测试占位/失效标记剔除；**成人内容一律保留**（含成人漫画/影视等非小说类）→ `bookSourceGroup="成人书源"`，排序最末、豁免改名与符号清理
6. **大厂保护**：12 个大厂任何环节不覆盖（合并时以既有版本为准）
7. 校验淘汰原因落盘 `dead.json`，报告真实统计

### 规则解析器（legado_rules.py，真实性校验的引擎）

支持 Legado 规则常用子集（够判断"至少能解析出一本书"）：
- **选择器**：`class.x` / `tag.x` / `id.x` / `.x` / `#x` / 标签名 / `tag.N` 索引 / `h4 a.0`（父选择器+索引）
- **XPath**：以 `/` 开头或含 `//` 的规则走 lxml 引擎（`//div[@class="round"]`、`//h3/a/text()`、`//h3/a/@href`）
- **动作**：`@text` `@ownText` `@textNodes` `@html` `@href` `@src` `@attr.x` `@data-x`
- **容错**：`||` 多候选逐个尝试、`##` 正则替换剥离、CSS 语法非法按解析失败处理

**2026-11-06 补齐的 9 类缺口**（全部由"误判为失效"的真实源驱动，逐条实测转正）：

| 语法 / 情况 | 说明 | 实测效果 |
|---|---|---|
| `!N` 排除索引 | `tag.tr!0` 去掉表头行，笔趣阁类最常用 | 笔趣阁 48 本 |
| `[a:b]` 切片（含负数） | `tbody tr[1:-1]` 去首尾 | 笔趣阁19 等 |
| 负数索引 `.-1` | 取最后一节 | — |
| `class.a b` 裸多 class | 作者漏写第二个 `class.` 前缀 | 老站小说 10 本 |
| `@css:` 显式前缀 | 整条按 CSS 处理，且后面仍可接 `@text` 等动作 | 书斋阁书 30 本 |
| `tbody` 透明层 | lxml 不像浏览器自动补 `tbody`，`table tbody tr` 会 0 匹配 → 退化 `table tr` | 七六文学 50 本 |
| `<js>` / `$.[]` / `$..` 脚本与 JSONPath 规则 | 静态解析无法复现 → 判 `blocked`（**不判失效**） | 顶点小说10 / 笔趣阁67 / 阅友小说3 保留 |
| 纯 JS 渲染页（SPA） | `You need to enable JavaScript` 类页面，WebView 可渲染 | 书网小说 保留 |
| 单引号 JSON 配置 | `{'method':'POST'}` 标准 `json.loads` 失败 → POST/charset 全丢 | 御宅屋书 5300 本、新御书屋2 20 本 |

配套的请求层修正：
- **POST 空结果自动回退 GET**（老源 method 配置过时，站点实际只认 GET）：香书小说 50 本
- **`{{searchKey}}` 先于裸 `searchKey` 替换**（原顺序会把 `{{searchKey}}` 变成 `{{词}}`）
- **智能编码打分**：多候选编码（声明 charset / meta / apparent / utf-8 / gb18030）按常用汉字命中数打分择优，修 "UTF-8 页面被 GBK 解码" 致解析全灭（谷歌网书 类）

**重测结论（1336 源，4 轮）**：初始判可用 537 → 修完 9 类缺口后 **707**，确认失效 393（站点暂停/域名挂售/换主改版/JS 跳转页），待验 224（反爬/脚本规则/跨洋网络）。误判率从 40% 降到接近 0。

### 专项检测脚本（scripts/check_usable.py）

```bash
python3 scripts/check_usable.py                # 全量检测 books.json（带断点续传）
python3 scripts/check_usable.py --limit 50     # 抽样
```
- 输出 `raw/autocollect/usable_report_<ts>.json`（每源 usable/search/explore/detail）
- 断点 `raw/autocollect/ckpt_usable.json`（已处理 URL 集合，中断重跑自动跳过）

### 已验证的实战案例（2026-11-06）

- `笔趣阁119`（biqugewu.com）：搜索接口返回 200 且页面 44KB，但内容是 **"BiqugeWu.com is for sale | HugeDomains"（域名挂售页）** → 旧校验（200+长度）必判合格，新校验正确判失效
- `书旗小说`：搜索规则解析不出（站点改版），但发现页"全部"入口解析出《剑来》《北派盗墓笔记》 → 判可用（符合"搜索/发现至少一个能用"）
- `潇湘书院`：XPath+索引语法支持后，搜索解析出 20 本 → 从误判 bad 转为 ok

---

### 每日自动采集（2026-11-06 改造）

- workflow `.github/workflows/auto-update.yml`：cron `7 17 * * *`（UTC，= 北京 01:07），定时触发默认 `full`
- 分层：Actions 只做「采集 + 清洗」（跨洋不做校验，避免误杀）→ artifact；本地做「存活校验 + 中间层 + 发布前 full 校验」
- 大文件（cleaned_*.json）已加入 .gitignore，改走 artifact（14 天），仓库只留每日摘要与 120 天趋势
- 本地等效：`scripts/run_daily_collect.sh`（替代原 run_weekly_collect.sh）

## 6. 发布流程（publisher.py）

**发布中断恢复（2026-11-06 新增）**：`is_partial_release()` 检测最新 Release 的 assets 是否缺失或 0 字节
（= 上次上传传到一半），命中则 `publish_release` 复用该 tag 补齐上传，**不再新开版本**；
两个 asset 都传齐才算发布成功，未齐会明确提示"重跑同一命令自动补齐"。

1. `git config user.name/email`（本地）→ `git add books.json clean_rules.json collect_report.md`
2. `git commit` + `git push origin main`
3. GitHub API 删除 Release v3.2 旧 assets（`DELETE /repos/{owner}/{repo}/releases/assets/{id}`）
4. `python requests` 上传新 assets（books.json + clean_rules.json）——**必须 requests，curl --data-binary 报 size must be >= 1**
5. Release 文案动态 `final_count`（`b0f1620` 修复）

**发布注意事项**：
- 发布由用户确认（用户明确要求"发布由我确认"）
- 操作前先 `GET /repos/luanmuc/legado-book-sources/releases` 重取现状（Release ID 可能变化）
- Actions 的 GITHUB_TOKEN 只读/写仓库，Release 上传用仓库级 token（workflow 不写明文 PAT）
- push 被拒（non-fast-forward）时：`git fetch && git pull --rebase` 后再推；注意 rebase 可能引入他人 commit 的文件版本（如 Actions 提交的 books.json），**push 前核对 books.json 数量**

---

## 7. 每日 / 每月任务运行方式

| 通道 | 调度 | 执行内容 | 状态 |
|------|------|----------|------|
| GitHub Actions | cron `0 2 * * 0`（周日 UTC 02:00） | 采集+清洗 → push weekly/cleaned_*.json | ✅ 已实测跑通（test 44s / full 9min） |
| 本地对话 | 用户开启对话 | `--from-cleaned ... --stage` → 中间层；确认后 `--publish-pending --publish` | 主路径 |
| 本地 crontab | `0 2 * * 0`（install_cron.sh 重建） | 全流程直接发布（备用，VM 重置会丢） | 已建/可重建 |

---

## 8. 故障排查速查

| 现象 | 原因 | 处理 |
|------|------|------|
| GitHub Actions 120 分钟超时被砍 | 跨洋 + 旧串行/短超时 | 已修复：30s 超时+20 并发+重试 3；上限 300 分钟 |
| Actions 校验合格率暴跌（72%→27%） | 跨洋误判国内书源 | 分离：采集在 Actions，校验国内网络（三层架构） |
| 沙箱重置丢 crontab/后台任务 | VM 环境重置 | `bash scripts/install_cron.sh` 重建；豆包定时可作双保险 |
| 后台任务 & /tmp 被清 | 沙箱限制 | 日志/数据落 `book-sources/logs/`、`raw/`；不依赖 /tmp |
| 内存峰值爆 | 全量载入 75 万条 | 流式 + checkpoint（clean_tmp.json 断点恢复） |
| 清洗遇损坏 JSON 崩溃 | 分片损坏 | 已容错：损坏直接跳过抛弃（用户要求） |
| 列表/合集 JSON 反爬拦截 | 无 UA/Referer | fetch_url 已带反爬头 |
| Release 上传 curl 失败 | curl --data-binary 限制 | 必须 python requests 上传 |
| push 被拒 non-fast-forward | 远端有 Actions commit | fetch + pull --rebase，核对 books.json 后再推 |
| 番茄第三方听书 API 全挂 | 非主线 | 已放弃，用户接受手机系统 TTS |
| URL 尾部混入中文/emoji（"已整理""🔞"） | 上游源作者手打注释，raw 数据脏 | clean_url 增强：剔除 URL 内中文/全角/emoji；正式版已清 24 个污染 URL |
| 失效标记大写（BAD/INVALID）漏判 | 关键词表小写、比对未统一小写 | 比对改 `k.lower() in blob` |
| 成人源被"非小说"词误剔（成人漫画等） | 垃圾分类先于成人判断 | 成人优先：先 `is_adult_source` 保留归组，再分类剔除 |
| 月份过滤解析失败整页丢弃 | all_old 误置 True | 解析失败视为不确定：保留且不置 all_old |
| 分批校验重复累计/淘汰记录丢失 | 包装结构取键用顶层 bookSourceUrl | 去重键兼容 `{source,...}` 包装结构与裸源 |
| Release 新建分支 NameError | 文案用未定义 final_count | 签名加 `final_count, rules_count`，规则数动态读取 |

---

## 9. 审计与回归

巡检管道的审计计划、检查点、证据分级与未验证项见仓库根目录 [AUDIT_PLAN.md](AUDIT_PLAN.md)。
发版前跑 `python3 scripts/audit_pipeline.py`，`FAIL` 必须为 0。

## 10. 开发约定（用户明确要求，不可违反）

- **发布必须发到 GitHub 发布页（Releases）**，不止 push main
- **发布由用户确认**；中间层合并到正式版前也必须用户确认
- 起点问题"要修复不要删除"（起点源使用 yckceo 7036 可用版，commit `fcac75a`）
- 四字纯汉字命名、去表情；笔趣阁类统一「笔趣阁+数字」排序不强制四字
- 只保留纯小说；大厂只留头部 12 个、起点第一；WAF 源（403 类）不淘汰
- 成人内容保留、单独成组（不视为垃圾）
- 损坏 JSON 分片直接跳过，不重下
- 采集月份动态（--months），默认只采最近 1 个月
- 采集范围：列表前 10 页、合集前 30 个
- 长任务维护 PROGRESS.md（最高规则）；完成后同步仓库全部相关文档

---

## 11. 数据源逆向笔记（已写进脚本，改脚本必读）

### yckceo 站点结构
```
书源列表页   https://www.yckceo.com/yuedu/shuyuan/index.html?page=N     （每页100个id）
详情id       /yuedu/shuyuan/content/id/(\d+).html                        （正则提取）
JSON直链     https://www.yckceo.com/yuedu/shuyuan/json/id/{id}.json      （list格式长度1=单源，主站直连不走CDN）
合集列表页   https://www.yckceo.com/yuedu/shuyuans/index.html?page=N    （每页100个合集id）
合集JSON     https://www.yckceo.com/yuedu/shuyuans/json/id/{cid}.json    （302跳jsdelivr CDN，海外快）
              → https://gcore.jsdelivr.net/gh/mumuceo/file01/YYYYMM/{hash}.json
合集结构     顶层为list，元素是【完整书源对象】，无需二次逐条请求（一个合集含数百个源）
时间字段     列表页/合集页均含 <p class="m-right">更新时间</p>（"3天前"/"10/26 09:26"/"2个月前"混合格式，
             由 parse_update_time 解析）
反爬         必须带 UA + Referer（fetch_url 已内置），裸请求返回拦截页
```
### 大佬仓库直链（collect_gurus）
> 2026-11-05 实测：原 4 个源中 2 个已失效并移除——
> **XIU2精品** `71e564f.json` 返回 HTTP 404（aoaostar 聚合站已删除该 id）；
> **shidahuilang** `legado3.json` 在 shuyuan/gh-pages 两个分支均 404，且仓库被 GitHub 以 tos 理由封禁
> （API 返回 "Repository access blocked"，reason=tos，网页 200 为封禁提示页）。
> 仅保留以下 2 个存活源。

| 来源 | 直链 | 规模 |
|------|------|------|
| 酷安三舞313 | `2a1f129b.json` | 1554 条 |
| 关耳女频 | `e3e5d620.json` | 86 条 |

### 净化规则源
- nyasama 书源包 `https://shuyuan.nyasama.net/shuyuan/e4a6f3324f10443a0018deba816852b3.json`（1200+条，去重后 1176 条）
- 用户自己的 nyasama 包 `6e67d2531a9076f40e3bb59f50c13e2e.json` 已移除（用户："这是我自己的书源，删掉"）

---

## 12. 采集实测数据（2026-11-05 实测，非推测）

| 数据 | 值 |
|------|-----|
| 列表每页书源数 | 100（1-20 页每页均 100，唯一 id 零重复） |
| 列表前 20 页总量 | 2000（前 10 页 = 1000） |
| 列表页时间字段 | 100/100（月份过滤可用） |
| 合集第 1 页合集数 | 100（唯一 100） |
| 合集第 1 页实际下载 | 99/100 成功 → **89,162 个书源**（平均 901 源/合集；样例 1330=794、1329=320、1328=10） |
| 合集时间字段 | 3天前/5天前/6天前/10/26… |
| months=1 合集第 1 页留存 | 13 个合集（months=2→30，months=6→100） |
| 跨洋延迟（Actions 美国 runner） | 列表页 3.3s / 列表JSON 2.2s / 合集CDN 1.9s |

---

## 13. 大厂正版源清单（12 个，config.py 保护名单）

| 序 | 名称 | URL | 序 | 名称 | URL |
|----|------|-----|----|------|-----|
| 1 | 起点中文 | https://www.qidian.com | 7 | 纵横中文 | https://m.zongheng.com |
| 2 | 番茄小说 | https://fanqienovel.com | 8 | 潇湘书院 | https://www.xxsy.net |
| 3 | 创世中文 | http://chuangshi.qq.com | 9 | 晋江文学 | https://www.jjwxc.net |
| 4 | 红袖添香 | https://hongxiua.com | 10 | 磨铁中文 | http://api.motie.com |
| 5 | 书旗小说 | https://www.shuqi.com/ | 11 | 黑岩阅读 | https://www.heiyan.com |
| 6 | QQ阅读 | https://ubook.reader.qq.com/?g_f=4000001 | 12 | 刺猬猫 | https://mm.sfacg.com |

- 保护逻辑：任何合并/整理环节以既有版本为准，新采集的同名大厂一律跳过不覆盖
- customOrder 1-12 置顶，顺序原样（起点→番茄→创世→红袖→书旗→QQ阅读→纵横→潇湘→晋江→磨铁→黑岩→刺猬猫）
- 验证基线：与 git HEAD 610 源版对比 URL 集合一致、逐字段完全一致 12/12

---

*文档版本：v3.2.6（2026-11-05）*
