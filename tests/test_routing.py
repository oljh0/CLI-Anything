"""P4 Supervisor 自动路由 测试"""
import pytest
from cli_anything.core.task_manager import TaskManager, TaskManagerError
from cli_anything.core.models import Terminal, TerminalRole
from cli_anything.storage.database import Database


@pytest.fixture
def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    database.connect()
    yield database
    database.close()


@pytest.fixture
def tm(db):
    mgr = TaskManager(db, terminal_id="master-1")
    mgr.register_terminal(Terminal(id="master-1", name="Master", role=TerminalRole.MASTER))
    return mgr


def _register_worker(tm, tid, caps=None):
    tm.register_terminal(Terminal(id=tid, name=tid, role=TerminalRole.WORKER))
    if caps:
        tm.update_capabilities(tid, caps)
    return tid


def _make_task(tm, title="Task", tags=None, priority=3):
    return tm.create_task(title=title, description="desc", tags=tags or [], priority=priority)


# ── TestUpdateCapabilities ──────────────────────────────────────

class TestUpdateCapabilities:
    def test_normal_register(self, tm):
        _register_worker(tm, "w1", ["python", "backend"])
        terminal = tm.db.get_terminal("w1")
        assert terminal.capabilities == ["python", "backend"]

    def test_update_overwrites(self, tm):
        _register_worker(tm, "w1", ["python"])
        tm.update_capabilities("w1", ["java", "frontend"])
        terminal = tm.db.get_terminal("w1")
        assert terminal.capabilities == ["java", "frontend"]

    def test_clear_capabilities(self, tm):
        _register_worker(tm, "w1", ["python"])
        tm.update_capabilities("w1", [])
        terminal = tm.db.get_terminal("w1")
        assert terminal.capabilities == []

    def test_nonexistent_terminal_raises(self, tm):
        with pytest.raises(TaskManagerError, match="不存在"):
            tm.update_capabilities("ghost", ["python"])


# ── TestSuggestTasks ──────────────────────────────────────────

class TestSuggestTasks:
    def test_empty_caps_returns_all(self, tm):
        """capabilities 为空时返回所有 pending 任务"""
        _register_worker(tm, "w1")
        _make_task(tm, "T1", tags=["python"])
        _make_task(tm, "T2", tags=["java"])
        result = tm.suggest_tasks("w1")
        assert len(result) == 2

    def test_with_caps_filters_by_tag(self, tm):
        """capabilities 非空时只返回有交集 tag 的任务"""
        _register_worker(tm, "w1", ["python"])
        _make_task(tm, "T-python", tags=["python"])
        _make_task(tm, "T-java", tags=["java"])
        result = tm.suggest_tasks("w1")
        assert len(result) == 1
        assert result[0].title == "T-python"

    def test_fallback_when_no_match(self, tm):
        """有 capabilities 但无匹配任务时 fallback 返回全量"""
        _register_worker(tm, "w1", ["rust"])
        _make_task(tm, "T1", tags=["python"])
        _make_task(tm, "T2", tags=["java"])
        result = tm.suggest_tasks("w1")
        assert len(result) == 2

    def test_sorted_by_priority(self, tm):
        """返回结果按优先级升序（1 = 最高）"""
        _register_worker(tm, "w1")
        _make_task(tm, "Low", priority=5)
        _make_task(tm, "High", priority=1)
        _make_task(tm, "Mid", priority=3)
        result = tm.suggest_tasks("w1")
        assert [t.priority for t in result] == [1, 3, 5]

    def test_limit_respected(self, tm):
        _register_worker(tm, "w1")
        for i in range(5):
            _make_task(tm, f"T{i}")
        result = tm.suggest_tasks("w1", limit=3)
        assert len(result) == 3

    def test_nonexistent_terminal_raises(self, tm):
        with pytest.raises(TaskManagerError, match="不存在"):
            tm.suggest_tasks("ghost")

    def test_only_pending_returned(self, tm):
        """只返回 pending 状态的任务，其他状态过滤掉"""
        _register_worker(tm, "w1")
        t = _make_task(tm, "T1")
        tm.claim_task(t.id)  # → claimed
        _make_task(tm, "T2")  # pending
        result = tm.suggest_tasks("w1")
        assert len(result) == 1
        assert result[0].title == "T2"


# ── TestRouteTask ────────────────────────────────────────────

class TestRouteTask:
    def test_no_tags_returns_all_workers(self, tm):
        """任务无 tag 时返回所有 Worker 终端"""
        _register_worker(tm, "w1", ["python"])
        _register_worker(tm, "w2", ["java"])
        task = _make_task(tm, tags=[])
        result = tm.route_task(task.id)
        ids = {r["terminal_id"] for r in result}
        assert ids == {"w1", "w2"}

    def test_tag_filters_workers(self, tm):
        """任务有 tag 时只返回 capabilities 有交集的 Worker"""
        _register_worker(tm, "w-py", ["python", "backend"])
        _register_worker(tm, "w-java", ["java"])
        task = _make_task(tm, tags=["python"])
        result = tm.route_task(task.id)
        assert len(result) == 1
        assert result[0]["terminal_id"] == "w-py"
        assert "python" in result[0]["matched_tags"]

    def test_no_matching_worker(self, tm):
        """无 capabilities 匹配时返回空列表"""
        _register_worker(tm, "w1", ["java"])
        task = _make_task(tm, tags=["rust"])
        result = tm.route_task(task.id)
        assert result == []

    def test_master_not_included(self, tm):
        """Master 终端不应出现在候选中"""
        task = _make_task(tm, tags=[])
        result = tm.route_task(task.id)
        roles = {r["role"] for r in result}
        assert "master" not in roles

    def test_nonexistent_task_raises(self, tm):
        with pytest.raises(TaskManagerError):
            tm.route_task("ghost-task-id")
