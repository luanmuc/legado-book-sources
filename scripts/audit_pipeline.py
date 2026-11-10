#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""巡检管道审计（只读，不改任何数据）

对象：每日采集 workflow → 中间层 → 每月自动合并发布 workflow 全链路。
方法：每个检查点给「判定标准 + 证据 + 结论」，结论分级：
  PASS  已用产物/结构/运行路径证据确认
  WARN  能跑但有隐患（会静默降级或需要人工兜底）
  FAIL  当前口径下会产错结果

用法：
  python3 scripts/audit_pipeline.py           # 输出表格
  python3 scripts/audit_pipeline.py --json    # 机器可读，供文档同步
"""
import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import yaml

CHECKS = []


def check(cid, dim, name, standard):
    def deco(fn):
        CHECKS.append((cid, dim, name, standard, fn))
        return fn
    return deco


def read(p):
    path = os.path.join(ROOT, p)
    return open(path, encoding="utf-8").read() if os.path.exists(path) else ""


def load_wf(p):
    try:
        return yaml.safe_load(read(p))
    except Exception as e:
        return {"_error": str(e)}


# ---------- A 调度与触发 ----------
@check("A1", "调度", "cron 与预期时区一致",
       "daily=17:07 UTC(北京01:07)、monthly=20:00 UTC(北京次日04:00)")
def a1():
    d = load_wf(".github/workflows/auto-update.yml")
    m = load_wf(".github/workflows/monthly-release.yml")
    dc = d[True]["schedule"][0]["cron"]
    mc = m[True]["schedule"][0]["cron"]
    ok = dc == "7 17 * * *" and mc == "0 20 1 * *"
    return ("PASS" if ok else "FAIL", f"daily={dc} monthly={mc}")


@check("A2", "调度", "schedule 触发时 inputs 为空可兜底",
       "shell 用 ${VAR:-默认} 兜底，不能靠 inputs 必有值")
def a2():
    d = read(".github/workflows/auto-update.yml")
    m = read(".github/workflows/monthly-release.yml")
    ok = bool(re.search(r"MONTHS=\"\$\{INPUT_MONTHS:-1\}\"", d)) and \
         bool(re.search(r"MONTHS=\"\$\{INPUT_MONTHS:-1\}\"", m))
    return ("PASS" if ok else "FAIL", "两处均用 :-1 兜底" if ok else "存在硬依赖 inputs 的写法")


@check("A3", "调度", "写权限声明",
       "建 release + 推代码需要 contents: write")
def a3():
    res = []
    for p in (".github/workflows/auto-update.yml", ".github/workflows/monthly-release.yml"):
        d = load_wf(p)
        res.append(str((d.get("permissions") or {}).get("contents")))
    ok = all(r == "write" for r in res)
    return ("PASS" if ok else "FAIL", f"contents={res}")


@check("A4", "调度", "并发互斥",
       "两个 workflow 都会 push main，需要 concurrency 或 push 重试")
def a4():
    d = load_wf(".github/workflows/auto-update.yml")
    m = load_wf(".github/workflows/monthly-release.yml")
    daily_conc = "concurrency" in d
    monthly_conc = "concurrency" in m
    monthly_retry = "--rebase" in read(".github/workflows/monthly-release.yml")
    if daily_conc and monthly_conc:
        return "PASS", "两处都有 concurrency"
    if monthly_retry:
        return "WARN", f"daily concurrency={daily_conc}，monthly 靠 rebase 重试兜底"
    return "FAIL", f"daily concurrency={daily_conc} monthly={monthly_conc}，无重试"


# ---------- B 采集层 ----------
@check("B1", "采集", "数据源配置可达性",
       "config 中的源地址集中声明，不散落在代码里")
def b1():
    cfg = read("autocollect_core/config.py").lower()
    keys = ["yckceo_list", "yckceo_heji", "gurus"]
    found = [k for k in keys if k in cfg]
    return ("PASS" if len(found) >= 2 else "WARN", f"config 内声明: {found}")


@check("B2", "采集", "清洗去重键稳定",
       "clean_url 为唯一去重键，且排除中文/emoji 污染")
def b2():
    utils = read("autocollect_core/utils.py")
    has_clean = "def clean_url" in utils
    handles_cjk = bool(re.search(r"[\u4e00-\u9fa5]|中文|emoji|\\\\u", utils))
    return ("PASS" if has_clean and handles_cjk else "WARN",
            f"clean_url={has_clean} 污染处理={handles_cjk}")


# ---------- C 中间层语义 ----------
@check("C1", "中间层", "pending 消费后状态可辨",
       "已并入正式版的条目应清空或归档，否则下次 stage 会重复处理")
def c1():
    import json as j
    p = j.load(open(os.path.join(ROOT, "books_pending.json"), encoding="utf-8")) if \
        os.path.exists(os.path.join(ROOT, "books_pending.json")) else []
    b = j.load(open(os.path.join(ROOT, "books.json"), encoding="utf-8"))
    pu = {s.get("bookSourceUrl") for s in p}
    bu = {s.get("bookSourceUrl") for s in b}
    overlap = len(pu & bu)
    if not p:
        return "PASS", "pending 为空"
    if overlap > len(p) * 0.8:
        return "WARN", f"pending {len(p)} 条中 {overlap} 条已在正式版（已消费未清空）"
    return "PASS", f"pending {len(p)} 条，与正式版重叠 {overlap}"


@check("C2", "中间层", "历史淘汰源不被复活",
       "月度合并不得从历史 cleaned/artifact 汇总，只从新采集取数")
def c2():
    s = read("scripts/monthly_release.py")
    has_artifact = "list_artifacts" in s or "archive_download_url" in s
    return ("FAIL" if has_artifact else "PASS",
            "月度脚本仍读历史 artifact" if has_artifact else "月度脚本只做新采集，不读历史池")


# ---------- D 校验层 ----------
@check("D1", "校验", "三态判定完整",
       "搜索/发现各返回 ok|bad|blocked|None，任一 ok 即为可用")
def d1():
    v = read("autocollect_core/validators.py")
    has_s = "def check_search_parsed" in v
    has_e = "def check_explore_parsed" in v
    has_u = "def check_source_usable" in v
    blocks = "'blocked'" in v or '"blocked"' in v
    return ("PASS" if has_s and has_e and has_u and blocks else "FAIL",
            f"search={has_s} explore={has_e} usable={has_u} blocked={blocks}")


@check("D2", "校验", "成人源豁免不看 group",
       "is_adult_source 只看 name/url/comment，不看 bookSourceGroup（防止归组自证）")
def d2():
    c = read("autocollect_core/cleaner.py")
    m = re.search(r"def is_adult_source.*?(?=\ndef |\Z)", c, re.S)
    if not m:
        return "FAIL", "找不到 is_adult_source"
    body = m.group(0)
    # 先用 ast 剥离 docstring/注释，只留可执行代码，避免把说明文字误判成使用
    try:
        import ast
        fn = ast.parse(body).body[0]
        # docstring 常量按「函数体第一条 Expr」定位（get_docstring 会 clean 缩进，字符串比较不可靠）
        doc_const = None
        if fn.body and isinstance(fn.body[0], ast.Expr) \
                and isinstance(fn.body[0].value, ast.Constant) \
                and isinstance(fn.body[0].value.value, str):
            doc_const = fn.body[0].value.value
        consts = [n.value for n in ast.walk(fn)
                  if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        rest = [c for c in consts if c != doc_const]
        uses_group = any("bookSourceGroup" in c for c in rest)
    except Exception:
        uses_group = "bookSourceGroup" in body
    return ("FAIL" if uses_group else "PASS",
            "可执行代码里仍读 bookSourceGroup（会自证成人）" if uses_group else "可执行代码只用 name/url/comment 三字段")


@check("D3", "校验", "quick/full 档位可区分",
       "validate_sources 支持 mode，断点按 mode 分名")
def d3():
    v = read("autocollect_core/validators.py")
    return ("PASS" if "mode=\"quick\"" in v or 'mode="quick"' in v else "WARN",
            "validate_sources(mode=...) 存在" if "mode" in v else "无档位参数")


# ---------- E 排序组织 ----------
@check("E1", "排序", "大厂顺序不被名字排序覆盖",
       "organize_sources 对大厂用 BIG_SITES 序做 _big_key 保护")
def e1():
    o = read("autocollect_core/organizer.py")
    return ("PASS" if "_big_key" in o and "BIG_SITES" in o else "FAIL",
            f"_big_key={'_big_key' in o} BIG_SITES={'BIG_SITES' in o}")


@check("E2", "排序", "正式版结构自洽",
       "customOrder 连续、分组区间连续、成人最末")
def e2():
    import json as j
    b = j.load(open(os.path.join(ROOT, "books.json"), encoding="utf-8"))
    orders = [s.get("customOrder") for s in b]
    cont = orders == list(range(1, len(b) + 1))
    groups = []
    for s in b:
        g = s.get("bookSourceGroup")
        if groups and groups[-1] == g:
            continue
        groups.append(g)
    adult_last = groups[-1] == "成人书源"
    adult_max = max((s.get("customOrder") for s in b if s.get("bookSourceGroup") == "成人书源"),
                    default=0)
    ok = cont and adult_last and adult_max == len(b)
    return ("PASS" if ok else "FAIL",
            f"连续={cont} 分组段={len(groups)} 成人最末={adult_last} 成人末位={adult_max}/{len(b)}")


# ---------- F 发布层 ----------
@check("F1", "发布", "版本号递增不覆盖",
       "get_next_release_tag 取最新 vX.Y.Z patch+1")
def f1():
    p = read("autocollect_core/publisher.py")
    return ("PASS" if "def get_next_release_tag" in p and "patch" in p.lower() or
            "int(" in p else "WARN", "get_next_release_tag 存在" if "get_next_release_tag" in p else "缺失")


@check("F2", "发布", "中断残留复用",
       "is_partial_release 命中时补齐同一 tag，不新开版本")
def f2():
    p = read("autocollect_core/publisher.py")
    used = "is_partial_release(latest)" in p
    return ("PASS" if used else "WARN", f"复用判断={used}")


@check("F3", "发布", "asset 上传端点正确",
       "必须用 uploads.github.com，api.github.com 上传会 404")
def f3():
    p = read("autocollect_core/publisher.py")
    return ("PASS" if "uploads.github.com" in p else "FAIL",
            "uploads 端点存在" if "uploads.github.com" in p else "用了错误端点")


@check("F4", "发布", "自动/手动版可区分",
       "标题前缀与说明标注校验口径，下载时能自行选择")
def f4():
    p = read("autocollect_core/publisher.py")
    m = read("scripts/monthly_release.py")
    has_meta = "def build_release_meta" in p
    auto_called = 'mode="auto"' in m
    return ("PASS" if has_meta and auto_called else "WARN",
            f"build_release_meta={has_meta} 月度用 auto={auto_called}")


@check("F5", "发布", "Actions 内不重复 git push",
       "auto_publish 内部 push 与 workflow 提交冲突，需跳过")
def f5():
    p = read("autocollect_core/publisher.py")
    return ("PASS" if "GITHUB_ACTIONS" in p else "FAIL",
            "已按 GITHUB_ACTIONS 跳过内部 push" if "GITHUB_ACTIONS" in p else "仍会与 workflow 抢推送")


# ---------- G 幂等与恢复 ----------
@check("G1", "恢复", "断点按档位分名",
       "ckpt 文件名含 mode，避免 quick/full 断点串用")
def g1():
    v = read("autocollect_core/validators.py")
    return ("PASS" if re.search(r"ckpt.*mode|mode.*ckpt", v) else "WARN",
            "ckpt 名含 mode" if "mode" in v else "未区分")


@check("G2", "恢复", "重跑不重复发版",
       "内容无变化时自动跳过发布")
def g2():
    p = read("autocollect_core/publisher.py")
    return ("PASS" if "没有更新内容" in p else "WARN", "有 no-change 短路" if "没有更新内容" in p else "缺短路")


# ---------- H 文档一致性 ----------
@check("H1", "文档", "README 源数与实际一致",
       "README 写的总数必须等于 books.json 实际条数")
def h1():
    import json as j
    n = len(j.load(open(os.path.join(ROOT, "books.json"), encoding="utf-8")))
    r = read("README.md")
    m = re.search(r"书源总数\*\*[:：]?\s*\*{0,2}\s*(\d+)", r) or re.search(r"书源总数.*?(\d+)", r)
    doc = int(m.group(1)) if m else -1
    return ("PASS" if doc == n else "FAIL", f"README={doc} 实际={n}")


@check("H2", "文档", "模块表覆盖新脚本",
       "DEVELOPMENT 模块表包含 monthly_release.py")
def h2():
    d = read("DEVELOPMENT.md")
    return ("PASS" if "monthly_release.py" in d else "WARN",
            "已登记" if "monthly_release.py" in d else "未登记")


@check("H3", "文档", "过期口径清理",
       "README 不应残留「每周采集」等旧描述")
def h3():
    r = read("README.md")
    # 更新日志（以「- v」开头的历史条目）是历史事实，不算过期口径
    current = "\n".join(l for l in r.splitlines() if not l.strip().startswith("- v"))
    stale = re.findall(r"每周[^\n]{0,20}采集|每周日", current)
    return ("WARN" if stale else "PASS",
            f"现行描述里发现旧口径 {len(stale)} 处" if stale else "现行描述无「每周」残留（仅更新日志历史条目保留）")


# ---------- 缺陷回归（第二轮审计沉淀，防止已修 bug 回潮） ----------
@check("D4", "校验", "WAF 403 类不判死",
       "probe_alive 只能把 404/410 判死；403/405(WAF)、429、5xx 必须保留")
def d4():
    m = read("autocollect_core/liveness.py")
    block = re.search(r"def probe_alive.*?(?=\ndef |\Z)", m, re.S)
    if not block:
        return "FAIL", "找不到 probe_alive"
    body = block.group(0)
    strict = ">= 400" in body and "return \"dead\"" in body and "404" not in body
    if strict:
        return "FAIL", "仍用 status>=400 一刀切判死（403 WAF 站会被误杀）"
    ok = "404" in body and "403" in body
    return ("PASS" if ok else "WARN", "只判 404/410，403/405/429/5xx 保留" if ok else "判死口径不明确")


@check("D5", "中间层", "现有源不重走垃圾过滤",
       "月度合并只对新采集源过滤；现有源已过历史校验，重过滤会误删（badaoge 因 URL 含 bad 被删）")
def d5():
    m = read("scripts/monthly_release.py")
    filt = re.search(r"validated = filter_junk_sources", m)
    if not filt:
        return "WARN", "未找到过滤调用"
    line = [l for l in m.splitlines() if "filter_junk_sources" in l and "validated" in l][0]
    merged_into_one = "existing_non_big" in line and "alive" in line
    return ("FAIL" if merged_into_one else "PASS",
            "现有源与新源一起过滤（会误删现有源）" if merged_into_one else "只过滤新源，现有源原样进入候选")


@check("F6", "发布", "发布失败不会被吞",
       "auto_publish 返回 bool，月度脚本失败必须非 0 退出（否则 CI 假绿）")
def f6():
    p = read("autocollect_core/publisher.py")
    m = read("scripts/monthly_release.py")
    has_ret = "return bool(publish_release" in p
    exits = "sys.exit(1)" in m
    return ("PASS" if has_ret and exits else "FAIL",
            f"返回值={has_ret} 失败退出={exits}")


@check("A5", "调度", "本地 cron 脚本与每日采集对齐",
       "install_cron.sh 必须指向 run_daily_collect.sh 且 cron 为每日")
def a5():
    s = read("scripts/install_cron.sh")
    ok = "run_daily_collect.sh" in s and re.search(r'CRON_LINE="7 17 \* \* \*', s)
    return ("PASS" if ok else "FAIL", "指向每日脚本 + UTC 17:07" if ok else "仍指向旧周任务或旧时间")


@check("A6", "文档", "旧脚本名零残留",
       "全仓不得残留 run_weekly_collect.sh 引用（除审计历史记录）")
def a6():
    hits = []
    for root, _, files in os.walk(ROOT):
        if ".git" in root:
            continue
        for f in files:
            if not f.endswith((".sh", ".py", ".md")):
                continue
            if f in ("AUDIT_PLAN.md", "audit_pipeline.py"):
                continue  # 审计计划/审计脚本自身会提到旧名，不算残留
            path = os.path.join(root, f)
            try:
                if "run_weekly_collect" in open(path, encoding="utf-8").read():
                    hits.append(os.path.relpath(path, ROOT))
            except Exception:
                pass
    return ("FAIL" if hits else "PASS", f"残留: {hits}" if hits else "无残留")



# ---------- 日采集闭环（2026-11-10 补：采集产物必须真进中间层） ----------
@check("A7", "调度", "漏跑补偿与幂等守卫",
       "双 cron 互补 + 按北京日期判今天是否已采，避免 GitHub 丢弃定时任务后永久少一天")
def a7():
    w = read(".github/workflows/auto-update.yml")
    crons = re.findall(r"-\s*cron:\s*'([^']+)'", w)
    guard = "今天是否已采过" in w and "daily_history" in w
    return ("PASS" if len(crons) >= 2 and guard else "FAIL",
            f"cron {len(crons)} 条 + 幂等守卫={guard}")


@check("C3", "中间层", "日采集产物真的进中间层",
       "workflow 必须有 stage 步骤，把当天新增源并入 books_pending.json（否则 artifact 过期后白采）")
def c3():
    w = read(".github/workflows/auto-update.yml")
    has = "stage_daily.py" in w and "books_pending.json" in w
    return ("PASS" if has else "FAIL", "有增量入库步骤并提交 pending" if has else "采集产物只进 artifact，中间层无人消费")


@check("D6", "校验", "探活口径唯一",
       "每日入库与月度合并必须共用 liveness.probe_alive，避免两套判死规则漂移")
def d6():
    a = "from autocollect_core.liveness import probe_many" in read("scripts/stage_daily.py")
    b = "from autocollect_core.liveness import probe_alive" in read("scripts/monthly_release.py")
    dup = "def probe_alive" in read("scripts/monthly_release.py")
    return ("PASS" if a and b and not dup else "FAIL",
            f"stage 复用={a} monthly 复用={b} 本地重复定义={dup}")


@check("H4", "文档", "摘要日期用北京时间",
       "runner 是 UTC，摘要日期必须显式加 8 小时，否则与北京日期差一天")
def h4():
    w = read(".github/workflows/auto-update.yml")
    ok = "timedelta(hours=8)" in w
    return ("PASS" if ok else "FAIL", "已显式转北京时区" if ok else "仍用 runner 本地时间(UTC)")



def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    results = []
    for cid, dim, name, standard, fn in CHECKS:
        try:
            status, ev = fn()
        except Exception as e:
            status, ev = "FAIL", f"检查异常: {type(e).__name__}: {e}"
        results.append({"id": cid, "dim": dim, "name": name, "standard": standard,
                        "status": status, "evidence": ev})

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return

    cnt = {"PASS": 0, "WARN": 0, "FAIL": 0}
    for r in results:
        cnt[r["status"]] = cnt.get(r["status"], 0) + 1
    print(f"{'ID':4s} {'维度':6s} {'结论':5s} {'检查点':30s} 证据")
    for r in results:
        print(f"{r['id']:4s} {r['dim']:6s} {r['status']:5s} {r['name']:30s} {r['evidence']}")
    print(f"\n合计：PASS {cnt['PASS']} / WARN {cnt['WARN']} / FAIL {cnt['FAIL']}")


if __name__ == "__main__":
    main()
