"""
SQLite 数据库初始化与连接管理

后端内部数据库包含 4 张表：
- templates:    邮件模板库（唯一真源，不在 Bitable）
- operators:    操作者与 Bitable/SMTP/Bot 映射
- send_jobs:    发送任务锁与重试状态
- app_settings: 全局键值配置

注意：KOL 数据不存在本地，只存在飞书 Bitable 中。
"""
import sqlite3
from pathlib import Path
from config import settings


def get_db_path() -> str:
    """获取数据库文件路径，确保目录存在"""
    db_path = Path(settings.DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return str(db_path)


def get_connection() -> sqlite3.Connection:
    """获取数据库连接（每次调用返回新连接，调用方负责关闭）"""
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """
    初始化数据库，创建所有表。
    使用 IF NOT EXISTS，可重复执行。
    """
    conn = get_connection()
    cursor = conn.cursor()

    # ── templates 表 ──
    # 邮件模板库，唯一真源存于 SQLite
    # template_key 是稳定唯一标识（如 tmpl_mc_global_v1），用于扩展和 Bitable 引用
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS templates (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            template_key    TEXT NOT NULL UNIQUE,
            template_name   TEXT NOT NULL,
            subject         TEXT NOT NULL DEFAULT '',
            body_text       TEXT NOT NULL DEFAULT '',
            body_html       TEXT NOT NULL DEFAULT '',
            variables_json  TEXT NOT NULL DEFAULT '["kol_name", "email"]',
            channel         TEXT NOT NULL DEFAULT 'all',
            enabled         INTEGER NOT NULL DEFAULT 1,
            version         INTEGER NOT NULL DEFAULT 1,
            created_at      TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)

    # ── operators 表 ──
    # [历史/未使用] 多操作者配置预留表，当前无业务代码读写此表。
    # daily_limit 等字段为历史设计遗留，不参与任何业务逻辑。
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS operators (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            operator_name       TEXT NOT NULL UNIQUE,
            bitable_app_token   TEXT NOT NULL DEFAULT '',
            bitable_table_id    TEXT NOT NULL DEFAULT '',
            smtp_user           TEXT NOT NULL DEFAULT '',
            smtp_password       TEXT NOT NULL DEFAULT '',
            smtp_from_name      TEXT NOT NULL DEFAULT '',
            preview_email       TEXT NOT NULL DEFAULT '',
            bot_webhook         TEXT NOT NULL DEFAULT '',
            daily_limit         INTEGER NOT NULL DEFAULT 20,
            enabled             INTEGER NOT NULL DEFAULT 1,
            created_at          TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)

    # ── send_jobs 表 ──
    # [历史/未使用] 发送任务锁预留表，当前无业务代码读写此表。
    # job_status 等字段为历史设计遗留，不参与任何业务逻辑。
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS send_jobs (
            job_id              TEXT PRIMARY KEY,
            operator            TEXT NOT NULL,
            job_status          TEXT NOT NULL DEFAULT 'draft',
            candidate_count     INTEGER NOT NULL DEFAULT 0,
            success_count       INTEGER NOT NULL DEFAULT 0,
            fail_count          INTEGER NOT NULL DEFAULT 0,
            kol_ids_json        TEXT NOT NULL DEFAULT '[]',
            failed_ids_json     TEXT NOT NULL DEFAULT '[]',
            last_success_kol_id TEXT NOT NULL DEFAULT '',
            created_at          TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)

    # ── users 表 ──
    # 飞书 OAuth 用户 + 用户级 Bitable/SMTP 配置
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            feishu_open_id      TEXT NOT NULL UNIQUE,
            feishu_union_id     TEXT NOT NULL DEFAULT '',
            display_name        TEXT NOT NULL DEFAULT '',
            avatar_url          TEXT NOT NULL DEFAULT '',
            session_token       TEXT NOT NULL DEFAULT '',
            user_access_token   TEXT NOT NULL DEFAULT '',
            refresh_token       TEXT NOT NULL DEFAULT '',
            token_expires_at    REAL NOT NULL DEFAULT 0,
            bitable_app_token   TEXT NOT NULL DEFAULT '',
            bitable_table_id    TEXT NOT NULL DEFAULT '',
            bitable_identity    TEXT NOT NULL DEFAULT '',
            smtp_email          TEXT NOT NULL DEFAULT '',
            smtp_password       TEXT NOT NULL DEFAULT '',
            smtp_from_name      TEXT NOT NULL DEFAULT '',
            preview_email       TEXT NOT NULL DEFAULT '',
            created_at          TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)

    # ── user_tables 表 ──
    # 用户创建的多维表格记录（一个用户可以创建多张）
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_tables (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER NOT NULL,
            app_token       TEXT NOT NULL,
            table_id        TEXT NOT NULL DEFAULT '',
            base_name       TEXT NOT NULL DEFAULT '',
            base_url        TEXT NOT NULL DEFAULT '',
            identity        TEXT NOT NULL DEFAULT 'user',
            created_at      TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    # ── app_settings 表 ──
    # 全局键值配置
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS app_settings (
            key         TEXT PRIMARY KEY,
            value       TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)

    # ── pending_tokens 表 ──
    # OAuth 扩展登录的一次性 token（持久化，避免重启丢失）
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pending_tokens (
            state           TEXT PRIMARY KEY,
            session_token   TEXT NOT NULL,
            created_at      REAL NOT NULL
        )
    """)

    # ── processed_events 表 ──
    # 飞书事件去重（持久化，避免重启后重复处理）
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS processed_events (
            event_id        TEXT PRIMARY KEY,
            processed_at    REAL NOT NULL
        )
    """)

    conn.commit()
    conn.close()
    print("Database initialized successfully.")
