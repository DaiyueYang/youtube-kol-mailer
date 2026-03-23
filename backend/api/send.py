"""
发送相关 API

- POST   /api/render/preview            只渲染 subject/body，不发送
- POST   /api/mail/preview-send         渲染 + 发送预览邮件到操作者邮箱
- POST   /api/mail/send                 正式发送（逐条，含随机延迟、防重）
- POST   /api/send/confirm              确认正式发送（Bot 流程入口，同 /api/mail/send）
- POST   /api/send/retry                重试失败项
"""
import logging
from fastapi import APIRouter, HTTPException, Request
from models.schemas import (
    RenderPreviewRequest,
    MailPreviewSendRequest,
    MailSendRequest,
    SendConfirmRequest,
    SendRetryRequest,
)
from services.template_service import template_service
from services.render_service import render_template
from services.send_validator import validate_before_send
from services.queue_service import send_batch
from services.user_context import get_user_context

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/render/preview")
async def render_preview(req: RenderPreviewRequest):
    """
    只渲染模板，返回 subject / body_text / body_html，不发送邮件。
    """
    tmpl = template_service.get_template(req.template_key)
    if not tmpl:
        raise HTTPException(status_code=404, detail=f"Template '{req.template_key}' not found")

    rendered = render_template(tmpl, req.kol_data)

    return {
        "success": True,
        "data": rendered,
        "message": "ok" if not rendered["warnings"] else "rendered with warnings",
    }


@router.post("/mail/preview-send")
async def mail_preview_send(req: MailPreviewSendRequest, request: Request):
    """渲染模板并发送一封预览邮件。使用当前用户的 SMTP。"""
    ctx = get_user_context(request)
    await ctx.ensure_fresh_token()

    kol_data = dict(req.variables)
    if "email" not in kol_data or not kol_data["email"]:
        kol_data["email"] = "preview@placeholder.com"

    # 使用用户级 SMTP 进行校验和发送（不 fallback 到全局）
    user_smtp = ctx.get_smtp_service()
    if not user_smtp:
        return {"success": False, "message": "SMTP 未配置，请先在 Dashboard SMTP 页签设置邮箱和密码", "data": None}
    validation = validate_before_send(kol_data, req.template_key, smtp=user_smtp)

    if not validation["valid"]:
        return {
            "success": False, "message": "Validation failed",
            "data": {"errors": validation["errors"], "warnings": validation["warnings"]},
        }

    preview_email = ctx.get_preview_email()
    if not preview_email:
        return {"success": False, "message": "预览邮箱未配置", "data": None}

    rendered = validation["rendered"]

    result = user_smtp.send_preview_email(
        to_email=preview_email,
        subject=rendered["subject"],
        body_text=rendered["body_text"],
        body_html=rendered["body_html"],
    )

    if not result.success:
        return {
            "success": False, "message": f"Preview send failed: {result.message}",
            "data": {"rendered": rendered, "send_error": result.message},
        }

    return {
        "success": True,
        "message": "Preview email sent",
        "data": {
            "sent_to": preview_email,
            "subject": result.subject,
            "rendered": rendered,
            "warnings": rendered.get("warnings", []),
        },
    }


@router.post("/mail/send")
async def mail_send(req: MailSendRequest, request: Request):
    """正式发送邮件。使用当前用户的 Bitable + SMTP 配置。"""
    if not req.kol_ids:
        return {"success": False, "message": "kol_ids list is empty", "data": None}

    ctx = get_user_context(request)
    await ctx.ensure_fresh_token()
    user_bitable = ctx.get_bitable_service()
    user_smtp = ctx.get_smtp_service()
    if not user_smtp:
        return {"success": False, "message": "SMTP 未配置，请先在 Dashboard SMTP 页签设置邮箱和密码", "data": None}

    smtp_missing = user_smtp.check_config()
    if smtp_missing:
        return {"success": False, "message": f"SMTP config incomplete, missing: {', '.join(smtp_missing)}", "data": None}

    result = await send_batch(req.kol_ids, bitable=user_bitable, smtp=user_smtp)

    return {
        "success": True,
        "message": (
            f"Batch complete: {result['sent']} sent, "
            f"{result['failed']} failed, "
            f"{result['skipped']} skipped"
        ),
        "data": result,
    }


@router.post("/send/confirm")
async def send_confirm(req: SendConfirmRequest, request: Request):
    """确认正式发送。使用当前用户的配置。"""
    ctx = get_user_context(request)
    await ctx.ensure_fresh_token()
    user_bitable = ctx.get_bitable_service()
    user_smtp = ctx.get_smtp_service()
    if not user_smtp:
        return {"success": False, "message": "SMTP 未配置，请先在 Dashboard SMTP 页签设置邮箱和密码", "data": None}

    kol_ids = req.kol_ids
    if not kol_ids:
        try:
            pending = await user_bitable.list_pending_kols(operator=req.operator)
            kol_ids = [k["kol_id"] for k in pending if k.get("kol_id")]
        except Exception as e:
            return {"success": False, "message": f"Failed to fetch pending KOLs: {e}", "data": None}

    if not kol_ids:
        return {"success": True, "message": "No pending KOLs to send",
                "data": {"total": 0, "sent": 0, "failed": 0, "skipped": 0, "results": []}}

    smtp_missing = user_smtp.check_config()
    if smtp_missing:
        return {"success": False, "message": f"SMTP config incomplete, missing: {', '.join(smtp_missing)}", "data": None}

    result = await send_batch(kol_ids, bitable=user_bitable, smtp=user_smtp)
    return {"success": True, "message": f"Batch complete: {result['sent']} sent, {result['failed']} failed, {result['skipped']} skipped", "data": result}


@router.post("/send/retry")
async def send_retry(req: SendRetryRequest, request: Request):
    """重试失败项。使用当前用户的配置。"""
    ctx = get_user_context(request)
    await ctx.ensure_fresh_token()
    user_bitable = ctx.get_bitable_service()
    user_smtp = ctx.get_smtp_service()
    if not user_smtp:
        return {"success": False, "message": "SMTP 未配置，请先在 Dashboard SMTP 页签设置邮箱和密码", "data": None}

    kol_ids = req.kol_ids
    if not kol_ids:
        try:
            records = await user_bitable.list_pending_kols(operator=req.operator)
            kol_ids = [k["kol_id"] for k in records if k.get("kol_id")]
        except Exception as e:
            return {"success": False, "message": f"Failed to fetch KOLs: {e}", "data": None}

    if not kol_ids:
        return {"success": True, "message": "没有需要重试的 KOL",
                "data": {"total": 0, "sent": 0, "failed": 0, "skipped": 0, "results": []}}

    smtp_missing = user_smtp.check_config()
    if smtp_missing:
        return {"success": False, "message": f"SMTP config incomplete, missing: {', '.join(smtp_missing)}", "data": None}

    result = await send_batch(kol_ids, bitable=user_bitable, smtp=user_smtp)
    return {"success": True, "message": f"Retry complete: {result['sent']} sent, {result['failed']} failed, {result['skipped']} skipped", "data": result}
