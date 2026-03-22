"""
飞书 OAuth 认证 API

- GET  /api/auth/login          跳转飞书授权页
- GET  /api/auth/callback       OAuth 回调（接收 code）
- GET  /api/auth/me             当前用户信息
- POST /api/auth/logout         退出登录
- POST /api/auth/settings       更新用户的 Bitable/SMTP 配置
- GET  /api/auth/status         用户配置完整性检查（供扩展使用）
"""
import time
import logging
from fastapi import APIRouter, Request, Cookie
from fastapi.responses import RedirectResponse, JSONResponse, HTMLResponse
from services.auth_service import auth_service
from repositories.user_repo import user_repo

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_session(request: Request) -> str:
    """从 Cookie 或 Header 中获取 session_token"""
    # 优先 Cookie
    token = request.cookies.get("session_token", "")
    if token:
        return token
    # 兜底 Header（扩展可能用这个）
    return request.headers.get("X-Session-Token", "")


def _get_user_or_none(request: Request) -> dict | None:
    """获取当前用户，未登录返回 None"""
    session = _get_session(request)
    return auth_service.get_current_user(session)


def _require_user(request: Request) -> dict:
    """获取当前用户，未登录抛异常"""
    user = _get_user_or_none(request)
    if not user:
        raise ValueError("未登录，请先登录飞书")
    return user


def _safe_user_info(user: dict) -> dict:
    """返回给前端的用户信息（脱敏，不含 token/密码）"""
    return {
        "id": user["id"],
        "feishu_open_id": user["feishu_open_id"],
        "display_name": user["display_name"],
        "avatar_url": user["avatar_url"],
        "has_bitable": bool(user.get("bitable_app_token") and user.get("bitable_table_id")),
        "has_smtp": bool(user.get("smtp_email") and user.get("smtp_password")),
        "bitable_app_token": user.get("bitable_app_token", "")[:10] + "..." if user.get("bitable_app_token") else "",
        "bitable_table_id": user.get("bitable_table_id", ""),
        "smtp_email": user.get("smtp_email", ""),
        "smtp_from_name": user.get("smtp_from_name", ""),
        "preview_email": user.get("preview_email", ""),
        "has_user_token": bool(user.get("user_access_token") and time.time() < user.get("token_expires_at", 0)),
    }


# ══════════════════════════════════════
# OAuth 流程
# ══════════════════════════════════════

@router.get("/auth/login")
async def login(ext_state: str = ""):
    """
    重定向到飞书 OAuth 授权页。
    ext_state: 扩展传入的随机标识，登录成功后用于取回 session_token。
    """
    # 把 ext_state 编码到 OAuth state 中，回调时带回
    state = ext_state or ""
    url = auth_service.get_login_url(state=state)
    return RedirectResponse(url=url)


@router.get("/auth/callback")
async def callback(code: str = "", state: str = ""):
    """飞书 OAuth 回调，用 code 换取 token"""
    if not code:
        return JSONResponse(
            status_code=400,
            content={"success": False, "message": "Missing code parameter"},
        )

    try:
        user = await auth_service.handle_callback(code)
    except Exception as e:
        logger.exception("OAuth callback error")
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": f"登录失败: {e}"},
        )

    token = user["session_token"]

    # 如果有 ext_state（扩展登录），存储 token 供扩展轮询取回
    if state:
        _pending_tokens[state] = token

    # 设置 Cookie + 重定向到 Dashboard
    response = RedirectResponse(url="/admin/", status_code=302)
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=86400 * 30,
    )
    return response


# 一次性 token 交换（用于 extension 登录）
_pending_tokens: dict[str, str] = {}  # state -> session_token

@router.get("/auth/session-token")
async def get_session_token(request: Request, state: str = ""):
    """
    供扩展获取 session_token。
    方式 1: 通过 state 参数查找一次性 token（extension 登录流程）
    方式 2: 通过 Cookie（Dashboard 同域调用）
    """
    # 方式 1: state 参数（extension 用）
    if state and state in _pending_tokens:
        token = _pending_tokens.pop(state)  # 一次性，取完即删
        return {"success": True, "session_token": token}

    # 方式 2: Cookie（Dashboard 用）
    token = request.cookies.get("session_token", "")
    if token:
        return {"success": True, "session_token": token}

    return {"success": False, "session_token": ""}


# ══════════════════════════════════════
# 用户信息与配置
# ══════════════════════════════════════

@router.get("/auth/me")
async def get_me(request: Request):
    """获取当前登录用户信息（脱敏）"""
    user = _get_user_or_none(request)
    if not user:
        return {"success": True, "data": None, "logged_in": False}

    return {
        "success": True,
        "logged_in": True,
        "data": _safe_user_info(user),
    }


@router.post("/auth/logout")
async def logout(request: Request):
    """退出登录"""
    user = _get_user_or_none(request)
    if user:
        auth_service.logout(user["id"])

    response = JSONResponse(content={"success": True, "message": "已退出登录"})
    response.delete_cookie("session_token")
    return response


@router.post("/auth/settings")
async def update_user_settings(request: Request):
    """
    更新当前用户的 Bitable / SMTP 配置。

    请求体（所有字段可选）：
    {
        "bitable_app_token": "...",
        "bitable_table_id": "...",
        "smtp_email": "...",
        "smtp_password": "...",
        "smtp_from_name": "...",
        "preview_email": "..."
    }
    """
    try:
        user = _require_user(request)
    except ValueError as e:
        return JSONResponse(status_code=401, content={"success": False, "message": str(e)})

    body = await request.json()

    # 只允许更新这些字段
    allowed = {"bitable_app_token", "bitable_table_id", "smtp_email", "smtp_password", "smtp_from_name", "preview_email"}
    data = {k: v for k, v in body.items() if k in allowed}

    if not data:
        return {"success": False, "message": "没有可更新的字段"}

    user_repo.update_settings(user["id"], data)

    # 返回更新后的信息
    updated = user_repo.find_by_id(user["id"])
    return {
        "success": True,
        "message": "配置已保存",
        "data": _safe_user_info(updated),
    }


@router.get("/auth/status")
async def user_status(request: Request):
    """
    用户配置完整性检查（供扩展调用）。
    返回当前用户的登录状态、Bitable 和 SMTP 配置状态。
    """
    user = _get_user_or_none(request)
    if not user:
        return {
            "logged_in": False,
            "has_bitable": False,
            "has_smtp": False,
            "display_name": "",
            "message": "未登录，请在 Admin Dashboard 登录飞书",
        }

    has_bitable = bool(user.get("bitable_app_token") and user.get("bitable_table_id"))
    has_smtp = bool(user.get("smtp_email") and user.get("smtp_password"))

    messages = []
    if not has_bitable:
        messages.append("请在 Admin Dashboard 配置 Bitable")
    if not has_smtp:
        messages.append("请在 Admin Dashboard 配置 SMTP 邮箱")

    return {
        "logged_in": True,
        "has_bitable": has_bitable,
        "has_smtp": has_smtp,
        "display_name": user.get("display_name", ""),
        "message": "；".join(messages) if messages else "配置完整",
    }
