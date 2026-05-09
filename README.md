# 今日头条博主内容抓取 + PostgreSQL 双写

基于 [Playwright](https://playwright.dev/python/) 的今日头条博主内容增量抓取工具，支持**文章 / 微头条 / 视频**全类型，数据同步写入 PostgreSQL，可通过 macOS `launchd` 定时跑。

---

## ✨ 功能特性

- **全类型抓取**：默认抓"全部"tab，自动识别 文章 / 微头条 / 视频
- **增量更新**：基于 `group_id` 去重，只拉新发布的内容，定时跑只需几秒
- **双写落盘**：JSON + Markdown（按类型分目录）+ PostgreSQL upsert
- **稳健容错**：实时落盘 + 断点续抓 + MAX_ITEMS 限量，中断不丢数据
- **无头模式**：`HEADLESS=1` 开启，适合定时任务
- **复用系统 Chrome**：`channel="chrome"`，无需下载 Chromium

---

## 📁 目录结构

```
browser-use/
├── toutiao_crawler.py          # 主爬虫脚本
├── db.py                       # PostgreSQL 双写模块
├── run_crawler.sh              # 定时任务包装脚本（会设置 HEADLESS=1 + 日志）
├── com.cty.toutiao.crawler.plist  # macOS launchd 定时任务配置
├── requirements.txt
├── .env.example                # 配置模板
├── .env                        # 实际配置（不入库）
└── output_toutiao/
    ├── articles.json           # 全量数据（含正文）
    ├── articles_list.json      # 列表快照（滚动中实时写入）
    ├── articles_md/            # Markdown 按类型分目录
    │   ├── 文章/
    │   ├── 微头条/
    │   └── 视频/
    └── logs/                   # 定时任务日志
        ├── cron_YYYYMMDD.log   # 每天一个
        ├── launchd.out.log     # launchd 自己的日志
        └── launchd.err.log
```

---

## 🔧 环境准备（首次使用）

### 1. Python 环境

```bash
cd /Users/cty/Documents/pythonStuty/browser-use
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. 系统 Chrome

已安装 Google Chrome 即可。脚本用 `channel="chrome"` 复用系统浏览器，**不用**跑 `playwright install chromium`。

### 3. PostgreSQL

数据库地址已配好（阿里云 `47.98.191.92:5432/postgres`），**表会在第一次运行时自动创建**（`toutiao_articles`）。

无需手动建表，只需在 `.env` 里填连接串。

---

## ⚙️ 配置 `.env`

复制 `.env.example` 为 `.env`，并填入真实值：

```bash
# 已配好
GOOGLE_API_KEY=xxxxx

# PostgreSQL（JDBC 格式需去掉 jdbc: 前缀）
DATABASE_URL=postgresql://postgres:3357@47.98.191.92:5432/postgres

# 可选：自定义表名，默认 toutiao_articles
# DB_TABLE=toutiao_articles
```

> **要换博主**？直接改 `toutiao_crawler.py` 顶部的 `USER_URL`。`user_token` 字段会自动区分，同一张表可存多博主。

---

## 🚀 日常使用

### 手动跑一次（有浏览器窗口，方便观察）

```bash
source .venv/bin/activate
python toutiao_crawler.py
```

- **首次**：拉 500 条（由 `MAX_ITEMS=500` 限制，想全量改成 `0`）
- **之后**：自动读取本地 `articles.json` 作为已知集，增量只拉新发布的

### 无头模式（不弹浏览器窗口）

```bash
HEADLESS=1 python toutiao_crawler.py
```

### 历史数据回灌到 PG（只需首次，用于迁移 JSON → 数据库）

```bash
python -c "
import json
from db import save_to_db
data = json.load(open('output_toutiao/articles.json', encoding='utf-8'))
save_to_db(data, user_url='https://www.toutiao.com/c/user/token/MS4wLjABAAAALa_PgXCdXqpsShJ5Bq2Ni4E2-hfmmRq_gkQpzwFxjLSOyqV09KOYsUxECzE9XiRr/')
"
```

---

## ⏰ 定时任务（macOS launchd）

> 推荐 launchd 而非 cron：**Mac 休眠错过的任务会在唤醒后自动补跑**。

### 安装（一次性配置）

```bash
# 1. 给包装脚本加执行权限
chmod +x /Users/cty/Documents/pythonStuty/browser-use/run_crawler.sh

# 2. 复制 plist 到 LaunchAgents 目录
cp /Users/cty/Documents/pythonStuty/browser-use/com.cty.toutiao.crawler.plist ~/Library/LaunchAgents/

# 3. 加载任务
launchctl load ~/Library/LaunchAgents/com.cty.toutiao.crawler.plist
```

**当前触发规则**：每天 `09:00` 和 `21:00` 各跑一次（见 plist 里的 `StartCalendarInterval`）。

### 常用运维命令

| 操作 | 命令 |
|------|------|
| 查看任务状态 | `launchctl list \| grep toutiao` |
| 立即手动触发一次 | `launchctl start com.cty.toutiao.crawler` |
| 停止 / 卸载任务 | `launchctl unload ~/Library/LaunchAgents/com.cty.toutiao.crawler.plist` |
| 查看今天的运行日志 | `tail -f output_toutiao/logs/cron_$(date +%Y%m%d).log` |
| 查看 launchd 错误 | `cat output_toutiao/logs/launchd.err.log` |

### 修改触发时间

编辑 [com.cty.toutiao.crawler.plist](./com.cty.toutiao.crawler.plist) 里的 `StartCalendarInterval`，然后**卸载 → 覆盖 → 重新加载**：

```bash
launchctl unload ~/Library/LaunchAgents/com.cty.toutiao.crawler.plist
cp com.cty.toutiao.crawler.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.cty.toutiao.crawler.plist
```

常见规则示例：

```xml
<!-- 每天 8:30 跑一次 -->
<key>StartCalendarInterval</key>
<dict>
    <key>Hour</key><integer>8</integer>
    <key>Minute</key><integer>30</integer>
</dict>

<!-- 每小时整点跑 -->
<key>StartCalendarInterval</key>
<dict>
    <key>Minute</key><integer>0</integer>
</dict>

<!-- 每 10 分钟跑（改用 StartInterval） -->
<key>StartInterval</key>
<integer>600</integer>

<!-- 仅周一到周五 9:00 -->
<key>StartCalendarInterval</key>
<array>
    <dict><key>Weekday</key><integer>1</integer><key>Hour</key><integer>9</integer></dict>
    <dict><key>Weekday</key><integer>2</integer><key>Hour</key><integer>9</integer></dict>
    <dict><key>Weekday</key><integer>3</integer><key>Hour</key><integer>9</integer></dict>
    <dict><key>Weekday</key><integer>4</integer><key>Hour</key><integer>9</integer></dict>
    <dict><key>Weekday</key><integer>5</integer><key>Hour</key><integer>9</integer></dict>
</array>
```

---

## 🗄️ 数据库查询示例

连上 PG 后常用 SQL：

```sql
-- 最新 10 条
SELECT publish_time, type_cn, title
FROM toutiao_articles
ORDER BY publish_time DESC LIMIT 10;

-- 按类型统计
SELECT type_cn, COUNT(*) FROM toutiao_articles GROUP BY type_cn;

-- 某天发布的
SELECT title FROM toutiao_articles
WHERE publish_time::date = '2026-05-08';

-- 全文关键字搜索
SELECT title, LEFT(content, 100) AS preview
FROM toutiao_articles
WHERE content ILIKE '%浪潮信息%' OR title ILIKE '%浪潮信息%';

-- 按评论数热度排序
SELECT title, comment_count FROM toutiao_articles
ORDER BY comment_count DESC LIMIT 20;

-- 多博主区分（多博主共存时）
SELECT user_token, COUNT(*) FROM toutiao_articles GROUP BY user_token;

-- 查 JSONB 原始字段
SELECT raw->>'digg_count' FROM toutiao_articles WHERE group_id='xxxx';
```

---

## 🔩 关键配置项（`toutiao_crawler.py` 顶部）

| 配置 | 默认值 | 说明 |
|------|--------|------|
| `USER_URL` | 远峰战略2025 | 目标博主主页 URL |
| `MAX_ITEMS` | 500 | 列表最大条数，`0`=不限 |
| `MAX_SCROLL_ROUNDS` | 300 | 最大滚动次数保底 |
| `SCROLL_INTERVAL` | 2.5s | 滚动间隔（控制频率） |
| `STABLE_LIMIT` | 6 | 全量模式下连续 N 次无新数据就停 |
| `INCREMENTAL` | True | 增量模式开关 |
| `INCREMENTAL_STABLE_LIMIT` | 3 | 增量模式下更激进的停止阈值 |
| `ARTICLE_INTERVAL` | 2.0s | 抓正文时每篇间隔 |
| `LIST_SAVE_EVERY` | 10 | 列表阶段每 N 次滚动落盘 |
| `CONTENT_SAVE_EVERY` | 20 | 正文阶段每 N 条落盘 |
| `HEADLESS` (env) | 0 | `HEADLESS=1` 启动无头 |

---

## ❓ FAQ

**Q1：定时跑时电脑休眠怎么办？**
launchd 配置了 `StartCalendarIntervalCatchUp=true`，唤醒后会自动补跑最近一次错过的。

**Q2：连续失败怎么排查？**
按顺序看三个日志：
1. `output_toutiao/logs/launchd.err.log` — launchd 能不能启动脚本
2. `output_toutiao/logs/cron_YYYYMMDD.log` — 脚本运行时输出
3. 数据库未写入但 JSON 正常 → 看 `cron_*.log` 里的 `⚠️ 数据库...` 相关行

**Q3：被风控了怎么办？**
调大 `SCROLL_INTERVAL` 和 `ARTICLE_INTERVAL`，减少 `MAX_ITEMS`。增量模式一般很安全（只拉几条就停）。

**Q4：想换个博主？**
改 `toutiao_crawler.py` 顶部的 `USER_URL`。历史数据仍会保留（`user_token` 字段自动区分）。

**Q5：想重新全量抓？**
```bash
# 方式 A：改 INCREMENTAL = False 跑一次
# 方式 B：删掉本地 JSON（PG 数据不受影响，会自动 upsert 覆盖）
rm output_toutiao/articles.json
python toutiao_crawler.py
```

**Q6：只想更新 Markdown 不重抓？**
```bash
python -c "
import json
from toutiao_crawler import save_outputs
data = json.load(open('output_toutiao/articles.json', encoding='utf-8'))
save_outputs(data)
"
```

**Q7：PG 数据库连接不上？**
- 检查 `.env` 里 `DATABASE_URL` 格式（不要 `jdbc:` 前缀）
- 阿里云安全组需放行 5432 端口到你本机 IP
- 密码含特殊字符要 URL 编码（`@` → `%40`）

---

## 📖 查看抓取结果（本地静态页面）

提供一个单文件 HTML 阅读器，直接读 `articles.json`，支持搜索 / 筛选 / 分页 / 展开全文。

```bash
# 一键启动（会自动打开浏览器）
./view.sh

# 或手动
Python3 -m http.server 8000
# 访问 http://localhost:8000/viewer.html
```

**功能**：
- 🔍 实时搜索（标题 + 正文 + 摘要，匹配词黄色高亮）
- 🏷️ 按类型筛选（文章 / 微头条 / 视频）
- 📅 按时间 / 评论数排序
- 📄 20 条/页分页
- 📖 点击卡片展开全文
- 🔗 点击“原文”跳转头条页面

爬虫跑完后直接刷新页面即可看到新数据。

---

## 📝 合规提示

仅供个人学习研究，请控制抓取频率，勿商用。
