"""
状态机常量与枚举定义

KOL 发送状态流转：

    ┌──────────┐
    │ pending  │  扩展写入 / 后端创建，邮箱有效
    └────┬─────┘
         │
    ┌────┴─────────────────────┐
    │ Bot 触发预览             │ 校验失败（无邮箱等）
    ▼                          ▼
┌──────────────┐          ┌────────┐
│ preview_sent │          │ failed │
└────┬─────────┘          └───┬────┘
     │ 操作者确认              │ 可重试 → 回到 pending
     ▼                         │
┌───────────┐                  │
│ confirmed ├──────────────────┘  校验失败也可 → failed
└────┬──────┘
     │ 进入发送队列
     ▼
┌──────────┐
│ sending  │  正在发送中（防并发，超时 5 分钟自动解锁）
└────┬─────┘
     │
┌────┴────┐
│         │
▼         ▼
┌──────┐  ┌────────┐
│ sent │  │ failed │
└──────┘  └────────┘

任何非终态 → skipped（人工忽略，终态）

关键规则：
- 只有 pending 和 failed 允许进入发送候选集
- preview_sent 不代表已给 KOL 发出正式邮件，只代表操作者收到了预览
- 一条 KOL 进入 sent 后，后端必须通过 kol_id + status 锁避免重复发信
- sending 是发送过程中的临时锁定状态，防止并发
- skipped 是终态，不参与任何自动流程
"""


class KolStatus:
    """KOL 发送状态枚举"""

    PENDING = "pending"              # 待联系 - 新写入且邮箱有效
    PREVIEW_SENT = "preview_sent"    # 预览已发送 - 操作者已收到测试预览
    CONFIRMED = "confirmed"          # 已确认 - 操作者已确认发送
    SENDING = "sending"              # 发送中 - 正在 SMTP 发信（临时锁）
    SENT = "sent"                    # 已发送 - SMTP 正式发送成功
    FAILED = "failed"                # 发送失败 - SMTP 或渲染失败
    SKIPPED = "skipped"              # 忽略 - 人工标记不发送

    # 允许进入发送候选集的状态
    SENDABLE = {PENDING, FAILED}

    # 终态（不再参与自动流程）
    TERMINAL = {SENT, SKIPPED}

    # 所有合法状态
    ALL = {PENDING, PREVIEW_SENT, CONFIRMED, SENDING, SENT, FAILED, SKIPPED}

    # 状态流转映射：当前状态 -> 允许转入的下一个状态集合
    TRANSITIONS = {
        PENDING:      {PREVIEW_SENT, CONFIRMED, SENDING, FAILED, SKIPPED},
        PREVIEW_SENT: {CONFIRMED, SKIPPED},
        CONFIRMED:    {SENDING, FAILED, SKIPPED},
        SENDING:      {SENT, FAILED},
        SENT:         set(),          # 终态，不允许再变
        FAILED:       {PENDING, SENDING, SKIPPED},  # 重试时可回到 pending 或直接进入 sending
        SKIPPED:      set(),          # 终态
    }

    @classmethod
    def can_transition(cls, from_status: str, to_status: str) -> bool:
        """检查状态转换是否合法"""
        if from_status not in cls.ALL or to_status not in cls.ALL:
            return False
        return to_status in cls.TRANSITIONS.get(from_status, set())


class SendJobStatus:
    """发送任务状态枚举（send_jobs 表）"""

    DRAFT = "draft"            # 草稿 - 任务刚创建
    PREVIEWED = "previewed"    # 已预览 - 预览邮件已发出
    CONFIRMED = "confirmed"    # 已确认 - 等待执行
    RUNNING = "running"        # 执行中
    DONE = "done"              # 完成
    FAILED = "failed"          # 失败（部分或全部）
    CANCELLED = "cancelled"    # 已取消


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
