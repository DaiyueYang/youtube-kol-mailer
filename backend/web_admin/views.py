"""
Admin 管理后台页面路由
"""
from pathlib import Path
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

_DASHBOARD_PATH = Path(__file__).parent / "static" / "dashboard.html"


@router.get("/", response_class=HTMLResponse)
async def dashboard():
    """Dashboard 首页 — 多用户配置中心 + 调试台"""
    return _DASHBOARD_PATH.read_text(encoding="utf-8")
