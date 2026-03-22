"""
YouTube KOL Mailer - FastAPI 应用入口

启动方式: uvicorn app:app --reload --port 8000
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import settings
from models.db import init_db
from api.auth import router as auth_router
from api.templates import router as templates_router
from api.kols import router as kols_router
from api.send import router as send_router
from api.bot import router as bot_router
from api.settings import router as settings_router
from web_admin.views import router as admin_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化数据库"""
    init_db()
    logger.info(
        "Reminder: first few days, send in small batches (20/50/100) "
        "to warm up the domain. Verify SPF/DKIM/DNS before scaling up."
    )
    yield


app = FastAPI(
    title="YouTube KOL Mailer",
    description="YouTube 博主自动化邮件系统后端",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS - 允许 Chrome 扩展跨域访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 开发阶段允许所有来源，生产环境应限制
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静态文件
app.mount("/static", StaticFiles(directory="web_admin/static"), name="static")

# 注册 API 路由
app.include_router(auth_router, prefix="/api", tags=["auth"])
app.include_router(templates_router, prefix="/api", tags=["templates"])
app.include_router(kols_router, prefix="/api", tags=["kols"])
app.include_router(send_router, prefix="/api", tags=["send"])
app.include_router(bot_router, prefix="/api", tags=["bot"])
app.include_router(settings_router, prefix="/api", tags=["settings"])

# 注册 Admin 页面路由
app.include_router(admin_router, prefix="/admin", tags=["admin"])


@app.get("/api/health")
async def health_check():
    """健康检查接口"""
    return {
        "status": "ok",
        "version": "0.1.0",
        "service": "youtube-kol-mailer",
    }
