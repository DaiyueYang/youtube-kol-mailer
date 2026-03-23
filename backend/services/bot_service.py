"""
飞书应用机器人消息服务

职责：
- 通过应用机器人 API 向群发送消息（文本 + 交互卡片）
- 构建交互卡片 JSON
- 更新已发送卡片内容（PATCH）
- 格式化待发送汇总、预览提示、发送结果

使用应用机器人 API（/im/v1/messages），不使用自定义机器人 webhook。
所有发送都需要 tenant_access_token + chat_id。
"""
import json
import logging
import httpx
from config import settings

logger = logging.getLogger(__name__)


class BotService:
    """飞书应用机器人消息服务"""

    def __init__(self):
        self._api_base = ""

    def _get_api_base(self) -> str:
        return settings.get_api_base()

    def is_configured(self) -> bool:
        """检查应用机器人所需配置是否完整"""
        return bool(settings.LARK_APP_ID and settings.LARK_APP_SECRET)

    async def _get_token(self) -> str:
        """复用 bitable_service 的 token（同一应用凭证）"""
        from services.bitable_service import bitable_service
        return await bitable_service._get_tenant_token()

    async def _headers(self) -> dict:
        token = await self._get_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    # ──────────────────────────────────
    # 发送消息（应用机器人 API）
    # ──────────────────────────────────

    async def send_text_to_chat(self, chat_id: str, text: str) -> dict:
        """
        用应用机器人 API 发送文本消息到群。
        返回 {"ok": bool, "message_id": str, "error": str}
        """
        url = f"{self._get_api_base()}/im/v1/messages"
        headers = await self._headers()
        payload = {
            "receive_id": chat_id,
            "msg_type": "text",
            "content": json.dumps({"text": text}),
        }
        params = {"receive_id_type": "chat_id"}

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, headers=headers, json=payload, params=params, timeout=10)
                data = resp.json()

            if data.get("code") != 0:
                err = f"code={data.get('code')}: {data.get('msg', 'unknown')}"
                logger.error("Send text failed: %s", err)
                return {"ok": False, "message_id": "", "error": err}

            msg_id = data.get("data", {}).get("message_id", "")
            return {"ok": True, "message_id": msg_id, "error": ""}
        except Exception as e:
            logger.exception("Send text error: %s", e)
            return {"ok": False, "message_id": "", "error": str(e)}

    async def send_card_to_chat(self, chat_id: str, card: dict) -> dict:
        """
        用应用机器人 API 发送交互卡片到群。
        返回 {"ok": bool, "message_id": str, "error": str}
        """
        url = f"{self._get_api_base()}/im/v1/messages"
        headers = await self._headers()
        payload = {
            "receive_id": chat_id,
            "msg_type": "interactive",
            "content": json.dumps(card),
        }
        params = {"receive_id_type": "chat_id"}

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, headers=headers, json=payload, params=params, timeout=10)
                data = resp.json()

            if data.get("code") != 0:
                err = f"code={data.get('code')}: {data.get('msg', 'unknown')}"
                logger.error("Send card failed: %s", err)
                return {"ok": False, "message_id": "", "error": err}

            msg_id = data.get("data", {}).get("message_id", "")
            logger.info("Card sent to %s, message_id=%s", chat_id, msg_id)
            return {"ok": True, "message_id": msg_id, "error": ""}
        except Exception as e:
            logger.exception("Send card error: %s", e)
            return {"ok": False, "message_id": "", "error": str(e)}

    async def update_card(self, message_id: str, card: dict) -> bool:
        """
        更新已发送的交互卡片内容（PATCH）。
        用于在用户点击按钮后更新卡片状态。
        """
        url = f"{self._get_api_base()}/im/v1/messages/{message_id}"
        headers = await self._headers()
        payload = {
            "msg_type": "interactive",
            "content": json.dumps(card),
        }

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.patch(
                    url, headers=headers, json=payload, timeout=10,
                )
                data = resp.json()

            if data.get("code") != 0:
                logger.error("Update card failed: %s", data.get("msg"))
                return False

            logger.info("Card updated: %s", message_id)
            return True
        except Exception as e:
            logger.exception("Update card error: %s", e)
            return False

    # ──────────────────────────────────
    # 卡片构建
    # ──────────────────────────────────

    def build_pending_card(
        self,
        operator: str,
        pending_kols: list,
        status_text: str = "等待操作",
        status_color: str = "neutral",
        user_id: int = None,
    ) -> dict:
        """
        构建待发送汇总交互卡片。

        status_color: neutral / blue / green / red / orange
        """
        total = len(pending_kols)

        # 统计模板分布
        template_counts: dict[str, int] = {}
        no_email_count = 0
        for kol in pending_kols:
            tname = kol.get("template_name") or kol.get("template_key") or "unknown"
            template_counts[tname] = template_counts.get(tname, 0) + 1
            if not kol.get("email"):
                no_email_count += 1

        template_dist = " / ".join(f"{n} ({c})" for n, c in template_counts.items())

        # KOL 摘要（最多 5 条）
        kol_lines = []
        for kol in pending_kols[:5]:
            name = kol.get("kol_name", "?")
            email = kol.get("email", "") or "NO EMAIL"
            tmpl = kol.get("template_key", "?")
            kol_lines.append(f"  {name} | {email} | {tmpl}")
        if total > 5:
            kol_lines.append(f"  ... 及其他 {total - 5} 条")

        kol_summary = "\n".join(kol_lines) if kol_lines else "（无）"

        # 构建卡片 JSON（飞书卡片 JSON 格式）
        card = {
            "header": {
                "template": status_color,
                "title": {"tag": "plain_text", "content": "📧 邮件发送确认"},
            },
            "elements": [
                {
                    "tag": "div",
                    "fields": [
                        {"is_short": True, "text": {"tag": "lark_md", "content": f"**操作者**\n{operator}"}},
                        {"is_short": True, "text": {"tag": "lark_md", "content": f"**待发送**\n{total} 封"}},
                        {"is_short": True, "text": {"tag": "lark_md", "content": f"**缺失邮箱**\n{no_email_count} 条"}},
                        {"is_short": True, "text": {"tag": "lark_md", "content": f"**模板分布**\n{template_dist or '-'}"}},
                    ],
                },
                {"tag": "hr"},
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"**待发送列表**\n```\n{kol_summary}\n```",
                    },
                },
                {"tag": "hr"},
                {
                    "tag": "note",
                    "elements": [
                        {"tag": "lark_md", "content": f"📌 **状态**: {status_text}"},
                    ],
                },
                {"tag": "hr"},
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "📤 发送预览"},
                            "type": "primary",
                            "value": json.dumps({
                                "action": "preview_send",
                                "operator": operator,
                                "user_id": user_id,
                            }),
                        },
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "✅ 确认发送"},
                            "type": "danger",
                            "value": json.dumps({
                                "action": "confirm_send",
                                "operator": operator,
                                "user_id": user_id,
                            }),
                        },
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "🔄 刷新列表"},
                            "value": json.dumps({
                                "action": "refresh_pending",
                                "operator": operator,
                                "user_id": user_id,
                            }),
                        },
                    ],
                },
            ],
        }

        return card

    def build_result_card(
        self,
        operator: str,
        status_text: str,
        status_color: str,
        detail_text: str = "",
        show_retry: bool = False,
    ) -> dict:
        """构建结果卡片（预览结果 / 发送结果）"""
        elements = [
            {
                "tag": "div",
                "fields": [
                    {"is_short": True, "text": {"tag": "lark_md", "content": f"**操作者**\n{operator}"}},
                ],
            },
            {"tag": "hr"},
            {
                "tag": "note",
                "elements": [
                    {"tag": "lark_md", "content": f"📌 **状态**: {status_text}"},
                ],
            },
        ]

        if detail_text:
            elements.insert(2, {
                "tag": "div",
                "text": {"tag": "lark_md", "content": detail_text},
            })

        actions = []
        if show_retry:
            actions.append({
                "tag": "button",
                "text": {"tag": "plain_text", "content": "🔄 重试失败"},
                "type": "primary",
                "value": json.dumps({
                    "action": "confirm_send",
                    "operator": operator,
                }),
            })
        actions.append({
            "tag": "button",
            "text": {"tag": "plain_text", "content": "🔄 刷新列表"},
            "value": json.dumps({
                "action": "refresh_pending",
                "operator": operator,
            }),
        })

        elements.append({"tag": "hr"})
        elements.append({"tag": "action", "actions": actions})

        return {
            "header": {
                "template": status_color,
                "title": {"tag": "plain_text", "content": "📧 邮件发送确认"},
            },
            "elements": elements,
        }



# 模块级单例
bot_service = BotService()
