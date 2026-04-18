"""tests/test_judgment_day.py — Judgment Day 双盲对抗审查功能测试"""
import pytest
from cli_anything.core.models import TaskStatus, TaskType
from cli_anything.core.task_manager import TaskManager, TaskManagerError
from cli_anything.storage.database import Database


@pytest.fixture
def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    database.connect()
    yield database
    database.close()


@pytest.fixture
def tm(db):
    return TaskManager(db, terminal_id="test-terminal")


@pytest.fixture
def submitted_task(tm):
    """创建一个已提交的任务用于审查"""
    task = tm.create_task(title="待审查的功能实现", description="实现了某个功能")
    tm.claim_task(task.id)
    tm.start_task(task.id)
    tm.submit_task(task.id)
    return tm.get_task(task.id)


# ─────────────────────────────────────────────────────────
# TestTriggerJudgmentDay
# ─────────────────────────────────────────────────────────

class TestTriggerJudgmentDay:
    def test_normal(self, tm, submitted_task):
        """正常触发：返回两个 REVIEW 任务"""
        judge_a, judge_b = tm.trigger_judgment_day(submitted_task.id)

        assert judge_a.task_type == TaskType.REVIEW
        assert judge_b.task_type == TaskType.REVIEW
        assert judge_a.parent_id == submitted_task.id
        assert judge_b.parent_id == submitted_task.id
        assert judge_a.status == TaskStatus.PENDING
        assert judge_b.status == TaskStatus.PENDING
        assert "jd-judge-a" in judge_a.tags
        assert "jd-judge-b" in judge_b.tags
        assert "jd-round-1" in judge_a.tags
        assert "jd-round-1" in judge_b.tags

    def test_original_task_tagged(self, tm, submitted_task):
        """触发后原始任务应带有 judgment-day 和 jd-round-1 标签"""
        tm.trigger_judgment_day(submitted_task.id)
        original = tm.get_task(submitted_task.id)
        assert "judgment-day" in original.tags
        assert "jd-round-1" in original.tags

    def test_non_submitted_raises(self, tm):
        """非 submitted 状态应报错"""
        task = tm.create_task(title="未提交的任务")
        with pytest.raises(TaskManagerError, match="submitted"):
            tm.trigger_judgment_day(task.id)

    def test_active_review_raises(self, tm, submitted_task):
        """已有活跃审查任务时再次触发应报错"""
        tm.trigger_judgment_day(submitted_task.id)
        with pytest.raises(TaskManagerError, match="进行中"):
            tm.trigger_judgment_day(submitted_task.id)

    def test_round_2_after_round_1_complete(self, tm, submitted_task):
        """第 1 轮审查完成后可触发第 2 轮"""
        judge_a, judge_b = tm.trigger_judgment_day(submitted_task.id)
        # 模拟第 1 轮审查完成
        for review in [judge_a, judge_b]:
            tm.claim_task(review.id)
            tm.submit_verdict(review.id, "issues", [{"desc": "bug", "severity": "WARNING"}])

        judge_a2, judge_b2 = tm.trigger_judgment_day(submitted_task.id)
        assert "jd-round-2" in judge_a2.tags
        assert "jd-round-2" in judge_b2.tags

    def test_exceeds_max_rounds_raises(self, tm, submitted_task):
        """超过 2 轮时应报错"""
        for _ in range(2):
            a, b = tm.trigger_judgment_day(submitted_task.id)
            for review in [a, b]:
                tm.claim_task(review.id)
                tm.submit_verdict(review.id, "issues", [{"desc": "bug"}])

        with pytest.raises(TaskManagerError, match="最大审查轮次"):
            tm.trigger_judgment_day(submitted_task.id)


# ─────────────────────────────────────────────────────────
# TestSubmitVerdict
# ─────────────────────────────────────────────────────────

class TestSubmitVerdict:
    def test_clean_verdict(self, tm, submitted_task):
        """提交 clean 裁决"""
        judge_a, _ = tm.trigger_judgment_day(submitted_task.id)
        tm.claim_task(judge_a.id)
        result = tm.submit_verdict(judge_a.id, "clean", summary="代码质量良好")
        assert result.status == TaskStatus.SUBMITTED
        assert result.test_report["verdict"] == "clean"
        assert result.test_report["summary"] == "代码质量良好"
        assert result.test_report["findings"] == []

    def test_issues_verdict_with_findings(self, tm, submitted_task):
        """提交 issues 裁决，带 findings"""
        judge_a, _ = tm.trigger_judgment_day(submitted_task.id)
        tm.claim_task(judge_a.id)
        findings = [
            {"desc": "空指针未处理", "severity": "CRITICAL", "location": "main.py:42"},
            {"desc": "命名不规范", "severity": "SUGGESTION", "location": "utils.py:10"},
        ]
        result = tm.submit_verdict(judge_a.id, "issues", findings=findings, summary="发现2个问题")
        assert result.status == TaskStatus.SUBMITTED
        assert result.test_report["verdict"] == "issues"
        assert len(result.test_report["findings"]) == 2

    def test_auto_start_from_claimed(self, tm, submitted_task):
        """CLAIMED 状态下调用 submit_verdict 应自动过渡"""
        judge_a, _ = tm.trigger_judgment_day(submitted_task.id)
        tm.claim_task(judge_a.id)
        assert tm.get_task(judge_a.id).status == TaskStatus.CLAIMED
        result = tm.submit_verdict(judge_a.id, "clean")
        assert result.status == TaskStatus.SUBMITTED

    def test_in_progress_allowed(self, tm, submitted_task):
        """IN_PROGRESS 状态下也可以提交"""
        judge_a, _ = tm.trigger_judgment_day(submitted_task.id)
        tm.claim_task(judge_a.id)
        tm.start_task(judge_a.id)
        result = tm.submit_verdict(judge_a.id, "clean")
        assert result.status == TaskStatus.SUBMITTED

    def test_non_review_type_raises(self, tm, submitted_task):
        """非 review 类型任务不能提交裁决"""
        with pytest.raises(TaskManagerError, match="review 类型"):
            tm.submit_verdict(submitted_task.id, "clean")

    def test_invalid_verdict_raises(self, tm, submitted_task):
        """非法 verdict 值应报错"""
        judge_a, _ = tm.trigger_judgment_day(submitted_task.id)
        tm.claim_task(judge_a.id)
        with pytest.raises(TaskManagerError, match="verdict"):
            tm.submit_verdict(judge_a.id, "maybe")

    def test_pending_status_raises(self, tm, submitted_task):
        """PENDING 状态不能直接提交裁决（必须先 claim）"""
        judge_a, _ = tm.trigger_judgment_day(submitted_task.id)
        with pytest.raises(TaskManagerError, match="claimed 或 in_progress"):
            tm.submit_verdict(judge_a.id, "clean")


# ─────────────────────────────────────────────────────────
# TestGetReviewTasks
# ─────────────────────────────────────────────────────────

class TestGetReviewTasks:
    def test_returns_empty_before_judgment_day(self, tm, submitted_task):
        result = tm.get_review_tasks(submitted_task.id)
        assert result == []

    def test_returns_two_after_trigger(self, tm, submitted_task):
        tm.trigger_judgment_day(submitted_task.id)
        reviews = tm.get_review_tasks(submitted_task.id)
        assert len(reviews) == 2
        assert all(t.task_type == TaskType.REVIEW for t in reviews)

    def test_returns_four_after_two_rounds(self, tm, submitted_task):
        for _ in range(2):
            a, b = tm.trigger_judgment_day(submitted_task.id)
            for r in [a, b]:
                tm.claim_task(r.id)
                tm.submit_verdict(r.id, "issues", [{"desc": "bug"}])
        reviews = tm.get_review_tasks(submitted_task.id)
        assert len(reviews) == 4


# ─────────────────────────────────────────────────────────
# TestSynthesizeJudgment
# ─────────────────────────────────────────────────────────

def _complete_round(tm, submitted_task, verdict_a, findings_a, verdict_b, findings_b):
    """辅助函数：触发并完成一轮审查"""
    judge_a, judge_b = tm.trigger_judgment_day(submitted_task.id)
    tm.claim_task(judge_a.id)
    tm.submit_verdict(judge_a.id, verdict_a, findings_a)
    tm.claim_task(judge_b.id)
    tm.submit_verdict(judge_b.id, verdict_b, findings_b)


class TestSynthesizeJudgment:
    def test_both_clean_gives_approve(self, tm, submitted_task):
        """双方都 clean → recommendation = approve"""
        _complete_round(tm, submitted_task, "clean", [], "clean", [])
        result = tm.synthesize_judgment(submitted_task.id)
        assert result["both_clean"] is True
        assert result["recommendation"] == "approve"

    def test_confirmed_issues(self, tm, submitted_task):
        """两方都发现同一问题 → confirmed 列表有该问题"""
        shared_finding = {"desc": "空指针未处理", "severity": "CRITICAL"}
        _complete_round(
            tm, submitted_task,
            "issues", [shared_finding],
            "issues", [shared_finding],
        )
        result = tm.synthesize_judgment(submitted_task.id)
        assert len(result["confirmed"]) == 1
        assert result["suspect_a"] == []
        assert result["suspect_b"] == []
        assert result["recommendation"] == "fix"

    def test_suspect_a_only(self, tm, submitted_task):
        """只有 Judge A 发现问题 → suspect_a 有，suspect_b 空"""
        _complete_round(
            tm, submitted_task,
            "issues", [{"desc": "潜在内存泄漏", "severity": "WARNING"}],
            "clean", [],
        )
        result = tm.synthesize_judgment(submitted_task.id)
        assert len(result["suspect_a"]) == 1
        assert result["suspect_b"] == []
        assert result["confirmed"] == []
        assert result["recommendation"] == "fix"

    def test_suspect_b_only(self, tm, submitted_task):
        """只有 Judge B 发现问题 → suspect_b 有，suspect_a 空"""
        _complete_round(
            tm, submitted_task,
            "clean", [],
            "issues", [{"desc": "日志记录不完整", "severity": "SUGGESTION"}],
        )
        result = tm.synthesize_judgment(submitted_task.id)
        assert len(result["suspect_b"]) == 1
        assert result["suspect_a"] == []

    def test_escalated_on_round_2(self, tm, submitted_task):
        """第 2 轮有问题 → recommendation = escalated"""
        for _ in range(2):
            a, b = tm.trigger_judgment_day(submitted_task.id)
            tm.claim_task(a.id)
            tm.submit_verdict(a.id, "issues", [{"desc": "严重 bug"}])
            tm.claim_task(b.id)
            tm.submit_verdict(b.id, "issues", [{"desc": "严重 bug"}])
        result = tm.synthesize_judgment(submitted_task.id)
        assert result["recommendation"] == "escalated"
        assert result["round"] == 2

    def test_no_reviews_raises(self, tm, submitted_task):
        """没有审查任务时应报错"""
        with pytest.raises(TaskManagerError, match="没有任何审查任务"):
            tm.synthesize_judgment(submitted_task.id)

    def test_pending_reviews_raises(self, tm, submitted_task):
        """审查任务尚未全部提交时应报错"""
        judge_a, judge_b = tm.trigger_judgment_day(submitted_task.id)
        tm.claim_task(judge_a.id)
        tm.submit_verdict(judge_a.id, "clean")
        # judge_b 仍在 pending
        with pytest.raises(TaskManagerError, match="尚未完成"):
            tm.synthesize_judgment(submitted_task.id)

    def test_result_contains_judge_info(self, tm, submitted_task):
        """综合结果应包含 judge_a 和 judge_b 的详细信息"""
        _complete_round(tm, submitted_task, "clean", [], "clean", [])
        result = tm.synthesize_judgment(submitted_task.id)
        assert "judge_a" in result
        assert "judge_b" in result
        assert result["judge_a"]["verdict"] == "clean"
        assert result["judge_b"]["verdict"] == "clean"
        assert result["round"] == 1
