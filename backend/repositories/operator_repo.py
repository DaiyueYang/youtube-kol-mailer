"""
操作者数据仓库 - operators 表 CRUD

存储操作者与其独立 Bitable / SMTP / Bot 的映射关系。
"""
from models.db import get_connection


# TODO: 阶段 4 实现
class OperatorRepo:
    """operators 表 CRUD"""

    def find_by_name(self, operator_name: str) -> dict:
        """按操作者名查询"""
        # TODO: 实现
        return None

    def find_all(self) -> list:
        """查询所有操作者"""
        # TODO: 实现
        return []

    def upsert(self, data: dict) -> dict:
        """新增或更新操作者"""
        # TODO: 实现
        return data
