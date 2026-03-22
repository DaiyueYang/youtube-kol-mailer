"""
Bitable 集成冒烟测试

使用方式:
    cd backend
    python ../scripts/smoke_test_bitable.py

前置条件:
    1. .env 中已配置 LARK_APP_ID / LARK_APP_SECRET / LARK_BITABLE_APP_TOKEN / LARK_BITABLE_TABLE_ID
    2. Bitable KOL 表已创建，且包含所有必要字段
    3. 飞书应用已授权访问该 Bitable

测试流程:
    1. 获取 tenant_access_token
    2. 创建一条测试 KOL 记录
    3. 按 kol_id 查询该记录
    4. 更新状态为 preview_sent
    5. 再次查询确认状态已更新
    6. 查询 pending 列表
"""
import sys
import os
import asyncio

# 修复 Windows 编码
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))


async def run_tests():
    from services.bitable_service import BitableService
    from config import settings

    # 检查配置
    missing = []
    if not settings.LARK_APP_ID:
        missing.append("LARK_APP_ID")
    if not settings.LARK_APP_SECRET:
        missing.append("LARK_APP_SECRET")
    if not settings.LARK_BITABLE_APP_TOKEN:
        missing.append("LARK_BITABLE_APP_TOKEN")
    if not settings.LARK_BITABLE_TABLE_ID:
        missing.append("LARK_BITABLE_TABLE_ID")

    if missing:
        print(f"[SKIP] Missing .env config: {', '.join(missing)}")
        print("Please configure .env first. Tests skipped.")
        return True  # 不算失败，只是跳过

    svc = BitableService()
    passed = 0
    failed = 0

    # Test 1: 获取 token
    print("[TEST 1] Get tenant_access_token...")
    try:
        token = await svc._get_tenant_token()
        assert token, "Token is empty"
        print(f"  PASS - token: {token[:20]}...")
        passed += 1
    except Exception as e:
        print(f"  FAIL - {e}")
        failed += 1
        return False  # token 失败，后续无法继续

    # Test 2: 创建/更新 KOL
    print("\n[TEST 2] Upsert KOL...")
    try:
        test_data = {
            "kol_name": "SmokeTestBot",
            "channel_name": "SmokeTestBot",
            "email": "smoketest@example.com",
            "source_url": "https://youtube.com/@smoketestbot",
            "template_key": "tmpl_youtube_general_v1",
            "template_name": "YouTube General Outreach",
            "operator": "smoke_test",
            "notes": "auto smoke test",
            "platform": "YouTube",
            "category": "Testing",
        }
        result = await svc.upsert_kol(test_data)
        kol_id = result["kol_id"]
        assert kol_id.startswith("yt_"), f"Unexpected kol_id format: {kol_id}"
        print(f"  PASS - kol_id: {kol_id}")
        passed += 1
    except Exception as e:
        print(f"  FAIL - {e}")
        failed += 1
        return False

    # Test 3: 查询 KOL
    print("\n[TEST 3] Get KOL by ID...")
    try:
        kol = await svc.get_kol_by_id(kol_id)
        assert kol is not None, "KOL not found"
        assert kol["kol_name"] == "SmokeTestBot"
        assert kol["template_key"] == "tmpl_youtube_general_v1"
        print(f"  PASS - kol_name: {kol['kol_name']}, template_key: {kol['template_key']}")
        passed += 1
    except Exception as e:
        print(f"  FAIL - {e}")
        failed += 1

    # Test 4: 更新状态
    print("\n[TEST 4] Update status to preview_sent...")
    try:
        await svc.update_kol_status(kol_id, "preview_sent")
        kol = await svc.get_kol_by_id(kol_id)
        assert kol["status"] == "preview_sent", f"Status mismatch: {kol['status']}"
        print(f"  PASS - status: {kol['status']}")
        passed += 1
    except Exception as e:
        print(f"  FAIL - {e}")
        failed += 1

    # Test 5: 恢复为 pending（通过 confirmed -> sending -> failed -> pending 路径模拟不了，
    # 直接将 preview_sent -> confirmed -> sending -> failed -> pending）
    # 简化：把状态改回 skipped（终态）来验证
    print("\n[TEST 5] Update status preview_sent -> skipped...")
    try:
        await svc.update_kol_status(kol_id, "skipped")
        kol = await svc.get_kol_by_id(kol_id)
        assert kol["status"] == "skipped"
        print(f"  PASS - status: {kol['status']}")
        passed += 1
    except Exception as e:
        print(f"  FAIL - {e}")
        failed += 1

    # Test 6: 查询 pending 列表
    print("\n[TEST 6] List pending KOLs...")
    try:
        pending = await svc.list_pending_kols()
        print(f"  PASS - found {len(pending)} pending/failed KOLs")
        passed += 1
    except Exception as e:
        print(f"  FAIL - {e}")
        failed += 1

    print(f"\n{'='*40}")
    print(f"Results: {passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(run_tests())
    sys.exit(0 if success else 1)
