"""
用户表格数据仓库 - user_tables 表 CRUD

存储每个用户创建的多维表格记录。一个用户可以创建多张表。
"""
from models.db import get_connection


class UserTablesRepo:

    def list_by_user(self, user_id: int) -> list[dict]:
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM user_tables WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def add(self, user_id: int, app_token: str, table_id: str,
            base_name: str, base_url: str, identity: str) -> dict:
        conn = get_connection()
        try:
            conn.execute(
                """INSERT INTO user_tables (user_id, app_token, table_id, base_name, base_url, identity)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (user_id, app_token, table_id, base_name, base_url, identity),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM user_tables WHERE user_id = ? AND app_token = ?",
                (user_id, app_token),
            ).fetchone()
            return dict(row) if row else {}
        finally:
            conn.close()

    def find_by_app_token(self, user_id: int, app_token: str) -> dict | None:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM user_tables WHERE user_id = ? AND app_token = ?",
                (user_id, app_token),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def update_table_id(self, user_id: int, app_token: str, table_id: str):
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE user_tables SET table_id = ? WHERE user_id = ? AND app_token = ?",
                (table_id, user_id, app_token),
            )
            conn.commit()
        finally:
            conn.close()

    def delete_all_by_user(self, user_id: int):
        conn = get_connection()
        try:
            conn.execute("DELETE FROM user_tables WHERE user_id = ?", (user_id,))
            conn.commit()
        finally:
            conn.close()


user_tables_repo = UserTablesRepo()
