"""TaskManager Core 单元测试"""

import os
import tempfile
import pytest

from cli_anything.core.models import (
    Task, TaskStatus, TaskType, TestStatus, TerminalRole, Terminal
)
from cli_anything.storage.database import Database
from cli_anything.core.task_manager import TaskManager, TaskManagerError


@pytest.fixture
def db(tmp_path):
    """创建临时数据库"""
    db_path = str(tmp_path / "test.db")
    database = Database(db_path)
    database.connect()
    yield database
    database.close()


@pytest.fixture
def tm(db):
    """创建 TaskManager 实例"""
    return TaskManager(db, terminal_id="test-terminal")


class TestCreateTask:
    def test_create_basic(self, tm):
        task = tm.create_task("测试任务", "描述")
        assert task.title == "测试任务"
        assert task.description == "描述"
        assert task.status == TaskStatus.PENDING
        assert task.task_type == TaskType.MASTER

    def test_create_with_priority(self, tm):
        task = tm.create_task("高优先级", priority=1)
        assert task.priority == 1

    def test_create_with_tags(self, tm):
        task = tm.create_task("带标签", tags=["bug", "urgent"])
        assert task.tags == ["bug", "urgent"]

    def test_create_empty_title_raises(self, tm):
        with pytest.raises(TaskManagerError, match="标题不能为空"):
            tm.create_task("")

    def test_create_invalid_priority_raises(self, tm):
        with pytest.raises(TaskManagerError, match="优先级"):
            tm.create_task("任务", priority=6)


class TestDecompose:
    def test_decompose_basic(self, tm):
        parent = tm.create_task("主任务")
        subs = tm.decompose_task(parent.id, [
            {"title": "子任务1", "description": "desc1"},
            {"title": "子任务2", "description": "desc2"},
        ])
        assert len(subs) == 2
        assert all(s.task_type == TaskType.SUBTASK for s in subs)
        assert all(s.parent_id == parent.id for s in subs)

    def test_decompose_non_master_raises(self, tm):
        parent = tm.create_task("主任务")
        subs = tm.decompose_task(parent.id, [{"title": "子"}])
        with pytest.raises(TaskManagerError, match="主任务"):
            tm.decompose_task(subs[0].id, [{"title": "不行"}])


class TestClaimUnclaim:
    def test_claim_and_unclaim(self, tm):
        task = tm.create_task("待领取")
        claimed = tm.claim_task(task.id)
        assert claimed.status == TaskStatus.CLAIMED
        assert claimed.claimed_by == "test-terminal"

        unclaimed = tm.unclaim_task(task.id)
        assert unclaimed.status == TaskStatus.PENDING
        assert unclaimed.claimed_by is None

    def test_claim_non_pending_raises(self, tm):
        task = tm.create_task("任务")
        tm.claim_task(task.id)
        with pytest.raises(TaskManagerError, match="pending"):
            tm.claim_task(task.id)

    def test_unclaim_by_other_terminal_raises(self, tm, db):
        task = tm.create_task("任务")
        tm.claim_task(task.id)
        other_tm = TaskManager(db, terminal_id="other-terminal")
        with pytest.raises(TaskManagerError, match="自己"):
            other_tm.unclaim_task(task.id)


class TestStatusTransitions:
    def test_full_workflow(self, tm):
        """pending → claimed → in_progress → submitted → done"""
        task = tm.create_task("完整流程")
        tm.claim_task(task.id)
        tm.start_task(task.id)
        tm.submit_task(task.id)

        result = tm.verify_task(task.id, approved=True, comment="好的")
        assert result.status == TaskStatus.DONE
        assert result.verify_comment == "好的"

    def test_reject_and_resubmit(self, tm):
        """submitted → rejected → in_progress → submitted → done"""
        task = tm.create_task("驳回流程")
        tm.claim_task(task.id)
        tm.start_task(task.id)
        tm.submit_task(task.id)

        rejected = tm.verify_task(task.id, approved=False, comment="需要修改")
        assert rejected.status == TaskStatus.REJECTED

        tm.start_task(task.id)
        tm.submit_task(task.id)
        done = tm.verify_task(task.id, approved=True, comment="通过")
        assert done.status == TaskStatus.DONE

    def test_invalid_transition_raises(self, tm):
        task = tm.create_task("测试")
        with pytest.raises(TaskManagerError, match="不能从"):
            tm.change_status(task.id, TaskStatus.DONE)


class TestProgress:
    def test_progress_calculation(self, tm):
        parent = tm.create_task("主任务")
        subs = tm.decompose_task(parent.id, [
            {"title": f"子{i}"} for i in range(4)
        ])
        # 完成 2 个子任务
        for s in subs[:2]:
            tm.claim_task(s.id)
            tm.start_task(s.id)
            tm.submit_task(s.id)
            tm.verify_task(s.id, approved=True)

        progress = tm.get_progress(parent.id)
        assert progress["total"] == 4
        assert progress["done"] == 2
        assert progress["progress"] == 50.0


class TestUpdateDelete:
    def test_update_task(self, tm):
        task = tm.create_task("原标题")
        updated = tm.update_task(task.id, title="新标题", priority=1)
        assert updated.title == "新标题"
        assert updated.priority == 1

    def test_delete_task(self, tm):
        task = tm.create_task("待删除")
        assert tm.delete_task(task.id) is True
        assert tm.get_task(task.id) is None


class TestLogs:
    def test_logs_recorded(self, tm):
        task = tm.create_task("日志测试")
        tm.claim_task(task.id)
        logs = tm.get_logs(task.id)
        assert len(logs) >= 2
        actions = [l.action for l in logs]
        assert "created" in actions
        assert "claimed" in actions


class TestTerminal:
    def test_register_terminal(self, tm):
        t = Terminal(id="t1", name="主终端", role=TerminalRole.MASTER, type="powershell")
        tm.register_terminal(t)
        terminals = tm.list_terminals()
        assert len(terminals) == 1
        assert terminals[0].name == "主终端"


class TestTestResult:
    def test_update_test_result(self, tm):
        task = tm.create_task("测试任务")
        report = {"total": 10, "passed": 8, "failed": 2}
        updated = tm.update_test_result(task.id, TestStatus.FAILED, report)
        assert updated.test_status == TestStatus.FAILED
        assert updated.test_report["passed"] == 8
