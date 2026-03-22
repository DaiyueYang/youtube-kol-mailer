"""
模板服务 - 模板 CRUD 业务逻辑

职责：
- 从 SQLite 读取模板（唯一真源）
- 创建/更新/软删除模板
- 按 channel 过滤
- 校验 template_key 唯一性
"""
from repositories.template_repo import template_repo


class TemplateService:
    """模板管理服务"""

    def list_templates(self, channel: str = None, enabled_only: bool = True) -> list:
        """获取模板列表"""
        return template_repo.find_all(channel=channel, enabled_only=enabled_only)

    def get_template(self, template_key: str) -> dict | None:
        """获取单个模板，不存在返回 None"""
        return template_repo.find_by_key(template_key)

    def create_template(self, data: dict) -> dict:
        """
        创建模板。
        如果 template_key 已存在，抛出 ValueError。
        """
        existing = template_repo.find_by_key(data["template_key"])
        if existing:
            raise ValueError(f"template_key '{data['template_key']}' already exists")
        return template_repo.insert(data)

    def update_template(self, template_key: str, data: dict) -> dict:
        """
        更新模板。
        如果 template_key 不存在，抛出 ValueError。
        """
        existing = template_repo.find_by_key(template_key)
        if not existing:
            raise ValueError(f"template_key '{template_key}' not found")
        return template_repo.update(template_key, data)

    def delete_template(self, template_key: str) -> bool:
        """软删除模板（enabled = 0）"""
        existing = template_repo.find_by_key(template_key)
        if not existing:
            raise ValueError(f"template_key '{template_key}' not found")
        return template_repo.soft_delete(template_key)

    def hard_delete_template(self, template_key: str) -> bool:
        """物理删除模板。"""
        existing = template_repo.find_by_key(template_key)
        if not existing:
            raise ValueError(f"template_key '{template_key}' not found")
        return template_repo.hard_delete(template_key)


# 模块级单例
template_service = TemplateService()
