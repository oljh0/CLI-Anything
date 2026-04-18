"""TaskManager Core 单元测试"""

import os
import tempfile
import pytest

from cli_anything.core.models import (
    Task, TaskStatus, TaskType, TestStatus, ReviewStatus, TerminalRole, Terminal
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


class TestReviewWorkflow:
    """审阅流程测试"""

    def test_create_with_review_enters_draft(self, tm):
        """指定审阅者时，任务初始状态为 draft"""
        task = tm.create_task("待审阅任务", reviewer="reviewer-1")
        assert task.status == TaskStatus.DRAFT
        assert task.reviewer == "reviewer-1"
        assert task.review_status == ReviewStatus.PENDING

    def test_create_without_review_enters_pending(self, tm):
        """不指定审阅者时，任务直接进入 pending"""
        task = tm.create_task("普通任务")
        assert task.status == TaskStatus.PENDING
        assert task.review_status == ReviewStatus.NOT_REQUIRED

    def test_review_approve(self, tm):
        """审阅通过：draft → pending"""
        task = tm.create_task("待审阅", reviewer="reviewer-1")
        reviewed = tm.review_task(task.id, approved=True, comment="看起来不错")
        assert reviewed.status == TaskStatus.PENDING
        assert reviewed.review_status == ReviewStatus.APPROVED
        assert reviewed.review_comment == "看起来不错"

    def test_review_reject(self, tm):
        """审阅驳回：保持 draft，标记 rejected"""
        task = tm.create_task("待审阅", reviewer="reviewer-1")
        reviewed = tm.review_task(task.id, approved=False, comment="描述不清楚")
        assert reviewed.status == TaskStatus.DRAFT
        assert reviewed.review_status == ReviewStatus.REJECTED
        assert reviewed.review_comment == "描述不清楚"

    def test_review_non_draft_raises(self, tm):
        """审阅非 draft 状态的任务应抛异常"""
        task = tm.create_task("普通任务")
        with pytest.raises(TaskManagerError, match="draft"):
            tm.review_task(task.id, approved=True)

    def test_review_not_required_raises(self, tm):
        """审阅未要求审阅的任务应抛异常"""
        task = tm.create_task("普通任务")
        # 强制改为 draft 但 review_status 是 NOT_REQUIRED
        task.status = TaskStatus.DRAFT
        tm.db.update_task(task)
        with pytest.raises(TaskManagerError, match="未要求审阅"):
            tm.review_task(task.id, approved=True)

    def test_resubmit_for_review(self, tm):
        """驳回后重新提交审阅"""
        task = tm.create_task("待审阅", reviewer="reviewer-1")
        tm.review_task(task.id, approved=False, comment="需要改进")
        resubmitted = tm.resubmit_for_review(task.id)
        assert resubmitted.review_status == ReviewStatus.PENDING
        assert resubmitted.review_comment == ""

    def test_resubmit_with_new_reviewer(self, tm):
        """重新提交时更换审阅者"""
        task = tm.create_task("待审阅", reviewer="reviewer-1")
        tm.review_task(task.id, approved=False)
        resubmitted = tm.resubmit_for_review(task.id, reviewer="reviewer-2")
        assert resubmitted.reviewer == "reviewer-2"
        assert resubmitted.review_status == ReviewStatus.PENDING

    def test_resubmit_non_rejected_raises(self, tm):
        """只有被驳回的任务才能重新提交审阅"""
        task = tm.create_task("待审阅", reviewer="reviewer-1")
        with pytest.raises(TaskManagerError, match="驳回"):
            tm.resubmit_for_review(task.id)

    def test_full_review_then_claim_workflow(self, tm):
        """完整流程：创建(draft) → 审阅通过(pending) → 领取(claimed)"""
        task = tm.create_task("需审阅的任务", reviewer="reviewer-1")
        assert task.status == TaskStatus.DRAFT

        # 审阅通过
        task = tm.review_task(task.id, approved=True, comment="OK")
        assert task.status == TaskStatus.PENDING

        # 领取
        task = tm.claim_task(task.id)
        assert task.status == TaskStatus.CLAIMED

    def test_decompose_with_review(self, tm):
        """拆解子任务时指定审阅者"""
        parent = tm.create_task("主任务")
        subtasks = tm.decompose_task(parent.id, [
            {"title": "子任务1"}, {"title": "子任务2"}
        ], reviewer="reviewer-1")

        for s in subtasks:
            assert s.status == TaskStatus.DRAFT
            assert s.reviewer == "reviewer-1"
            assert s.review_status == ReviewStatus.PENDING

    def test_draft_cannot_be_claimed(self, tm):
        """draft 状态的任务不能被领取"""
        task = tm.create_task("草稿任务", reviewer="reviewer-1")
        with pytest.raises(TaskManagerError, match="pending"):
            tm.claim_task(task.id)


class TestSubmitEnvelope:
    """P1 结构化提交信封测试"""

    @pytest.fixture
    def in_progress_task(self, tm):
        task = tm.create_task(title="实现登录模块")
        tm.claim_task(task.id)
        tm.start_task(task.id)
        return tm.get_task(task.id)

    def test_submit_without_envelope(self, tm, in_progress_task):
        """不带信封的提交，行为与以前相同"""
        result = tm.submit_task(in_progress_task.id)
        assert result.status == TaskStatus.SUBMITTED

    def test_submit_with_summary(self, tm, in_progress_task):
        """带 summary 的提交，存入 test_report"""
        result = tm.submit_task(in_progress_task.id, summary="实现了 JWT 登录")
        assert result.test_report["submit_summary"] == "实现了 JWT 登录"

    def test_submit_with_changed_files(self, tm, in_progress_task):
        """带 changed_files 的提交"""
        files = ["src/auth.py", "tests/test_auth.py"]
        result = tm.submit_task(in_progress_task.id, changed_files=files)
        assert result.test_report["submit_changed_files"] == files

    def test_submit_with_test_note(self, tm, in_progress_task):
        """带 test_note 的提交"""
        result = tm.submit_task(in_progress_task.id, test_note="全部 15 个测试通过")
        assert result.test_report["submit_test_note"] == "全部 15 个测试通过"

    def test_envelope_merges_with_existing_test_report(self, tm, in_progress_task):
        """信封与 TestRunner 已有数据合并，不覆盖"""
        from cli_anything.core.models import TestStatus
        tm.update_test_result(in_progress_task.id, TestStatus.PASSED, {"total": 10, "passed": 10})
        result = tm.submit_task(in_progress_task.id, summary="功能完成")
        r = result.test_report
        assert r["total"] == 10
        assert r["submit_summary"] == "功能完成"

    def test_empty_envelope_not_written(self, tm, in_progress_task):
        """空值不写入 test_report"""
        result = tm.submit_task(in_progress_task.id, summary="", changed_files=None, test_note="")
        assert (result.test_report or {}).get("submit_summary") is None
