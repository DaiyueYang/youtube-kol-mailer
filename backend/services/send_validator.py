"""
发送前校验服务

可复用的校验函数，在预览发送和正式发送前统一调用。
校验不通过时返回明确的错误列表，不静默跳过。
"""
import re
from services.template_service import template_service
from services.render_service import render_template
from services.smtp_service import smtp_service

# 基本邮箱格式
_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


def validate_email_format(email: str) -> bool:
    """校验邮箱格式"""
    return bool(email and _EMAIL_RE.match(email))


def validate_before_send(
    kol_data: dict,
    template_key: str,
) -> dict:
    """
    发送前完整校验。

    返回:
    {
        "valid": bool,
        "errors": ["..."],       # 阻断性错误，不可发送
        "warnings": ["..."],     # 警告（变量缺失等），可发但需注意
        "template": dict | None, # 校验通过时返回模板数据
        "rendered": dict | None, # 校验通过时返回渲染结果
    }
    """
    errors = []
    warnings = []

    # 1. KOL 是否有 email
    email = kol_data.get("email", "")
    if not email:
        errors.append("KOL has no email address")
    elif not validate_email_format(email):
        errors.append(f"Invalid email format: '{email}'")

    # 2. template_key 是否存在
    tmpl = template_service.get_template(template_key)
    if not tmpl:
        errors.append(f"Template '{template_key}' not found")
        return {
            "valid": False,
            "errors": errors,
            "warnings": warnings,
            "template": None,
            "rendered": None,
        }

    if not tmpl.get("enabled"):
        errors.append(f"Template '{template_key}' is disabled")

    # 3. 模板变量是否可完整渲染
    rendered = render_template(tmpl, kol_data)
    warnings.extend(rendered.get("warnings", []))

    # subject 和 body 不能渲染为空
    if not rendered["subject"].strip():
        errors.append("Rendered subject is empty")
    if not rendered["body_text"].strip() and not rendered["body_html"].strip():
        errors.append("Rendered body is empty (both text and html)")

    # 4. SMTP 配置是否完整
    smtp_missing = smtp_service.check_config()
    if smtp_missing:
        errors.append(f"SMTP config incomplete, missing: {', '.join(smtp_missing)}")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "template": tmpl,
        "rendered": rendered,
    }
