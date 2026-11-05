# 开发文档（DEVELOPMENT.md）

> Legado 阅读书源仓库自动采集系统的架构、数据流、CLI、发布与故障排查说明。
> 维护者视角的完整手册。用户文档见 [README.md](README.md)。

---

## 1. 系统架构：三层隔离

```
┌─ 采集层（GitHub Actions 每周日自动，无人值守）─────────────────────────┐
│ .github/workflows/auto-update.yml                                     │
│   → collect_staged 逻辑（collectors.py）                               │
│   → yckceo列表(前10页) + 合集(前30个) + 大佬仓库(4个)                  │
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
│   → auto_publish：git commit+push + Release v3.2 assets 更新           │
└──────────────────────────────────────────────────────────────────────┘
```

**为什么采集与校验分离**：GitHub Actions 免费 runner 在美国，跨洋访问国内站点
采集可行（实测列表页 3.3s / JSON 2.2s / CDN 1.9s），但存活/搜索校验针对国内书源站
跨洋大量误判（合格率 72% → 27%）。因此：**采集在 Actions，校验必须国内网络**。

---

## 2. 模块职责

### autocollect_core/（9 模块，核心逻辑单一数据源）

| 模块 | 职责 | 关键函数 |
|------|------|----------|
| `config.py` | 常量：大厂12清单、垃圾/成人关键词表、数据源URL、路径、请求参数 | `BIG_SITE_*`、`JUNK_*`、`ADULT_GROUP`、`REQUEST_TIMEOUT/RETRY/CONCURRENCY`（支持 `YCKCEO_*` 环境变量覆盖） |
| `utils.py` | 日志、反爬请求、域名工具 | `fetch_url(url, timeout, retry)`（UA+Referer+verify=False）、`clean_url`、`get_domain` |
| `collectors.py` | 采集三路数据源 | `collect_yckceo_list(months, page_start, page_end)`、`collect_yckceo_heji(months, page_start, page_end, limit)`、`collect_gurus()`、`collect_all(months)`；`parse_update_time`/`extract_update_times`/`filter_by_months`（时间过滤） |
| `cleaner.py` | 清洗去重 + 分类判定 | `clean_and_dedup(raw)`（流式+checkpoint）、`is_big_site`、`classify_junk`/`is_adult_source`/`filter_junk_sources` |
| `validators.py` | 两级校验 | `check_rule_integrity`（详情/目录/正文规则）、`quick_validate`（连通性，WAF 403 不淘汰）、`full_validate`（3 关键词搜索）、`validate_sources(cleaned)` → `(validated, dead)` |
| `organizer.py` | 整理输出 | `organize_sources(validated, existing)`（大厂保护最顶 + 四字改名 + 分组排序 + customOrder） |
| `cleanrules.py` | 净化规则 | `collect_clean_rules()`（nyasama 包）、`generate_clean_rules(final, rules)`（去重优化输出） |
| `report.py` | 采集报告 | `generate_report(raw, cleaned, dead, final, big_count)`（真实统计） |
| `publisher.py` | 发布 | `auto_publish(final_count, big_count)`（git 配置→add→commit→push→删旧 assets→requests 上传 Release） |

### scripts/（分步执行，断点恢复友好）

| 脚本 | 用途 |
|------|------|
| `run_weekly_collect.sh` | 一键分步全流程（MONTHS 参数，默认 1；A 采集→B 清洗→C 分批校验→D 垃圾过滤→E 整理发布） |
| `collect_staged.py` | 分段采集：`list`（前10页）/ `heji start end`（--limit 默认30）/ `gurus` |
| `collect_heji_ids.py` | 提取合集列表全部 id → `heji_ids.json` |
| `collect_heji_batch.py` | 逐合集独立落盘下载（断点续传，中断零损失） |
| `run_from_fragments.py` | 分片恢复：`clean`（合并分片+清洗，兼容 raw_heji_*.json 与 heji/*.json 两种路径）/ `validate --start --count`（分批）/ `final --input --publish` |
| `filter_junk_sources.py` | 垃圾过滤+成人归组（复用 cleaner 核心函数） |
| `install_cron.sh` | 一键重建本地 crontab（每周日 02:00，VM 重置后恢复用） |

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

1. **格式校验**：必填字段（bookSourceUrl/searchUrl）、JSON 结构
2. **规则完整性**：ruleBookInfo/ruleSearch/ruleDetail/ruleContent 等非空、类型正确（dict 防御）
3. **快速存活过滤**：首页 + 搜索接口连通性；**WAF（403/405/503）不淘汰**（能搜出书就保留）
4. **完整搜索校验**：3 个关键词搜索测试，淘汰低质量
5. **垃圾过滤**：非小说/测试占位/失效标记剔除；**成人内容保留归组** `bookSourceGroup="成人书源"`
6. **大厂保护**：12 个大厂任何环节不覆盖（合并时以既有版本为准）
7. 校验淘汰原因落盘 `dead.json`，报告真实统计

---

## 6. 发布流程（publisher.py）

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

## 7. 周任务运行方式

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

---

## 9. 开发约定（用户明确要求，不可违反）

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

## 10. 数据源逆向笔记（已写进脚本，改脚本必读）

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
| 来源 | 直链 | 规模 |
|------|------|------|
| 酷安三舞313 | `2a1f129b.json` | 1554 条 |
| 关耳女频 | `e3e5d620.json` | 86 条 |
| XIU2精品 | `71e564f.json` | 22 条 |
| shidahuilang | `legado3.json` | 939 条 |

### 净化规则源
- nyasama 书源包 `https://shuyuan.nyasama.net/shuyuan/e4a6f3324f10443a0018deba816852b3.json`（1200+条，去重后 1176 条）
- 用户自己的 nyasama 包 `6e67d2531a9076f40e3bb59f50c13e2e.json` 已移除（用户："这是我自己的书源，删掉"）

---

## 11. 采集实测数据（2026-11-05 实测，非推测）

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

## 12. 大厂正版源清单（12 个，config.py 保护名单）

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
