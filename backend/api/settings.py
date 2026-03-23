"""
设置与诊断 API

- GET    /api/settings                  返回当前配置信息
- POST   /api/admin/create-table        创建新表格（用户身份）
- GET    /api/admin/my-tables           列出当前用户创建的所有表格
- POST   /api/admin/select-table        选择使用哪张表格
- GET    /api/admin/send-queue          查询当前用户的 KOL 记录
- GET    /api/admin/bitable-status      查询当前 Bitable 连通状态
- GET    /api/admin/bitable-url         获取当前表格的打开链接
- GET    /api/debug/bitable             诊断 Bitable 连接
- GET    /api/debug/smtp                诊断 SMTP 配置
"""
import time as _time
import os
import logging
import httpx
from fastapi import APIRouter, Request
from config import settings, ENV_PATH, ENV_FILE_EXISTS
from services.bitable_service import BitableService
from services.user_context import get_user_context
from repositories.user_repo import user_repo
from repositories.user_tables_repo import user_tables_repo

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/settings")
async def get_settings():
    return {
        "app_env": settings.APP_ENV,
        "smtp_host": settings.LARK_SMTP_HOST,
        "smtp_port": settings.LARK_SMTP_PORT,
        "send_delay_min": settings.SEND_DELAY_MIN,
        "send_delay_max": settings.SEND_DELAY_MAX,
        "api_base": settings.get_api_base(),
    }


# ══════════════════════════════════════
# 表格创建与管理
# ══════════════════════════════════════

@router.post("/admin/create-table")
async def create_table(request: Request):
    """
    以当前登录用户的身份创建一张新的多维表格 Base + KOL Table + 字段。
    必须有有效的 user_access_token，不允许 fallback 到应用身份。
    """
    ctx = get_user_context(request)
    user = ctx.user

    if not user:
        return {"success": False, "message": "请先登录飞书"}

    await ctx.ensure_fresh_token()
    user_token = ctx._get_user_token()
    if not user_token:
        expires = user.get("token_expires_at", 0)
        if _time.time() > expires and user.get("user_access_token"):
            return {"success": False, "message": "用户令牌已过期，请重新登录飞书",
                    "debug": {"has_token": True, "expired": True}}
        return {"success": False, "message": "未获取到用户身份令牌。请重新登录飞书（授权页面需勾选「多维表格」权限）。",
                "debug": {"has_token": bool(user.get("user_access_token")), "expired": False}}

    # 构建名称
    display_name = user.get("display_name", "").strip() or "My"
    ts = _time.strftime("%m%d-%H%M")
    base_name = f"{display_name} YouTube KOL {ts}"

    logger.info("Creating table: user_id=%s, name=%s, token=%s...", user["id"], base_name, user_token[:10])

    # Step 1: 创建 Base（用户身份）
    try:
        svc = BitableService(app_token="", user_token=user_token)
        base_result = await svc.create_base(base_name)
        app_token = base_result["app_token"]
        base_url = base_result.get("url", "")
    except Exception as e:
        logger.error("Create base failed: %s", e)
        return {"success": False, "message": f"创建表格失败: {e}",
                "debug": {"token_type": "user", "error": str(e)}}

    # Step 2: 创建 KOL Table + 字段
    try:
        svc2 = BitableService(app_token=app_token, table_id="", user_token=user_token)
        result = await svc2.init_kol_table()
        table_id = result["table_id"]
    except Exception as e:
        logger.error("Init KOL table failed: %s", e)
        return {"success": False, "message": f"创建 KOL 表失败: {e}",
                "debug": {"app_token": app_token, "error": str(e)}}

    # Step 3: 保存到 user_tables
    user_tables_repo.add(
        user_id=user["id"],
        app_token=app_token,
        table_id=table_id,
        base_name=base_name,
        base_url=base_url,
        identity="user",
    )

    # Step 4: 自动选中为当前使用的表
    user_repo.update_settings(user["id"], {
        "bitable_app_token": app_token,
        "bitable_table_id": table_id,
        "bitable_identity": "user",
    })

    fields = result.get("fields", [])
    created = sum(1 for f in fields if f["status"] == "created")

    return {
        "success": True,
        "message": f"表格「{base_name}」创建成功",
        "data": {
            "app_token": app_token,
            "table_id": table_id,
            "base_name": base_name,
            "base_url": base_url,
            "identity": "user",
            "fields_created": created,
            "token_type_used": "user",
        },
    }


@router.get("/admin/my-tables")
async def list_my_tables(request: Request):
    """列出当前用户创建的所有表格"""
    ctx = get_user_context(request)
    if not ctx.user:
        return {"success": False, "message": "请先登录飞书", "data": []}

    tables = user_tables_repo.list_by_user(ctx.user["id"])
    current_token = ctx.user.get("bitable_app_token", "")

    result = []
    for t in tables:
        result.append({
            "id": t["id"],
            "app_token": t["app_token"],
            "table_id": t["table_id"],
            "base_name": t["base_name"],
            "base_url": t["base_url"],
            "identity": t["identity"],
            "created_at": t["created_at"],
            "is_selected": t["app_token"] == current_token,
        })

    return {"success": True, "data": result}


@router.post("/admin/select-table")
async def select_table(request: Request):
    """选择使用哪张表格"""
    ctx = get_user_context(request)
    if not ctx.user:
        return {"success": False, "message": "请先登录飞书"}

    body = await request.json()
    app_token = body.get("app_token", "")

    if not app_token:
        return {"success": False, "message": "请指定 app_token"}

    # 验证这张表属于当前用户
    table = user_tables_repo.find_by_app_token(ctx.user["id"], app_token)
    if not table:
        return {"success": False, "message": "未找到该表格，或不属于当前用户"}

    user_repo.update_settings(ctx.user["id"], {
        "bitable_app_token": app_token,
        "bitable_table_id": table["table_id"],
        "bitable_identity": table["identity"],
    })

    return {"success": True, "message": f"已切换到「{table['base_name']}」"}


@router.post("/admin/delete-table")
async def delete_table(request: Request):
    """从用户记录中移除一张表格（不删除飞书里的实际表格）"""
    ctx = get_user_context(request)
    if not ctx.user:
        return {"success": False, "message": "请先登录飞书"}

    body = await request.json()
    app_token = body.get("app_token", "")
    if not app_token:
        return {"success": False, "message": "请指定 app_token"}

    # 从 user_tables 中删除
    from models.db import get_connection
    conn = get_connection()
    try:
        conn.execute("DELETE FROM user_tables WHERE user_id = ? AND app_token = ?", (ctx.user["id"], app_token))
        conn.commit()
    finally:
        conn.close()

    # 如果删除的是当前选中的表，清空选中状态
    if ctx.user.get("bitable_app_token") == app_token:
        user_repo.update_settings(ctx.user["id"], {"bitable_app_token": "", "bitable_table_id": "", "bitable_identity": ""})

    return {"success": True, "message": "已移除"}


@router.get("/admin/tables-in-base")
async def list_tables_in_base(request: Request, app_token: str = ""):
    """列出某个 Base 中的所有 table（用于让用户选择写入哪个 table）"""
    ctx = get_user_context(request)
    if not ctx.user:
        return {"success": False, "message": "请先登录飞书", "data": []}

    token = app_token or ctx.user.get("bitable_app_token", "")
    if not token:
        return {"success": False, "message": "未指定 app_token", "data": []}

    user_token = ctx._get_user_token()
    bt_identity = ctx.user.get("bitable_identity", "")
    ut = user_token if bt_identity == "user" else ""

    try:
        svc = BitableService(app_token=token, user_token=ut)
        tables = await svc.list_tables()
        return {"success": True, "data": tables}
    except Exception as e:
        return {"success": False, "message": str(e), "data": []}


@router.post("/admin/select-subtable")
async def select_subtable(request: Request):
    """选择当前 Base 中使用哪个 table"""
    ctx = get_user_context(request)
    if not ctx.user:
        return {"success": False, "message": "请先登录飞书"}

    body = await request.json()
    table_id = body.get("table_id", "")
    if not table_id:
        return {"success": False, "message": "请指定 table_id"}

    user_repo.update_settings(ctx.user["id"], {"bitable_table_id": table_id})

    # 也更新 user_tables 记录
    app_token = ctx.user.get("bitable_app_token", "")
    if app_token:
        user_tables_repo.update_table_id(ctx.user["id"], app_token, table_id)

    return {"success": True, "message": f"已选择 table: {table_id}"}


# ══════════════════════════════════════
# Send Queue
# ══════════════════════════════════════

@router.get("/admin/send-queue")
async def get_send_queue(request: Request):
    """查询当前用户 Bitable 中的 KOL 记录，分为待发送和已发送"""
    ctx = get_user_context(request)
    if not ctx.logged_in:
        return {"success": False, "message": "请先登录飞书", "data": None}
    await ctx.ensure_fresh_token()
    bitable = ctx.get_bitable_service()

    if not bitable.app_token:
        return {"success": False, "message": "未选择表格。请先创建或选择一张表格。", "data": None}

    try:
        all_records = await bitable.list_all_kols()
    except Exception as e:
        return {"success": False, "message": f"读取失败: {e}", "data": None}

    # 按 kol_contact_status 分组
    pending = []   # 未联系
    contacted = [] # 已联系
    for r in all_records:
        cs = r.get("kol_contact_status", "")
        if cs == "已联系":
            contacted.append(r)
        else:
            pending.append(r)  # 未联系 或 空 都算待发送

    # 已联系记录按 sent_at 倒序（最近发送的在前）
    contacted.sort(key=lambda x: x.get("sent_at", "") or "", reverse=True)

    return {
        "success": True,
        "message": f"{len(all_records)} 条记录",
        "data": {
            "pending": pending,
            "pending_count": len(pending),
            "contacted": contacted,
            "contacted_count": len(contacted),
            "total": len(all_records),
        },
    }


# ══════════════════════════════════════
# Bitable 状态与链接
# ══════════════════════════════════════

@router.get("/admin/bitable-status")
async def bitable_status(request: Request):
    """查询当前选中表格的连通状态"""
    from models.constants import KOL_TABLE_FIELDS

    ctx = get_user_context(request)
    if not ctx.logged_in:
        return {"success": False, "data": {"error": "请先登录飞书"}}
    await ctx.ensure_fresh_token()
    bitable = ctx.get_bitable_service()
    user = ctx.user

    status = {
        "config_ok": False, "token_ok": False, "table_ok": False, "fields_ok": False,
        "identity": bitable.identity_mode,
        "table_id": bitable.table_id,
        "app_token": bitable.app_token[:10] + "..." if bitable.app_token else "",
        "has_user_token": bool(ctx._get_user_token()) if user else False,
        "missing_fields": [], "existing_fields": [], "error": None,
    }

    if not bitable.app_token:
        status["error"] = "未选择表格。请先创建或选择一张表格。"
        return {"success": True, "data": status}
    status["config_ok"] = True

    try:
        await bitable._get_tenant_token()
        status["token_ok"] = True
    except Exception as e:
        status["error"] = f"Token 获取失败: {e}"
        return {"success": True, "data": status}

    table_id = bitable.table_id
    if not table_id:
        try:
            tables = await bitable.list_tables()
            for t in tables:
                if t["name"] == "KOL":
                    table_id = t["table_id"]
                    break
        except Exception as e:
            status["error"] = f"列出表失败: {e}"
            return {"success": True, "data": status}

    if not table_id:
        status["error"] = "KOL 表不存在"
        return {"success": True, "data": status}
    status["table_ok"] = True
    status["table_id"] = table_id

    expected = {f["field_name"] for f in KOL_TABLE_FIELDS}
    try:
        fields = await bitable.list_fields(table_id)
        existing = {f["field_name"] for f in fields}
        status["existing_fields"] = sorted(existing & expected)
        status["missing_fields"] = sorted(expected - existing)
        status["fields_ok"] = len(status["missing_fields"]) == 0
    except Exception as e:
        status["error"] = f"读取字段失败: {e}"
    return {"success": True, "data": status}


@router.get("/admin/bitable-url")
async def get_bitable_url(request: Request):
    """返回当前选中表格的打开链接"""
    ctx = get_user_context(request)
    if not ctx.logged_in:
        return {"success": False, "url": "", "message": "请先登录飞书"}
    bitable = ctx.get_bitable_service()
    app_token = bitable.app_token
    table_id = bitable.table_id

    if not app_token:
        return {"success": False, "url": "", "message": "未选择表格"}

    # 尝试从 user_tables 获取 URL
    if ctx.user:
        t = user_tables_repo.find_by_app_token(ctx.user["id"], app_token)
        if t and t.get("base_url"):
            url = t["base_url"]
            if table_id:
                url += f"?table={table_id}"
            return {"success": True, "url": url, "message": "ok"}

    # Fallback 构造
    api_base = settings.get_api_base()
    domain = "www.larksuite.com" if "larksuite.com" in api_base else "www.feishu.cn"
    url = f"https://{domain}/base/{app_token}"
    if table_id:
        url += f"?table={table_id}"
    return {"success": True, "url": url, "message": "ok"}


# ══════════════════════════════════════
# 兼容旧接口（保留以免前端报错）
# ══════════════════════════════════════

@router.post("/admin/init-bitable")
async def init_bitable(request: Request):
    """兼容旧接口，重定向到 create-table"""
    return await create_table(request)

@router.post("/admin/init-all")
async def init_all(request: Request):
    """兼容旧接口，重定向到 create-table"""
    return await create_table(request)


# ══════════════════════════════════════
# 诊断
# ══════════════════════════════════════

@router.get("/debug/bitable")
async def debug_bitable(request: Request):
    from models.constants import KOL_TABLE_FIELDS
    ctx = get_user_context(request)
    if not ctx.logged_in:
        return {"success": False, "steps": [{"step": "Auth", "status": "FAIL", "detail": "请先登录飞书"}]}
    await ctx.ensure_fresh_token()
    bitable = ctx.get_bitable_service()
    api_base = settings.get_api_base()
    steps = []

    steps.append({"step": "0. Environment", "status": "INFO", "detail": {
        "api_base": api_base, "identity": bitable.identity_mode,
        "has_user_token": bool(ctx._get_user_token()) if ctx.user else False,
    }})

    if not bitable.app_token:
        steps.append({"step": "1. Config", "status": "FAIL", "detail": "未选择表格"})
        return {"success": False, "steps": steps}
    steps.append({"step": "1. Config", "status": "PASS", "detail": f"app_token: {bitable.app_token[:10]}..."})

    try:
        await bitable._get_tenant_token()
        steps.append({"step": "2. Token", "status": "PASS"})
    except Exception as e:
        steps.append({"step": "2. Token", "status": "FAIL", "detail": str(e)})
        return {"success": False, "steps": steps}

    try:
        tables = await bitable.list_tables()
        steps.append({"step": "3. Access Base", "status": "PASS", "detail": f"{len(tables)} tables"})
    except Exception as e:
        steps.append({"step": "3. Access Base", "status": "FAIL", "detail": str(e)})
        return {"success": False, "steps": steps}

    if bitable.table_id:
        try:
            fields = await bitable.list_fields()
            expected = {f["field_name"] for f in KOL_TABLE_FIELDS}
            existing = {f["field_name"] for f in fields}
            missing = sorted(expected - existing)
            if missing:
                steps.append({"step": "4. Fields", "status": "FAIL", "detail": f"Missing: {missing}"})
            else:
                steps.append({"step": "4. Fields", "status": "PASS", "detail": f"{len(existing)} fields"})
        except Exception as e:
            steps.append({"step": "4. Fields", "status": "FAIL", "detail": str(e)})

    return {"success": all(s.get("status") in ("PASS", "INFO") for s in steps), "steps": steps}


@router.get("/debug/smtp")
async def debug_smtp(request: Request):
    """诊断当前用户的 SMTP 配置"""
    ctx = get_user_context(request)
    if not ctx.logged_in:
        return {"success": False, "detail": "请先登录飞书"}
    user_smtp = ctx.get_smtp_service()
    if not user_smtp:
        return {"success": False, "detail": "SMTP 未配置，请在 Dashboard SMTP 页签设置邮箱和密码"}
    missing = user_smtp.check_config()
    if missing:
        return {"success": False, "detail": f"Missing: {', '.join(missing)}"}
    return {"success": True, "detail": {
        "host": user_smtp.host, "port": user_smtp.port,
        "user": user_smtp.username[:3] + "***" if user_smtp.username else "",
    }}
