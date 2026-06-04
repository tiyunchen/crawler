"""
今日头条博主文章抓取脚本
====================================
思路：
1. 用 Playwright 打开博主主页（真实浏览器规避 _signature 签名）
2. 拦截 XHR 响应，提取文章列表（标题 / URL / 发布时间 / 摘要）
3. 不断下拉滚动直到没有新数据
4. 再用无头浏览器逐篇打开文章详情页，抽取正文
5. 输出 JSON（完整数据）+ 单篇 Markdown（便于阅读）

运行前：
    pip install -r requirements.txt
    playwright install chromium

⚠️ 合规提示：仅供个人学习研究，控制频率，勿商用。
"""

import asyncio
import json
import os
import platform
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit

from dotenv import load_dotenv
from playwright.async_api import async_playwright, Page, Response

load_dotenv()

# ---------------- 配置 ----------------
DEFAULT_USER_URLS = [
    (
        "https://www.toutiao.com/c/user/token/"
        "MS4wLjABAAAALa_PgXCdXqpsShJ5Bq2Ni4E2-hfmmRq_gkQpzwFxjLSOyqV09KOYsUxECzE9XiRr/"
    ),
    (
        "https://www.toutiao.com/c/user/token/"
        "CiyOuniN4Sex-9o3I4U6kSU8GDrUkChVtoVOtnMMQ5cus5FWJot1gKb8mOnN9xpJCjwAAAAAAAAAAAAAUIDGcJLwMYCL1BOF5j4xT-GGDiY7rp_VD2JxD80QGaVAEMDNPPjAcVOoc5me_R68w10QhaCTDhjDxYPqBCIBA7i4GXs=/"
    ),
]

OUTPUT_DIR = Path(__file__).parent / "output_toutiao"
OUTPUT_DIR.mkdir(exist_ok=True)
MD_DIR = OUTPUT_DIR / "articles_md"
MD_DIR.mkdir(exist_ok=True)

# 翻页参数
MAX_SCROLL_ROUNDS = 300          # 最大滚动次数，避免死循环
SCROLL_INTERVAL = 2.5            # 每次滚动间隔（秒），控制频率
STABLE_LIMIT = 6                 # 连续 N 次无新数据则停止
ARTICLE_INTERVAL = 2.0           # 抓正文时每篇间隔（秒）
MAX_ITEMS = 500                  # 列表最大条数（达到即停， 0 = 不限）
LIST_SAVE_EVERY = 10             # 列表阶段：每滚动 N 次落盘一次
CONTENT_SAVE_EVERY = 20          # 正文阶段：每抓 N 条落盘一次

# 增量模式（适合定时跱脚本）
INCREMENTAL = True               # True=只拉新发布的；False=全量重抓
INCREMENTAL_STABLE_LIMIT = 3     # 增量模式下连续 N 次无新增就停（比全量时更激进）

# 无头模式：默认有头（手动调试）；定时任务设 HEADLESS=1 即可隐藏浏览器窗口
HEADLESS = os.getenv("HEADLESS", "0").lower() in ("1", "true", "yes")

# macOS 复用系统 Chrome，其他平台用 Playwright 自带 Chromium
CHROME_CHANNEL = "chrome" if platform.system() == "Darwin" else None

# User-Agent：伪装成普通 Chrome
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# 匹配“全部” tab 下各种列表接口（头条 PC 版常见路径）
LIST_API_PATTERNS = [
    "/api/pc/list/user",
    "/api/pc/feed",
    "/pgc/ma/",
    "post_list",
    "/c/user/article/",
    "/c/user/relation/",
    "user_profile",
]

# 类型标签
TYPE_ARTICLE = "article"       # 图文长文
TYPE_WEITOUTIAO = "weitoutiao"  # 微头条
TYPE_VIDEO = "video"            # 视频
TYPE_UNKNOWN = "unknown"

TYPE_CN = {
    TYPE_ARTICLE: "文章",
    TYPE_WEITOUTIAO: "微头条",
    TYPE_VIDEO: "视频",
    TYPE_UNKNOWN: "未知",
}


def _normalize_user_url(url: str) -> str:
    """去掉头条分享链接里的追踪参数，保留稳定的博主主页地址。"""
    parts = urlsplit((url or "").strip())
    if not parts.scheme or not parts.netloc:
        return (url or "").strip()
    path = parts.path if parts.path.endswith("/") else parts.path + "/"
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def _extract_user_token(url: str) -> str:
    """从博主主页 URL 提取 user_token，用于多博主增量和页面筛选。"""
    m = re.search(r"/token/([^/?#]+)", url or "")
    return unquote(m.group(1)) if m else ""


def _short_user_token(user_token: str) -> str:
    """日志和兜底展示用短 token，避免长 token 影响可读性。"""
    return user_token[:8] + "..." + user_token[-6:] if len(user_token) > 18 else user_token


def _load_user_urls() -> list[str]:
    """支持环境变量覆盖，方便后续新增博主时不必再改代码。"""
    raw = (
        os.getenv("TOUTIAO_USER_URLS")
        or os.getenv("USER_URLS")
        or os.getenv("USER_URL")
        or ""
    )
    candidates = re.split(r"[\n,;]+", raw) if raw.strip() else DEFAULT_USER_URLS
    urls: list[str] = []
    seen_tokens: set[str] = set()
    for item in candidates:
        url = _normalize_user_url(item)
        token = _extract_user_token(url)
        if not url or (token and token in seen_tokens):
            continue
        if token:
            seen_tokens.add(token)
        urls.append(url)
    return urls


USER_URLS = _load_user_urls()
USER_NAME_BY_TOKEN: dict[str, str] = {}


def _is_list_api(url: str) -> bool:
    return any(p in url for p in LIST_API_PATTERNS)


def _ts_to_str(ts: Any) -> str:
    try:
        return datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ts or "")


def _safe_filename(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", name or "").strip()
    return name[:80] or "untitled"


def _clean_user_name(text: str) -> str:
    """清理页面标题/DOM 中提取到的博主名称。"""
    name = re.sub(r"[\r\n\t]+", " ", text or "").strip()
    name = re.sub(r"\s+", " ", name)
    name = re.sub(r"(的个人主页.*|[-_ ]*今日头条.*)$", "", name).strip()
    if not name or len(name) > 40:
        return ""
    banned = ("今日头条", "登录", "关注", "粉丝", "获赞", "作品", "全部")
    return "" if any(word == name or word in name and len(name) <= len(word) + 2 for word in banned) else name


async def _extract_user_name(page: Page) -> str:
    """从博主主页提取展示名称，失败时返回空字符串走 token 兜底。"""
    data = await page.evaluate(
        """() => {
            const visibleText = (el) => {
                if (!el) return '';
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                if (style.display === 'none' || style.visibility === 'hidden' || rect.width === 0 || rect.height === 0) {
                    return '';
                }
                return (el.innerText || el.textContent || '').trim();
            };
            const selectors = [
                'h1',
                'h2',
                '[class*="user" i][class*="name" i]',
                '[class*="author" i][class*="name" i]',
                '[class*="name" i]',
                '[class*="title" i]'
            ];
            const candidates = [document.title || ''];
            for (const selector of selectors) {
                for (const el of document.querySelectorAll(selector)) {
                    const text = visibleText(el);
                    if (text) candidates.push(text);
                }
            }
            return candidates;
        }"""
    )
    if not isinstance(data, list):
        return ""
    for item in data:
        name = _clean_user_name(str(item))
        if name:
            return name
    return ""


# ---------------- 中间状态落盘 ----------------
LIST_SNAPSHOT = OUTPUT_DIR / "articles_list.json"
FULL_SNAPSHOT = OUTPUT_DIR / "articles.json"


def _save_list_snapshot(articles: list[dict]) -> None:
    try:
        LIST_SNAPSHOT.write_text(
            json.dumps(articles, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        print(f"  ⚠️ 列表落盘失败：{e}")


def _save_full_snapshot(articles: list[dict]) -> None:
    try:
        FULL_SNAPSHOT.write_text(
            json.dumps(articles, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        print(f"  ⚠️ 全文落盘失败：{e}")


def _load_existing_content_map() -> dict[str, str]:
    """从已保存的 articles.json 里读出已有 content 的条目（用于断点续抓）"""
    if not FULL_SNAPSHOT.exists():
        return {}
    try:
        old = json.loads(FULL_SNAPSHOT.read_text(encoding="utf-8"))
        return {
            a["group_id"]: a.get("content", "")
            for a in old
            if isinstance(a, dict) and a.get("group_id") and a.get("content")
        }
    except Exception:
        return {}


def _infer_type_and_url(item: dict, gid: str) -> tuple[str, str]:
    """根据 item 的字段判断内容类型，并返回适合的详情 URL"""
    # 1) 直接用接口返回的 URL字段
    raw_url = (
        item.get("share_url")
        or item.get("source_url")
        or item.get("article_url")
        or item.get("url")
        or ""
    )
    if raw_url.startswith("//"):
        raw_url = "https:" + raw_url
    elif raw_url.startswith("/"):
        raw_url = "https://www.toutiao.com" + raw_url

    # 2) 根据 URL 特征判断类型
    if "/w/" in raw_url or "/group/" in raw_url:
        t = TYPE_WEITOUTIAO
    elif "/video/" in raw_url or "/v/" in raw_url:
        t = TYPE_VIDEO
    elif "/article/" in raw_url or "/i" in raw_url:
        t = TYPE_ARTICLE
    else:
        # 3) 根据显式类型字段判断
        has_video = bool(item.get("has_video")) or item.get("video_id") or item.get("video_play_info")
        art_type = str(item.get("article_type") or item.get("item_type") or "").lower()
        if has_video or art_type in ("video", "0"):
            t = TYPE_VIDEO
        elif item.get("title") and len(str(item.get("title"))) > 5:
            t = TYPE_ARTICLE
        elif item.get("content"):
            t = TYPE_WEITOUTIAO
        else:
            t = TYPE_UNKNOWN

    # 4) 没有 raw_url 则按类型拼 URL
    if not raw_url:
        if t == TYPE_WEITOUTIAO:
            raw_url = f"https://www.toutiao.com/w/{gid}/"
        elif t == TYPE_VIDEO:
            raw_url = f"https://www.toutiao.com/video/{gid}/"
        else:
            raw_url = f"https://www.toutiao.com/article/{gid}/"
    return t, raw_url


def _collect_item(item: dict, articles: list, seen: set, user_url: str, user_token: str, user_name: str) -> None:
    """解析单条 item 并追加到 articles，幂等"""
    if not isinstance(item, dict):
        return
    gid = item.get("group_id") or item.get("item_id") or item.get("id")
    if not gid:
        return
    gid = str(gid)
    if gid in seen:
        return
    seen.add(gid)

    item_type, detail_url = _infer_type_and_url(item, gid)
    title = item.get("title") or ""
    # 微头条的列表接口通常直接返回全文 content
    inline_content = item.get("content", "") or ""
    if not title and inline_content:
        title = str(inline_content)[:40].replace("\n", " ")

    articles.append({
        "group_id": gid,
        "user_token": user_token,
        "user_name": user_name,
        "user_url": user_url,
        "type": item_type,
        "type_cn": TYPE_CN.get(item_type, "未知"),
        "title": title,
        "url": detail_url,
        "publish_time": _ts_to_str(item.get("publish_time")),
        "abstract": item.get("abstract", ""),
        "source": item.get("source", ""),
        "inline_content": inline_content,
        "video_id": item.get("video_id", ""),
        "has_video": bool(item.get("has_video")),
        "comment_count": item.get("comment_count", 0),
        "digg_count": item.get("digg_count", 0),
    })


# ---------------- 列表抓取 ----------------
async def collect_article_list(user_url: str, known_ids: set[str] | None = None) -> list[dict]:
    """拉取博主列表。known_ids 中的条目会被跳过（用于增量模式）"""
    articles: list[dict] = []
    user_token = _extract_user_token(user_url)
    user_name = ""
    # seen 预填旧 ID，_collect_item 会自动跳过
    seen: set[str] = set(known_ids or set())
    pre_known_count = len(seen)

    async with async_playwright() as p:
        browser = await p.chromium.launch(channel=CHROME_CHANNEL, headless=HEADLESS)
        context = await browser.new_context(user_agent=UA, locale="zh-CN")
        page = await context.new_page()

        async def on_response(resp: Response):
            nonlocal user_name
            if not _is_list_api(resp.url):
                return
            try:
                data = await resp.json()
            except Exception:
                return
            items = data.get("data") or data.get("list") or []
            if not isinstance(items, list):
                return
            for item in items:
                try:
                    _collect_item(item, articles, seen, user_url, user_token, user_name)
                except Exception as e:
                    print(f"   ⚠️ item 解析失败：{e}")

        page.on("response", on_response)

        print(f"🌐 打开博主主页：{user_url}")
        if pre_known_count:
            print(f"🔄 增量模式：已知 {pre_known_count} 条历史内容，将自动跳过")
        await page.goto(user_url, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(3)
        user_name = await _extract_user_name(page)
        if user_name:
            USER_NAME_BY_TOKEN[user_token] = user_name
            for art in articles:
                if not art.get("user_name"):
                    art["user_name"] = user_name
            print(f"👤 识别博主：{user_name}")
        else:
            print(f"👤 未识别到博主名，使用 token：{_short_user_token(user_token)}")
        # 默认就在“全部” tab，不再切换

        # 下拉加载：增量模式下更早停（正常新发布数量很少）
        stable_limit = INCREMENTAL_STABLE_LIMIT if pre_known_count else STABLE_LIMIT
        last_count = 0
        stable = 0
        try:
            for i in range(MAX_SCROLL_ROUNDS):
                await page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
                await asyncio.sleep(SCROLL_INTERVAL)
                cur = len(articles)
                print(f"  ↓ 第 {i + 1} 次滚动，本次新增 {cur} 条")

                # 实时落盘
                if (i + 1) % LIST_SAVE_EVERY == 0:
                    _save_list_snapshot(articles)

                # 达到上限即停
                if MAX_ITEMS and cur >= MAX_ITEMS:
                    print(f"  🚩 已达 MAX_ITEMS={MAX_ITEMS}，停止滚动")
                    break

                if cur == last_count:
                    stable += 1
                    if stable >= stable_limit:
                        reason = "新发布内容已全部收集" if pre_known_count else "连续多次无新数据"
                        print(f"  ✅ {reason}，停止滚动")
                        break
                else:
                    stable = 0
                last_count = cur
        except (KeyboardInterrupt, asyncio.CancelledError):
            print("  ⏹️  收到中断信号，保留已收集的数据")
        finally:
            _save_list_snapshot(articles)
            await browser.close()

    # 按时间倒序
    articles.sort(key=lambda x: x.get("publish_time", ""), reverse=True)
    return articles


# ---------------- 正文抓取 ----------------
async def extract_detail(page: Page, url: str, item_type: str) -> tuple[str, str]:
    """返回 (title, content_text)，根据类型选择不同选择器"""
    await page.goto(url, wait_until="domcontentloaded", timeout=45000)
    # 等待正文渲染
    try:
        await page.wait_for_selector(
            "article, .article-content, .syl-article-base, .wtt-detail, .weitoutiao, .wt-thread",
            timeout=8000,
        )
    except Exception:
        pass
    await asyncio.sleep(1.2)

    data = await page.evaluate(
        """() => {
            const pickText = (sel) => {
                const el = document.querySelector(sel);
                return el ? el.innerText.trim() : '';
            };
            const title =
                pickText('h1') ||
                document.title ||
                '';
            // 依次尝试：长文 / 微头条 / 视频
            const content =
                pickText('article') ||
                pickText('.article-content') ||
                pickText('.syl-article-base') ||
                pickText('.main-content') ||
                pickText('.wtt-detail') ||
                pickText('.weitoutiao-content') ||
                pickText('.wt-thread') ||
                pickText('.wt-detail-body') ||
                pickText('.feed-card-content') ||
                pickText('.video-description') ||
                pickText('.vi-description') ||
                '';
            return { title, content };
        }"""
    )
    return data.get("title", ""), data.get("content", "")


async def fetch_all_contents(articles: list[dict]) -> None:
    # 断点续抓：从历史 articles.json 读取已抓内容
    existing = _load_existing_content_map()
    if existing:
        print(f"🔄 检测到历史数据，已完成 {len(existing)} 条将跳过")

    async with async_playwright() as p:
        browser = await p.chromium.launch(channel=CHROME_CHANNEL, headless=True)
        context = await browser.new_context(user_agent=UA, locale="zh-CN")
        page = await context.new_page()

        total = len(articles)
        done = 0
        try:
            for idx, art in enumerate(articles, 1):
                tag = art.get("type_cn", "")
                title_preview = (art.get("title") or "")[:40]

                # 跳过已有 content 的
                prev = existing.get(art["group_id"])
                if prev:
                    art["content"] = prev
                    done += 1
                    continue

                print(f"[{idx}/{total}][{tag}] {title_preview}")

                # 微头条：优先用列表接口返回的全文，避免再打开页面
                inline = art.get("inline_content") or ""
                if art.get("type") == TYPE_WEITOUTIAO and len(inline) > 20:
                    art["content"] = inline
                    done += 1
                else:
                    try:
                        title, content = await extract_detail(page, art["url"], art.get("type", ""))
                        if title and not art.get("title"):
                            art["title"] = title
                        art["content"] = content or inline
                        done += 1
                    except Exception as e:
                        art["content"] = inline
                        art["error"] = str(e)
                        print(f"   ⚠️ 失败：{e}")
                    await asyncio.sleep(ARTICLE_INTERVAL)

                # 定期落盘
                if done % CONTENT_SAVE_EVERY == 0:
                    _save_full_snapshot(articles)
        except (KeyboardInterrupt, asyncio.CancelledError):
            print("⏹️  收到中断信号，保留已抓数据")
        finally:
            _save_full_snapshot(articles)
            await browser.close()


# ---------------- 输出 ----------------
def _reclassify_by_content(articles: list[dict]) -> None:
    """根据正文特征二次分类：纯短文/含评论引用 → 微头条；长文 → 文章"""
    wt_pat = re.compile(r"//@[^\s:\uff1a]+[:\uff1a]")
    for a in articles:
        if a.get("type") != TYPE_UNKNOWN:
            continue
        content = a.get("content") or a.get("inline_content") or ""
        title = a.get("title") or ""
        if wt_pat.search(content) or wt_pat.search(title) or len(content) < 600:
            a["type"] = TYPE_WEITOUTIAO
            a["type_cn"] = TYPE_CN[TYPE_WEITOUTIAO]
            # 修正 URL 为微头条形式
            if "/article/" in (a.get("url") or ""):
                a["url"] = f"https://www.toutiao.com/w/{a['group_id']}/"
        else:
            a["type"] = TYPE_ARTICLE
            a["type_cn"] = TYPE_CN[TYPE_ARTICLE]


def save_outputs(articles: list[dict], db_subset: list[dict] | None = None) -> None:
    # 先做二次分类
    _reclassify_by_content(articles)

    # JSON 总文件
    json_path = OUTPUT_DIR / "articles.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)
    print(f"💾 JSON 已保存：{json_path}")

    # 同步写入 PostgreSQL（失败不阻塞）
    try:
        from db import save_to_db
        # db_subset 为 None 时写全部（首次迁移或全量重跑）；否则只写新增/更新的子集
        fallback_user_url = USER_URLS[0] if USER_URLS else ""
        save_to_db(db_subset if db_subset is not None else articles, user_url=fallback_user_url)
    except Exception as e:
        print(f"  ⚠️ 数据库模块加载失败：{e}")

    # 按类型分子目录
    type_dirs = {
        TYPE_ARTICLE: MD_DIR / "文章",
        TYPE_WEITOUTIAO: MD_DIR / "微头条",
        TYPE_VIDEO: MD_DIR / "视频",
        TYPE_UNKNOWN: MD_DIR / "未知",
    }
    for d in type_dirs.values():
        d.mkdir(exist_ok=True)

    counters = {k: 0 for k in type_dirs}
    for art in articles:
        t = art.get("type", TYPE_UNKNOWN)
        tag = TYPE_CN.get(t, "未知")
        counters[t] = counters.get(t, 0) + 1

        date_part = art.get("publish_time", "")[:10] or "nodate"
        fname = f"{date_part}_[{tag}]_{_safe_filename(art.get('title'))}_{art.get('group_id', '')[-8:]}.md"
        fname = fname.replace(" ", "_").replace(":", "-")
        path = type_dirs.get(t, MD_DIR) / fname

        md = (
            f"# {art.get('title', '')}\n\n"
            f"- 类型：{tag}\n"
            f"- 发布时间：{art.get('publish_time', '')}\n"
            f"- 原文链接：{art.get('url', '')}\n"
            f"- 点赞：{art.get('digg_count', 0)} ・ 评论：{art.get('comment_count', 0)}\n"
            f"- 摘要：{art.get('abstract', '')}\n\n"
            f"---\n\n"
            f"{art.get('content', '')}\n"
        )
        path.write_text(md, encoding="utf-8")

    stat = "、".join(f"{TYPE_CN.get(k, k)} {v}" for k, v in counters.items() if v)
    print(f"📝 共 {len(articles)} 条内容已输出到：{MD_DIR}（{stat}）")


# ---------------- 入口 ----------------
def _load_previous_articles() -> list[dict]:
    """读取历史 articles.json（优先）或 articles_list.json"""
    for path in (FULL_SNAPSHOT, LIST_SNAPSHOT):
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return data
            except Exception:
                pass
    return []


def _merge_articles(new_list: list[dict], old_list: list[dict]) -> list[dict]:
    """合并新旧数据：以 group_id 去重，新版本优先"""
    merged: dict[str, dict] = {}
    for a in old_list:
        if isinstance(a, dict) and a.get("group_id"):
            merged[a["group_id"]] = a
    for a in new_list:
        if isinstance(a, dict) and a.get("group_id"):
            # 新版本覆盖旧版本，但保留旧版的 content（如果新版没抓到）
            if a["group_id"] in merged and not a.get("content"):
                a["content"] = merged[a["group_id"]].get("content", "")
            merged[a["group_id"]] = a
    # 按发布时间倒序
    return sorted(merged.values(), key=lambda x: x.get("publish_time", ""), reverse=True)


def _fill_legacy_user_info(articles: list[dict], default_user_url: str) -> bool:
    """历史 JSON 没有 user_token，默认归到第一个博主，保证页面筛选能立即生效。"""
    default_user_token = _extract_user_token(default_user_url)
    changed = False
    for art in articles:
        if not isinstance(art, dict) or not art.get("group_id"):
            continue
        if not art.get("user_token"):
            art["user_token"] = default_user_token
            changed = True
        if not art.get("user_url"):
            art["user_url"] = default_user_url
            changed = True
    return changed


def _fill_user_name_for_token(articles: list[dict], user_token: str, user_name: str) -> bool:
    """博主主页识别到名称后，同步补齐历史 JSON 的可读来源名称。"""
    if not user_token or not user_name:
        return False
    changed = False
    for art in articles:
        if not isinstance(art, dict) or art.get("user_token") != user_token:
            continue
        if art.get("user_name") != user_name:
            art["user_name"] = user_name
            changed = True
    return changed


async def main():
    print("=" * 60)
    print("今日头条多博主全部内容抓取（文章 + 微头条 + 视频）")
    print("=" * 60)
    print(f"👥 本次配置博主数：{len(USER_URLS)}")

    # 1. 加载历史数据
    old_articles = _load_previous_articles() if INCREMENTAL else []
    legacy_changed = _fill_legacy_user_info(old_articles, USER_URLS[0]) if old_articles and USER_URLS else False
    known_ids = {a["group_id"] for a in old_articles if a.get("group_id")}
    if INCREMENTAL and known_ids:
        print(f"📂 加载历史数据：{len(known_ids)} 条（增量模式）")
    else:
        print("🆕 首次拉取或全量模式")

    # 2. 逐个博主拉取新增列表，known_ids 会持续更新，避免同一次任务重复抓同一 group_id
    new_articles: list[dict] = []
    for idx, user_url in enumerate(USER_URLS, 1):
        user_token = _extract_user_token(user_url)
        token_label = _short_user_token(user_token)
        print(f"\n👤 [{idx}/{len(USER_URLS)}] 开始抓取博主：{token_label}")
        user_new_articles = await collect_article_list(user_url, known_ids=known_ids)
        legacy_changed = _fill_user_name_for_token(
            old_articles, user_token, USER_NAME_BY_TOKEN.get(user_token, "")
        ) or legacy_changed
        if user_new_articles:
            known_ids.update(a["group_id"] for a in user_new_articles if a.get("group_id"))
            new_articles.extend(user_new_articles)
            print(f"  ✅ 该博主新增 {len(user_new_articles)} 条")
        else:
            print("  ✅ 该博主暂无新增")

    if not new_articles:
        if legacy_changed:
            _save_full_snapshot(old_articles)
        if known_ids:
            print("\n✅ 本次跳脚本无新增内容，任务结束\n")
        else:
            print("❌ 未抓到任何内容，可能原因：接口路径变动 / 页面结构变化 / 被风控")
        return

    stat = {}
    for a in new_articles:
        stat[a.get("type_cn", "未知")] = stat.get(a.get("type_cn", "未知"), 0) + 1
    stat_str = "、".join(f"{k} {v}" for k, v in stat.items())
    print(f"\n📊 本次新增 {len(new_articles)} 条（{stat_str}）\n")

    # 3. 只拓新增条目的正文（旧数据的 content 已在 articles.json 里）
    await fetch_all_contents(new_articles)

    # 4. 合并新旧数据
    merged = _merge_articles(new_articles, old_articles)
    # 入库只写本次新增/更新的子集，避免每次 update 全表
    save_outputs(merged, db_subset=new_articles)
    print(f"\n✅ 全部完成，当前总计 {len(merged)} 条\n")


if __name__ == "__main__":
    asyncio.run(main())
