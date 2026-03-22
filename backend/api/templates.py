"""
模板管理 API

- GET    /api/templates                    获取模板列表（供扩展下拉框 + 后台管理）
- GET    /api/templates/{template_key}     获取模板详情
- POST   /api/templates                    新建模板
- PUT    /api/templates/{template_key}     更新模板
- DELETE /api/templates/{template_key}     软删除模板（enabled=0）
- POST   /api/templates/preview            渲染模板预览（不发送邮件）
"""
from fastapi import APIRouter, HTTPException
from models.schemas import (
    TemplateCreate,
    TemplateUpdate,
    TemplatePreviewRequest,
    TemplatePreviewResponse,
    ApiResponse,
)
from services.template_service import template_service
from services.render_service import render_template

router = APIRouter()


@router.get("/templates")
async def list_templates(channel: str = None, enabled_only: bool = True):
    """
    获取模板列表。

    Query params:
        channel:      过滤渠道（youtube / tiktok / all），不传则返回全部
        enabled_only: 是否只返回启用的模板（默认 true）

    返回格式适配扩展下拉框：每条包含 template_key + template_name + enabled。
    """
    templates = template_service.list_templates(channel=channel, enabled_only=enabled_only)
    return {
        "success": True,
        "data": {
            "templates": templates,
            "total": len(templates),
        },
        "message": "ok",
    }


@router.get("/templates/{template_key}")
async def get_template(template_key: str):
    """获取单个模板完整详情"""
    tmpl = template_service.get_template(template_key)
    if not tmpl:
        raise HTTPException(status_code=404, detail=f"Template '{template_key}' not found")
    return {
        "success": True,
        "data": tmpl,
        "message": "ok",
    }


@router.post("/templates")
async def create_template(req: TemplateCreate):
    """新建模板"""
    try:
        tmpl = template_service.create_template(req.model_dump())
        return {
            "success": True,
            "data": tmpl,
            "message": f"Template '{req.template_key}' created",
        }
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.put("/templates/{template_key}")
async def update_template(template_key: str, req: TemplateUpdate):
    """更新模板（只更新请求中非 None 的字段）"""
    try:
        data = {k: v for k, v in req.model_dump().items() if v is not None}
        tmpl = template_service.update_template(template_key, data)
        return {
            "success": True,
            "data": tmpl,
            "message": f"Template '{template_key}' updated",
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/templates/{template_key}")
async def delete_template(template_key: str, hard: bool = False):
    """
    删除模板。
    hard=false（默认）：软删除（enabled=0，保留记录）
    hard=true：物理删除（从数据库移除）
    """
    try:
        if hard:
            template_service.hard_delete_template(template_key)
            return {"success": True, "data": None, "message": f"Template '{template_key}' deleted"}
        else:
            template_service.delete_template(template_key)
            return {"success": True, "data": None, "message": f"Template '{template_key}' disabled"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/templates/preview")
async def preview_template(req: TemplatePreviewRequest):
    """
    渲染模板预览 - 只做变量替换，不发送邮件。

    请求示例:
    {
        "template_key": "tmpl_youtube_general_v1",
        "variables": {
            "kol_id": "KOL-001",
            "kol_name": "Modestas",
            "category": "Gaming",
            "operator": "Brian"
        }
    }
    """
    tmpl = template_service.get_template(req.template_key)
    if not tmpl:
        raise HTTPException(status_code=404, detail=f"Template '{req.template_key}' not found")

    result = render_template(tmpl, req.variables)

    return {
        "success": True,
        "data": result,
        "message": "ok" if not result["warnings"] else "rendered with warnings",
    }
