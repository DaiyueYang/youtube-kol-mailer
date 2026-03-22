"""
发送任务数据仓库 - send_jobs 表 CRUD

记录发送任务锁、进度、失败项，用于断点续发。
"""
from models.db import get_connection


# TODO: 阶段 5 实现
class SendJobRepo:
    """send_jobs 表 CRUD"""

    def create(self, data: dict) -> dict:
        """创建发送任务"""
        # TODO: 实现
        return data

    def find_by_id(self, job_id: str) -> dict:
        """查询任务"""
        # TODO: 实现
        return None

    def update(self, job_id: str, data: dict) -> dict:
        """更新任务状态"""
        # TODO: 实现
        return data

    def find_active_by_operator(self, operator: str) -> list:
        """查询操作者的活跃任务"""
        # TODO: 实现
        return []
