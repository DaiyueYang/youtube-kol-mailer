"""
KOL 管理 API

- POST   /api/kols/upsert               写入或更新单条 KOL 到 Bitable
- GET    /api/kols/pending               拉取待发送 KOL 列表
- GET    /api/kols/{kol_id}              查询单条 KOL
- POST   /api/kols/{kol_id}/status       更新 KOL 状态

支持用户级 Bitable 隔离：如果当前用户已登录并配置了自己的 Bitable，
则操作该用户的 Bitable；否则 fallback 到全局配置。
"""
import logging
from fastapi import APIRouter, HTTPException, Request
from models.schemas import KolUpsertRequest, KolStatusUpdateRequest
from models.constants import KolStatus
from services.user_context import get_user_context

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/kols/upsert")
async def upsert_kol(req: KolUpsertRequest, request: Request):
    """写入或更新单条 KOL 记录到飞书 Bitable。"""
    ctx = get_user_context(request)
    bitable = ctx.get_bitable_service()

    # 调试日志：追踪身份识别链路
    session = request.cookies.get("session_token", "")
    logger.info(
        "KOL upsert: session=%s user=%s app_token=%s table_id=%s identity=%s",
        session[:8] + "..." if session else "(none)",
        f"id={ctx.user_id}" if ctx.logged_in else "(anonymous)",
        bitable.app_token[:10] + "..." if bitable.app_token else "(empty)",
        bitable.table_id or "(auto-detect)",
        bitable.identity_mode,
    )

    try:
        kol_data = req.model_dump()
        # 如果请求没有指定 operator，用当前用户名
        if not kol_data.get("operator") and ctx.operator_name:
            kol_data["operator"] = ctx.operator_name

        result = await bitable.upsert_kol(kol_data)
        return {
            "success": True,
            "data": result,
            "message": f"KOL '{result['kol_id']}' upserted",
        }
    except Exception as e:
        logger.exception("KOL upsert failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/kols/pending")
async def get_pending_kols(request: Request, operator: str = None):
    """拉取待发送 KOL 列表（status = pending 或 failed）。"""
    ctx = get_user_context(request)
    bitable = ctx.get_bitable_service()

    try:
        kols = await bitable.list_pending_kols(operator=operator)
        return {
            "success": True,
            "data": {"kols": kols, "total": len(kols)},
            "message": "ok",
        }
    except Exception as e:
        logger.exception("Failed to list pending KOLs")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/kols/{kol_id}")
async def get_kol(kol_id: str, request: Request):
    """查询单条 KOL 记录"""
    ctx = get_user_context(request)
    bitable = ctx.get_bitable_service()

    try:
        kol = await bitable.get_kol_by_id(kol_id)
        if not kol:
            raise HTTPException(status_code=404, detail=f"KOL '{kol_id}' not found")
        return {"success": True, "data": kol, "message": "ok"}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get KOL")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/kols/{kol_id}/status")
async def update_kol_status(kol_id: str, req: KolStatusUpdateRequest, request: Request):
    """更新 KOL 发送状态。"""
    ctx = get_user_context(request)
    bitable = ctx.get_bitable_service()

    if req.status not in KolStatus.ALL:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status '{req.status}'. Valid: {sorted(KolStatus.ALL)}",
        )

    try:
        await bitable.update_kol_status(
            kol_id=kol_id, new_status=req.status,
            last_error=req.last_error, sent_at=req.sent_at,
        )
        return {
            "success": True,
            "data": {"kol_id": kol_id, "status": req.status},
            "message": f"KOL '{kol_id}' status updated to '{req.status}'",
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Failed to update KOL status")
        raise HTTPException(status_code=500, detail=str(e))
