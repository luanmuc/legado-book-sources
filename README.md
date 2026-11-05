# Legado 阅读书源仓库

## 📖 项目介绍
这是一个开源阅读（Legado）书源整理仓库，持续更新维护。

## 📊 当前版本
- **版本**: 发布页 v3.2.10（2026-11-06 发布，assets 已验证完整）
- **更新日期**: 2026-11-06
- **书源总数**: 807 个（纯小说 + 成人组全保留；剔除 393 确认失效 + 141 无法验证源；并入 88 个二次复检合格源）
- **净化规则**: 1176 条配套净化

## 🏷️ 分组统计
| 分组 | 数量 | 说明 |
|------|------|------|
| 综合其他 | 562 | 其他各类小说站 |
| 成人书源 | 144 | 成人内容全保留（含漫画/短剧/图片类），排序最末（664-807）、豁免改名与符号清理 |
| 笔趣阁类 | 72 | 笔趣阁镜像站（同族聚合，数字递增排序） |
| 言情女频 | 9 | 言情/女频类 |
| 大厂正版 | 12 | 正版大站，需登录使用（永不淘汰） |
| 玄幻武侠 | 8 | 玄幻/武侠类 |

## 🏢 大厂正版列表（共12个）
按优先级排序，导入后排在最前面：

| 序号 | 名称 | 需要登录 | 说明 |
|------|------|----------|------|
| 1 | 起点中文 | ✅ 是 | https://www.qidian.com |
| 2 | 番茄小说 | ✅ 是 | https://fanqienovel.com |
| 3 | 创世中文 | ❌ 否 | http://chuangshi.qq.com |
| 4 | 红袖添香 | ✅ 是 | https://hongxiua.com |
| 5 | 书旗小说 | ✅ 是 | https://www.shuqi.com/ |
| 6 | QQ阅读 | ✅ 是 | https://ubook.reader.qq.com/?g_f=4000001 |
| 7 | 纵横中文 | ❌ 否 | https://m.zongheng.com |
| 8 | 潇湘书院 | ✅ 是 | https://www.xxsy.net |
| 9 | 晋江文学 | ✅ 是 | https://www.jjwxc.net |
| 10 | 磨铁中文 | ❌ 否 | http://api.motie.com |
| 11 | 黑岩阅读 | ✅ 是 | https://www.heiyan.com |
| 12 | 刺猬猫 | ✅ 是 | https://mm.sfacg.com |

## 📥 导入方法

**书源导入：**
1. 下载最新版 books.json
2. 打开阅读APP → 我的 → 书源管理 → 本地导入
3. 选择下载的 books.json 文件即可

**配套净化规则：**
1. 下载 clean_rules.json
2. 打开阅读APP → 我的 → 替换净化 → 本地导入
3. 自动过滤网页广告、弹窗、无用内容

## 🔍 校验流程
校验分两档（2026-11 用户明确要求）：

| 档位 | 时机 | 内容 | 特点 |
|------|------|------|------|
| **快速存活**（quick） | 采集池第一遍（`--collect` / `validate` 默认） | 首页可达性 + WAF 识别，快速剔除死站 | 量大也能几分钟跑完 |
| **完整真实性**（full） | **发布前**（`--publish-pending` / `validate --full` / `final --publish`） | 存活 + 搜索/发现至少一项可用 + 全部过滤规则 | 一步不少，慢但发布必跑 |

发布前完整执行以下校验（一步不少）：

1. **基础结构校验**：必填字段、URL 格式、域名去重
2. **网站存活校验**：首页可达性（WAF 盾站 403/405/503 不淘汰）
3. **真实性校验——搜索/发现至少一项可用**（2026-11 新增，解决"网站活着 ≠ 书源有效"）：
   - **搜索**：通用关键词轮试（我的/天下/重生/总裁/王爷/系统/都市/修仙/神/爱），用书源自身 `ruleSearch.bookList` 规则**真实解析 HTML**，解析出 ≥1 本书才算可用
   - **发现**：`exploreUrl` 前 3 个入口轮试，用 `ruleExplore.bookList` 解析，**至少 1 个入口解析出书才算可用**（发现页按钮至少一个能用）
   - **判定**：搜索或发现任一可用 → 保留；两者都解析不出 → 淘汰（识别"域名还在但内容已换/域名挂售"的失效源）；网络/反爬无法判定 → 保留待验
   - **成人源按实际情况校验（宽松豁免）**：成人组混有漫画/短剧/影视/图片/听书站，本来就没有"书名"可解析，拿书籍规则硬卡必然误杀。改为判"至少有一条能取内容的规则链"（正文/目录/搜索/发现任一条非空）→ 可用保留；四条全空的空壳规则才淘汰；死站仍照常淘汰（失效不保留）
   - 12 个大厂源永不淘汰（反爬环境判定不可靠，阅读器端可用）
4. **规则完整性校验**：详情/目录/正文规则完整性
5. **垃圾过滤**：非小说/测试/失效标记剔除；**成人内容一律保留**（含成人漫画/影视等非小说类），成人组排序最末、豁免改名与符号清理

> 发布（`--publish-pending`）时同样全量执行上述校验，一步不少。

## 🤖 自动采集脚本
本仓库内置全自动采集脚本 `autocollect.py`，可一键采集、校验、合并书源。

### 数据源池
- yckceo.com 书源列表（前10页最新上传的源，每页100个）
- yckceo.com 书源合集（列表前30个大佬整理的合集，每个合集含数百个源）
- 2个直链大佬仓库（酷安三舞313/关耳女频；原XIU2精品与shidahuilang已于2026-11失效：71e564f.json 404、shidahuilang/shuyuan 被GitHub以tos封禁）

### 自动更新
- **采集层**：GitHub Actions 每周日自动采集+清洗（跨洋已优化：30s超时+20并发+重试），结果 push 到 `weekly/cleaned_*.json`，全程无人值守
- **中间层**：本地（国内网络）从 cleaned 继续：**快速存活校验（quick，量大只判站点活着）** + 垃圾过滤（成人豁免）+ 整理 → 合并进 `books_pending.json`（不碰正式版）
- **正式版**：确认后把中间层提升为 books.json + clean_rules，**发布前自动跑完整真实性校验（full，一步不少）**，并自动发新版本 Release（vX.Y.Z patch+1）
- **断点续传**：采集/清洗/校验全链路支持中断恢复——校验每批落盘 checkpoint（`raw/autocollect/ckpt_*.json`），对话中断或沙箱重置后重跑同一命令自动跳过已验源，只补未验部分（详见 DEVELOPMENT.md 断点矩阵）

> ⚠️ 采集与校验分离的原因：GitHub Actions 免费 runner 位于美国，访问国内站点**采集**已通过加大超时+并发+重试跑通（实测单请求 2-3s）；但**存活/搜索校验**针对国内书源站点，跨洋会大量误判（合格率 72%→27%），因此校验必须在国内网络执行。

### 三层架构（采集 → 中间层 → 正式版）
```
采集层（GitHub Actions 每周自动，跨洋已优化）     中间层（本地国内网络）        正式版
list前10页+合集前30个+大佬仓库  → 清洗去重 → weekly/cleaned_*.json
                                                        ↓
快速存活校验(quick) + 垃圾过滤 + 整理 → 合并进 books_pending.json（待你确认，不动正式版）
                                                        ↓ 你确认后
books_pending.json 完整真实性校验(full) → books.json + clean_rules + Release 新版本
```

### 使用方法
```bash
# ① GitHub Actions 每周自动：采集+清洗 → weekly/cleaned_*.json（已配置 schedule 每周日 UTC 02:00）

# ② 本地：从 Actions 采集结果继续 → 合并进中间层（每次采集都并入，等你确认）
python3 autocollect.py --from-cleaned weekly/cleaned_XXX.json --stage

# ③ 本地：确认后把中间层提升为正式版并发布（发布由你确认）
python3 autocollect.py --publish-pending --publish

# 一键（cron 每周自动）：采集 → 清洗 → 并入中间层（quick 存活校验，不发布）
bash scripts/run_weekly_collect.sh 1

# 或手动分步执行（每步独立落盘、可断点恢复）：
python3 scripts/collect_staged.py list --months 1      # A1: 采集yckceo书源列表前10页
python3 scripts/collect_staged.py heji 1 1 --months 1 --limit 30  # A2: 合集只采列表前30个（每个含多源）
python3 scripts/collect_staged.py gurus                # A3: 2个存活大佬仓库直链
python3 scripts/run_from_fragments.py clean            # B: 流式合并清洗去重(checkpoint)
python3 scripts/run_from_fragments.py validate --start 0 --count 1000   # C: 分批快速存活校验（发布前用 --full 切完整真实性）
python3 scripts/filter_junk_sources.py                 # D: 垃圾过滤(成人单独分组)
python3 scripts/run_from_fragments.py final --input raw/autocollect/validated_clean.json --publish  # E: 整理+发布（--publish 时自动跑发布前 full 复检）

# 单命令完整流程（适合交互调试，沙箱环境可能中断）
python3 autocollect.py --publish --months 1
```

### 优化特性
- **增量采集**：`--months N` 按更新时间过滤，只采集最近N个月的列表/合集，超范围自动停止翻页
- **两级过滤**：快速连通性过滤 + 完整搜索测试（3关键词），节省时间
- **域名去重**：同一站多域名自动合并，保留最优规则
- **WAF友好**：403盾站不淘汰，能搜出书就保留
- **大厂保护**：12个正版大站单独保护，任何环节不被覆盖
- **垃圾过滤**：剔除失效标记/测试占位/非小说，成人内容单独归组
- **自动报告**：每次跑完生成采集报告，采集/清洗/淘汰/入库一目了然
- **断点恢复**：采集分片独立落盘、清洗checkpoint、校验分批追加，中断零损失
- **跨洋优化**：超时/重试/并发可环境变量调节（YCKCEO_TIMEOUT/RETRY/CONCURRENCY）
- **三层隔离**：采集→中间层（待确认）→正式版，正式版不被自动更新直接覆盖

### 模块化结构（v3.2.6）
核心逻辑在 `autocollect_core/` 包，主入口 `autocollect.py`；`scripts/` 提供分步执行脚本（每周任务主路径）：

```
autocollect.py              # 主入口（五阶段编排 + 三层架构：--collect-only/--stage/--publish-pending）
autocollect_core/
├── config.py               # 配置区：数据源/关键词/路径/请求参数(支持环境变量覆盖)
├── utils.py                # 日志 + 工具（fetch_url带反爬头/clean_url/get_domain）
├── collectors.py           # 采集：yckceo列表/合集(按月份过滤+前N个)/大佬仓库
├── cleaner.py              # 清洗去重 + 大厂判断 + 垃圾过滤/成人归组
├── validators.py           # 规则完整性/快速/完整/两级校验
├── organizer.py            # 四字改名/分组/customOrder/大厂保护
├── cleanrules.py           # 净化规则采集/优化/生成
├── report.py               # 采集报告（真实统计）
└── publisher.py            # git推送 + 发布页Release更新
scripts/
├── run_weekly_collect.sh   # 一键分步全流程（采集→清洗→校验→过滤→整理→发布）
├── collect_staged.py       # 分段采集（list/heji/gurus，--months/--limit）
├── collect_heji_ids.py     # 阶段A: 提取合集列表全部ID
├── collect_heji_batch.py   # 阶段B: 逐合集独立落盘批量下载（断点续传）
├── run_from_fragments.py   # 分片恢复: clean/validate/final(可--publish)
├── filter_junk_sources.py  # 垃圾过滤+成人分组（复用核心函数）
└── install_cron.sh         # 一键重建本地crontab（备用触发）
```

> 完整开发文档见 [DEVELOPMENT.md](DEVELOPMENT.md)：模块职责、数据流、CLI 参数全集、发布流程、故障排查。
> 中断恢复（对话/额度/沙箱重置/发布传到一半）见 [RESUME.md](RESUME.md)；
> 任何接续先跑 `python3 scripts/status.py` 拿真实状态。

## ✏️ 命名规范
- 大厂正版保留原名（起点中文/番茄小说等）
- 其他源四字纯汉字（不足补足、无中文兜底），重名加数字
- 笔趣阁类统一「笔趣阁+数字」排序
- 去掉表情符号和特殊字符
- **成人书源豁免**：保留原名原样（含特殊符号/表情），仅重名时加数字；仍参与名字族排序，整组排在最后
- 同名族聚合：同名前缀的源（笔趣阁1/2/3…）相邻排序，序号按数值递增
- **同族名字聚合排序**：组内按"名字族+数值"自然排序（笔趣阁 → 笔趣阁2 → … → 笔趣阁141 相邻且数值递增），customOrder 字段控制导入后顺序
- 分组顺序固定：大厂正版（12，手动顺序保护）→ 笔趣阁类 → 玄幻武侠 → 言情女频 → 综合其他 → 成人书源

## 📝 更新日志
- v3.2.10 (2026-11-06) 已发布: 校验真实性彻底做实——补齐 9 类 Legado 规则解析缺口（`!N` 排除索引 / `[a:b]` 负数切片 / 裸多 class / `@css:` 前缀 / `tbody` 透明层 / 脚本与 JSONPath 规则判 blocked 不误杀 / SPA 页判 blocked / 单引号 JSON 配置 / 智能编码打分），POST 空结果自动回退 GET。1336 源 4 轮真实解析重测：可用 537→707，确认失效 393 剔除，1345→943 源；成人判定去掉 group 自证 bug，回溯校正 6 个误分组源
- v3.2.8 (2026-11-05): 中间层合并发布——708 个新源经发布前完整校验并入正式版，929→1359（新增430）；同族名字聚合排序（笔趣阁系 13-153 连续递增）；合并路径统一 clean_url 防 URL 污染残留；发布策略升级：每次发布自动开新版本号
- v3.2.7 (2026-11-05): 全代码审计修复——移除失效gurus源(XIU2 404/shidahuilang仓库tos封禁)/失效标记关键词大小写漏判修复/成人源优先保留(名字含漫画等不再误剔)/月份过滤解析失败不再误停整页/合集下载改并发/publisher Release文案NameError修复/分批校验与淘汰落盘去重键修复/merge不再混入中间产物/日志统一落logs/；数据修复：books.json清理24个URL污染(上游手打"已整理/昵称"注释)，clean_url增强剔除中文与emoji污染
- v3.2.6 (2026-11-05): 三层架构（采集→中间层→正式版）+ 跨洋采集打通——GitHub Actions 每周自动采集+清洗 push weekly/cleaned（30s超时+20并发+重试解决跨洋）；本地 --stage 合并进 books_pending.json 等你确认，--publish-pending 确认后提升正式版+发布
- v3.2.5 (2026-11-05): 采集范围收敛——书源列表只采前10页、书源合集只采列表前30个（每个合集含数百个源；实测第1页100合集=约8.9万源）
- v3.2.4 (2026-11-05): 全对话复盘维护——修复清洗脚本漏读raw_heji_*.json分片断链/默认采集月份改1(贴合"只采集当前一个月")/清理4个死代码脚本(crawler/pipeline/validate/rename)
- v3.2.3 (2026-11-05): 脚本维护——months参数真正生效（按更新时间过滤，超范围自动停止）/周任务改分步执行/报告真实统计/校验淘汰落盘
- v3.2.2 (2026-11-05): 全自动采集链路升级——两阶段采集（提取链接+批量下载）/流式清洗/两级校验/垃圾过滤/命名规范化，书源 610→929
- v3.2.1 (2026-11-05): 脚本模块化重构，拆分为 autocollect_core/ 9模块包
- v3.2 (2026-11-01): 修复起点书源分类页加载为空的问题
- v3.1 (2026-11-01): 全自动脚本升级：真实搜索校验/净化规则自动优化/两级过滤/自动发布
- v3.0 (2026-10-31): 新增全自动采集脚本，每周日自动跑
- v2.8 (2026-10-30): 删除微信读书/17K，大厂剩12个
- v2.7 (2026-10-30): 大厂源扩充到14个，带登录配置
- v2.6 (2026-10-30): 设置customOrder排序字段
- v2.5 (2026-10-30): 重新按分组排序
- v2.4 (2026-10-30): 删除吾爱破解/豆瓣读书等非小说站
- v2.3 (2026-10-30): 删除漫画/听书/影视，纯小说版
- v2.2 (2026-10-30): 新增nyasama星辰整理书源包
- v2.1 (2026-10-30): 合并全网大佬书源
- v2.0 (2026-10-30): 初始版本，9-10月合集采集

## 📄 许可证
本项目基于 [MIT License](LICENSE) 开源。书源数据来自公开渠道（yckceo.com 等），仅供学习交流使用，请遵守相关站点规则与法律法规。

## 🔗 相关链接
- 仓库地址：https://github.com/luanmuc/legado-book-sources
- 最新下载：https://github.com/luanmuc/legado-book-sources/releases/latest
