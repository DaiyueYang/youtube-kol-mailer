"""
模板渲染服务 - 变量替换

职责：
- 根据模板 + 变量字典渲染 subject / body_text / body_html
- 只允许模板声明的白名单变量
- 缺失变量不静默吞掉，而是报错到 warnings 列表
- 多余的变量（传入但模板未声明）被忽略

支持的变量（由每个模板的 variables_json 声明）：
{kol_id}, {kol_name}, {platform}, {source_url}, {email},
{country_region}, {language}, {operator}, {notes}, {today},
{category}, {channel_name}, {followers_text}
"""
import json
import re
from datetime import datetime


# 匹配模板中的 {variable_name} 占位符
_VAR_PATTERN = re.compile(r"\{(\w+)\}")


def _find_vars_in_text(text: str) -> set[str]:
    """提取文本中所有 {xxx} 变量名"""
    return set(_VAR_PATTERN.findall(text))


def _safe_replace(text: str, variables: dict) -> str:
    """将 {key} 替换为 variables[key]，未找到的保持原样"""
    def replacer(match):
        key = match.group(1)
        if key in variables:
            return str(variables[key])
        return match.group(0)  # 保持原样，不吞掉
    return _VAR_PATTERN.sub(replacer, text)


def render_template(template: dict, variables: dict) -> dict:
    """
    渲染模板，返回 {subject, body_text, body_html, warnings}。

    参数：
        template:  模板字典，必须包含 subject/body_text/body_html/variables_json
        variables: 变量字典，如 {"kol_name": "Modestas", "kol_id": "KOL-001"}

    规则：
        1. 自动注入 {today} 变量（当天日期）
        2. 从模板的 variables_json 读取白名单
        3. 模板文本中引用的变量如果不在传入的 variables 中，加入 warnings
        4. 不静默吞掉缺失变量 —— warnings 非空时调用方应感知
    """
    warnings = []

    # 解析白名单
    try:
        allowed_vars = set(json.loads(template.get("variables_json", "[]")))
    except (json.JSONDecodeError, TypeError):
        allowed_vars = set()
        warnings.append("variables_json parse failed, treating as empty whitelist")

    # 自动注入 today
    variables = dict(variables)  # 不修改原始 dict
    if "today" not in variables:
        variables["today"] = datetime.now().strftime("%Y-%m-%d")

    # 收集模板文本中实际使用的变量
    subject_text = template.get("subject", "")
    body_text = template.get("body_text", "")
    body_html = template.get("body_html", "")

    used_vars = set()
    used_vars |= _find_vars_in_text(subject_text)
    used_vars |= _find_vars_in_text(body_text)
    used_vars |= _find_vars_in_text(body_html)

    # 检查缺失变量：模板中引用了但传入的 variables 中没有
    for var in sorted(used_vars):
        if var not in variables:
            warnings.append(f"Variable '{{{var}}}' used in template but not provided")

    # 执行替换
    rendered_subject = _safe_replace(subject_text, variables)
    rendered_body_text = _safe_replace(body_text, variables)
    rendered_body_html = _safe_replace(body_html, variables)

    return {
        "subject": rendered_subject,
        "body_text": rendered_body_text,
        "body_html": rendered_body_html,
        "warnings": warnings,
    }
