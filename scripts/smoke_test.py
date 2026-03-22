"""
最小验收测试 - 检查系统基础功能

使用方式: python scripts/smoke_test.py [backend_url]
默认测试 http://localhost:8000
"""
import sys
import os
import urllib.request
import json

# 修复 Windows 终端编码
if sys.platform == 'win32':
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def test_health(base_url):
    """测试健康检查接口"""
    url = f"{base_url}/api/health"
    print(f"[TEST] GET {url}")
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            assert data["status"] == "ok", f"Expected status=ok, got {data}"
            print(f"  ✓ Health check passed: {data}")
            return True
    except Exception as e:
        print(f"  ✗ Health check failed: {e}")
        return False


def test_templates_list(base_url):
    """测试模板列表接口"""
    url = f"{base_url}/api/templates"
    print(f"[TEST] GET {url}")
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            # 支持两种格式：直接 {templates} 或 {data: {templates}}
            if "data" in data and isinstance(data["data"], dict):
                total = data["data"].get("total", len(data["data"].get("templates", [])))
            else:
                assert "templates" in data, f"Unexpected response format"
                total = data.get("total", len(data.get("templates", [])))
            print(f"  ✓ Templates list returned: {total} templates")
            return True
    except Exception as e:
        print(f"  ✗ Templates list failed: {e}")
        return False


def test_admin_dashboard(base_url):
    """测试 Admin 页面"""
    url = f"{base_url}/admin/"
    print(f"[TEST] GET {url}")
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = resp.read().decode()
            assert "KOL Mailer" in body, "Admin page missing expected content"
            print(f"  ✓ Admin dashboard accessible")
            return True
    except Exception as e:
        print(f"  ✗ Admin dashboard failed: {e}")
        return False


if __name__ == '__main__':
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
    print(f"Running smoke tests against: {base_url}\n")

    results = [
        test_health(base_url),
        test_templates_list(base_url),
        test_admin_dashboard(base_url),
    ]

    print(f"\nResults: {sum(results)}/{len(results)} passed")
    sys.exit(0 if all(results) else 1)
