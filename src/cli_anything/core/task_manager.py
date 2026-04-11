"""TaskManager Core — 任务全生命周期管理"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from cli_anything.core.models import (
    Task,
    TaskLog,
    Terminal,
    TaskStatus,
    TaskType,
    TestStatus,
    ReviewStatus,
    TerminalRole,
    VALID_TRANSITIONS,
    _new_id,
    _now_iso,
)
from cli_anything.storage.database import Database


class TaskManagerError(Exception):
    """TaskManager 业务异常"""


class TaskManager:
    """任务管理核心，所有业务逻辑的入口"""

    def __init__(self, db: Database, terminal_id: str = "", notifier=None):
        self.db = db
        self.terminal_id = terminal_id
        self._notifier = notifier

    def _notify_status_change(self, task: "Task", old_status: str, new_status: str):
        """通知状态变更（如果 Notifier 已配置）"""
        if self._notifier:
            self._notifier.on_status_change(task.id, old_status, new_status, task.title)

    def _notify_submit(self, task: "Task"):
        if self._notifier:
            self._notifier.on_submit(task.id, task.title, self.terminal_id)

    def _notify_verify(self, task: "Task", approved: bool, comment: str):
        if self._notifier:
            self._notifier.on_verify(task.id, task.title, approved, comment)

    # ── 任务创建 ───────────────────────────────────────────

    def create_task(
        self,
        title: str,
        description: str = "",
        priority: int = 3,
        tags: Optional[list[str]] = None,
        task_type: TaskType = TaskType.MASTER,
        parent_id: Optional[str] = None,
        reviewer: Optional[str] = None,
    ) -> Task:
        """创建新任务

        Args:
            reviewer: 审阅者终端 ID，指定后任务进入 draft 状态等待审阅
        """
        if not title.strip():
            raise TaskManagerError("任务标题不能为空")
        if priority < 1 or priority > 5:
            raise TaskManagerError("优先级必须在 1-5 之间")
        if parent_id:
            parent = self.db.get_task(parent_id)
            if not parent:
                raise TaskManagerError(f"父任务 {parent_id} 不存在")

        # 如果指定审阅者，初始状态为 draft
        initial_status = TaskStatus.DRAFT if reviewer else TaskStatus.PENDING
        review_status = ReviewStatus.PENDING if reviewer else ReviewStatus.NOT_REQUIRED

        task = Task(
            title=title.strip(),
            description=description.strip(),
            priority=priority,
            tags=tags or [],
            task_type=task_type,
            parent_id=parent_id,
            created_by=self.terminal_id,
            status=initial_status,
            reviewer=reviewer,
            review_status=review_status,
        )
        self.db.insert_task(task)
        detail = f"创建任务: {title}"
        if reviewer:
            detail += f"（待 {reviewer} 审阅）"
        self._log(task.id, "created", detail=detail)
        return task

    # ── 任务拆解 ───────────────────────────────────────────

    def decompose_task(
        self,
        parent_id: str,
        subtasks: list[dict],
        reviewer: Optional[str] = None,
    ) -> list[Task]:
        """将主任务拆解为子任务

        Args:
            parent_id: 父任务 ID
            subtasks: 子任务列表，每项为 {"title": str, "description": str, ...}
            reviewer: 审阅者终端 ID，指定后子任务进入 draft 状态

        Returns:
            创建的子任务列表
        """
        parent = self._get_or_raise(parent_id)
        if parent.task_type != TaskType.MASTER:
            raise TaskManagerError("只有主任务可以拆解")

        results = []
        for sub in subtasks:
            child = self.create_task(
                title=sub.get("title", ""),
                description=sub.get("description", ""),
                priority=sub.get("priority", parent.priority),
                tags=sub.get("tags", parent.tags.copy()),
                task_type=TaskType.SUBTASK,
                parent_id=parent_id,
                reviewer=reviewer,
            )
            results.append(child)

        self._log(parent_id, "decomposed", detail=f"拆解为 {len(results)} 个子任务")
        return results

    # ── 任务领取/释放 ──────────────────────────────────────

    def claim_task(self, task_id: str) -> Task:
        """领取任务"""
        task = self._get_or_raise(task_id)
        if task.status != TaskStatus.PENDING:
            raise TaskManagerError(f"只能领取 pending 状态的任务，当前状态: {task.status.value}")

        task.status = TaskStatus.CLAIMED
        task.claimed_by = self.terminal_id
        task.claimed_at = _now_iso()
        self.db.update_task(task)
        self._log(task_id, "claimed", detail=f"终端 {self.terminal_id} 领取任务")
        return task

    def unclaim_task(self, task_id: str) -> Task:
        """释放已领取的任务"""
        task = self._get_or_raise(task_id)
        if task.status != TaskStatus.CLAIMED:
            raise TaskManagerError("只能释放 claimed 状态的任务")
        if task.claimed_by != self.terminal_id:
            raise TaskManagerError("只能释放自己领取的任务")

        old_claimed = task.claimed_by
        task.status = TaskStatus.PENDING
        task.claimed_by = None
        task.claimed_at = None
        self.db.update_task(task)
        self._log(task_id, "unclaimed", detail=f"终端 {old_claimed} 释放任务")
        return task

    # ── 状态变更 ───────────────────────────────────────────

    def change_status(self, task_id: str, new_status: TaskStatus) -> Task:
        """变更任务状态（通用，遵循状态机）"""
        task = self._get_or_raise(task_id)
        old_status = task.status

        if not task.can_transition_to(new_status):
            allowed = [s.value for s in VALID_TRANSITIONS.get(old_status, set())]
            raise TaskManagerError(
                f"不能从 {old_status.value} 转为 {new_status.value}。"
                f"允许的状态: {', '.join(allowed) if allowed else '无（终态）'}"
            )

        task.status = new_status
        self.db.update_task(task)
        self._log(
            task_id,
            "status_changed",
            old_value=old_status.value,
            new_value=new_status.value,
        )
        self._notify_status_change(task, old_status.value, new_status.value)
        return task

    def start_task(self, task_id: str) -> Task:
        """开始工作（claimed → in_progress）"""
        task = self._get_or_raise(task_id)
        if task.status not in (TaskStatus.CLAIMED, TaskStatus.REJECTED):
            raise TaskManagerError(
                f"只能从 claimed/rejected 状态开始工作，当前: {task.status.value}"
            )
        return self.change_status(task_id, TaskStatus.IN_PROGRESS)

    def submit_task(self, task_id: str) -> Task:
        """提交任务（in_progress → submitted）"""
        task = self._get_or_raise(task_id)
        if task.status != TaskStatus.IN_PROGRESS:
            raise TaskManagerError("只能提交 in_progress 状态的任务")

        task.status = TaskStatus.SUBMITTED
        task.submitted_at = _now_iso()
        self.db.update_task(task)
        self._log(task_id, "submitted", detail="任务已提交待审核")
        self._notify_submit(task)
        return task

    # ── 审核验收 ───────────────────────────────────────────

    def verify_task(self, task_id: str, approved: bool, comment: str = "") -> Task:
        """主终端验收任务

        Args:
            task_id: 任务 ID
            approved: True=通过(→done), False=驳回(→rejected)
            comment: 验收意见
        """
        task = self._get_or_raise(task_id)
        if task.status != TaskStatus.SUBMITTED:
            raise TaskManagerError("只能验收 submitted 状态的任务")

        task.verified_by = self.terminal_id
        task.verified_at = _now_iso()
        task.verify_comment = comment

        if approved:
            task.status = TaskStatus.DONE
            self.db.update_task(task)
            self._log(task_id, "verified", detail=f"验收通过: {comment}")
        else:
            task.status = TaskStatus.REJECTED
            self.db.update_task(task)
            self._log(task_id, "rejected", detail=f"验收驳回: {comment}")

        self._notify_verify(task, approved, comment)
        return task

    # ── 审阅 ────────────────────────────────────────────────

    def review_task(self, task_id: str, approved: bool, comment: str = "") -> Task:
        """审阅任务定义

        Args:
            task_id: 任务 ID
            approved: True=通过(draft→pending), False=驳回(保持 draft，标记 rejected)
            comment: 审阅意见
        """
        task = self._get_or_raise(task_id)
        if task.status != TaskStatus.DRAFT:
            raise TaskManagerError("只能审阅 draft 状态的任务")
        if task.review_status != ReviewStatus.PENDING:
            raise TaskManagerError("该任务未要求审阅或已审阅完成")

        task.review_comment = comment

        if approved:
            task.status = TaskStatus.PENDING
            task.review_status = ReviewStatus.APPROVED
            self.db.update_task(task)
            self._log(task_id, "review_approved", detail=f"审阅通过: {comment}")
        else:
            task.review_status = ReviewStatus.REJECTED
            self.db.update_task(task)
            self._log(task_id, "review_rejected", detail=f"审阅驳回: {comment}")

        return task

    def resubmit_for_review(self, task_id: str, reviewer: Optional[str] = None) -> Task:
        """重新提交审阅（审阅被驳回后修改再提交）

        Args:
            task_id: 任务 ID
            reviewer: 新的审阅者（可选，留空沿用原审阅者）
        """
        task = self._get_or_raise(task_id)
        if task.status != TaskStatus.DRAFT:
            raise TaskManagerError("只能重新提交 draft 状态的任务")
        if task.review_status != ReviewStatus.REJECTED:
            raise TaskManagerError("只能重新提交被驳回的任务")

        if reviewer:
            task.reviewer = reviewer
        task.review_status = ReviewStatus.PENDING
        task.review_comment = ""
        self.db.update_task(task)
        self._log(task_id, "review_resubmitted", detail=f"重新提交审阅（审阅者: {task.reviewer}）")
        return task

    # ── 测试相关 ───────────────────────────────────────────

    def update_test_result(
        self,
        task_id: str,
        test_status: TestStatus,
        test_report: Optional[dict] = None,
    ) -> Task:
        """更新任务的测试结果"""
        task = self._get_or_raise(task_id)
        old_ts = task.test_status.value
        task.test_status = test_status
        if test_report is not None:
            task.test_report = test_report
        self.db.update_task(task)
        self._log(
            task_id,
            "test_run",
            old_value=old_ts,
            new_value=test_status.value,
            detail=f"测试结果: {test_status.value}",
        )
        return task

    # ── 查询 ──────────────────────────────────────────────

    def get_task(self, task_id: str) -> Optional[Task]:
        """获取任务"""
        return self.db.get_task(task_id)

    def list_tasks(self, **kwargs) -> list[Task]:
        """列出任务，支持过滤"""
        return self.db.list_tasks(**kwargs)

    def list_subtasks(self, parent_id: str) -> list[Task]:
        """列出子任务"""
        return self.db.list_tasks(parent_id=parent_id)

    def get_progress(self, parent_id: str) -> dict:
        """获取主任务的进度统计"""
        counts = self.db.count_subtasks_by_status(parent_id)
        total = sum(counts.values())
        done = counts.get("done", 0)
        return {
            "parent_id": parent_id,
            "total": total,
            "done": done,
            "progress": round(done / total * 100, 1) if total > 0 else 0,
            "by_status": counts,
        }

    def get_logs(self, task_id: Optional[str] = None, **kwargs) -> list[TaskLog]:
        """获取操作日志"""
        return self.db.list_logs(task_id=task_id, **kwargs)

    # ── 更新/删除 ─────────────────────────────────────────

    def update_task(
        self,
        task_id: str,
        title: Optional[str] = None,
        description: Optional[str] = None,
        priority: Optional[int] = None,
        tags: Optional[list[str]] = None,
        test_path: Optional[str] = None,
        work_dir: Optional[str] = None,
    ) -> Task:
        """更新任务属性"""
        task = self._get_or_raise(task_id)
        changes = []
        if title is not None:
            task.title = title.strip()
            changes.append(f"title={title}")
        if description is not None:
            task.description = description.strip()
            changes.append("description 已更新")
        if priority is not None:
            task.priority = priority
            changes.append(f"priority={priority}")
        if tags is not None:
            task.tags = tags
            changes.append(f"tags={tags}")
        if test_path is not None:
            task.test_path = test_path
            changes.append(f"test_path={test_path}")
        if work_dir is not None:
            task.work_dir = work_dir
            changes.append(f"work_dir={work_dir}")

        self.db.update_task(task)
        if changes:
            self._log(task_id, "updated", detail="; ".join(changes))
        return task

    def delete_task(self, task_id: str) -> bool:
        """删除任务"""
        task = self.db.get_task(task_id)
        if not task:
            return False
        self._log(task_id, "deleted", detail=f"删除任务: {task.title}")
        return self.db.delete_task(task_id)

    # ── 终端管理 ──────────────────────────────────────────

    def register_terminal(self, terminal: Terminal) -> Terminal:
        """注册终端"""
        return self.db.upsert_terminal(terminal)

    def list_terminals(self) -> list[Terminal]:
        """列出所有终端"""
        return self.db.list_terminals()

    # ── 内部辅助 ──────────────────────────────────────────

    def _get_or_raise(self, task_id: str) -> Task:
        """获取任务，不存在则抛异常"""
        task = self.db.get_task(task_id)
        if not task:
            raise TaskManagerError(f"任务 {task_id} 不存在")
        return task

    def _log(
        self,
        task_id: str,
        action: str,
        old_value: str = "",
        new_value: str = "",
        detail: str = "",
    ):
        """记录操作日志"""
        log = TaskLog(
            task_id=task_id,
            action=action,
            terminal_id=self.terminal_id,
            old_value=old_value,
            new_value=new_value,
            detail=detail,
        )
        self.db.insert_log(log)
