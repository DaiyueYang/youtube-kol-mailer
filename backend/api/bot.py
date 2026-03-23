"""
飞书应用机器人 API — 交互卡片方案（多用户隔离版）

接口：
  POST /api/bot/event          飞书事件订阅入口（im.message.receive_v1）
  POST /api/bot/card-callback  飞书卡片交互回调（按钮点击）
  POST /api/bot/command        手动 API 调用（测试/备用）
  POST /api/bot/test-card      测试发送交互卡片（Admin 用）
  POST /api/bot/test-text      测试发送文本消息（Admin 用）

用户隔离：
  - 事件入口通过 sender.open_id 查找本地用户
  - 卡片按钮 value 中携带 user_id
  - 回调通过 user_id 恢复用户上下文
  - preview/confirm/refresh 使用用户专属 Bitable + SMTP
"""
import asyncio
import json
import re
import time
import logging
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from config import settings
from models.db import get_connection
from services.bot_service import bot_service
from services.template_service import template_service
from services.render_service import render_template
from services.queue_service import send_batch
from services.user_context import get_user_context_by_open_id, get_user_context_by_id, UserContext

logger = logging.getLogger(__name__)
router = APIRouter()

DEFAULT_OPERATOR = "default"

# 事件去重 TTL（秒）
_EVENT_TTL = 300

# 每用户发送锁：防止同一用户并发重复发送，但不同用户互不阻塞
_user_send_locks: dict[int, asyncio.Lock] = {}

# 最近操作日志（调试用，内存中保留最近 20 条）
_recent_actions: list[dict] = []
_MAX_RECENT = 20


def _log_action(action: str, user_id: int | None, operator: str, detail: str):
    """记录最近操作日志"""
    entry = {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "action": action,
        "user_id": user_id,
        "operator": operator,
        "detail": detail[:200],
    }
    _recent_actions.append(entry)
    if len(_recent_actions) > _MAX_RECENT:
        _recent_actions.pop(0)


def _get_user_lock(user_id: int | None) -> asyncio.Lock:
    """获取用户级发送锁"""
    key = user_id or 0
    if key not in _user_send_locks:
        _user_send_locks[key] = asyncio.Lock()
    return _user_send_locks[key]


# ══════════════════════════════════════
# 持久化事件去重（SQLite）
# ══════════════════════════════════════

def _is_duplicate_event(event_id: str) -> bool:
    """检查事件是否已处理（持久化到 SQLite）"""
    now = time.time()
    conn = get_connection()
    try:
        # 清理过期事件
        conn.execute("DELETE FROM processed_events WHERE processed_at < ?", (now - _EVENT_TTL,))
        # 检查是否已存在
        row = conn.execute("SELECT 1 FROM processed_events WHERE event_id = ?", (event_id,)).fetchone()
        if row:
            conn.commit()
            return True
        # 记录新事件
        conn.execute(
            "INSERT INTO processed_events (event_id, processed_at) VALUES (?, ?)",
            (event_id, now),
        )
        conn.commit()
        return False
    finally:
        conn.close()


# ══════════════════════════════════════
# 飞书事件订阅入口
# ══════════════════════════════════════

@router.post("/bot/event")
async def handle_feishu_event(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(content={})

    if "challenge" in body:
        logger.info("Feishu challenge verification received")
        return JSONResponse(content={"challenge": body["challenge"]})

    if body.get("type") == "url_verification":
        return JSONResponse(content={"challenge": body.get("challenge", "")})

    header = body.get("header", {})
    event_type = header.get("event_type", "")
    event_id = header.get("event_id", "")

    if event_id and _is_duplicate_event(event_id):
        return {"success": True, "message": "Duplicate event ignored"}

    if event_type != "im.message.receive_v1":
        return {"success": True, "message": "Event type ignored"}

    event = body.get("event", {})
    message = event.get("message", {})
    msg_type = message.get("message_type", "")
    chat_id = message.get("chat_id", "")

    if msg_type != "text":
        return {"success": True, "message": "Non-text message ignored"}

    content_str = message.get("content", "{}")
    try:
        content = json.loads(content_str)
        text = content.get("text", "")
    except (json.JSONDecodeError, AttributeError):
        text = content_str

    # 通过 open_id 查找用户
    sender = event.get("sender", {})
    sender_id = sender.get("sender_id", {})
    open_id = sender_id.get("open_id", "")
    ctx = get_user_context_by_open_id(open_id)

    command = _extract_command(text)
    _log_action("event", ctx.user_id, ctx.operator_name, f"cmd={command} open_id={open_id}")

    if not command:
        help_text = (
            "支持的命令：\n"
            "  发送邮件 - 查看待发送汇总（交互卡片）\n"
            "  查看待发送 - 同上\n"
            "  预览发送 - 发一封预览到你的邮箱"
        )
        if not ctx.logged_in:
            help_text += "\n\n注意：你尚未在系统中登录，请先在 Admin Dashboard 登录飞书"
        await bot_service.send_text_to_chat(chat_id, help_text)
        return {"success": True, "message": "Help sent"}

    logger.info("Event command: '%s' from '%s' (user_id=%s) in chat '%s'", command, ctx.operator_name, ctx.user_id, chat_id)

    if command in ("发送邮件", "查看待发送"):
        return await _handle_send_card(chat_id, ctx)
    elif command == "预览发送":
        return await _handle_preview_direct(chat_id, ctx)
    else:
        await bot_service.send_text_to_chat(chat_id, f"未识别的命令: {command}")
        return {"success": False, "message": f"Unknown command: {command}"}


# ══════════════════════════════════════
# 卡片交互回调
# ══════════════════════════════════════

@router.post("/bot/card-callback")
async def handle_card_callback(request: Request):
    try:
        body = await request.json()
    except Exception:
        logger.error("Card callback: failed to parse JSON body")
        return JSONResponse(content={})

    if "challenge" in body:
        return JSONResponse(content={"challenge": body["challenge"]})
    if body.get("type") == "url_verification":
        return JSONResponse(content={"challenge": body.get("challenge", "")})

    # ── 解析 action value ──
    raw_action = body.get("action", {})
    raw_value = raw_action.get("value") if isinstance(raw_action, dict) else raw_action

    parsed = _parse_card_value(raw_value)
    action_type = parsed.get("action", "")
    user_id = parsed.get("user_id")
    operator = parsed.get("operator", DEFAULT_OPERATOR)

    logger.info("Card callback: action=%s user_id=%s (raw_type=%s)", action_type, user_id, type(raw_value).__name__)

    open_message_id = body.get("open_message_id", "")
    open_chat_id = body.get("open_chat_id", "")

    ctx = get_user_context_by_id(user_id) if user_id else UserContext(None)

    _log_action(f"card:{action_type}", ctx.user_id, ctx.operator_name, f"msg_id={open_message_id}")

    # 未登录用户禁止发送
    if action_type in ("preview_send", "confirm_send") and not ctx.logged_in:
        err_card = bot_service.build_result_card(
            "未知用户", "操作失败", "red",
            detail_text="无法确定操作者身份。请先在 Admin Dashboard 登录飞书。",
        )
        await bot_service.update_card(open_message_id, err_card)
        return {}

    if action_type == "preview_send":
        return await _cb_preview_send(open_message_id, open_chat_id, ctx)
    elif action_type == "confirm_send":
        return await _cb_confirm_send(open_message_id, open_chat_id, ctx)
    elif action_type == "refresh_pending":
        return await _cb_refresh_pending(open_message_id, open_chat_id, ctx)
    else:
        logger.warning("Unknown card action: '%s' (raw_value=%s)", action_type, str(raw_value)[:100])
        return {}


# ══════════════════════════════════════
# 手动命令入口（API 测试）
# ══════════════════════════════════════

@router.post("/bot/command")
async def handle_bot_command(request: Request):
    body = await request.json()

    if "challenge" in body:
        return JSONResponse(content={"challenge": body["challenge"]})

    command = body.get("command", "").strip()
    chat_id = body.get("chat_id", "")
    user_id = body.get("user_id")

    if not command:
        text = body.get("text", "")
        command = _extract_command(text) if text else ""

    if not command:
        return {"success": False, "message": "No command recognized", "data": {"supported": ["发送邮件", "查看待发送", "预览发送"]}}

    ctx = get_user_context_by_id(user_id) if user_id else UserContext(None)

    if command in ("发送邮件", "查看待发送") and chat_id:
        return await _handle_send_card(chat_id, ctx)
    elif command == "预览发送" and chat_id:
        return await _handle_preview_direct(chat_id, ctx)
    else:
        return {"success": False, "message": f"需要 chat_id 或不支持的命令: {command}"}


# ══════════════════════════════════════
# Admin 测试接口
# ══════════════════════════════════════

@router.post("/bot/test-text")
async def test_send_text(request: Request):
    body = await request.json()
    chat_id = body.get("chat_id", "")
    text = body.get("text", "KOL Mailer Bot test")
    if not chat_id:
        return {"success": False, "message": "chat_id is required"}
    r = await bot_service.send_text_to_chat(chat_id, text)
    if r["ok"]:
        return {"success": True, "message": f"message_id={r['message_id']}"}
    return {"success": False, "message": f"发送失败: {r['error']}"}


@router.post("/bot/test-card")
async def test_send_card(request: Request):
    body = await request.json()
    chat_id = body.get("chat_id", "")
    if not chat_id:
        return {"success": False, "message": "chat_id is required"}
    test_kols = [
        {"kol_name": "TestBot1", "email": "test1@example.com", "template_key": "tmpl_test", "kol_contact_status": "未联系"},
    ]
    card = bot_service.build_pending_card("test_user", test_kols, user_id=None)
    r = await bot_service.send_card_to_chat(chat_id, card)
    if r["ok"]:
        return {"success": True, "message": f"message_id={r['message_id']}"}
    return {"success": False, "message": f"发送失败: {r['error']}"}


@router.get("/bot/debug-log")
async def get_debug_log():
    """返回最近 Bot 操作日志（调试用）"""
    return {"success": True, "data": list(reversed(_recent_actions))}


# ══════════════════════════════════════
# 命令处理
# ══════════════════════════════════════

async def _handle_send_card(chat_id: str, ctx: UserContext) -> dict:
    """查询待发 KOL 并回复交互卡片"""
    await ctx.ensure_fresh_token()
    config_check = _check_user_config(ctx)

    bitable = ctx.get_bitable_service()
    try:
        pending = await bitable.list_pending_kols(operator=None)
    except Exception as e:
        msg = f"查询待发送 KOL 失败: {e}"
        await bot_service.send_text_to_chat(chat_id, f"ERROR: {msg}")
        return {"success": False, "message": msg}

    card = bot_service.build_pending_card(
        ctx.operator_name, pending,
        status_text=config_check or "等待操作",
        status_color="orange" if config_check else "neutral",
        user_id=ctx.user_id,
    )
    r = await bot_service.send_card_to_chat(chat_id, card)
    if r["ok"]:
        return {"success": True, "message": f"Card sent: {len(pending)} pending KOLs"}
    return {"success": False, "message": f"Send card failed: {r['error']}"}


async def _handle_preview_direct(chat_id: str, ctx: UserContext) -> dict:
    """直接发送预览"""
    await ctx.ensure_fresh_token()
    result_text = await _do_preview_send(ctx)
    r = await bot_service.send_text_to_chat(chat_id, result_text)
    return {"success": r["ok"], "message": result_text if r["ok"] else f"Send failed: {r['error']}"}


# ══════════════════════════════════════
# 卡片回调处理
# ══════════════════════════════════════

async def _cb_preview_send(message_id: str, chat_id: str, ctx: UserContext) -> dict:
    operator = ctx.operator_name
    await bot_service.update_card(message_id,
        bot_service.build_result_card(operator, "正在发送预览...", "blue"))

    await ctx.ensure_fresh_token()
    result_text = await _do_preview_send(ctx)
    _log_action("preview_send_done", ctx.user_id, operator, result_text[:100])

    ok = "成功" in result_text or "已发送" in result_text
    await bot_service.update_card(message_id,
        bot_service.build_result_card(
            operator,
            "预览已发送" if ok else "预览发送失败",
            "green" if ok else "red",
            detail_text=result_text,
        ))
    if not ok:
        await bot_service.send_text_to_chat(chat_id, f"预览发送失败: {result_text}")
    return {}


async def _cb_confirm_send(message_id: str, chat_id: str, ctx: UserContext) -> dict:
    operator = ctx.operator_name
    lock = _get_user_lock(ctx.user_id)

    if lock.locked():
        await bot_service.update_card(message_id,
            bot_service.build_result_card(operator, "你有发送任务正在执行中，请稍后再试", "orange"))
        return {}

    await ctx.ensure_fresh_token()
    config_err = _check_user_config(ctx, require_smtp=True)
    if config_err:
        await bot_service.update_card(message_id,
            bot_service.build_result_card(operator, "配置不完整", "red", detail_text=config_err))
        return {}

    await bot_service.update_card(message_id,
        bot_service.build_result_card(operator, "正式发送中，请稍候...", "blue"))
    await bot_service.send_text_to_chat(chat_id, f"发送任务已开始 (操作者: {operator})，正在处理待发送 KOL...")

    asyncio.create_task(_do_confirm_send_and_update(message_id, chat_id, ctx))
    return {}


async def _do_confirm_send_and_update(message_id: str, chat_id: str, ctx: UserContext):
    operator = ctx.operator_name
    lock = _get_user_lock(ctx.user_id)

    async with lock:
        try:
            result_text, has_failures = await _do_confirm_send(ctx)
            _log_action("confirm_send_done", ctx.user_id, operator, result_text[:100])

            color = "orange" if has_failures else "green"
            status = "发送完成（有失败项）" if has_failures else "发送完成"
            await bot_service.update_card(message_id,
                bot_service.build_result_card(operator, status, color, detail_text=result_text, show_retry=has_failures))

            await bot_service.send_text_to_chat(chat_id, f"发送完成\n{result_text}")

        except Exception as e:
            logger.exception("Confirm send background error")
            await bot_service.update_card(message_id,
                bot_service.build_result_card(operator, "发送异常", "red", detail_text=f"{e}"))
            await bot_service.send_text_to_chat(chat_id, f"发送任务异常中断: {e}")


async def _cb_refresh_pending(message_id: str, chat_id: str, ctx: UserContext) -> dict:
    await ctx.ensure_fresh_token()
    bitable = ctx.get_bitable_service()
    config_check = _check_user_config(ctx)
    try:
        pending = await bitable.list_pending_kols(operator=None)
        card = bot_service.build_pending_card(
            ctx.operator_name, pending,
            status_text=config_check or "等待操作",
            status_color="orange" if config_check else "neutral",
            user_id=ctx.user_id,
        )
        await bot_service.update_card(message_id, card)
    except Exception as e:
        await bot_service.update_card(message_id,
            bot_service.build_result_card(ctx.operator_name, "刷新失败", "red", detail_text=f"{e}"))
    return {}


# ══════════════════════════════════════
# 核心业务执行
# ══════════════════════════════════════

async def _do_preview_send(ctx: UserContext) -> str:
    """执行预览发送。使用用户专属 SMTP。"""
    preview_email = ctx.get_preview_email()
    if not preview_email:
        return "预览邮箱未配置，请在 Admin Dashboard 设置"

    user_smtp = ctx.get_smtp_service()
    if not user_smtp:
        return "SMTP 未配置。请在 Admin Dashboard「我的 SMTP 配置」中设置邮箱和密码"

    bitable = ctx.get_bitable_service()
    try:
        pending = await bitable.list_pending_kols(operator=None)
    except Exception as e:
        return f"查询待发送 KOL 失败: {e}"

    if not pending:
        return "没有待发送的 KOL，无法生成预览"

    kol = pending[0]
    template_key = kol.get("template_key", "")
    if not template_key:
        return f"KOL {kol.get('kol_name')} 没有关联模板"

    tmpl = template_service.get_template(template_key)
    if not tmpl:
        return f"模板 '{template_key}' 不存在"

    rendered = render_template(tmpl, kol)
    result = user_smtp.send_preview_email(
        to_email=preview_email,
        subject=rendered["subject"],
        body_text=rendered["body_text"],
        body_html=rendered["body_html"],
    )

    if result.success:
        return (
            f"预览邮件已发送\n"
            f"操作者：{ctx.operator_name}\n"
            f"发送到：{preview_email}\n"
            f"KOL：{kol.get('kol_name')}\n"
            f"模板：{template_key}\n"
            f"标题：{rendered['subject']}"
        )
    return f"预览发送失败: {result.message}"


async def _do_confirm_send(ctx: UserContext) -> tuple[str, bool]:
    """执行正式发送。使用用户专属 Bitable + SMTP。"""
    user_smtp = ctx.get_smtp_service()
    if not user_smtp:
        return "SMTP 未配置。请在 Admin Dashboard「我的 SMTP 配置」中设置邮箱和密码", False

    bitable = ctx.get_bitable_service()
    try:
        pending = await bitable.list_pending_kols(operator=None)
    except Exception as e:
        return f"查询待发送 KOL 失败: {e}", False

    if not pending:
        return "没有待发送的 KOL", False

    kol_ids = [k["kol_id"] for k in pending if k.get("kol_id")]
    if not kol_ids:
        return "没有可发送的 KOL（全部缺少 kol_id）", False

    result = await send_batch(kol_ids, bitable=bitable, smtp=user_smtp)

    sent = result["sent"]
    failed = result["failed"]
    skipped = result["skipped"]

    lines = [
        f"**发送结果**（{ctx.operator_name}）",
        f"总计：{result['total']} 封",
        f"成功：{sent}",
        f"失败：{failed}",
        f"跳过：{skipped}",
    ]

    failed_details = [r for r in result.get("results", []) if r["status"] == "failed"]
    if failed_details:
        lines.append("")
        lines.append("**失败详情：**")
        for item in failed_details[:5]:
            lines.append(f"  {item.get('kol_id', '?')}: {item.get('detail', '?')[:60]}")
        if len(failed_details) > 5:
            lines.append(f"  ... 及其他 {len(failed_details) - 5} 条")

    return "\n".join(lines), failed > 0


# ══════════════════════════════════════
# 工具函数
# ══════════════════════════════════════

def _check_user_config(ctx: UserContext, require_smtp: bool = False) -> str | None:
    """
    检查用户配置完整性。
    返回错误提示文本，None 表示配置完整。
    """
    if not ctx.logged_in:
        return "未登录：请先在 Admin Dashboard 登录飞书"

    user = ctx.user
    issues = []

    if not user.get("bitable_app_token"):
        issues.append("Bitable 未配置")

    if require_smtp:
        if not user.get("smtp_email") or not user.get("smtp_password"):
            issues.append("SMTP 邮箱未配置")

    if issues:
        return "、".join(issues) + "（请在 Admin Dashboard 设置）"

    return None


def _parse_card_value(raw) -> dict:
    """
    解析飞书卡片按钮的 value，兼容多种格式：
    - dict: 直接返回
    - JSON string: 解码（支持多层编码）
    - 纯字符串: 当作 action 名
    - None: 返回空 dict
    """
    val = raw
    for _ in range(3):
        if isinstance(val, dict):
            return val
        if isinstance(val, str):
            try:
                val = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                return {"action": val.strip()}
        else:
            return {}
    return {"action": str(val)} if val else {}


def _extract_command(text: str) -> str:
    text = text.strip()
    text = re.sub(r"@\S+\s*", "", text).strip()
    for cmd in ["发送邮件", "查看待发送", "预览发送"]:
        if cmd in text:
            return cmd
    return ""
