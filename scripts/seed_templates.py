"""
模板初始化脚本 - 插入示例模板到 SQLite

使用方式: cd backend && python ../scripts/seed_templates.py

特性：
- 按 template_key 幂等插入（已存在则跳过）
- 包含 2 条示例模板
- 可重复运行
"""
import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from models.db import init_db, get_connection

SEED_TEMPLATES = [
    {
        "template_key": "tmpl_youtube_general_v1",
        "template_name": "YouTube General Outreach",
        "subject": "Collaboration Opportunity with {kol_name}",
        "body_text": (
            "Hi {kol_name},\n\n"
            "I came across your YouTube channel and was really impressed by your content.\n\n"
            "We'd love to explore a potential collaboration with you. "
            "Our team has been following your work in the {category} space "
            "and we think there's a great fit.\n\n"
            "Would you be open to a quick chat about this?\n\n"
            "Best regards,\n"
            "{operator}\n"
            "{today}"
        ),
        "body_html": (
            "<p>Hi {kol_name},</p>"
            "<p>I came across your YouTube channel and was really impressed by your content.</p>"
            "<p>We'd love to explore a potential collaboration with you. "
            "Our team has been following your work in the <strong>{category}</strong> space "
            "and we think there's a great fit.</p>"
            "<p>Would you be open to a quick chat about this?</p>"
            "<p>Best regards,<br>{operator}<br>{today}</p>"
        ),
        "variables_json": json.dumps([
            "kol_name", "category", "operator", "today"
        ]),
        "channel": "youtube",
        "enabled": 1,
    },
    {
        "template_key": "tmpl_mc_global_v1",
        "template_name": "Minecraft Global Group Outreach",
        "subject": "Minecraft Partnership - {kol_name}",
        "body_text": (
            "Hey {kol_name},\n\n"
            "We're reaching out from an international Minecraft creator group.\n\n"
            "We noticed your channel ({source_url}) and your amazing Minecraft content. "
            "We're currently building a global creator community and think you'd be a perfect fit!\n\n"
            "Here's what we can offer:\n"
            "- Early access to new content and updates\n"
            "- Cross-promotion with other creators\n"
            "- Revenue sharing opportunities\n\n"
            "Interested? Just reply to this email and we'll set up a call.\n\n"
            "Cheers,\n"
            "{operator}"
        ),
        "body_html": (
            "<p>Hey {kol_name},</p>"
            "<p>We're reaching out from an international Minecraft creator group.</p>"
            "<p>We noticed your channel (<a href='{source_url}'>{source_url}</a>) "
            "and your amazing Minecraft content. "
            "We're currently building a global creator community and think you'd be a perfect fit!</p>"
            "<p>Here's what we can offer:</p>"
            "<ul>"
            "<li>Early access to new content and updates</li>"
            "<li>Cross-promotion with other creators</li>"
            "<li>Revenue sharing opportunities</li>"
            "</ul>"
            "<p>Interested? Just reply to this email and we'll set up a call.</p>"
            "<p>Cheers,<br>{operator}</p>"
        ),
        "variables_json": json.dumps([
            "kol_name", "source_url", "operator", "today"
        ]),
        "channel": "youtube",
        "enabled": 1,
    },
]


def seed():
    """插入 seed 模板数据（幂等，已存在的跳过）"""
    init_db()
    conn = get_connection()
    cursor = conn.cursor()

    inserted = 0
    skipped = 0

    for tmpl in SEED_TEMPLATES:
        # 检查是否已存在
        existing = cursor.execute(
            "SELECT template_key FROM templates WHERE template_key = ?",
            (tmpl["template_key"],)
        ).fetchone()

        if existing:
            print(f"  SKIP  {tmpl['template_key']} (already exists)")
            skipped += 1
            continue

        cursor.execute(
            """
            INSERT INTO templates (
                template_key, template_name, subject,
                body_text, body_html, variables_json,
                channel, enabled
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tmpl["template_key"],
                tmpl["template_name"],
                tmpl["subject"],
                tmpl["body_text"],
                tmpl["body_html"],
                tmpl["variables_json"],
                tmpl["channel"],
                tmpl["enabled"],
            ),
        )
        print(f"  INSERT {tmpl['template_key']}")
        inserted += 1

    conn.commit()
    conn.close()
    print(f"\nSeed complete: {inserted} inserted, {skipped} skipped.")


if __name__ == "__main__":
    # 修复 Windows 终端编码
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    seed()
