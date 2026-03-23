"""
Admin 管理后台页面路由

访问 /admin/ 需要飞书 OAuth 登录。未登录时重定向到登录页。
"""
from pathlib import Path
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from services.auth_service import auth_service

router = APIRouter()

_DASHBOARD_PATH = Path(__file__).parent / "static" / "dashboard.html"


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Dashboard 首页 — 需要飞书登录"""
    session = request.cookies.get("session_token", "")
    user = auth_service.get_current_user(session) if session else None
    if not user:
        return RedirectResponse(url="/api/auth/login", status_code=302)
    return _DASHBOARD_PATH.read_text(encoding="utf-8")
