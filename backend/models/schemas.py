"""
Pydantic 数据模型 - 请求/响应数据校验与 KOL Bitable 字段映射

注意：KOL 模型不是本地数据表，而是后端与 Bitable 之间的字段映射结构。
"""
from typing import Optional, List
from pydantic import BaseModel, Field


# ══════════════════════════════════════
# 模板相关（对应 SQLite templates 表）
# ══════════════════════════════════════

class TemplateCreate(BaseModel):
    """创建模板请求"""
    template_key: str = Field(..., description="唯一标识，如 tmpl_mc_global_v1")
    template_name: str = Field(..., description="后台展示名")
    subject: str = Field("", description="邮件标题模板，支持 {kol_name} 等变量")
    body_text: str = Field("", description="纯文本正文模板")
    body_html: str = Field("", description="HTML 正文模板")
    variables_json: str = Field('["kol_name", "email"]', description="允许的变量清单 JSON 数组")
    channel: str = Field("all", description="适用渠道: youtube / tiktok / all")
    enabled: int = Field(1, description="1 启用，0 停用")


class TemplateUpdate(BaseModel):
    """更新模板请求（所有字段可选）"""
    template_name: Optional[str] = None
    subject: Optional[str] = None
    body_text: Optional[str] = None
    body_html: Optional[str] = None
    variables_json: Optional[str] = None
    channel: Optional[str] = None
    enabled: Optional[int] = None


class TemplateResponse(BaseModel):
    """模板完整响应"""
    id: int
    template_key: str
    template_name: str
    subject: str
    body_text: str
    body_html: str
    variables_json: str
    channel: str
    enabled: int
    version: int
    created_at: str
    updated_at: str


class TemplateListItem(BaseModel):
    """模板列表项（不含正文，供扩展下拉选择用）"""
    template_key: str
    template_name: str
    channel: str
    enabled: int


# ══════════════════════════════════════
# KOL 相关（对应 Bitable KOL 表字段映射）
# 这不是本地数据表，而是后端与 Bitable 之间的数据结构
# ══════════════════════════════════════

class KolUpsertRequest(BaseModel):
    """
    KOL 写入/更新请求（来自 Chrome 扩展）

    扩展抓取 YouTube 页面后，携带此数据调用 POST /api/kols/upsert，
    后端生成 kol_id 后写入 Bitable。
    """
    kol_name: str = Field(..., description="博主名/频道名")
    channel_name: str = Field("", description="频道名称（可能与 kol_name 相同）")
    email: str = Field("", description="联系邮箱")
    source_url: str = Field("", description="频道主页链接")
    country_region: str = Field("", description="地区")
    language: str = Field("English", description="沟通语言")
    followers_text: str = Field("", description="原始粉丝数文本，如 152K")
    category: str = Field("", description="内容分类")
    template_key: str = Field(..., description="所选模板的 template_key")
    template_name: str = Field("", description="所选模板的展示名")
    operator: str = Field("", description="操作者名称")
    notes: str = Field("", description="备注")
    platform: str = Field("YouTube", description="平台")


class KolRecord(BaseModel):
    """
    KOL 完整记录（从 Bitable 读取后的后端数据结构）

    字段与 Bitable KOL 表一一对应，通过 constants.BITABLE_FIELD_MAP 做映射。
    """
    kol_id: str = Field(..., description="后端生成的唯一 ID，如 yt_9f7c2a1d")
    kol_name: str = Field(..., description="博主名/频道名")
    channel_name: str = Field("", description="频道名称")
    email: str = Field("", description="联系邮箱")
    source_url: str = Field("", description="频道主页链接")
    country_region: str = Field("", description="地区")
    language: str = Field("English", description="沟通语言")
    followers_text: str = Field("", description="粉丝数文本")
    category: str = Field("", description="内容分类")
    template_key: str = Field("", description="模板标识")
    template_name: str = Field("", description="模板名称")
    status: str = Field("pending", description="发送状态，见 KolStatus")
    operator: str = Field("", description="操作者")
    notes: str = Field("", description="备注")
    platform: str = Field("YouTube", description="平台")
    last_error: str = Field("", description="最近一次失败原因")
    sent_at: str = Field("", description="正式发送成功时间")
    created_at: str = Field("", description="创建时间")
    updated_at: str = Field("", description="最后更新时间")


# ══════════════════════════════════════
# 发送相关
# ══════════════════════════════════════

class TemplatePreviewRequest(BaseModel):
    """模板预览请求 - 传入变量，渲染模板，不发送邮件"""
    template_key: str
    variables: dict = Field(
        default_factory=dict,
        description="变量字典，如 {\"kol_name\": \"Modestas\", \"kol_id\": \"KOL-001\"}",
    )


class TemplatePreviewResponse(BaseModel):
    """模板预览响应"""
    subject: str
    body_text: str
    body_html: str
    warnings: List[str] = []


class RenderPreviewRequest(BaseModel):
    """渲染预览请求（发送流程用，接收完整 kol_data）"""
    template_key: str
    kol_data: dict


class RenderPreviewResponse(BaseModel):
    """渲染预览响应"""
    subject: str
    body_text: str
    body_html: str
    warnings: List[str] = []


class KolStatusUpdateRequest(BaseModel):
    """KOL 状态更新请求"""
    status: str = Field(..., description="目标状态: pending/preview_sent/confirmed/sending/sent/failed/skipped")
    last_error: str = Field("", description="失败原因（仅 status=failed 时需要）")
    sent_at: str = Field("", description="发送成功时间（仅 status=sent 时自动填充）")


class MailPreviewSendRequest(BaseModel):
    """
    预览发送请求 - 渲染模板并发送到操作者邮箱。

    请求示例:
    {
        "template_key": "tmpl_youtube_general_v1",
        "variables": {
            "kol_id": "KOL-001",
            "kol_name": "Modestas",
            "email": "demo@example.com",
            "category": "Gaming",
            "operator": "Brian"
        },
        "kol_id": "yt_abc12345"
    }
    """
    template_key: str = Field(..., description="模板标识")
    variables: dict = Field(default_factory=dict, description="渲染变量")
    kol_id: Optional[str] = Field(None, description="关联的 KOL ID，如提供则更新状态为 preview_sent")


class SendPreviewRequest(BaseModel):
    """发送预览邮件请求 - 给操作者自己发一封测试（Bot 流程用）"""
    operator: str
    kol_id: Optional[str] = None


class MailSendRequest(BaseModel):
    """
    正式发送请求

    请求示例:
    {
        "kol_ids": ["yt_abc12345", "yt_def67890"]
    }
    """
    kol_ids: List[str] = Field(..., description="要发送的 KOL ID 列表")


class SendConfirmRequest(BaseModel):
    """确认正式发送请求（Bot 流程用）"""
    operator: str
    kol_ids: Optional[List[str]] = None


class SendRetryRequest(BaseModel):
    """重试失败项请求"""
    operator: str
    kol_ids: Optional[List[str]] = None


# ══════════════════════════════════════
# 通用响应
# ══════════════════════════════════════

class ApiResponse(BaseModel):
    """通用 API 响应"""
    success: bool
    message: str
    data: Optional[dict] = None
