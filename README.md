# Legado 阅读书源合集

适用于 [Legado 阅读](https://github.com/gedoor/legado)（开源阅读 App）的书源仓库。

## 书源统计

| 分组 | 数量 | 说明 |
|---|---:|---|
| 头部大厂 | 15 | 起点、番茄、七猫、QQ阅读、晋江等 |
| 精品小说站 | 75 | 知名第三方大站，稳定可用 |
| 免费小说站 | 32 | 免费盗版小说站 |
| 笔趣阁备用 | 20 | 各类笔趣阁镜像 |
| **合计** | **142** | |

## 快速导入

在阅读 App 中粘贴以下 URL 直接导入：

```
https://raw.githubusercontent.com/luanmuc/legado-book-sources/main/阅读书源_最终可用.json
```

或手动下载 JSON 文件后在 App 内导入本地。

## 书源格式说明

书源为 JSON 数组，每个对象是一个书源，核心字段：

```json
{
  "bookSourceName": "书源名称",
  "bookSourceUrl": "书源主页URL",
  "bookSourceGroup": "分组（头部大厂/精品小说站/免费小说站/笔趣阁备用）",
  "bookSourceType": 0,
  "customOrder": 9999,
  "enabled": true,
  "searchUrl": "/搜索路径?keyword={{key}}&page={{page}}",
  "ruleSearch": {
    "bookList": "搜索结果列表选择器",
    "name": "书名选择器",
    "author": "作者选择器",
    "bookUrl": "书籍链接选择器",
    "coverUrl": "封面图选择器",
    "intro": "简介选择器",
    "lastChapter": "最新章节选择器"
  },
  "ruleBookInfo": {
    "name": "书名",
    "author": "作者",
    "coverUrl": "封面",
    "intro": "简介",
    "kind": "分类",
    "lastChapter": "最新章节",
    "tocUrl": "目录页URL（留空则用详情页）"
  },
  "ruleToc": {
    "chapterList": "章节列表选择器",
    "chapterName": "章节名选择器",
    "chapterUrl": "章节链接选择器"
  },
  "ruleContent": {
    "content": "正文内容选择器",
    "replaceRegex": "净化规则（每行一条）",
    "nextContentUrl": "下一页链接（分页正文用）"
  }
}
```

### 规则选择器语法

- CSS 选择器：`div.class a@href` 表示 div.class 下的 a 标签的 href 属性
- `@text` 取文本，`@html` 取 HTML，`@属性名` 取属性
- `||` 或关系（多个选择器按顺序尝试）
- `&&` 且关系（拼接多个字段）
- `##` 分隔正则替换：`匹配##替换值`（删除则只写匹配）
- `{{key}}` 搜索关键词占位符，`{{page}}` 页码占位符

### 净化规则示例

`ruleContent.replaceRegex` 每行一条：

```
<script>.*?</script>
本章未完.*请翻页
http[s]?://[^\s<]+
旳##的
嚿##会
國##国
```

无 `##` 后接替换值的规则表示删除该行/该匹配内容。

## 仓库结构

```
legado-book-sources/
├── 阅读书源_最终可用.json    # ⭐ 手动整理后的书源（直接导入用）
├── README.md               # 本文件
├── crawler.py               # 自动抓取脚本
├── validate.py              # 书源校验脚本
├── raw/                     # 自动抓取的原始书源（未整理）
│   ├── merged_sources.json  # 4000+ 去重后的原始书源库
│   ├── shuyuan_list.json    # 书源列表元数据
│   ├── shuyuans_list.json   # 合集列表元数据
│   └── sources_alive.json   # 域名存活的源
└── .github/workflows/
    └── auto-update.yml      # 每周自动更新
```

**说明**：`raw/` 里是从 yckceo 自动抓取的原始数据（4000+ 个源，未筛选、未去重、规则未补全），供后续挖掘新源用；根目录的 `阅读书源_最终可用.json` 是经过校验、去重、规则补全、净化后的 142 个可用源，直接导入即可。

## 自动抓取

```bash
# 抓取全部书源列表（59页）-> raw/shuyuan_list.json
python3 crawler.py --fetch-list

# 下载全部书源JSON并去重 -> raw/merged_sources.json
python3 crawler.py --fetch-all

# 下载指定合集 -> raw/collection_<id>.json
python3 crawler.py --fetch-collection <id>

# 校验整理后的书源
python3 validate.py --test 阅读书源_最终可用.json
```

## 自动更新

GitHub Actions 每周一自动运行校验脚本。
