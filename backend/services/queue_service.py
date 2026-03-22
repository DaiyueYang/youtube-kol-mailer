"""
发送队列服务 - 逐条发送、随机延迟、断点续发、防重

支持用户级隔离：调用方传入用户专属的 BitableService 和 SmtpService。
不再使用模块级全局单例，避免多用户场景下串用配置。
"""
import asyncio
import random
import logging
from datetime import datetime, timedelta

from config import settings
from models.constants import KolStatus, KOL_CONTACT_CONTACTED, KOL_CONTACT_NOT_CONTACTED
from services.bitable_service import BitableService, bitable_service as default_bitable
from services.template_service import template_service
from services.render_service import render_template
from services.smtp_service import SmtpService, smtp_service as default_smtp
from services.send_validator import validate_email_format

logger = logging.getLogger(__name__)

SENDING_TIMEOUT_SECONDS = 300  # 5 分钟


async def send_batch(
    kol_ids: list[str],
    bitable: BitableService = None,
    smtp: SmtpService = None,
) -> dict:
    """
    批量发送邮件（同步逐条，含随机延迟）。

    参数:
        kol_ids: 要发送的 KOL ID 列表
        bitable: 用户专属 BitableService（不传则用全局默认）
        smtp: 用户专属 SmtpService（不传则用全局默认）
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
        result = await _send_one(kol_id, bitable=bitable, smtp=smtp, index=i, total=len(kol_ids))

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
    """发送单条 KOL 邮件。使用传入的 bitable 和 smtp 实例。"""
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

    # 2. 防重检查 — 只基于 kol_contact_status（忽略旧 status 字段）
    contact_status = kol.get("kol_contact_status", "")
    if contact_status == KOL_CONTACT_CONTACTED:
        return {"kol_id": kol_id, "status": "skipped", "detail": "已联系，跳过"}

    # 3. 校验
    email = kol.get("email", "")
    if not email or not validate_email_format(email):
        detail = f"Invalid or missing email: '{email}'"
        await _safe_set_error(bitable, kol_id, detail)
        return {"kol_id": kol_id, "status": "failed", "detail": detail}

    template_key = kol.get("template_key", "")
    if not template_key:
        detail = "No template_key on KOL record"
        await _safe_set_error(bitable, kol_id, detail)
        return {"kol_id": kol_id, "status": "failed", "detail": detail}

    tmpl = template_service.get_template(template_key)
    if not tmpl:
        detail = f"Template '{template_key}' not found"
        await _safe_set_error(bitable, kol_id, detail)
        return {"kol_id": kol_id, "status": "failed", "detail": detail}

    # 4. 渲染模板
    try:
        rendered = render_template(tmpl, kol)
    except Exception as e:
        detail = f"Render error: {e}"
        await _safe_set_error(bitable, kol_id, detail)
        return {"kol_id": kol_id, "status": "failed", "detail": detail}

    # 5. SMTP 发送
    send_result = smtp.send_email(
        to_email=email,
        subject=rendered["subject"],
        body_text=rendered["body_text"],
        body_html=rendered["body_html"],
    )

    # 6. 回写结果 — 只更新 kol_contact_status + sent_at + last_error
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
            logger.error("%s: Sent but failed to update: %s", log_prefix, e)
        logger.info("%s: Sent to %s", log_prefix, email)
        return {"kol_id": kol_id, "status": "sent", "detail": f"Sent to {email}"}
    else:
        detail = send_result.message
        await _safe_set_error(bitable, kol_id, detail)
        logger.error("%s: Send failed: %s", log_prefix, detail)
        return {"kol_id": kol_id, "status": "failed", "detail": detail}


async def _safe_set_error(bitable, kol_id: str, error: str):
    """安全地设置 last_error（不改变 kol_contact_status）"""
    try:
        existing = await bitable.search_by_kol_id(kol_id)
        if existing:
            await bitable.update_record(existing["_record_id"], {"last_error": error})
    except Exception as e:
        logger.error("Failed to set error for %s: %s", kol_id, e)
    updated_at = kol.get("updated_at", "")
    if not updated_at:
        return True
    try:
        updated_time = datetime.strptime(updated_at, "%Y-%m-%d %H:%M:%S")
        return datetime.utcnow() - updated_time > timedelta(seconds=SENDING_TIMEOUT_SECONDS)
    except (ValueError, TypeError):
        return True


async def _safe_update_status(
    bitable: BitableService,
    kol_id: str,
    current_status: str,
    new_status: str,
    last_error: str = "",
):
    """安全更新状态，忽略状态转换校验错误"""
    try:
        await bitable.update_kol_status(kol_id, new_status, last_error=last_error)
    except ValueError as e:
        logger.warning("Status transition %s -> %s blocked for %s, forcing: %s", current_status, new_status, kol_id, e)
        try:
            existing = await bitable.search_by_kol_id(kol_id)
            if existing:
                now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
                await bitable.update_record(
                    existing["_record_id"],
                    {"status": new_status, "last_error": last_error, "updated_at": now_str},
                )
        except Exception as e2:
            logger.error("Force update also failed for %s: %s", kol_id, e2)
    except Exception as e:
        logger.error("Failed to update status for %s: %s", kol_id, e)
