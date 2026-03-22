"""
模板数据仓库 - templates 表 CRUD

直接操作 SQLite，被 template_service 调用。
"""
from models.db import get_connection


class TemplateRepo:
    """templates 表 CRUD"""

    def find_all(self, channel: str = None, enabled_only: bool = True) -> list:
        """查询模板列表，可按 channel 过滤"""
        conn = get_connection()
        try:
            sql = "SELECT * FROM templates WHERE 1=1"
            params = []

            if enabled_only:
                sql += " AND enabled = 1"

            if channel and channel != "all":
                sql += " AND (channel = ? OR channel = 'all')"
                params.append(channel)

            sql += " ORDER BY id ASC"
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def find_by_key(self, template_key: str) -> dict | None:
        """按 template_key 查询单条"""
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM templates WHERE template_key = ?",
                (template_key,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def insert(self, data: dict) -> dict:
        """插入新模板，返回完整记录"""
        conn = get_connection()
        try:
            conn.execute(
                """
                INSERT INTO templates (
                    template_key, template_name, subject,
                    body_text, body_html, variables_json,
                    channel, enabled
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data["template_key"],
                    data["template_name"],
                    data.get("subject", ""),
                    data.get("body_text", ""),
                    data.get("body_html", ""),
                    data.get("variables_json", '["kol_name", "email"]'),
                    data.get("channel", "all"),
                    data.get("enabled", 1),
                ),
            )
            conn.commit()
            return self.find_by_key(data["template_key"])
        finally:
            conn.close()

    def update(self, template_key: str, data: dict) -> dict | None:
        """
        更新模板，只更新 data 中非 None 的字段。
        同时自增 version 并更新 updated_at。
        """
        conn = get_connection()
        try:
            # 构建动态 SET 子句
            updatable = [
                "template_name", "subject", "body_text", "body_html",
                "variables_json", "channel", "enabled",
            ]
            sets = []
            params = []
            for field in updatable:
                if field in data and data[field] is not None:
                    sets.append(f"{field} = ?")
                    params.append(data[field])

            if not sets:
                return self.find_by_key(template_key)

            sets.append("version = version + 1")
            sets.append("updated_at = datetime('now')")
            params.append(template_key)

            sql = f"UPDATE templates SET {', '.join(sets)} WHERE template_key = ?"
            conn.execute(sql, params)
            conn.commit()
            return self.find_by_key(template_key)
        finally:
            conn.close()

    def soft_delete(self, template_key: str) -> bool:
        """软删除：将 enabled 设为 0"""
        conn = get_connection()
        try:
            cursor = conn.execute(
                "UPDATE templates SET enabled = 0, updated_at = datetime('now') WHERE template_key = ?",
                (template_key,),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def hard_delete(self, template_key: str) -> bool:
        """物理删除模板"""
        conn = get_connection()
        try:
            cursor = conn.execute("DELETE FROM templates WHERE template_key = ?", (template_key,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()


# 模块级单例
template_repo = TemplateRepo()
