"""Dashboard Basic Auth 和 REST API 测试"""

import base64
import pytest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from cli_anything.core.models import TaskStatus
from cli_anything.storage.database import Database
from cli_anything.core.task_manager import TaskManager
from cli_anything.utils.config import Config


@pytest.fixture
def db(tmp_path):
    """创建跨线程安全的测试数据库"""
    db_path = str(tmp_path / "test.db")
    database = Database(db_path)
    database.connect()
    yield database
    database.close()


@pytest.fixture
def tm(db):
    return TaskManager(db, terminal_id="dashboard")


@pytest.fixture
def client(db, tm):
    """创建测试客户端（认证禁用）"""
    import cli_anything.web.dashboard as dash
    dash._db = db
    dash._tm = tm
    mock_config = MagicMock(spec=Config)
    mock_config.get.side_effect = lambda key, default=None: {
        "dashboard.auth.enabled": False,
    }.get(key, default)
    dash._config = mock_config
    yield TestClient(dash.web_app)
    dash._db = None
    dash._tm = None
    dash._config = None
    dash._ws_tokens.clear()


@pytest.fixture
def auth_client(db, tm):
    """创建启用认证的测试客户端"""
    import cli_anything.web.dashboard as dash
    dash._db = db
    dash._tm = tm
    mock_config = MagicMock(spec=Config)
    mock_config.get.side_effect = lambda key, default=None: {
        "dashboard.auth.enabled": True,
        "dashboard.auth.username": "admin",
        "dashboard.auth.password": "secret123",
    }.get(key, default)
    dash._config = mock_config
    yield TestClient(dash.web_app)
    dash._db = None
    dash._tm = None
    dash._config = None
    dash._ws_tokens.clear()


def _basic_auth(username: str, password: str) -> dict:
    """生成 Basic Auth header"""
    cred = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {cred}"}


class TestDashboardAuth:
    """Basic Auth 认证测试"""

    def test_no_auth_when_disabled(self, client):
        """认证禁用时应直接放行"""
        resp = client.get("/api/tasks")
        assert resp.status_code == 200

    def test_auth_required_when_enabled(self, auth_client):
        """认证启用时无凭据应返回 401"""
        resp = auth_client.get("/api/tasks")
        assert resp.status_code == 401
        assert "WWW-Authenticate" in resp.headers

    def test_auth_wrong_password(self, auth_client):
        """密码错误应返回 401"""
        resp = auth_client.get("/api/tasks", headers=_basic_auth("admin", "wrong"))
        assert resp.status_code == 401

    def test_auth_wrong_username(self, auth_client):
        """用户名错误应返回 401"""
        resp = auth_client.get("/api/tasks", headers=_basic_auth("hacker", "secret123"))
        assert resp.status_code == 401

    def test_auth_correct_credentials(self, auth_client):
        """正确凭据应放行"""
        resp = auth_client.get("/api/tasks", headers=_basic_auth("admin", "secret123"))
        assert resp.status_code == 200

    def test_ws_token_requires_auth(self, auth_client):
        """认证启用时 WebSocket token 端点也需要凭据"""
        resp = auth_client.get("/api/ws-token")
        assert resp.status_code == 401

    def test_ws_token_with_auth(self, auth_client):
        """认证通过后可获取 WebSocket token"""
        resp = auth_client.get("/api/ws-token", headers=_basic_auth("admin", "secret123"))
        assert resp.status_code == 200
        assert resp.json()["token"]

    def test_auth_invalid_base64(self, auth_client):
        """无效 Base64 应返回 401"""
        resp = auth_client.get("/api/tasks", headers={"Authorization": "Basic !!!invalid!!!"})
        assert resp.status_code == 401


class TestDashboardRESTApi:
    """Dashboard REST API 端点测试"""

    def test_get_tasks(self, client):
        """GET /api/tasks 应返回空列表"""
        resp = client.get("/api/tasks")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_tasks_with_data(self, client, tm):
        """有任务时应返回任务列表"""
        tm.create_task("测试任务1", tags=["api", "dashboard"])
        tm.create_task("测试任务2")
        resp = client.get("/api/tasks")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert all(isinstance(item["tags"], list) for item in data)

    def test_get_task_detail(self, client, tm):
        """GET /api/tasks/{id} 应返回任务详情"""
        task = tm.create_task("详情测试")
        resp = client.get(f"/api/tasks/{task.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "详情测试"

    def test_get_summary(self, client, tm):
        """GET /api/dashboard/summary 应返回统计"""
        tm.create_task("任务A")
        resp = client.get("/api/dashboard/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert "status_counts" in data

    def test_post_claim(self, client, tm):
        """POST /api/tasks/{id}/claim 应领取任务"""
        task = tm.create_task("待领取")
        resp = client.post(f"/api/tasks/{task.id}/claim")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "claimed"

    def test_post_claim_invalid(self, client, tm):
        """对非 pending 任务 claim 应返回 400"""
        task = tm.create_task("已领取")
        tm.claim_task(task.id)
        resp = client.post(f"/api/tasks/{task.id}/claim")
        assert resp.status_code == 400
        assert "error" in resp.json()

    def test_post_submit(self, client, tm):
        """POST /api/tasks/{id}/submit 应提交任务"""
        task = tm.create_task("待提交")
        tm.claim_task(task.id)
        tm.change_status(task.id, TaskStatus.IN_PROGRESS)
        resp = client.post(f"/api/tasks/{task.id}/submit")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "submitted"

    def test_post_verify_approve(self, client, tm):
        """POST /api/tasks/{id}/verify 通过验收"""
        task = tm.create_task("待验收")
        tm.claim_task(task.id)
        tm.change_status(task.id, TaskStatus.IN_PROGRESS)
        tm.submit_task(task.id)
        resp = client.post(
            f"/api/tasks/{task.id}/verify",
            json={"approved": True, "comment": "OK"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "done"

    def test_post_verify_reject(self, client, tm):
        """POST /api/tasks/{id}/verify 驳回"""
        task = tm.create_task("待验收")
        tm.claim_task(task.id)
        tm.change_status(task.id, TaskStatus.IN_PROGRESS)
        tm.submit_task(task.id)
        resp = client.post(
            f"/api/tasks/{task.id}/verify",
            json={"approved": False, "comment": "需要修改"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"

    def test_post_review(self, client, tm):
        """POST /api/tasks/{id}/review 审阅通过"""
        task = tm.create_task("草稿任务", reviewer="reviewer-1")
        assert task.status == TaskStatus.DRAFT
        resp = client.post(
            f"/api/tasks/{task.id}/review",
            json={"approved": True, "comment": "LGTM"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "pending"

    def test_post_resubmit_review(self, client, tm):
        """POST /api/tasks/{id}/resubmit-review 重新提交审阅"""
        task = tm.create_task("草稿任务", reviewer="reviewer-1")
        tm.review_task(task.id, approved=False, comment="不行")
        resp = client.post(f"/api/tasks/{task.id}/resubmit-review")
        assert resp.status_code == 200
        assert resp.json()["review_status"] == "pending_review"

    def test_homepage_returns_html(self, client):
        """GET / 应返回 HTML 页面"""
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
