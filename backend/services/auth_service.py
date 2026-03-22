"""
飞书 OAuth 认证服务

职责：
- 生成飞书 OAuth 授权 URL
- 用 code 换取 user_access_token / refresh_token
- 获取飞书用户信息
- 刷新 user_access_token
- 管理用户会话
"""
import time
import uuid
import logging
import httpx
from config import settings
from repositories.user_repo import user_repo

logger = logging.getLogger(__name__)


class AuthService:

    def _api_base(self) -> str:
        return settings.get_api_base()

    def get_login_url(self, state: str = "") -> str:
        """生成飞书 OAuth 授权页 URL，包含 bitable 等必要 scope"""
        if not state:
            state = uuid.uuid4().hex[:16]

        base = self._api_base()
        return (
            f"{base}/authen/v1/authorize"
            f"?app_id={settings.LARK_APP_ID}"
            f"&redirect_uri={settings.OAUTH_REDIRECT_URI}"
            f"&response_type=code"
            f"&state={state}"
            f"&scope=bitable:app"
        )

    async def handle_callback(self, code: str) -> dict:
        """
        用 OAuth code 换取 token 并获取用户信息。
        返回用户记录 dict。
        """
        # Step 1: code → token
        token_data = await self._exchange_code(code)
        access_token = token_data["access_token"]
        refresh_token = token_data.get("refresh_token", "")
        expires_in = token_data.get("expires_in", 7200)
        token_expires_at = time.time() + expires_in - 60  # 提前 1 分钟

        # Step 2: 获取用户信息
        user_info = await self._get_user_info(access_token)

        # Step 3: 创建/更新用户记录
        # 复用已有 session_token（避免互相挤掉登录状态）
        existing = user_repo.find_by_open_id(user_info["open_id"])
        if existing and existing.get("session_token"):
            session_token = existing["session_token"]  # 复用
            logger.info("OAuth login: reusing session=%s... for %s", session_token[:8], user_info.get("name"))
        else:
            session_token = uuid.uuid4().hex  # 首次登录或 token 被清空
            logger.info("OAuth login: new session=%s... for %s", session_token[:8], user_info.get("name"))

        user = user_repo.upsert_oauth(
            feishu_open_id=user_info["open_id"],
            feishu_union_id=user_info.get("union_id", ""),
            display_name=user_info.get("name", ""),
            avatar_url=user_info.get("avatar_url", ""),
            user_access_token=access_token,
            refresh_token=refresh_token,
            token_expires_at=token_expires_at,
            session_token=session_token,
        )
        return user

    async def _exchange_code(self, code: str) -> dict:
        """用 code 换取 user_access_token"""
        # 先获取 app_access_token（飞书 OAuth 需要）
        app_token = await self._get_app_access_token()

        url = f"{self._api_base()}/authen/v1/oidc/access_token"
        headers = {
            "Authorization": f"Bearer {app_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "grant_type": "authorization_code",
            "code": code,
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=headers, json=payload, timeout=10)
            data = resp.json()

        if data.get("code") != 0:
            raise RuntimeError(f"OAuth token exchange failed: {data.get('msg', data)}")

        return data.get("data", {})

    async def _get_app_access_token(self) -> str:
        """获取 app_access_token（用于 OAuth code exchange）"""
        url = f"{self._api_base()}/auth/v3/app_access_token/internal"
        payload = {
            "app_id": settings.LARK_APP_ID,
            "app_secret": settings.LARK_APP_SECRET,
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, timeout=10)
            data = resp.json()

        if data.get("code") != 0:
            raise RuntimeError(f"Get app_access_token failed: {data.get('msg', data)}")

        return data["app_access_token"]

    async def _get_user_info(self, access_token: str) -> dict:
        """用 user_access_token 获取用户信息"""
        url = f"{self._api_base()}/authen/v1/user_info"
        headers = {
            "Authorization": f"Bearer {access_token}",
        }

        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers, timeout=10)
            data = resp.json()

        if data.get("code") != 0:
            raise RuntimeError(f"Get user info failed: {data.get('msg', data)}")

        return data.get("data", {})

    async def refresh_user_token(self, user: dict) -> dict | None:
        """
        刷新用户的 access_token。
        成功返回更新后的用户记录，失败返回 None（需要重新登录）。
        """
        refresh_token = user.get("refresh_token", "")
        if not refresh_token:
            logger.warning("No refresh_token for user %s", user.get("id"))
            return None

        try:
            app_token = await self._get_app_access_token()
            url = f"{self._api_base()}/authen/v1/oidc/refresh_access_token"
            headers = {
                "Authorization": f"Bearer {app_token}",
                "Content-Type": "application/json",
            }
            payload = {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            }

            async with httpx.AsyncClient() as client:
                resp = await client.post(url, headers=headers, json=payload, timeout=10)
                data = resp.json()

            if data.get("code") != 0:
                logger.error("Token refresh failed for user %s: %s", user.get("id"), data.get("msg"))
                return None

            token_data = data.get("data", {})
            new_access = token_data["access_token"]
            new_refresh = token_data.get("refresh_token", refresh_token)
            expires_in = token_data.get("expires_in", 7200)

            user_repo.update_tokens(
                user["id"],
                new_access,
                new_refresh,
                time.time() + expires_in - 60,
            )

            logger.info("Token refreshed for user %s", user.get("id"))
            return user_repo.find_by_id(user["id"])

        except Exception as e:
            logger.exception("Token refresh error for user %s: %s", user.get("id"), e)
            return None

    async def get_valid_user_token(self, user: dict) -> str | None:
        """
        获取用户的有效 access_token。
        如果过期则自动刷新。刷新失败返回 None。
        """
        if time.time() < user.get("token_expires_at", 0):
            return user["user_access_token"]

        # 需要刷新
        refreshed = await self.refresh_user_token(user)
        if refreshed:
            return refreshed["user_access_token"]
        return None

    def get_current_user(self, session_token: str) -> dict | None:
        """通过 session_token 获取当前用户"""
        if not session_token:
            return None
        return user_repo.find_by_session(session_token)

    def logout(self, user_id: int):
        """登出：清除会话和 token"""
        user_repo.clear_session(user_id)


auth_service = AuthService()
