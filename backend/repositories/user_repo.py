"""
用户数据仓库 - users 表 CRUD

存储飞书 OAuth 用户信息 + 用户级 Bitable/SMTP 配置。
"""
import time
from models.db import get_connection


class UserRepo:
    """users 表 CRUD"""

    def find_by_open_id(self, feishu_open_id: str) -> dict | None:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM users WHERE feishu_open_id = ?",
                (feishu_open_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def find_by_session(self, session_token: str) -> dict | None:
        if not session_token:
            return None
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM users WHERE session_token = ?",
                (session_token,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def find_by_id(self, user_id: int) -> dict | None:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def upsert_oauth(
        self,
        feishu_open_id: str,
        feishu_union_id: str,
        display_name: str,
        avatar_url: str,
        user_access_token: str,
        refresh_token: str,
        token_expires_at: float,
        session_token: str,
    ) -> dict:
        """创建或更新 OAuth 登录信息，返回用户记录"""
        conn = get_connection()
        try:
            existing = conn.execute(
                "SELECT id FROM users WHERE feishu_open_id = ?",
                (feishu_open_id,),
            ).fetchone()

            if existing:
                conn.execute(
                    """UPDATE users SET
                        feishu_union_id = ?, display_name = ?, avatar_url = ?,
                        session_token = ?, user_access_token = ?,
                        refresh_token = ?, token_expires_at = ?,
                        updated_at = datetime('now')
                    WHERE feishu_open_id = ?""",
                    (
                        feishu_union_id, display_name, avatar_url,
                        session_token, user_access_token,
                        refresh_token, token_expires_at,
                        feishu_open_id,
                    ),
                )
            else:
                conn.execute(
                    """INSERT INTO users (
                        feishu_open_id, feishu_union_id, display_name, avatar_url,
                        session_token, user_access_token, refresh_token, token_expires_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        feishu_open_id, feishu_union_id, display_name, avatar_url,
                        session_token, user_access_token, refresh_token, token_expires_at,
                    ),
                )
            conn.commit()
            return self.find_by_open_id(feishu_open_id)
        finally:
            conn.close()

    def update_tokens(
        self,
        user_id: int,
        user_access_token: str,
        refresh_token: str,
        token_expires_at: float,
    ):
        conn = get_connection()
        try:
            conn.execute(
                """UPDATE users SET
                    user_access_token = ?, refresh_token = ?,
                    token_expires_at = ?, updated_at = datetime('now')
                WHERE id = ?""",
                (user_access_token, refresh_token, token_expires_at, user_id),
            )
            conn.commit()
        finally:
            conn.close()

    def update_settings(self, user_id: int, data: dict):
        """更新用户的 Bitable/SMTP 配置"""
        conn = get_connection()
        try:
            updatable = [
                "bitable_app_token", "bitable_table_id", "bitable_identity",
                "smtp_email", "smtp_password", "smtp_from_name", "preview_email",
            ]
            sets = []
            params = []
            for field in updatable:
                if field in data:
                    sets.append(f"{field} = ?")
                    params.append(data[field])

            if not sets:
                return

            sets.append("updated_at = datetime('now')")
            params.append(user_id)
            sql = f"UPDATE users SET {', '.join(sets)} WHERE id = ?"
            conn.execute(sql, params)
            conn.commit()
        finally:
            conn.close()

    def clear_session(self, user_id: int):
        conn = get_connection()
        try:
            conn.execute(
                """UPDATE users SET
                    session_token = '', user_access_token = '',
                    refresh_token = '', token_expires_at = 0,
                    updated_at = datetime('now')
                WHERE id = ?""",
                (user_id,),
            )
            conn.commit()
        finally:
            conn.close()


user_repo = UserRepo()
