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
def submitted_task(tm, tmp_path):
    """创建一个已提交的任务用于审查（work_dir 指向空临时目录，确保测试隔离）"""
    task = tm.create_task(
        title="待审查的功能实现",
        description="实现了某个功能",
        work_dir=str(tmp_path),
    )
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

    def test_round_tag_missing_raises(self, tm, submitted_task):
        """审查任务缺少 jd-round-N 标签时应报错（round=0 分支）"""
        # 直接插入一个没有 jd-round-N 标签的 REVIEW 任务
        from cli_anything.core.models import Task, TaskStatus, TaskType
        from cli_anything.core.models import _new_id, _now_iso
        broken = tm.db.insert_task(Task(
            id=_new_id(),
            title="broken review",
            description="",
            task_type=TaskType.REVIEW,
            parent_id=submitted_task.id,
            status=TaskStatus.SUBMITTED,
            tags=["jd-judge-a"],  # 故意缺少 jd-round-N
            test_report={"verdict": "clean", "findings": [], "summary": ""},
            created_at=_now_iso(),
            updated_at=_now_iso(),
        ))
        broken2 = tm.db.insert_task(Task(
            id=_new_id(),
            title="broken review b",
            description="",
            task_type=TaskType.REVIEW,
            parent_id=submitted_task.id,
            status=TaskStatus.SUBMITTED,
            tags=["jd-judge-b"],  # 同样缺少 jd-round-N
            test_report={"verdict": "clean", "findings": [], "summary": ""},
            created_at=_now_iso(),
            updated_at=_now_iso(),
        ))
        with pytest.raises(TaskManagerError, match="jd-round-N"):
            tm.synthesize_judgment(submitted_task.id)


class TestProjectStandardsInjection:
    """project_standards 注入到 judge 任务描述的测试"""

    def test_standards_appear_in_judge_descriptions(self, tm, submitted_task):
        """提供 project_standards 时，两个 judge 任务的描述都应包含该内容"""
        standards = "使用 Python 3.10+ 类型注解，禁止直接操作 DB 绕过 TaskManager"
        judge_a, judge_b = tm.trigger_judgment_day(submitted_task.id, project_standards=standards)

        assert standards in judge_a.description
        assert standards in judge_b.description
        assert "项目规范" in judge_a.description
        assert "项目规范" in judge_b.description

    def test_no_standards_no_block(self, tm, submitted_task):
        """不传 project_standards 时，judge 描述中不应出现"项目规范"块"""
        judge_a, judge_b = tm.trigger_judgment_day(submitted_task.id)

        assert "项目规范" not in judge_a.description
        assert "项目规范" not in judge_b.description

    def test_empty_string_standards_ignored(self, tm, submitted_task):
        """传入空字符串时等同于不传，不插入规范块"""
        judge_a, judge_b = tm.trigger_judgment_day(submitted_task.id, project_standards="   ")

        assert "项目规范" not in judge_a.description
        assert "项目规范" not in judge_b.description


class TestSkillRegistryAutoRead:
    """get_project_standards 文件扫描与自动注入测试"""

    def test_reads_claude_md(self, tm, tmp_path):
        """在目录中放置 CLAUDE.md 时，应返回其内容"""
        (tmp_path / "CLAUDE.md").write_text("# 项目规范\n不得直接操作 DB", encoding="utf-8")
        result = tm.get_project_standards(str(tmp_path))
        assert "不得直接操作 DB" in result

    def test_atl_skill_registry_takes_priority_over_claude_md(self, tm, tmp_path):
        """同时存在 .atl/skill-registry.md 和 CLAUDE.md 时，应优先读取前者"""
        atl_dir = tmp_path / ".atl"
        atl_dir.mkdir()
        (atl_dir / "skill-registry.md").write_text("来自 skill-registry", encoding="utf-8")
        (tmp_path / "CLAUDE.md").write_text("来自 CLAUDE.md", encoding="utf-8")
        result = tm.get_project_standards(str(tmp_path))
        assert "来自 skill-registry" in result
        assert "来自 CLAUDE.md" not in result

    def test_returns_empty_when_no_files_found(self, tm, tmp_path):
        """目录中没有任何规范文件时，应返回空字符串"""
        result = tm.get_project_standards(str(tmp_path))
        assert result == ""

    def test_content_truncated_at_4000_chars(self, tm, tmp_path):
        """内容超过 4000 字符时，应截断并追加提示"""
        long_content = "x" * 5000
        (tmp_path / "CLAUDE.md").write_text(long_content, encoding="utf-8")
        result = tm.get_project_standards(str(tmp_path))
        assert len(result) < 5000
        assert "...(内容已截断)" in result

    def test_auto_injects_when_project_standards_empty_and_work_dir_has_file(
        self, tm, tmp_path
    ):
        """trigger_judgment_day 未传 project_standards 时，应自动读取 work_dir 中的规范"""
        (tmp_path / "CLAUDE.md").write_text("自动注入的规范内容", encoding="utf-8")
        # 创建 work_dir 指向 tmp_path 的已提交任务
        task = tm.create_task(title="带工作目录的任务", work_dir=str(tmp_path))
        tm.claim_task(task.id)
        tm.start_task(task.id)
        tm.submit_task(task.id)

        judge_a, judge_b = tm.trigger_judgment_day(task.id)
        assert "自动注入的规范内容" in judge_a.description
        assert "自动注入的规范内容" in judge_b.description

    def test_manual_standards_override_auto_read(self, tm, tmp_path):
        """显式传入 project_standards 时，不应被文件内容覆盖"""
        (tmp_path / "CLAUDE.md").write_text("文件中的规范", encoding="utf-8")
        task = tm.create_task(title="任务", work_dir=str(tmp_path))
        tm.claim_task(task.id)
        tm.start_task(task.id)
        tm.submit_task(task.id)

        manual = "手动传入的规范"
        judge_a, _ = tm.trigger_judgment_day(task.id, project_standards=manual)
        assert manual in judge_a.description
        assert "文件中的规范" not in judge_a.description


class TestTaskNotes:
    """add_task_note / get_task_notes 任务上下文笔记测试"""

    def _make_task(self, tm):
        task = tm.create_task(title="带笔记的任务")
        tm.claim_task(task.id)
        tm.start_task(task.id)
        return tm.get_task(task.id)

    def test_add_note_basic(self, tm):
        """添加一条笔记后，test_report 中应包含该笔记"""
        task = self._make_task(tm)
        updated = tm.add_task_note(task.id, "发现了一个边界条件")
        notes = updated.test_report.get("task_notes", [])
        assert len(notes) == 1
        assert notes[0]["content"] == "发现了一个边界条件"
        assert notes[0]["type"] == "general"

    def test_add_note_with_type(self, tm):
        """note_type 字段应正确保存"""
        task = self._make_task(tm)
        tm.add_task_note(task.id, "决定使用 BFS", note_type="decision")
        notes = tm.get_task_notes(task.id)
        assert notes[0]["type"] == "decision"

    def test_add_multiple_notes_accumulates(self, tm):
        """多次添加笔记，应按顺序累积，不覆盖旧笔记"""
        task = self._make_task(tm)
        tm.add_task_note(task.id, "第一条笔记")
        tm.add_task_note(task.id, "第二条笔记")
        tm.add_task_note(task.id, "第三条笔记")
        notes = tm.get_task_notes(task.id)
        assert len(notes) == 3
        assert notes[0]["content"] == "第一条笔记"
        assert notes[2]["content"] == "第三条笔记"

    def test_get_task_notes_returns_empty_list_when_none(self, tm):
        """没有笔记时，get_task_notes 应返回空列表"""
        task = self._make_task(tm)
        notes = tm.get_task_notes(task.id)
        assert notes == []

    def test_add_empty_note_raises(self, tm):
        """添加空内容笔记应抛出 TaskManagerError"""
        task = self._make_task(tm)
        with pytest.raises(TaskManagerError):
            tm.add_task_note(task.id, "   ")

    def test_note_persisted_in_db(self, tm):
        """笔记应持久化，重新 get_task 后仍可读取"""
        task = self._make_task(tm)
        tm.add_task_note(task.id, "持久化测试", note_type="context")
        reloaded = tm.get_task(task.id)
        notes = reloaded.test_report.get("task_notes", [])
        assert len(notes) == 1
        assert notes[0]["content"] == "持久化测试"
        assert notes[0]["type"] == "context"



class TestSubmitEnvelopeRisks:
    """submit_task risks 字段测试"""

    def _make_inprogress(self, tm):
        task = tm.create_task(title="测试任务")
        tm.claim_task(task.id)
        tm.start_task(task.id)
        return tm.get_task(task.id)

    def test_risks_stored_in_test_report(self, tm):
        """risks 字段应存入 test_report.submit_risks"""
        task = self._make_inprogress(tm)
        result = tm.submit_task(task.id, risks="修改了 API 签名，需更新调用方")
        assert result.test_report.get("submit_risks") == "修改了 API 签名，需更新调用方"

    def test_empty_risks_not_stored(self, tm):
        """未传 risks 时，test_report 中不应有 submit_risks 键"""
        task = self._make_inprogress(tm)
        result = tm.submit_task(task.id)
        assert "submit_risks" not in result.test_report

    def test_risks_combined_with_other_envelope_fields(self, tm):
        """risks 与 summary / changed_files 可以同时存入"""
        task = self._make_inprogress(tm)
        result = tm.submit_task(
            task.id,
            summary="完成实现",
            changed_files=["src/a.py"],
            risks="无明显风险",
        )
        assert result.test_report["submit_summary"] == "完成实现"
        assert result.test_report["submit_changed_files"] == ["src/a.py"]
        assert result.test_report["submit_risks"] == "无明显风险"
