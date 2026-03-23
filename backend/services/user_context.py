"""
用户上下文工具

从 Request 中提取当前用户，并为该用户构建专属的 BitableService / SmtpService。
BitableService 优先使用 user_access_token（用户身份），使用户创建的 Base 归属于用户本人。
"""
import time
import logging
from fastapi import Request
from services.auth_service import auth_service
from services.bitable_service import BitableService, bitable_service as default_bitable
from services.smtp_service import SmtpService
from config import settings

logger = logging.getLogger(__name__)


class UserContext:
    """一个请求周期内的用户上下文"""

    def __init__(self, user: dict | None):
        self.user = user
        self.user_id = user["id"] if user else None
        self.display_name = user.get("display_name", "") if user else ""
        self.logged_in = user is not None

    @property
    def operator_name(self) -> str:
        if self.user:
            return self.user.get("display_name") or self.user.get("smtp_email") or f"user_{self.user_id}"
        return "default"

    def _get_user_token(self) -> str:
        """获取用户的 access_token（如果未过期）"""
        if not self.user:
            return ""
        expires = self.user.get("token_expires_at", 0)
        if time.time() < expires:
            return self.user.get("user_access_token", "")
        return ""

    async def ensure_fresh_token(self):
        """
        尝试刷新过期的 user_access_token。
        在需要用户身份操作 Bitable 之前调用。
        """
        if not self.user:
            return
        if time.time() < self.user.get("token_expires_at", 0):
            return  # 未过期，无需刷新
        # 尝试刷新
        refreshed = await auth_service.refresh_user_token(self.user)
        if refreshed:
            self.user = refreshed
            logger.info("Token refreshed for user %s", self.user_id)
        else:
            logger.warning(
                "Token refresh failed for user %s. "
                "User-identity Bitable operations may fail. "
                "Please re-login.",
                self.user_id,
            )

    def get_bitable_service(self) -> BitableService:
        """
        获取当前用户专属的 BitableService。
        如果用户的 Bitable 是以用户身份创建的（bitable_identity=user），使用 user_token。
        如果是应用身份创建的（bitable_identity=app），使用应用身份。
        如果用户身份 token 已过期，会明确警告而非静默 fallback。
        """
        if self.user:
            app_token = self.user.get("bitable_app_token", "")
            table_id = self.user.get("bitable_table_id", "")
            bt_identity = self.user.get("bitable_identity", "")

            if app_token:
                user_token = ""
                if bt_identity == "user":
                    user_token = self._get_user_token()
                    if not user_token:
                        # 用户身份 token 已过期，不静默降级到应用身份
                        raise RuntimeError(
                            "用户身份令牌已过期，无法访问以用户身份创建的表格。"
                            "请重新登录飞书以刷新令牌。"
                        )
                logger.info("BitableService: user=%s app_token=%s... table_id=%s identity=%s token_valid=%s",
                            self.user_id, app_token[:8], table_id or "(auto)", bt_identity, bool(user_token))
                return BitableService(
                    app_token=app_token,
                    table_id=table_id,
                    user_token=user_token,
                )
        logger.info("BitableService: fallback to default (user=%s, has_app_token=%s)",
                     self.user_id, bool(self.user.get("bitable_app_token")) if self.user else False)
        return default_bitable

    def get_smtp_service(self) -> SmtpService | None:
        """获取用户专属 SMTP。如未配置返回 None。"""
        if self.user:
            email = self.user.get("smtp_email", "")
            password = self.user.get("smtp_password", "")
            if email and password:
                return SmtpService(username=email, password=password, from_name=self.user.get("smtp_from_name", ""))
        return None

    def get_preview_email(self) -> str:
        if self.user:
            return self.user.get("preview_email", "") or self.user.get("smtp_email", "")
        return settings.PREVIEW_RECEIVER_EMAIL

    async def get_user_access_token(self) -> str | None:
        if not self.user:
            return None
        return await auth_service.get_valid_user_token(self.user)


def get_user_context(request: Request) -> UserContext:
    session = request.cookies.get("session_token", "") or request.headers.get("X-Session-Token", "")
    user = auth_service.get_current_user(session)
    return UserContext(user)


def get_user_context_by_id(user_id: int) -> UserContext:
    from repositories.user_repo import user_repo
    return UserContext(user_repo.find_by_id(user_id))


def get_user_context_by_open_id(open_id: str) -> UserContext:
    from repositories.user_repo import user_repo
    return UserContext(user_repo.find_by_open_id(open_id))
