"""
发送队列服务 - 逐条发送、随机延迟、防重

错误隔离原则：
- item-level failure（单条 KOL 数据问题）只影响该条，不中断批次
- batch-level failure（SMTP 未配置、Bitable 不可用等环境问题）在调用方提前拦截

防重逻辑统一使用 kol_contact_status 字段（"未联系"/"已联系"）。
"""
import asyncio
import random
import logging
from datetime import datetime

from config import settings
from models.constants import KOL_CONTACT_CONTACTED
from services.bitable_service import BitableService, bitable_service as default_bitable
from services.template_service import template_service
from services.render_service import render_template
from services.smtp_service import SmtpService, smtp_service as default_smtp
from services.send_validator import validate_email_format

logger = logging.getLogger(__name__)


async def send_batch(
    kol_ids: list[str],
    bitable: BitableService = None,
    smtp: SmtpService = None,
) -> dict:
    """
    批量发送邮件（逐条执行，含随机延迟）。

    单条失败只记录到该条结果中，不中断后续发送。
    只有不可恢复的环境级错误（应在调用方提前拦截）才允许整批失败。
    """
    bitable = bitable or default_bitable
    smtp = smtp or default_smtp

    results = []
    sent_count = 0
    failed_count = 0
    skipped_count = 0

    delay_min = settings.SEND_DELAY_MIN
    delay_max = settings.SEND_DELAY_MAX

    logger.info(
        "Starting batch send: %d KOLs, delay %d-%ds, bitable=%s smtp=%s",
        len(kol_ids), delay_min, delay_max,
        bitable.app_token[:8] + "..." if bitable.app_token else "(default)",
        smtp.username[:5] + "..." if smtp.username else "(default)",
    )

    for i, kol_id in enumerate(kol_ids):
        # 关键：单条发送的任何异常都不能中断批次循环
        try:
            result = await _send_one(kol_id, bitable=bitable, smtp=smtp, index=i, total=len(kol_ids))
        except Exception as e:
            # _send_one 内部已有 try/except，此处为最后兜底
            logger.exception("Unexpected error in _send_one for %s", kol_id)
            result = {"kol_id": kol_id, "status": "failed", "detail": f"Unexpected error: {e}"}
            await _safe_set_error(bitable, kol_id, f"Unexpected error: {e}")

        results.append(result)
        if result["status"] == "sent":
            sent_count += 1
        elif result["status"] == "failed":
            failed_count += 1
        else:
            skipped_count += 1

        # 随机延迟（最后一条不延迟）
        if i < len(kol_ids) - 1 and result["status"] in ("sent", "failed"):
            delay = random.randint(delay_min, delay_max)
            logger.debug("Waiting %ds before next send...", delay)
            await asyncio.sleep(delay)

    logger.info(
        "Batch send complete: total=%d sent=%d failed=%d skipped=%d",
        len(kol_ids), sent_count, failed_count, skipped_count,
    )

    return {
        "total": len(kol_ids),
        "sent": sent_count,
        "failed": failed_count,
        "skipped": skipped_count,
        "results": results,
    }


async def _send_one(
    kol_id: str,
    bitable: BitableService,
    smtp: SmtpService,
    index: int = 0,
    total: int = 0,
) -> dict:
    """
    发送单条 KOL 邮件。

    此函数保证不向外抛出异常：所有 item-level 错误都转化为
    {"status": "failed", "detail": "..."} 返回值，并安全写回 last_error。
    """
    log_prefix = f"[{index+1}/{total}] {kol_id}"

    # 1. 读取 KOL 记录
    try:
        kol = await bitable.get_kol_by_id(kol_id)
    except Exception as e:
        logger.error("%s: Failed to read KOL: %s", log_prefix, e)
        return {"kol_id": kol_id, "status": "failed", "detail": f"Read error: {e}"}

    if not kol:
        logger.warning("%s: KOL not found in Bitable", log_prefix)
        return {"kol_id": kol_id, "status": "skipped", "detail": "KOL not found"}

    kol_name = kol.get("kol_name", kol_id)

    # 2. 防重检查 — 基于 kol_contact_status
    contact_status = kol.get("kol_contact_status", "")
    if contact_status == KOL_CONTACT_CONTACTED:
        return {"kol_id": kol_id, "status": "skipped", "detail": "已联系，跳过"}

    # 3. 校验 email
    email = (kol.get("email") or "").strip()
    if not email:
        detail = "No email address"
        logger.warning("%s (%s): %s", log_prefix, kol_name, detail)
        await _safe_set_error(bitable, kol_id, detail)
        return {"kol_id": kol_id, "status": "failed", "detail": detail}
    if not validate_email_format(email):
        detail = f"Invalid email format: {email}"
        logger.warning("%s (%s): %s", log_prefix, kol_name, detail)
        await _safe_set_error(bitable, kol_id, detail)
        return {"kol_id": kol_id, "status": "failed", "detail": detail}

    # 4. 校验模板
    template_key = kol.get("template_key", "")
    if not template_key:
        detail = "No template assigned"
        await _safe_set_error(bitable, kol_id, detail)
        return {"kol_id": kol_id, "status": "failed", "detail": detail}

    tmpl = template_service.get_template(template_key)
    if not tmpl:
        detail = f"Template '{template_key}' not found"
        await _safe_set_error(bitable, kol_id, detail)
        return {"kol_id": kol_id, "status": "failed", "detail": detail}

    # 5. 渲染模板
    try:
        rendered = render_template(tmpl, kol)
    except Exception as e:
        detail = f"Render error: {e}"
        await _safe_set_error(bitable, kol_id, detail)
        return {"kol_id": kol_id, "status": "failed", "detail": detail}

    # 6. SMTP 发送
    try:
        send_result = smtp.send_email(
            to_email=email,
            subject=rendered["subject"],
            body_text=rendered["body_text"],
            body_html=rendered["body_html"],
        )
    except Exception as e:
        detail = f"SMTP unexpected error: {e}"
        logger.exception("%s: %s", log_prefix, detail)
        await _safe_set_error(bitable, kol_id, detail)
        return {"kol_id": kol_id, "status": "failed", "detail": detail}

    # 7. 回写结果 — 更新 kol_contact_status + sent_at + last_error
    if send_result.success:
        now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        try:
            existing = await bitable.search_by_kol_id(kol_id)
            if existing:
                await bitable.update_record(existing["_record_id"], {
                    "kol_contact_status": KOL_CONTACT_CONTACTED,
                    "sent_at": now_str,
                    "last_error": "",
                })
        except Exception as e:
            logger.error("%s: Sent but failed to update Bitable: %s", log_prefix, e)
        logger.info("%s: Sent to %s", log_prefix, email)
        return {"kol_id": kol_id, "status": "sent", "detail": f"Sent to {email}"}
    else:
        detail = send_result.message
        await _safe_set_error(bitable, kol_id, detail)
        logger.error("%s: Send failed: %s", log_prefix, detail)
        return {"kol_id": kol_id, "status": "failed", "detail": detail}


async def _safe_set_error(bitable: BitableService, kol_id: str, error: str):
    """
    安全地将 last_error 写回 Bitable（不改变 kol_contact_status）。
    此函数保证不抛出异常，避免写 last_error 本身导致批次中断。
    """
    try:
        existing = await bitable.search_by_kol_id(kol_id)
        if existing:
            await bitable.update_record(existing["_record_id"], {"last_error": error})
    except Exception as e:
        logger.error("Failed to write last_error for %s: %s (error was: %s)", kol_id, e, error)
