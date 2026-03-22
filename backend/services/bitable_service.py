"""
飞书 Bitable 服务 - 封装唯一 KOL 表的读写操作

支持双身份模式：
- user_access_token（用户身份）：用户创建的 Base 归属于用户本人
- tenant_access_token（应用身份）：fallback / 系统管理用

优先级：如果传入了 user_token，所有操作使用用户身份。
"""
import asyncio
import time
import hashlib
import logging
from datetime import datetime

import httpx

from config import settings
from models.constants import (
    KolStatus, BITABLE_FIELD_MAP, BACKEND_TO_BITABLE,
    KOL_TABLE_NAME, KOL_TABLE_FIELDS,
    KOL_CONTACT_NOT_CONTACTED, KOL_CONTACT_CONTACTED,
)

logger = logging.getLogger(__name__)

_init_lock = asyncio.Lock()


class BitableService:
    """飞书 Bitable KOL 表操作（支持用户身份 / 应用身份双模式）"""

    def __init__(
        self,
        app_id: str = "",
        app_secret: str = "",
        app_token: str = "",
        table_id: str = "",
        user_token: str = "",
    ):
        self.app_id = app_id or settings.LARK_APP_ID
        self.app_secret = app_secret or settings.LARK_APP_SECRET
        self.app_token = app_token or settings.LARK_BITABLE_APP_TOKEN
        self.table_id = table_id or settings.LARK_BITABLE_TABLE_ID

        # 用户身份 token（优先使用）
        self.user_token = user_token

        # 应用身份 token 缓存
        self._tenant_token: str = ""
        self._tenant_token_expires_at: float = 0

    @property
    def identity_mode(self) -> str:
        """当前使用的身份模式"""
        return "user" if self.user_token else "app"

    # ──────────────────────────────────
    # 鉴权
    # ──────────────────────────────────

    def _api_base(self) -> str:
        return settings.get_api_base()

    def _app_base_url(self) -> str:
        return f"{self._api_base()}/bitable/v1/apps/{self.app_token}"

    async def _get_tenant_token(self) -> str:
        """获取应用身份 tenant_access_token（带缓存）"""
        now = time.time()
        if self._tenant_token and now < self._tenant_token_expires_at:
            return self._tenant_token

        url = f"{self._api_base()}/auth/v3/tenant_access_token/internal"
        payload = {"app_id": self.app_id, "app_secret": self.app_secret}

        logger.info("Requesting tenant_token: app_id=%s...", self.app_id[:8] if self.app_id else "(empty)")

        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, timeout=10)
            data = resp.json()

        if data.get("code") != 0:
            raise RuntimeError(f"Failed to get tenant_token: {data.get('msg', data)}")

        self._tenant_token = data["tenant_access_token"]
        expire = data.get("expire", 7200)
        self._tenant_token_expires_at = now + expire - 300
        return self._tenant_token

    async def _headers(self) -> dict:
        """
        构建鉴权请求头。
        优先使用 user_token（用户身份），否则 fallback 到 tenant_token（应用身份）。
        """
        if self.user_token:
            token = self.user_token
        else:
            token = await self._get_tenant_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _format_api_error(operation: str, http_status: int, data: dict) -> str:
        msg = data.get("msg", "unknown error")
        code = data.get("code", 0)
        error_info = data.get("error", {})
        parts = [f"{operation} failed (HTTP {http_status}, code={code}): {msg}"]
        violations = error_info.get("permission_violations", [])
        if violations:
            scopes = [v.get("subject", "") for v in violations]
            parts.append(f"需要的权限: {', '.join(scopes)}")
        helps = error_info.get("helps", [])
        if helps:
            url = helps[0].get("url", "")
            if url:
                parts.append(f"添加权限: {url}")
        return " | ".join(parts)

    # ──────────────────────────────────
    # Base 创建
    # ──────────────────────────────────

    async def create_base(self, name: str = "KOL Mailer") -> dict:
        """
        创建新 Bitable/Base。使用当前身份（user_token 优先）。
        用户身份创建的 Base 归属于用户本人。
        """
        url = f"{self._api_base()}/bitable/v1/apps"
        headers = await self._headers()
        payload = {"name": name}

        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=headers, json=payload, timeout=15)
            data = resp.json()

        if data.get("code") != 0:
            raise RuntimeError(self._format_api_error("Create Base", resp.status_code, data))

        app_data = data["data"]["app"]
        self.app_token = app_data["app_token"]
        logger.info("Created Base '%s': %s (identity=%s)", name, app_data["app_token"], self.identity_mode)
        return {
            "app_token": app_data["app_token"],
            "default_table_id": app_data.get("default_table_id", ""),
            "url": app_data.get("url", ""),
            "identity": self.identity_mode,
        }

    # ──────────────────────────────────
    # 表结构管理
    # ──────────────────────────────────

    async def list_tables(self) -> list[dict]:
        url = f"{self._app_base_url()}/tables"
        headers = await self._headers()
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers, timeout=10)
            data = resp.json()
        if data.get("code") != 0:
            msg = data.get("msg", str(data))
            if "deleted" in msg.lower():
                raise RuntimeError(f"Bitable 已被删除: {msg}")
            if data["code"] in (1254043, 1254044):
                raise RuntimeError(f"app_token 无效: {msg}")
            if "permission" in msg.lower() or "scope" in msg.lower():
                raise RuntimeError(f"无访问权限: {msg}")
            raise RuntimeError(f"List tables failed: {msg}")
        items = data.get("data", {}).get("items", [])
        return [{"table_id": t["table_id"], "name": t.get("name", "")} for t in items]

    async def create_table(self, name: str = KOL_TABLE_NAME) -> str:
        url = f"{self._app_base_url()}/tables"
        headers = await self._headers()
        payload = {"table": {"name": name}}
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=headers, json=payload, timeout=15)
            data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"Create table failed: {data.get('msg', data)}")
        table_id = data["data"]["table_id"]
        self.table_id = table_id
        logger.info("Created table '%s': %s", name, table_id)
        return table_id

    async def list_fields(self, table_id: str = "") -> list[dict]:
        tid = table_id or self.table_id
        if not tid:
            raise RuntimeError("table_id 未配置")
        url = f"{self._app_base_url()}/tables/{tid}/fields"
        headers = await self._headers()
        all_fields = []
        page_token = None
        async with httpx.AsyncClient() as client:
            while True:
                params = {"page_size": 100}
                if page_token:
                    params["page_token"] = page_token
                resp = await client.get(url, headers=headers, params=params, timeout=10)
                data = resp.json()
                if data.get("code") != 0:
                    raise RuntimeError(f"List fields failed: {data.get('msg', data)}")
                for f in data.get("data", {}).get("items", []):
                    all_fields.append({"field_id": f.get("field_id", ""), "field_name": f.get("field_name", ""), "type": f.get("type", 0)})
                if not data.get("data", {}).get("has_more", False):
                    break
                page_token = data["data"].get("page_token")
        return all_fields

    async def create_field(self, field_name: str, field_type: int = 1, table_id: str = "", property: dict = None) -> dict:
        tid = table_id or self.table_id
        url = f"{self._app_base_url()}/tables/{tid}/fields"
        headers = await self._headers()
        payload = {"field_name": field_name, "type": field_type}
        if property:
            payload["property"] = property
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, headers=headers, json=payload, timeout=10)
            try:
                data = resp.json()
            except Exception:
                return {"status": "failed", "field_name": field_name, "detail": f"HTTP {resp.status_code}: {resp.text[:200]}"}

            if data.get("code") == 0:
                return {"status": "created", "field_name": field_name, "detail": "ok"}

            msg = data.get("msg", "")
            code = data.get("code", 0)
            error_info = data.get("error", {})

            if code == 1254036 or "exist" in msg.lower():
                return {"status": "exists", "field_name": field_name, "detail": msg}

            if resp.status_code == 403 or "permission" in msg.lower() or "denied" in msg.lower():
                violations = error_info.get("permission_violations", [])
                needed = [v.get("subject", "") for v in violations]
                detail = f"权限不足 (HTTP {resp.status_code}): {msg}"
                if needed:
                    detail += f" | 需要: {', '.join(needed)}"
                return {"status": "failed", "field_name": field_name, "detail": detail}

            return {"status": "failed", "field_name": field_name, "detail": f"code={code}: {msg}"}
        except Exception as e:
            return {"status": "failed", "field_name": field_name, "detail": str(e)}

    async def init_kol_table(self, table_name: str = KOL_TABLE_NAME) -> dict:
        async with _init_lock:
            return await self._do_init_kol_table(table_name)

    async def _do_init_kol_table(self, table_name: str) -> dict:
        result = {"table_id": "", "table_status": "", "fields": [], "action_required": None}

        tables = await self.list_tables()
        table_found = False

        if self.table_id:
            for t in tables:
                if t["table_id"] == self.table_id:
                    table_found = True
                    result["table_id"] = self.table_id
                    result["table_status"] = "exists"
                    break
            if not table_found:
                logger.warning("Configured table_id '%s' not found, searching by name", self.table_id)

        if not table_found:
            for t in tables:
                if t["name"] == table_name:
                    table_found = True
                    self.table_id = t["table_id"]
                    result["table_id"] = t["table_id"]
                    result["table_status"] = "exists"
                    break

        if not table_found:
            new_id = await self.create_table(table_name)
            result["table_id"] = new_id
            result["table_status"] = "created"

        existing_fields = await self.list_fields()
        existing_names = {f["field_name"] for f in existing_fields}

        for spec in KOL_TABLE_FIELDS:
            fname = spec["field_name"]
            if fname in existing_names:
                result["fields"].append({"field_name": fname, "status": "exists", "detail": "ok"})
            else:
                result["fields"].append(await self.create_field(
                    fname, spec["type"], property=spec.get("property"),
                ))

        return result

    # ──────────────────────────────────
    # 记录 CRUD
    # ──────────────────────────────────

    _WRITABLE_BITABLE_FIELDS = {f["field_name"] for f in KOL_TABLE_FIELDS}

    async def _ensure_table_id(self):
        """确保 table_id 存在。如果为空，自动使用 Base 中的第一个 table。"""
        if self.table_id:
            return
        if not self.app_token:
            raise RuntimeError("未选择表格，请先创建或选择一张 Bitable")
        # 自动检测第一个 table
        tables = await self.list_tables()
        if not tables:
            raise RuntimeError("当前 Base 中没有任何数据表")
        self.table_id = tables[0]["table_id"]
        logger.info("Auto-detected table_id: %s (%s)", self.table_id, tables[0].get("name", ""))

    async def _records_url(self) -> str:
        await self._ensure_table_id()
        return f"{self._api_base()}/bitable/v1/apps/{self.app_token}/tables/{self.table_id}/records"

    def _to_bitable_fields(self, backend_data: dict) -> dict:
        fields = {}
        for backend_key, value in backend_data.items():
            bitable_key = BACKEND_TO_BITABLE.get(backend_key, backend_key)
            if value is not None and bitable_key in self._WRITABLE_BITABLE_FIELDS:
                fields[bitable_key] = value
        return fields

    def _from_bitable_record(self, record: dict) -> dict:
        fields = record.get("fields", {})
        result = {"_record_id": record.get("record_id", "")}
        for bitable_key, backend_key in BITABLE_FIELD_MAP.items():
            value = fields.get(bitable_key, "")
            if isinstance(value, list):
                value = value[0].get("text", str(value)) if value else ""
            elif isinstance(value, dict):
                value = value.get("text", str(value))
            result[backend_key] = value if value is not None else ""
        return result

    async def search_by_kol_id(self, kol_id: str) -> dict | None:
        url = f"{await self._records_url()}/search"
        headers = await self._headers()
        payload = {"filter": {"conjunction": "and", "conditions": [{"field_name": "kol_id", "operator": "is", "value": [kol_id]}]}, "page_size": 1}
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=headers, json=payload, timeout=15)
            data = resp.json()
        if data.get("code") != 0:
            return None
        items = data.get("data", {}).get("items", [])
        return self._from_bitable_record(items[0]) if items else None

    async def create_record(self, backend_data: dict) -> str:
        url = await self._records_url()
        headers = await self._headers()
        payload = {"fields": self._to_bitable_fields(backend_data)}
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=headers, json=payload, timeout=15)
            data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(self._format_api_error("Bitable create", resp.status_code, data))
        return data["data"]["record"]["record_id"]

    async def update_record(self, record_id: str, backend_data: dict) -> None:
        url = f"{await self._records_url()}/{record_id}"
        headers = await self._headers()
        payload = {"fields": self._to_bitable_fields(backend_data)}
        async with httpx.AsyncClient() as client:
            resp = await client.put(url, headers=headers, json=payload, timeout=15)
            data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(self._format_api_error("Bitable update", resp.status_code, data))

    async def list_by_status(self, statuses: list[str], operator: str = None) -> list:
        url = f"{await self._records_url()}/search"
        headers = await self._headers()

        # Feishu 的 "is" operator 只支持单值。多个 status 需要用 OR 连接多个条件。
        if len(statuses) == 1:
            status_filter = {
                "conjunction": "and",
                "conditions": [{"field_name": "status", "operator": "is", "value": [statuses[0]]}],
            }
        else:
            # 多个 status：用 OR 连接
            status_filter = {
                "conjunction": "or",
                "conditions": [{"field_name": "status", "operator": "is", "value": [s]} for s in statuses],
            }

        # 如果有 operator 过滤，需要嵌套：(status OR filter) AND operator
        if operator:
            payload = {
                "filter": {
                    "conjunction": "and",
                    "conditions": [
                        status_filter,
                        {"field_name": "operator", "operator": "is", "value": [operator]},
                    ],
                },
                "page_size": 500,
            }
        else:
            payload = {"filter": status_filter, "page_size": 500}
        all_records = []
        page_token = None
        async with httpx.AsyncClient() as client:
            while True:
                if page_token:
                    payload["page_token"] = page_token
                resp = await client.post(url, headers=headers, json=payload, timeout=15)
                data = resp.json()
                if data.get("code") != 0:
                    break
                for item in data.get("data", {}).get("items", []):
                    all_records.append(self._from_bitable_record(item))
                if not data.get("data", {}).get("has_more", False):
                    break
                page_token = data["data"].get("page_token")
        return all_records

    async def list_all_kols(self) -> list:
        url = f"{await self._records_url()}/search"
        headers = await self._headers()
        payload = {"page_size": 500}
        all_records = []
        page_token = None
        async with httpx.AsyncClient() as client:
            while True:
                if page_token:
                    payload["page_token"] = page_token
                resp = await client.post(url, headers=headers, json=payload, timeout=15)
                data = resp.json()
                if data.get("code") != 0:
                    break
                for item in data.get("data", {}).get("items", []):
                    r = self._from_bitable_record(item)
                    r.pop("_record_id", None)
                    all_records.append(r)
                if not data.get("data", {}).get("has_more", False):
                    break
                page_token = data["data"].get("page_token")
        return all_records

    # ──────────────────────────────────
    # 业务方法
    # ──────────────────────────────────

    @staticmethod
    def generate_kol_id(source_url: str, kol_name: str) -> str:
        raw = f"{source_url}|{kol_name}".strip().lower()
        return f"yt_{hashlib.md5(raw.encode()).hexdigest()[:8]}"

    async def upsert_kol(self, kol_data: dict) -> dict:
        kol_id = self.generate_kol_id(kol_data.get("source_url", ""), kol_data.get("kol_name", ""))
        now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        existing = await self.search_by_kol_id(kol_id)

        if existing:
            record_id = existing["_record_id"]
            update_data = {
                "kol_name": kol_data.get("kol_name", existing.get("kol_name", "")),
                "email": kol_data.get("email", existing.get("email", "")),
                "source_url": kol_data.get("source_url", existing.get("source_url", "")),
                "category": kol_data.get("category", existing.get("category", "")),
                "followers_text": kol_data.get("followers_text", existing.get("followers_text", "")),
                "template_key": kol_data.get("template_key", existing.get("template_key", "")),
                "operator": kol_data.get("operator", existing.get("operator", "")),
            }
            await self.update_record(record_id, update_data)
            result = {**existing, **update_data, "kol_id": kol_id}
            result.pop("_record_id", None)
            return result
        else:
            new_data = {
                "kol_id": kol_id,
                "kol_name": kol_data.get("kol_name", ""),
                "email": kol_data.get("email", ""),
                "source_url": kol_data.get("source_url", ""),
                "category": kol_data.get("category", ""),
                "followers_text": kol_data.get("followers_text", ""),
                "template_key": kol_data.get("template_key", ""),
                "operator": kol_data.get("operator", ""),
                "last_error": "",
                "sent_at": "",
                "kol_contact_status": KOL_CONTACT_NOT_CONTACTED,
            }
            await self.create_record(new_data)
            return new_data

    async def get_kol_by_id(self, kol_id: str) -> dict | None:
        result = await self.search_by_kol_id(kol_id)
        if result:
            result.pop("_record_id", None)
        return result

    async def update_kol_status(self, kol_id: str, new_status: str, last_error: str = "", sent_at: str = "") -> bool:
        existing = await self.search_by_kol_id(kol_id)
        if not existing:
            raise ValueError(f"KOL '{kol_id}' not found")
        current = existing.get("status", "")
        if current and not KolStatus.can_transition(current, new_status):
            raise ValueError(f"Invalid transition: '{current}' -> '{new_status}'")
        update_data = {"status": new_status}
        if last_error is not None:
            update_data["last_error"] = last_error
        if sent_at:
            update_data["sent_at"] = sent_at
        elif new_status == KolStatus.SENT:
            update_data["sent_at"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        # 发送成功时自动标记为"已联系"
        if new_status == KolStatus.SENT:
            update_data["kol_contact_status"] = KOL_CONTACT_CONTACTED
        await self.update_record(existing["_record_id"], update_data)
        return True

    async def list_pending_kols(self, operator: str = None) -> list:
        """查询 kol_contact_status = '未联系' 的 KOL（基于 Bitable 当前值，不缓存）"""
        url = f"{await self._records_url()}/search"
        headers = await self._headers()
        payload = {
            "filter": {
                "conjunction": "and",
                "conditions": [
                    {"field_name": "kol_contact_status", "operator": "is", "value": [KOL_CONTACT_NOT_CONTACTED]},
                ],
            },
            "page_size": 500,
        }
        if operator:
            payload["filter"]["conditions"].append(
                {"field_name": "operator", "operator": "is", "value": [operator]}
            )
        all_records = []
        page_token = None
        async with httpx.AsyncClient() as client:
            while True:
                if page_token:
                    payload["page_token"] = page_token
                resp = await client.post(url, headers=headers, json=payload, timeout=15)
                data = resp.json()
                if data.get("code") != 0:
                    logger.error("list_pending_kols error: code=%s msg=%s", data.get("code"), data.get("msg"))
                    break
                for item in data.get("data", {}).get("items", []):
                    all_records.append(self._from_bitable_record(item))
                if not data.get("data", {}).get("has_more", False):
                    break
                page_token = data["data"].get("page_token")
        for r in all_records:
            r.pop("_record_id", None)
        return all_records


# 模块级单例（全局 fallback，使用 .env 应用身份）
bitable_service = BitableService()
