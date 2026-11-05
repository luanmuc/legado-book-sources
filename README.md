# Legado 阅读书源仓库

## 📖 项目介绍
这是一个开源阅读（Legado）书源整理仓库，持续更新维护。

## 📊 当前版本
- **版本**: v3.2.6
- **更新日期**: 2026-11-05
- **书源总数**: 929 个（纯小说）
- **净化规则**: 1176 条配套净化

## 🏷️ 分组统计
| 分组 | 数量 | 说明 |
|------|------|------|
| 大厂正版 | 12 | 正版大站，需登录使用 |
| 综合其他 | 701 | 其他各类小说站 |
| 成人书源 | 114 | 特殊题材，按需启用 |
| 笔趣阁类 | 89 | 笔趣阁镜像站（统一数字排序） |
| 言情女频 | 10 | 言情/女频类 |
| 玄幻武侠 | 3 | 玄幻/武侠类 |

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
所有书源都经过以下四阶段校验：
1. **基础结构校验**：必填字段、URL格式、域名去重
2. **网站存活校验**：首页可达性检测（WAF盾站不淘汰）
3. **搜索接口校验**：3个关键词实测搜索（快速连通性过滤 + 完整搜索测试）
4. **规则完整性校验**：详情/目录/正文规则完整性

> 发布（`--publish-pending`）时同样全量执行上述校验，一步不少。

## 🤖 自动采集脚本
本仓库内置全自动采集脚本 `autocollect.py`，可一键采集、校验、合并书源。

### 数据源池
- yckceo.com 书源列表（前10页最新上传的源，每页100个）
- yckceo.com 书源合集（列表前30个大佬整理的合集，每个合集含数百个源）
- 4个直链大佬仓库（酷安三舞313/关耳女频/XIU2精品/shidahuilang）

### 自动更新
- **采集层**：GitHub Actions 每周日自动采集+清洗（跨洋已优化：30s超时+20并发+重试），结果 push 到 `weekly/cleaned_*.json`，全程无人值守
- **中间层**：本地（国内网络）从 cleaned 继续：校验+垃圾过滤+整理 → 合并进 `books_pending.json`（不碰正式版）
- **正式版**：确认后把中间层提升为 books.json + clean_rules，并自动更新 GitHub 发布页（Releases）

> ⚠️ 采集与校验分离的原因：GitHub Actions 免费 runner 位于美国，访问国内站点**采集**已通过加大超时+并发+重试跑通（实测单请求 2-3s）；但**存活/搜索校验**针对国内书源站点，跨洋会大量误判（合格率 72%→27%），因此校验必须在国内网络执行。

### 三层架构（采集 → 中间层 → 正式版）
```
采集层（GitHub Actions 每周自动，跨洋已优化）     中间层（本地国内网络）        正式版
list前10页+合集前30个+大佬仓库  → 清洗去重 → weekly/cleaned_*.json
                                                        ↓
校验+垃圾过滤+整理 → 合并进 books_pending.json（待你确认，不动正式版）
                                                        ↓ 你确认后
books_pending.json 提升为 books.json + clean_rules + Release 更新
```

### 使用方法
```bash
# ① GitHub Actions 每周自动：采集+清洗 → weekly/cleaned_*.json（已配置 schedule 每周日 UTC 02:00）

# ② 本地：从 Actions 采集结果继续 → 合并进中间层（每次采集都并入，等你确认）
python3 autocollect.py --from-cleaned weekly/cleaned_XXX.json --stage

# ③ 本地：确认后把中间层提升为正式版并发布（发布由你确认）
python3 autocollect.py --publish-pending --publish

# 一键完整流程（不分层，直接出正式版，适合交互调试）
bash scripts/run_weekly_collect.sh 1

# 或手动分步执行（每步独立落盘、可断点恢复）：
python3 scripts/collect_staged.py list --months 1      # A1: 采集yckceo书源列表前10页
python3 scripts/collect_staged.py heji 1 1 --months 1 --limit 30  # A2: 合集只采列表前30个（每个含多源）
python3 scripts/collect_staged.py gurus                # A3: 4个大佬仓库直链
python3 scripts/run_from_fragments.py clean            # B: 流式合并清洗去重(checkpoint)
python3 scripts/run_from_fragments.py validate --start 0 --count 1000   # C: 分批两级校验
python3 scripts/filter_junk_sources.py                 # D: 垃圾过滤(成人单独分组)
python3 scripts/run_from_fragments.py final --input raw/autocollect/validated_clean.json --publish  # E: 整理+发布

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

## ✏️ 命名规范
- 大厂正版保留原名（起点中文/番茄小说等）
- 其他源四字纯汉字（不足补足、无中文兜底），重名加数字
- 笔趣阁类统一「笔趣阁+数字」排序
- 去掉表情符号和特殊字符
- 按分组+域名排序，customOrder字段控制导入后顺序

## 📝 更新日志
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
