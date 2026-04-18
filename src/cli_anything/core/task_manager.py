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
        
        # 使用批量事务同时插入任务和日志，减少锁竞争
        from datetime import datetime
        task_dict = task.to_dict()
        task_cols = ", ".join(task_dict.keys())
        task_placeholders = ", ".join(["?"] * len(task_dict))
        
        log = TaskLog(
            task_id=task.id,
            action="created",
            terminal_id=self.terminal_id,
            detail=f"创建任务: {title}" + (f"（待 {reviewer} 审阅）" if reviewer else ""),
        )
        log_dict = log.to_dict()
        log_cols = ", ".join(log_dict.keys())
        log_placeholders = ", ".join(["?"] * len(log_dict))
        
        # 在单个事务中执行两个 INSERT
        operations = [
            (f"INSERT INTO tasks ({task_cols}) VALUES ({task_placeholders})", list(task_dict.values())),
            (f"INSERT INTO task_logs ({log_cols}) VALUES ({log_placeholders})", list(log_dict.values())),
        ]
        self.db.execute_in_transaction(operations)
        
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
        """领取任务（领取前校验所有前置依赖是否已完成）"""
        task = self._get_or_raise(task_id)
        if task.status != TaskStatus.PENDING:
            raise TaskManagerError(f"只能领取 pending 状态的任务，当前状态: {task.status.value}")

        # 依赖检查：前置任务必须全部 done
        blocking = self.db.list_blocking_deps(task_id)
        if blocking:
            raise TaskManagerError(
                f"任务 {task_id} 有未完成的前置依赖，无法领取。"
                f"请先完成: {blocking}"
            )

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

    def submit_task(
        self,
        task_id: str,
        summary: str = "",
        changed_files: Optional[list[str]] = None,
        test_note: str = "",
    ) -> Task:
        """提交任务（in_progress → submitted），可附带结构化交付信封

        Args:
            task_id: 任务 ID（必须处于 in_progress 状态）
            summary: 本次实现内容的一句话摘要（可选）
            changed_files: 本次修改的文件列表（可选），如 ["src/auth.py", "tests/test_auth.py"]
            test_note: 测试通过情况的简要说明（可选），如 "全部 10 个测试通过"

        如果提供了信封字段，将合并写入 test_report，不会覆盖 TestRunner 已有的测试数据。
        """
        task = self._get_or_raise(task_id)
        if task.status != TaskStatus.IN_PROGRESS:
            raise TaskManagerError("只能提交 in_progress 状态的任务")

        # 合并结构化提交信封到 test_report
        envelope: dict = {}
        if summary:
            envelope["submit_summary"] = summary
        if changed_files:
            envelope["submit_changed_files"] = changed_files
        if test_note:
            envelope["submit_test_note"] = test_note
        if envelope:
            task.test_report = {**(task.test_report or {}), **envelope}

        task.status = TaskStatus.SUBMITTED
        task.submitted_at = _now_iso()
        self.db.update_task(task)
        log_detail = f"任务已提交待审核" + (f": {summary[:60]}" if summary else "")
        self._log(task_id, "submitted", detail=log_detail)
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

    # ── 任务依赖图（DAG）────────────────────────────────────

    def add_dependency(self, task_id: str, depends_on_id: str) -> None:
        """为任务添加前置依赖

        task_id 的任务在 depends_on_id 完成（done）之前无法被领取。

        Args:
            task_id: 需要等待前置任务完成才能开始的任务 ID
            depends_on_id: 前置任务 ID（必须先完成）

        Raises:
            TaskManagerError: 任务不存在、自依赖、或会形成循环依赖
        """
        self._get_or_raise(task_id)
        self._get_or_raise(depends_on_id)
        if task_id == depends_on_id:
            raise TaskManagerError("任务不能依赖自身")
        # 检测循环依赖：depends_on_id 是否已经（直接或间接）依赖 task_id
        if self._has_path(depends_on_id, task_id):
            raise TaskManagerError(
                f"添加依赖会形成循环：{task_id} → {depends_on_id} → ... → {task_id}"
            )
        self.db.add_dependency(task_id, depends_on_id)
        self._log(task_id, "dep_added", detail=f"添加前置依赖: {depends_on_id}")

    def remove_dependency(self, task_id: str, depends_on_id: str) -> None:
        """移除任务的前置依赖

        Args:
            task_id: 任务 ID
            depends_on_id: 要移除的前置任务 ID

        Raises:
            TaskManagerError: 依赖关系不存在
        """
        removed = self.db.remove_dependency(task_id, depends_on_id)
        if not removed:
            raise TaskManagerError(
                f"任务 {task_id} 不存在对 {depends_on_id} 的依赖"
            )
        self._log(task_id, "dep_removed", detail=f"移除前置依赖: {depends_on_id}")

    def get_dependencies(self, task_id: str) -> dict:
        """获取任务的依赖关系详情

        Args:
            task_id: 任务 ID

        Returns:
            dict 包含：
            - depends_on: 该任务依赖的任务列表（前置任务）
            - depended_by: 依赖该任务的任务列表（下游任务）
            - blocking: 当前阻塞该任务的前置任务列表（未完成的）
            - is_blocked: 是否被阻塞
        """
        self._get_or_raise(task_id)
        dep_ids = self.db.list_dependencies(task_id)
        dependent_ids = self.db.list_dependents(task_id)
        blocking_ids = self.db.list_blocking_deps(task_id)

        dep_tasks = [self.db.get_task(tid) for tid in dep_ids]
        dependent_tasks = [self.db.get_task(tid) for tid in dependent_ids]

        def _task_summary(t):
            if t is None:
                return None
            return {"id": t.id, "title": t.title, "status": t.status.value}

        return {
            "task_id": task_id,
            "depends_on": [_task_summary(t) for t in dep_tasks if t],
            "depended_by": [_task_summary(t) for t in dependent_tasks if t],
            "blocking": blocking_ids,
            "is_blocked": len(blocking_ids) > 0,
        }

    def _has_path(self, from_id: str, to_id: str) -> bool:
        """BFS 检测从 from_id 出发是否能到达 to_id（用于循环检测）"""
        visited: set[str] = set()
        queue = [from_id]
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            for dep in self.db.list_dependencies(current):
                if dep == to_id:
                    return True
                queue.append(dep)
        return False

    # ── Supervisor 自动路由 ──────────────────────────────────

    def update_capabilities(self, terminal_id: str, capabilities: list[str]) -> None:
        """更新终端的技能列表

        技能列表用于任务路由匹配。Worker 注册后调用此方法声明自己能处理哪类标签的任务。

        Args:
            terminal_id: 终端 ID
            capabilities: 技能/标签列表，与任务 tags 做匹配
        """
        terminal = self.db.get_terminal(terminal_id)
        if terminal is None:
            raise TaskManagerError(f"终端 {terminal_id} 不存在，请先注册")
        terminal.capabilities = capabilities
        self.db.upsert_terminal(terminal)

    def route_task(self, task_id: str) -> list[dict]:
        """为指定任务推荐候选终端（Supervisor 视角）

        根据任务 tags 与终端 capabilities 的交集匹配，返回候选 Worker 终端。

        匹配规则：
        - 任务有 tags → 返回 capabilities 包含任意匹配 tag 的 Worker 终端
        - 任务无 tags → 返回所有活跃 Worker 终端

        Args:
            task_id: 任务 ID

        Returns:
            list of dict，每项包含：
            - terminal_id, name, role, matched_tags（交集），capabilities
        """
        task = self._get_or_raise(task_id)
        terminals = self.db.list_terminals()
        workers = [t for t in terminals if t.role.value == "worker"]

        task_tags = set(task.tags)
        result = []

        if not task_tags:
            for t in workers:
                result.append({
                    "terminal_id": t.id,
                    "name": t.name,
                    "role": t.role.value,
                    "matched_tags": [],
                    "capabilities": t.capabilities,
                })
        else:
            for t in workers:
                matched = list(task_tags & set(t.capabilities))
                if matched:
                    result.append({
                        "terminal_id": t.id,
                        "name": t.name,
                        "role": t.role.value,
                        "matched_tags": matched,
                        "capabilities": t.capabilities,
                    })

        return result

    def suggest_tasks(self, terminal_id: str, limit: int = 10) -> list[Task]:
        """为指定终端推荐候选任务（Worker 视角）

        根据终端 capabilities 与任务 tags 的交集过滤，按优先级从高到低排序。

        匹配规则：
        - capabilities 不为空 → 先过滤有匹配 tag 的任务，若无匹配则 fallback 全量
        - capabilities 为空 → 直接返回所有 pending 任务

        Args:
            terminal_id: 终端 ID
            limit: 最多返回多少条（默认 10）

        Returns:
            按优先级排序的 pending 任务列表
        """
        terminal = self.db.get_terminal(terminal_id)
        if terminal is None:
            raise TaskManagerError(f"终端 {terminal_id} 不存在，请先注册")

        all_pending = self.db.list_tasks(status=TaskStatus.PENDING.value)
        all_pending.sort(key=lambda t: t.priority)

        if not terminal.capabilities:
            return all_pending[:limit]

        caps = set(terminal.capabilities)
        matched = [t for t in all_pending if set(t.tags) & caps]
        if matched:
            return matched[:limit]
        return all_pending[:limit]

    # ── Judgment Day 双盲对抗审查 ────────────────────────────────

    def trigger_judgment_day(self, task_id: str) -> tuple[Task, Task]:
        """为 submitted 状态的任务启动双盲对抗审查

        创建 Judge A 和 Judge B 两个独立审查任务（REVIEW 类型），
        供两个不同的 Worker 终端各自认领、独立审查，互不知晓对方结论。

        Args:
            task_id: 待审查的任务 ID（必须处于 submitted 状态）

        Returns:
            (judge_a_task, judge_b_task)

        Raises:
            TaskManagerError: 如果任务状态不是 submitted，或已有活跃审查，或超过最大轮次
        """
        task = self._get_or_raise(task_id)
        if task.status != TaskStatus.SUBMITTED:
            raise TaskManagerError(
                f"只能对 submitted 状态的任务发起 Judgment Day，当前状态: {task.status.value}"
            )

        # 获取所有已有审查任务，检查是否有活跃审查
        existing = self.db.list_tasks(parent_id=task_id, task_type=TaskType.REVIEW.value, limit=100)
        active = [t for t in existing if t.status not in (TaskStatus.DONE, TaskStatus.CANCELLED, TaskStatus.SUBMITTED)]
        if active:
            raise TaskManagerError(
                f"该任务已有 {len(active)} 个进行中的审查任务，请等待当前轮次完成后再触发"
            )

        # 已完成的轮次数 = 已提交审查任务对数
        submitted = [t for t in existing if t.status == TaskStatus.SUBMITTED]
        current_round = len(submitted) // 2 + 1
        if current_round > 2:
            raise TaskManagerError(
                "已达到最大审查轮次（2 轮），建议人工介入处理或直接验收"
            )

        # 在原始任务上打标记
        if "judgment-day" not in task.tags:
            task.tags.append("judgment-day")
        round_tag = f"jd-round-{current_round}"
        if round_tag not in task.tags:
            task.tags.append(round_tag)
        self.db.update_task(task)

        # 创建 Judge A 审查任务
        judge_a = self.create_task(
            title=f"【Judgment Day R{current_round}】Judge A 审查 #{task_id}",
            description=(
                f"## 双盲对抗审查 — Judge A（第 {current_round} 轮）\n\n"
                f"**待审查任务**: #{task_id} — {task.title}\n\n"
                f"**重要规则**：独立审查，不得查看 Judge B 的结论，不得与其他审查者沟通。\n\n"
                f"**审查维度**：正确性 / 边界情况 / 错误处理 / 性能 / 安全性 / 命名与约定\n\n"
                f"审查完成后调用 `task_submit_verdict` 提交裁决，"
                f"verdict 为 'clean'（无问题）或 'issues'（有问题）。"
            ),
            task_type=TaskType.REVIEW,
            parent_id=task_id,
            tags=["jd-judge-a", round_tag],
        )

        # 创建 Judge B 审查任务
        judge_b = self.create_task(
            title=f"【Judgment Day R{current_round}】Judge B 审查 #{task_id}",
            description=(
                f"## 双盲对抗审查 — Judge B（第 {current_round} 轮）\n\n"
                f"**待审查任务**: #{task_id} — {task.title}\n\n"
                f"**重要规则**：独立审查，不得查看 Judge A 的结论，不得与其他审查者沟通。\n\n"
                f"**审查维度**：正确性 / 边界情况 / 错误处理 / 性能 / 安全性 / 命名与约定\n\n"
                f"审查完成后调用 `task_submit_verdict` 提交裁决，"
                f"verdict 为 'clean'（无问题）或 'issues'（有问题）。"
            ),
            task_type=TaskType.REVIEW,
            parent_id=task_id,
            tags=["jd-judge-b", round_tag],
        )

        self._log(
            task_id,
            "judgment_day_triggered",
            detail=f"Round {current_round}: Judge A={judge_a.id}, Judge B={judge_b.id}",
        )
        return judge_a, judge_b

    def submit_verdict(
        self,
        review_task_id: str,
        verdict: str,
        findings: Optional[list[dict]] = None,
        summary: str = "",
    ) -> Task:
        """Worker 提交审查裁决

        将裁决结果（verdict + findings）存入 test_report，并将审查任务状态变为 submitted。

        Args:
            review_task_id: 审查任务 ID（task_type 必须是 review）
            verdict: "clean"（无问题）或 "issues"（发现问题）
            findings: 发现的问题列表，每项格式：
                      {"desc": "描述", "severity": "CRITICAL|WARNING|SUGGESTION", "location": "文件:行号"}
            summary: 一句话总结（可选）

        Raises:
            TaskManagerError: 如果任务类型不是 review，状态不对，或 verdict 值不合法
        """
        review_task = self._get_or_raise(review_task_id)
        if review_task.task_type != TaskType.REVIEW:
            raise TaskManagerError("只能对 review 类型的任务提交裁决")
        if verdict not in ("clean", "issues"):
            raise TaskManagerError("verdict 必须是 'clean' 或 'issues'")
        if review_task.status not in (TaskStatus.CLAIMED, TaskStatus.IN_PROGRESS):
            raise TaskManagerError(
                f"审查任务必须处于 claimed 或 in_progress 状态，当前: {review_task.status.value}"
            )

        # 若还在 claimed，先自动过渡到 in_progress
        if review_task.status == TaskStatus.CLAIMED:
            review_task.status = TaskStatus.IN_PROGRESS
            self.db.update_task(review_task)

        # 存储裁决到 test_report
        review_task.test_report = {
            "verdict": verdict,
            "findings": findings or [],
            "summary": summary,
        }
        review_task.status = TaskStatus.SUBMITTED
        review_task.submitted_at = _now_iso()
        self.db.update_task(review_task)
        self._log(
            review_task_id,
            "verdict_submitted",
            detail=f"裁决: {verdict}, 发现 {len(findings or [])} 个问题",
        )
        return review_task

    def get_review_tasks(self, task_id: str) -> list[Task]:
        """获取某任务的所有审查任务（按创建时间升序）

        Args:
            task_id: 被审查的原始任务 ID
        """
        return self.db.list_tasks(parent_id=task_id, task_type=TaskType.REVIEW.value, limit=100)

    def synthesize_judgment(self, task_id: str) -> dict:
        """综合两份审查裁决，生成对比分析报告

        比较 Judge A 和 Judge B 的发现，分类为：
        - confirmed：两者都发现的问题（高置信度）
        - suspect_a：只有 Judge A 发现的
        - suspect_b：只有 Judge B 发现的

        Args:
            task_id: 被审查的原始任务 ID

        Returns:
            synthesis 报告字典，包含 recommendation（"approve"/"fix"/"escalated"）

        Raises:
            TaskManagerError: 如果审查任务不存在或尚未全部提交
        """
        self._get_or_raise(task_id)

        all_reviews = self.db.list_tasks(parent_id=task_id, task_type=TaskType.REVIEW.value, limit=100)
        if not all_reviews:
            raise TaskManagerError("该任务没有任何审查任务，请先调用 trigger_judgment_day")

        # 提取轮次信息，找最大轮次
        def _extract_round(t: Task) -> int:
            for tag in t.tags:
                if tag.startswith("jd-round-"):
                    try:
                        return int(tag.split("-")[-1])
                    except ValueError:
                        pass
            return 0

        max_round = max(_extract_round(t) for t in all_reviews)
        if max_round == 0:
            raise TaskManagerError("审查任务缺少 jd-round-N 标签，无法确认轮次")

        latest = [t for t in all_reviews if _extract_round(t) == max_round]
        submitted = [t for t in latest if t.status == TaskStatus.SUBMITTED]
        if len(submitted) < 2:
            pending_ids = [t.id for t in latest if t.status != TaskStatus.SUBMITTED]
            raise TaskManagerError(
                f"第 {max_round} 轮审查尚未完成，待提交的审查任务: {pending_ids}"
            )

        judge_a = next((t for t in submitted if "jd-judge-a" in t.tags), None)
        judge_b = next((t for t in submitted if "jd-judge-b" in t.tags), None)
        if not judge_a or not judge_b:
            raise TaskManagerError("无法区分 Judge A 和 Judge B，请检查审查任务的 tags")

        report_a = judge_a.test_report
        report_b = judge_b.test_report
        verdict_a = report_a.get("verdict", "unknown")
        verdict_b = report_b.get("verdict", "unknown")
        findings_a: list[dict] = report_a.get("findings", [])
        findings_b: list[dict] = report_b.get("findings", [])

        # 简单键匹配：取 desc 前 40 字符，规范化空白
        def _key(f: dict) -> str:
            return " ".join(f.get("desc", "").lower().split())[:40]

        keys_b = {_key(f) for f in findings_b}
        confirmed = [f for f in findings_a if _key(f) in keys_b]
        suspect_a = [f for f in findings_a if _key(f) not in keys_b]
        keys_a = {_key(f) for f in findings_a}
        suspect_b = [f for f in findings_b if _key(f) not in keys_a]

        both_clean = (verdict_a == "clean" and verdict_b == "clean")
        if both_clean:
            recommendation = "approve"
        elif max_round >= 2:
            recommendation = "escalated"
        else:
            recommendation = "fix"

        result = {
            "round": max_round,
            "judge_a": {
                "task_id": judge_a.id,
                "verdict": verdict_a,
                "summary": report_a.get("summary", ""),
                "findings_count": len(findings_a),
            },
            "judge_b": {
                "task_id": judge_b.id,
                "verdict": verdict_b,
                "summary": report_b.get("summary", ""),
                "findings_count": len(findings_b),
            },
            "confirmed": confirmed,
            "suspect_a": suspect_a,
            "suspect_b": suspect_b,
            "both_clean": both_clean,
            "recommendation": recommendation,
        }

        self._log(
            task_id,
            "judgment_synthesized",
            detail=(
                f"Round {max_round}: confirmed={len(confirmed)}, "
                f"suspect_a={len(suspect_a)}, suspect_b={len(suspect_b)}, "
                f"recommendation={recommendation}"
            ),
        )
        return result

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
