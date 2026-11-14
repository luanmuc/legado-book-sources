# Legado 书源校验口径调研

> 调研日期：2026-11-14　执行人：Doubao
> 目的：对齐 Legado 官方与开源阅读社区的书源校验口径，找出本项目 `autocollect_core/validators.py`
> 与官方/社区做法的差距，避免"自己发明一套校验标准"。
> 结论已落地到代码（commit `0ea1882`），本文是可复查的依据存档。

---

## 一、官方依据：`BookSource.kt` 字段语义

来源：gedoor/legado 仓库
`app/src/main/java/io/legado/app/data/entities/BookSource.kt`

| 字段 | 官方语义 | 对本项目的意义 | 我方数据覆盖率（2140 源） |
|---|---|---|---|
| `bookSourceType` | 0=文本 / 1=音频 / 2=图片 / 3=文件 / 4=视频 | 判断"是不是小说源"的唯一权威字段 | 非 0 的 42 个（成人段 41 + 已清理） |
| `checkKeyWord` | 该源的自定义校验关键词（官方 `getCheckKeyword()` 会优先用它，空则用全局默认） | 校验搜索/发现时该用什么词 | 481 源 |
| `bookUrlPattern` | 书籍详情页 URL 的正则。官方用它判断"搜到的结果是不是真的书籍详情页" | 防止把搜索页/分类页当书 | 559 源 |
| `searchUrl` / `exploreUrl` | 搜索入口 / 发现（分类）入口 | 校验两条通道 | searchUrl 全覆盖；exploreUrl 1509 源（71%） |
| `ruleSearch` / `ruleExplore` / `ruleBookInfo` / `ruleToc` / `ruleContent` | 各阶段解析规则 | 四级链路 | 见 §六 |
| `getInvalidGroupNames()` | 返回"失效 / 校验超时"等分组名 | 官方用分组标记失效，我们用审计字段 | — |
| `removeErrorComment()` | 清除 comment 里 `// Error:` 前缀 | 我们未实现（不影响可用性） | — |

**关键认知**：`bookSourceType` 是官方唯一的类型权威字段，不是靠名字猜。判断"纯小说"必须看这个字段 + 实际站型证据。

---

## 二、社区校验口径：四项校验 / 七类失败

来源：Legado 阅读社区（QQ 频道 LegadoRead 校验科普帖）

### 2.1 内置校验实际做四件事

| 项 | 做什么 | 失败意味着 |
|---|---|---|
| 搜索校验 | 用关键词请求 `searchUrl`，能否解析出书名+链接 | 搜索规则坏 / 搜索接口挂了 |
| 详情校验 | 打开一本书的详情页，解析书名、作者等 | 详情规则坏 / 详情页改版 |
| 目录校验 | 解析章节目录 | 目录规则坏 / 目录在 JS 里 |
| 正文校验 | 打开第一章正文 | 正文规则坏 / 正文加密或需登录 |

**四项独立**：任何一项挂了都给对应标记，不是一票否决。这一点很重要——我们的原实现只检查规则字符串非空，等于四项全没做。

### 2.2 七类失败结果（社区归纳）

1. 搜索规则为空（`searchUrl` 缺失或解析不出）
2. 搜索目录为空（详情页解析不出目录）
3. 搜索失效（搜索接口 4xx/5xx）
4. 正文失效（正文解析不出内容）
5. 校验超时
6. 网站失效（域名/DNS）
7. js 失效（规则里的 JS 出错）

前 6 类我们能判；第 7 类需要执行 JS，Python 侧无法可靠模拟。

### 2.3 默认参数

- 默认校验关键词：**"我的"**（社区默认，也是我们 `GENERIC_TEST_KEYWORDS` 的第一项）
- 默认超时：官方 App 内是 **180s**（照顾慢站与反爬重试），我们用 8s（远紧）
  → 实测教训：三一读书正文需 12s，8s 会误判超时。本地专项校验应放宽到 12-15s。

---

## 三、索引语法：`class.xxx.N`

来源：书源制作教程

- `class.xxx.N` = 取 class 为 xxx 的元素列表里的**第 N 个**（0 起）
- 同族写法：`tag.a.N`、`.odd.0`、`a[0:10]`（切片）
- **关键**：`class` 名本身可以带连字符（`section-list`），所以 `.section-list.1`
  必须整体识别为「class=section-list，索引=1」，不能按 `.` 切分。

我方 1756/2140 源（82%）用到 `.N` 索引，这条语法错了影响面极大。

---

## 四、对照结论：查出的 5 处差距

| # | 差距 | 证据 | 处置 |
|---|---|---|---|
| 1 | 校验关键词忽略 `checkKeyWord` | 481 源带该字段（起点/番茄/红袖/书旗/QQ阅读等大站），原来一律用通用词池 → 这类源用错词搜索会判空 | 已修：源自带词优先，回落默认池 |
| 2 | 搜索结果不校核 `bookUrlPattern` | 559 源带该字段 | 已修：URL 全不匹配 → `blocked`（保留待验，不淘汰） |
| 3 | **只检查规则字符串非空，从不真跑详情/目录/正文** | 2140 源四块规则都"非空"，正文能否打开从未验证 | 已修：新增 `check_detail_parsed` / `check_toc_parsed` / `check_content_parsed` / `check_chain_usable`，`check_source_usable(deep=True)` 触发 |
| 4 | `_split_index` 拆错带连字符的 class | `class.section-list.1` 被拆成 `.section- list`（CSS 非法，0 匹配） | 已修：去掉末尾 `.数字`，前面整段即选择器 |
| 5 | `chapterList` 新格式取错 URL | 新格式只选元素，URL 须按 `chapterUrl` 规则取；原实现把章节名当链接请求 → 404 | 已修：新增 `legado_rules.parse_first_attr` |

---

## 五、实测：字段可得性（决定"能不能做站点质量画像"）

| 可解析字段 | 覆盖源数 | 占比 | 用途 |
|---|---|---|---|
| `bookSourceType` | 2140 | 100% | 类型判定 |
| `searchUrl` | 2140 | 100% | 搜索通道 |
| `exploreUrl` | 1509 | 71% | 发现/分类通道 |
| `ruleBookInfo.kind`（分类/状态） | 1771 | 83% | 完本/连载判断 |
| `ruleBookInfo.lastChapter`（最新章节） | 1758 | 82% | 更新活跃度 |
| `ruleBookInfo.wordCount`（字数） | 591 | 28% | 完本佐证（完本通常字数大） |
| `ruleSearch.kind` | 1531 | 72% | 同 kind |
| `ruleSearch.lastChapter` | 1228 | 57% | 同 lastChapter |
| `exploreUrl` 含"完本/全本/完结"分类 | 567 | 26% | **最可靠的完本入口** |
| `exploreUrl` 含"连载/更新"分类 | 348 | 16% | 活跃度佐证 |
| `bookUrlPattern` | 559 | 26% | 详情页正则 |
| `checkKeyWord` | 481 | 22% | 校验关键词 |

**结论**：站点质量画像有数据基础，但覆盖不均——约 8 成源能拿到 kind/lastChapter，2 成只有分类页入口可判。

---

## 六、deep 链路校验的实测边界（重要，别误用）

抽样 24 源跑 `--deep`：

| 结果 | 数量 | 说明 |
|---|---|---|
| `None`（无法判定） | 17 | 反爬、Cloudflare、跨洋网络、慢站超时 |
| `False`（确认不通） | 2 | — |
| `True`（确认通） | 5 | 详情+目录+正文全通 |

**不可判定率 71%**。因此：

- ❌ 不能用于自动淘汰（会大面积误杀）
- ✅ 只能作为本地专项诊断 + 发布前人工复核线索
- ✅ 自动发布仍走"浅校验 + 明确死站剔除"

这与既有认知一致：内容真实性校验必须在国内网络，Actions 的美国网络跨洋合格率只有 27%。

---

## 七、踩过的坑（都是自测才暴露，看代码看不出来）

### 坑 1：`NameError` 被宽 `except` 吞成"解析不出"

`parse_rule_list` 忘了 import → 抛 `NameError` → 被 `_pick_first_value` 里的
`except Exception` 捕获 → 返回 `None` → 好源"三一读书"被判详情失效。

**修法**：`_pick_first_value` 收窄捕获，`NameError` / `ImportError` 必须抛出。
**教训**：宽捕获会把"代码 bug"伪装成"数据问题"，诊断时会顺着错误方向排查很久。

### 坑 2：`chapterList` 只选元素，URL 要单独取

新格式 `ruleToc.chapterList` 只负责选出章节元素，章节 URL 必须按
`ruleToc.chapterUrl`（或 `chapterList` 自带 `@attr`）取。
我把章节名当链接去请求 → 404 → 误判"正文失效"。

### 坑 3：`class` 名带连字符时索引拆错

见 §三。影响 82% 的源。

---

## 八、来源清单

| 内容 | 地址 |
|---|---|
| 官方实体定义 | `https://raw.githubusercontent.com/gedoor/legado/master/app/src/main/java/io/legado/app/data/entities/BookSource.kt` |
| 社区校验科普（四项/七类失败/默认关键词） | `https://pd.qq.com/g/LegadoRead3/post/B_6cf11d67a7da03001441152192590164580X60` |
| 书源制作教程（`class.xxx.N` 索引语法） | `https://damingzhijun.github.io/mymob/阅读书源教程/教程.html` |

---

## 九、后续可做（未实现，留档）

1. **站点质量画像工具**（`scripts/site_profile.py`）：对每源采样 N 本，统计完本率、更新活跃度、书目规模。数据基础见 §五，但需国内网络、耗时大，不宜进 CI。
2. **`removeErrorComment` 对齐**：清理 comment 里的 `// Error:` 前缀（低优先级）。
3. **超时参数分级**：deep 专项校验放宽到 12-15s，自动浅校验保持 8s。
