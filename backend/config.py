"""
全局配置 - 从 .env 文件加载环境变量

所有配置集中在此文件管理，其他模块通过 `from config import settings` 使用。
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# 加载 .env 文件
ENV_PATH = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=ENV_PATH)


def _get(key: str, default: str = "") -> str:
    """读取环境变量并 strip 前后空白/引号"""
    val = os.getenv(key, default)
    if val:
        val = val.strip().strip('"').strip("'")
    return val


def _get_int(key: str, default: int = 0) -> int:
    """读取整数环境变量"""
    val = _get(key, str(default))
    # 去掉行内注释（如 "5  # 这是注释"）
    val = val.split("#")[0].strip() if "#" in val else val
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


class Settings:
    """应用配置 - 与 .env 字段一一对应"""

    # ── 应用基础 ──
    APP_ENV: str = _get("APP_ENV", "dev")
    APP_HOST: str = _get("APP_HOST", "0.0.0.0")
    APP_PORT: int = _get_int("APP_PORT", 8000)

    # ── 数据库 ──
    DB_PATH: str = _get("DB_PATH", "./data/app.db")

    # ── 飞书 API 基础地址 ──
    # 飞书国内版: https://open.feishu.cn/open-apis
    # Lark 国际版: https://open.larksuite.com/open-apis
    LARK_API_BASE: str = _get("LARK_API_BASE", "")

    # ── 飞书 SMTP（企业邮箱） ──
    LARK_SMTP_HOST: str = _get("LARK_SMTP_HOST", "smtp.larksuite.com")
    LARK_SMTP_PORT: int = _get_int("LARK_SMTP_PORT", 465)
    LARK_SMTP_USER: str = _get("LARK_SMTP_USER", "")
    LARK_SMTP_PASSWORD: str = _get("LARK_SMTP_PASSWORD", "")
    LARK_SMTP_FROM_NAME: str = _get("LARK_SMTP_FROM_NAME", "")

    # ── 飞书 Bitable ──
    LARK_BITABLE_APP_TOKEN: str = _get("LARK_BITABLE_APP_TOKEN", "")
    LARK_BITABLE_TABLE_ID: str = _get("LARK_BITABLE_TABLE_ID", "")

    # ── 飞书应用凭证 ──
    LARK_APP_ID: str = _get("LARK_APP_ID", "")
    LARK_APP_SECRET: str = _get("LARK_APP_SECRET", "")

    # ── 发送配置 ──
    PREVIEW_RECEIVER_EMAIL: str = _get("PREVIEW_RECEIVER_EMAIL", "")
    SEND_DELAY_MIN: int = _get_int("SEND_DELAY_MIN", 5)
    SEND_DELAY_MAX: int = _get_int("SEND_DELAY_MAX", 15)

    # ── OAuth ──
    OAUTH_REDIRECT_URI: str = _get("OAUTH_REDIRECT_URI", "https://api.youtube-kol.com/api/auth/callback")

    def get_api_base(self) -> str:
        """
        获取飞书 API 基础地址。
        必须在 .env 中配置 LARK_API_BASE，否则默认飞书国内版。
        """
        if self.LARK_API_BASE:
            return self.LARK_API_BASE.rstrip("/")
        return "https://open.feishu.cn/open-apis"


# .env 文件信息（用于诊断）
ENV_FILE_EXISTS = ENV_PATH.exists()

settings = Settings()
