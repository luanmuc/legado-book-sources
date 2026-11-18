#!/usr/bin/env python3
"""真浏览器进站核验：逐条打开站点、整页截图、自动初判 + 人工复核清单。

为什么需要它
------------
HTTP 客户端（requests / curl）会被 TLS 指纹识别。实测同一批站：
  - scripts/quality_check.py 判 `sobiquge.net` HTTP 403 → "判不出"
  - 真浏览器打开是完整笔趣阁：分类导航 + 人气榜 + 172 个书链
所以 **403 / 超时 / 渲染超时都不能判死**，必须以浏览器渲染结果为准。

自动判定的边界
--------------
脚本只能判"有明确证据"的两类（有书链 / 有死站指纹），认不出的一律进人工复核清单，
不做猜测性删除。这是误删过 1587 条的教训。

用法
----
    # 对 books.json 里全部源截图核验（会很慢，建议分批）
    python3 scripts/shot_check.py --limit 60

    # 只核验指定 URL 列表
    python3 scripts/shot_check.py --urls urls.txt

    # 只核验上次判"打不开"的待复检清单
    python3 scripts/shot_check.py --pending

输出
----
    raw/autocollect/shots/<idx>_<host>.png      整页截图
    raw/autocollect/shots/meta.jsonl            逐条元数据
    raw/autocollect/shots/verdict.csv           自动判定 + 待人工复核清单
"""
import argparse
import asyncio
import csv
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, 'raw', 'autocollect', 'shots')
META = os.path.join(OUT_DIR, 'meta.jsonl')
VERDICT = os.path.join(OUT_DIR, 'verdict.csv')
PENDING = os.path.join(OUT_DIR, 'pending.json')

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/122.0 Safari/537.36')
CHROMIUM = os.environ.get('YCKCEO_CHROMIUM', '/usr/local/bin/chromium')
TIMEOUT_MS = int(os.environ.get('YCKCEO_SHOT_TIMEOUT_MS', '90000'))
CONCURRENCY = int(os.environ.get('YCKCEO_SHOT_CONCURRENCY', '8'))

SAFE = re.compile(r'[^a-z0-9.]')

# ---- 死站指纹：命中即可判死，不需要再看图 ----
DEAD_TITLE = re.compile(
    r'for sale|出售中|域名出售|域名 - 域名|is registered at|'
    r'welcome to nginx|http server test page|welcome to openresty|'
    r'读书业务关停|关停公告|redirecting|'
    r'国家反诈|必发|赌|彩票|'
    r'最新视频|影视|naked|瑟瑟|'
    r'hello, world|hello world|^login$|404 not found|400 bad request',
    re.I)
DEAD_URL = re.compile(
    r'\.xyz$|ur0q9o7t2uqxh10|wk8nakkhhlma1th|gegedangbook|'
    r'vinniebags|thearticlebuzz|headlinelogic', re.I)

# ---- 小说站特征 ----
NOVEL_TITLE = re.compile(
    r'小说|阅读|书屋|书城|书库|书吧|中文网|文学|txt|电子书|书友|'
    r'玄幻|言情|都市|修真|穿越', re.I)

def is_api(u):
    h = u.split('//')[-1].split('/')[0].lower()
    return bool(re.search(r'(^api\.|\.api\.|^api-|api\.|quickapi|/api/)', h + u))


def host_of(u):
    return u.split('//')[-1].split('/')[0].split(':')[0].lower().replace('www.', '')


def shot_path(idx, url):
    return os.path.join(OUT_DIR, f'{idx:03d}_{SAFE.sub("_", host_of(url))[:40]}.png')


async def capture(browser, sem, idx, url):
    if not url.startswith('http'):
        url = 'https://' + url
    path = shot_path(idx, url)
    rec = {'idx': idx, 'url': url, 'shot': path, 'status': None, 'final_url': '',
           'title': '', 'books': 0, 'links': 0, 'err': ''}
    async with sem:
        ctx = None
        try:
            ctx = await browser.new_context(user_agent=UA, ignore_https_errors=True,
                                            viewport={'width': 1280, 'height': 900})
            page = await ctx.new_page()
            try:
                resp = await page.goto(url, timeout=TIMEOUT_MS, wait_until='domcontentloaded')
                rec['status'] = resp.status if resp else None
                rec['final_url'] = page.url
                await page.wait_for_timeout(2500)
                rec['title'] = (await page.title() or '')[:90]
                html = await page.content()
                rec['books'] = len(re.findall(
                    r'href=["\'][^"\']*(?:/book/|/novel/|/read/|/txt/|/\d+_\d+/)', html, re.I))
                rec['links'] = len(re.findall(r'>[^<>\s]{2,20}</a>', html))
                await page.screenshot(path=path, full_page=False)
            except Exception as e:
                rec['err'] = type(e).__name__
                try:
                    await page.screenshot(path=path, full_page=False)
                except Exception:
                    pass
        except Exception as e:
            rec['err'] = 'ctx:' + type(e).__name__
        finally:
            if ctx:
                try:
                    await ctx.close()
                except Exception:
                    pass
            with open(META, 'a', encoding='utf-8') as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + '\n')
        return rec


def auto_verdict(r):
    """只判有硬证据的两类；其余交给人工，不做猜测性删除。"""
    t = (r.get('title') or '').strip()
    if DEAD_TITLE.search(t) or DEAD_URL.search(r['url']) or DEAD_URL.search(r.get('final_url') or ''):
        return 'dead', f'死站指纹：{t[:30] or host_of(r["url"])}'
    if r['books'] >= 3:
        return 'novel', f'实测 {r["books"]} 个书链'
    if NOVEL_TITLE.search(t) and not DEAD_TITLE.search(t):
        return 'novel', 'title 即小说网'
    if is_api(r['url']):
        return 'keep', 'API 接口域名（首页空属正常）'
    if r['status'] in (401, 403, 429) or (r['status'] or 0) >= 500:
        return 'keep', f'反爬/网关 {r["status"]}，不能判死'
    if r['status'] is None or r['err']:
        return 'pending', f'打不开（{r["err"] or "no status"}），无死站证据'
    return 'pending', f'有响应但认不出：{t[:26]}'


async def run(urls, fresh):
    os.makedirs(OUT_DIR, exist_ok=True)
    if fresh and os.path.exists(META):
        os.remove(META)
    from playwright.async_api import async_playwright
    t0 = time.time()
    sem = asyncio.Semaphore(CONCURRENCY)
    print(f'核验 {len(urls)} 条，并发 {CONCURRENCY}，超时 {TIMEOUT_MS}ms', flush=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            executable_path=CHROMIUM,
            args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu'])
        done = 0
        recs = []
        for fut in asyncio.as_completed([capture(browser, sem, i, u) for i, u in enumerate(urls)]):
            recs.append(await fut)
            done += 1
            if done % 10 == 0:
                print(f'  {done}/{len(urls)}  {time.time()-t0:.0f}s', flush=True)
        await browser.close()

    rows = []
    for r in sorted(recs, key=lambda x: x['idx']):
        v, why = auto_verdict(r)
        rows.append({'idx': r['idx'], 'url': r['url'], 'verdict': v, 'reason': why,
                     'status': r['status'], 'books': r['books'], 'title': r['title'],
                     'shot': r['shot']})

    with open(VERDICT, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=['idx', 'url', 'verdict', 'reason', 'status', 'books', 'title', 'shot'])
        w.writeheader(); w.writerows(rows)

    pend = [r for r in rows if r['verdict'] == 'pending']
    json.dump([r['url'] for r in pend], open(PENDING, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    import collections
    c = collections.Counter(r['verdict'] for r in rows)
    print(f'\n耗时 {time.time()-t0:.0f}s')
    for k in ('novel', 'keep', 'dead', 'pending'):
        print(f'  {k:8s} {c.get(k,0):4d}')
    print(f'\n人工复核清单 {len(pend)} 条 → {PENDING}')
    print(f'明细 → {VERDICT}')
    return rows


def load_urls(args):
    if args.urls:
        return [l.strip() for l in open(args.urls, encoding='utf-8') if l.strip()]
    if args.pending and os.path.exists(PENDING):
        return json.load(open(PENDING, encoding='utf-8'))
    books = json.load(open(os.path.join(ROOT, 'books.json'), encoding='utf-8'))
    urls = [b['bookSourceUrl'] for b in books if b.get('bookSourceUrl')]
    return urls[:args.limit] if args.limit else urls


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--urls', help='URL 清单文件（每行一条）')
    ap.add_argument('--pending', action='store_true', help='只跑上次的人工复核清单')
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--fresh', action='store_true', help='清空 meta.jsonl')
    a = ap.parse_args()
    asyncio.run(run(load_urls(a), a.fresh))


if __name__ == '__main__':
    main()
