# 中断恢复手册（RESUME.md）

> 任何中断（豆包对话额度耗尽 / 上下文丢失 / 沙箱或 VM 重置 / 网络断开 / 命令超时被杀 / 发布传到一半）
> 恢复时**只做这五步**，禁止凭记忆重做已完成步骤。

## 一、接续五步（固定顺序）

```bash
# 第 1 步：定位工作分区（持久卷，不是 /tmp）
cd /home/user/Doubao/chats/38450368417489154

# 第 2 步：读进度记录（本任务唯一事实来源）
cat PROGRESS.md

# 第 3 步：验证真实状态（一条命令，覆盖本地+发布页）
cd book-sources && python3 scripts/status.py

# 第 4 步：按下面的「场景 → 续跑命令」表，从断点继续（命令本身幂等/带断点，重跑不重复劳动）

# 第 5 步：本步完成后立即更新 PROGRESS.md（写清已完成/中断点/下一步命令）
```

**核心原则**：`status.py` 的输出是唯一可信状态；PROGRESS.md 是唯一可信计划。
两者冲突时以 status.py 的实际文件为准，并在 PROGRESS.md 里纠正。

## 二、场景 → 续跑命令

| 中断场景 | 判定标志（status.py 看到什么） | 续跑命令（直接跑，自动续） |
|---|---|---|
| 对话/额度中断，采集中途 | `raw_*.json` / `heji/` 分片不完整 | `python3 scripts/collect_staged.py list --months 1` 等，已下载的分片自动跳过 |
| 采集中途（合集大批量） | `heji/` 少若干 cid | `python3 scripts/collect_heji_batch.py`（逐合集落盘，已下载的跳过） |
| 清洗中断 | `ckpt_clean*.json` 存在 | `python3 scripts/run_from_fragments.py clean`（流式 checkpoint 续） |
| 采集池校验中断（quick） | `ckpt_*_quick_*.json` | 重跑同一命令（`autocollect.py --from-cleaned X --stage`），已验源自动跳过 |
| 发布前校验中断（full） | `ckpt_pending_full_*.json` | `python3 autocollect.py --publish-pending --publish`，已验源自动跳过 |
| 专项真实性检测中断 | `ckpt_usable.json` | `python3 scripts/check_usable.py`，已测 URL 自动跳过 |
| git push 失败 | `git status -sb` 显示 ahead | `git push origin main`（提交已在本地） |
| 发布页上传中断 | 最新 Release assets 缺一个或 0 字节 | 重跑发布命令：**自动复用该版本补齐，不会新开空壳版本** |
| VM/沙箱重置 | `crontab -l` 无 `run_weekly_collect` | `bash scripts/install_cron.sh`（幂等重建周任务） |
| 暑假/长期停机后恢复 | 上次 cleaned 很旧 | `python3 scripts/status.py` 核对 → 直接跑 `bash scripts/run_weekly_collect.sh 1` |

## 三、断点落盘位置（全部在持久区）

| 环节 | 断点文件 | 完成后 |
|---|---|---|
| 采集列表 | `raw/autocollect/raw_list.json` | 保留 |
| 采集合集 | `raw/autocollect/heji/{cid}.json`（一个合集一个文件） | 保留 |
| 清洗 | `raw/autocollect/ckpt_clean_tmp.json` | 自动清理 |
| 校验（quick/full） | `raw/autocollect/ckpt_{tag}_{mode}_{validated,dead}.json` | 全部验完后自动清理 |
| 专项检测 | `raw/autocollect/ckpt_usable.json` | 手动清理才会重测 |
| 发布页 | GitHub Release assets 本身（缺 asset = 中断标志） | 复用补齐 |

## 四、禁止事项（踩过的坑）

1. **禁止把任何产物写 `/tmp` 或根目录**——历史 3 次重置（10:48/12:17/14:36）只清这两处。
2. **禁止凭记忆重跑已完成步骤**——先 `status.py`，再决定从哪一步续。
3. **禁止在跨洋网络（GitHub Actions 美国 runner）做存活/真实性校验**——误杀率极高（合格率 72%→27%），Actions 只采集+清洗。
4. **禁止跳过发布前完整校验**（`--publish` 前必须 full 档，一步不少）。
5. **禁止自动发布正式版**——中间层 `books_pending.json` 必须由用户确认后才 `--publish-pending`。
6. **禁止用整个 JSON blob 匹配失效关键词**——会误杀（曾误删 414 个源含 4 大厂），只允许匹配 `bookSourceName/bookSourceUrl/bookSourceComment`。
7. **禁止一个进程跑十几小时不带断点**——长循环必须每批落盘。
