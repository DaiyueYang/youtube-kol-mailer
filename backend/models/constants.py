"""
常量定义

KOL 联系状态（kol_contact_status）：
- 未联系：新写入，尚未发送邮件
- 已联系：邮件发送成功

防重规则：kol_contact_status = "已联系" 的 KOL 不会重复发信。
"""


# Bitable KOL 表字段名 -> 后端字段名 映射
# 左侧是 Bitable 中的字段名，右侧是后端代码中使用的字段名
BITABLE_FIELD_MAP = {
    "kol_id":         "kol_id",
    "kol_name":       "kol_name",
    "channel_name":   "channel_name",     # 频道名称（可能与 kol_name 相同）
    "platform":       "platform",
    "channel_url":    "source_url",       # Bitable 中叫 channel_url，后端模型叫 source_url
    "email":          "email",
    "country_region": "country_region",
    "language":       "language",
    "followers_text": "followers_text",
    "category":       "category",
    "template_id":    "template_key",     # Bitable 中叫 template_id，后端模型叫 template_key
    "template_name":  "template_name",
    "operator":       "operator",
    "notes":          "notes",
    "last_error":     "last_error",
    "sent_at":        "sent_at",
    "created_at":     "created_at",
    "updated_at":     "updated_at",
    "kol_contact_status": "kol_contact_status",
}

# 反向映射：后端字段名 -> Bitable 字段名
BACKEND_TO_BITABLE = {v: k for k, v in BITABLE_FIELD_MAP.items()}

# KOL 表默认名称（自动创建时使用）
KOL_TABLE_NAME = "KOL"

# KOL 表 init-bitable 创建的最小字段集
# 只包含扩展写入 + 后端发送流程实际需要的字段
# type 1 = 多行文本
KOL_TABLE_FIELDS = [
    {"field_name": "kol_id", "type": 1},
    {"field_name": "kol_name", "type": 1},
    {"field_name": "email", "type": 1},
    {"field_name": "channel_url", "type": 1},
    {"field_name": "template_id", "type": 1},
    {"field_name": "operator", "type": 1},
    {"field_name": "category", "type": 1},
    {"field_name": "followers_text", "type": 1},
    {"field_name": "last_error", "type": 1},
    {"field_name": "sent_at", "type": 1},
    # 单选字段：type=3, 带 options
    {
        "field_name": "kol_contact_status",
        "type": 3,
        "property": {
            "options": [
                {"name": "未联系", "color": 0},
                {"name": "已联系", "color": 1},
            ]
        },
    },
]

# KOL 联系状态常量
KOL_CONTACT_NOT_CONTACTED = "未联系"
KOL_CONTACT_CONTACTED = "已联系"
