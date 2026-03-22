"""
SMTP 邮件发送服务

使用飞书企业邮箱 SMTP 发送邮件：
- host: smtp.larksuite.com
- port: 465
- SSL（非 STARTTLS）

所有凭证从 .env 读取，不硬编码。
"""
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from dataclasses import dataclass

from config import settings

logger = logging.getLogger(__name__)


@dataclass
class SendResult:
    """发送结果"""
    success: bool
    message: str
    to_email: str = ""
    subject: str = ""


class SmtpService:
    """飞书企业邮箱 SMTP 发送服务"""

    def __init__(
        self,
        host: str = "",
        port: int = 0,
        username: str = "",
        password: str = "",
        from_name: str = "",
    ):
        self.host = host or settings.LARK_SMTP_HOST
        self.port = port or settings.LARK_SMTP_PORT
        self.username = username or settings.LARK_SMTP_USER
        self.password = password or settings.LARK_SMTP_PASSWORD
        self.from_name = from_name or settings.LARK_SMTP_FROM_NAME

    def check_config(self) -> list[str]:
        """
        检查 SMTP 配置是否完整，返回缺失项列表。
        空列表表示配置完整。
        """
        missing = []
        if not self.host:
            missing.append("LARK_SMTP_HOST")
        if not self.port:
            missing.append("LARK_SMTP_PORT")
        if not self.username:
            missing.append("LARK_SMTP_USER")
        if not self.password:
            missing.append("LARK_SMTP_PASSWORD")
        return missing

    def _build_message(
        self,
        to_email: str,
        subject: str,
        body_text: str = "",
        body_html: str = "",
    ) -> MIMEMultipart:
        """构建 MIME 邮件消息"""
        msg = MIMEMultipart("alternative")

        # 发件人
        if self.from_name:
            msg["From"] = formataddr((self.from_name, self.username))
        else:
            msg["From"] = self.username

        msg["To"] = to_email
        msg["Subject"] = subject

        # 纯文本部分（兜底）
        if body_text:
            msg.attach(MIMEText(body_text, "plain", "utf-8"))

        # HTML 部分（优先显示）
        if body_html:
            msg.attach(MIMEText(body_html, "html", "utf-8"))
        elif body_text:
            # 没有 HTML 时用纯文本的简单 HTML 包装
            simple_html = f"<pre style='font-family:sans-serif'>{body_text}</pre>"
            msg.attach(MIMEText(simple_html, "html", "utf-8"))

        return msg

    def send_email(
        self,
        to_email: str,
        subject: str,
        body_text: str = "",
        body_html: str = "",
    ) -> SendResult:
        """
        发送单封邮件。

        使用 SMTP_SSL（端口 465，直接 SSL 连接）。
        返回 SendResult 包含成功/失败信息。
        """
        # 配置检查
        missing = self.check_config()
        if missing:
            return SendResult(
                success=False,
                message=f"SMTP config incomplete, missing: {', '.join(missing)}",
                to_email=to_email,
                subject=subject,
            )

        if not to_email:
            return SendResult(
                success=False,
                message="Recipient email is empty",
                to_email=to_email,
                subject=subject,
            )

        # 构建消息
        msg = self._build_message(to_email, subject, body_text, body_html)

        try:
            # 飞书企业邮箱使用 SMTP_SSL（465 端口直接 SSL）
            with smtplib.SMTP_SSL(self.host, self.port, timeout=30) as server:
                server.login(self.username, self.password)
                server.send_message(msg)

            logger.info("Email sent: to=%s subject=%s", to_email, subject)
            return SendResult(
                success=True,
                message="Email sent successfully",
                to_email=to_email,
                subject=subject,
            )

        except smtplib.SMTPAuthenticationError as e:
            error_msg = f"SMTP authentication failed: {e}"
            logger.error(error_msg)
            return SendResult(success=False, message=error_msg, to_email=to_email, subject=subject)

        except smtplib.SMTPRecipientsRefused as e:
            error_msg = f"Recipient refused: {e}"
            logger.error(error_msg)
            return SendResult(success=False, message=error_msg, to_email=to_email, subject=subject)

        except smtplib.SMTPException as e:
            error_msg = f"SMTP error: {e}"
            logger.error(error_msg)
            return SendResult(success=False, message=error_msg, to_email=to_email, subject=subject)

        except Exception as e:
            error_msg = f"Unexpected error sending email: {e}"
            logger.exception(error_msg)
            return SendResult(success=False, message=error_msg, to_email=to_email, subject=subject)

    def send_preview_email(
        self,
        to_email: str,
        subject: str,
        body_text: str = "",
        body_html: str = "",
    ) -> SendResult:
        """
        发送预览邮件（给操作者自己）。

        在 subject 前加 [PREVIEW] 标记，便于区分。
        """
        preview_subject = f"[PREVIEW] {subject}"
        return self.send_email(to_email, preview_subject, body_text, body_html)


# 模块级单例
smtp_service = SmtpService()
