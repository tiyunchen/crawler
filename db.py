"""
PostgreSQL 持久化模块
====================
- 依赖：psycopg2-binary（同步客户端，够用且依赖少）
- 连接：读取 .env 中的 DATABASE_URL，例如：
    DATABASE_URL=postgresql://user:password@localhost:5432/toutiao
- 表：toutiao_articles，group_id 为主键，写入用 upsert（ON CONFLICT DO UPDATE）
- 调用方式：save_to_db(articles, user_token=...) 即可；失败只打印告警，不中断主流程
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
DB_TABLE = os.getenv("DB_TABLE", "toutiao_articles").strip() or "toutiao_articles"

SCHEMA_SQL = f"""
CREATE TABLE IF NOT EXISTS {DB_TABLE} (
    group_id      VARCHAR(64) PRIMARY KEY,
    user_token    VARCHAR(128),
    type          VARCHAR(32),
    type_cn       VARCHAR(16),
    title         TEXT,
    url           TEXT,
    publish_time  TIMESTAMPTZ,
    abstract      TEXT,
    source        VARCHAR(256),
    content       TEXT,
    comment_count INTEGER DEFAULT 0,
    digg_count    INTEGER DEFAULT 0,
    has_video     BOOLEAN DEFAULT FALSE,
    video_id      VARCHAR(64),
    raw           JSONB,
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    updated_at    TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_{DB_TABLE}_publish_time ON {DB_TABLE}(publish_time DESC);
CREATE INDEX IF NOT EXISTS idx_{DB_TABLE}_type         ON {DB_TABLE}(type);
CREATE INDEX IF NOT EXISTS idx_{DB_TABLE}_user_token   ON {DB_TABLE}(user_token);
"""

UPSERT_SQL = f"""
INSERT INTO {DB_TABLE} (
    group_id, user_token, type, type_cn, title, url, publish_time,
    abstract, source, content, comment_count, digg_count,
    has_video, video_id, raw, updated_at
) VALUES %s
ON CONFLICT (group_id) DO UPDATE SET
    user_token    = EXCLUDED.user_token,
    type          = EXCLUDED.type,
    type_cn       = EXCLUDED.type_cn,
    title         = EXCLUDED.title,
    url           = EXCLUDED.url,
    publish_time  = EXCLUDED.publish_time,
    abstract      = EXCLUDED.abstract,
    source        = EXCLUDED.source,
    -- content 只在新值非空时才覆盖，避免抓取失败把旧正文清掉
    content       = CASE
                      WHEN COALESCE(EXCLUDED.content, '') <> '' THEN EXCLUDED.content
                      ELSE {DB_TABLE}.content
                    END,
    comment_count = EXCLUDED.comment_count,
    digg_count    = EXCLUDED.digg_count,
    has_video     = EXCLUDED.has_video,
    video_id      = EXCLUDED.video_id,
    raw           = EXCLUDED.raw,
    updated_at    = NOW();
"""


def _extract_user_token(url: str) -> str:
    """从博主主页 URL 提取 user_token"""
    m = re.search(r"/token/([A-Za-z0-9_\-]+)", url or "")
    return m.group(1) if m else ""


def _to_row(art: dict, user_token: str) -> tuple:
    """把 article dict 转成 upsert 的值 tuple"""
    pub = art.get("publish_time") or None
    # 空字符串在 pg 的 TIMESTAMPTZ 上会报错，统一转 None
    if isinstance(pub, str) and not pub.strip():
        pub = None
    return (
        str(art.get("group_id") or ""),
        user_token,
        art.get("type") or "",
        art.get("type_cn") or "",
        art.get("title") or "",
        art.get("url") or "",
        pub,
        art.get("abstract") or "",
        art.get("source") or "",
        art.get("content") or "",
        int(art.get("comment_count") or 0),
        int(art.get("digg_count") or 0),
        bool(art.get("has_video")),
        art.get("video_id") or "",
        json.dumps(art, ensure_ascii=False),
    )


def save_to_db(articles: list[dict], user_url: str = "") -> bool:
    """
    把文章列表 upsert 进 PG。
    - 未配置 DATABASE_URL 时直接跳过（不报错，兼容仅想用 JSON 的场景）
    - 任何异常只打印告警，不抛出
    返回：是否成功写入
    """
    if not DATABASE_URL:
        print("ℹ️  未配置 DATABASE_URL，跳过数据库写入（仅保存 JSON/Markdown）")
        return False

    try:
        import psycopg2
        from psycopg2.extras import execute_values
    except ImportError:
        print("⚠️  未安装 psycopg2-binary，跳过数据库写入。安装命令：pip install psycopg2-binary")
        return False

    user_token = _extract_user_token(user_url)
    rows = [_to_row(a, user_token) for a in articles if a.get("group_id")]
    if not rows:
        print("ℹ️  无可入库数据")
        return False

    try:
        conn = psycopg2.connect(DATABASE_URL)
    except Exception as e:
        print(f"⚠️  数据库连接失败：{e}")
        return False

    try:
        with conn:
            with conn.cursor() as cur:
                # 首次建表
                cur.execute(SCHEMA_SQL)
                # 批量 upsert（每批 500 条，避免一次性 SQL 过长）
                # 注意：execute_values 的 template 必须和 INSERT 的列数匹配
                template = (
                    "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, NOW())"
                )
                execute_values(cur, UPSERT_SQL, rows, template=template, page_size=500)
        print(f"🗄️  PostgreSQL 入库成功：{len(rows)} 条 → {DB_TABLE}")
        return True
    except Exception as e:
        print(f"⚠️  数据库写入失败：{e}")
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass
