"""数据模型定义：Task、TaskLog、Terminal"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Optional


class TaskType(str, Enum):
    """任务类型"""
    MASTER = "master"
    SUBTASK = "subtask"


class TaskStatus(str, Enum):
    """任务状态"""
    PENDING = "pending"
    CLAIMED = "claimed"
    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"
    DONE = "done"
    REJECTED = "rejected"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class TestStatus(str, Enum):
    """测试状态"""
    NOT_RUN = "not_run"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"


class TerminalRole(str, Enum):
    """终端角色"""
    MASTER = "master"
    WORKER = "worker"


# 合法的状态流转表
VALID_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.PENDING: {TaskStatus.CLAIMED, TaskStatus.IN_PROGRESS, TaskStatus.CANCELLED},
    TaskStatus.CLAIMED: {TaskStatus.IN_PROGRESS, TaskStatus.PENDING, TaskStatus.CANCELLED},
    TaskStatus.IN_PROGRESS: {TaskStatus.SUBMITTED, TaskStatus.BLOCKED, TaskStatus.CANCELLED},
    TaskStatus.SUBMITTED: {TaskStatus.DONE, TaskStatus.REJECTED},
    TaskStatus.REJECTED: {TaskStatus.IN_PROGRESS},
    TaskStatus.BLOCKED: {TaskStatus.IN_PROGRESS, TaskStatus.CANCELLED},
    TaskStatus.DONE: set(),  # 终态
    TaskStatus.CANCELLED: {TaskStatus.PENDING},  # 可重新激活
}


def _now_iso() -> str:
    """返回当前时间的 ISO8601 字符串"""
    return datetime.now().isoformat(timespec="seconds")


def _new_id() -> str:
    """生成短 UUID（前 8 位）"""
    return uuid.uuid4().hex[:8]


@dataclass
class Task:
    """任务数据模型"""
    id: str = field(default_factory=_new_id)
    title: str = ""
    description: str = ""
    status: TaskStatus = TaskStatus.PENDING
    task_type: TaskType = TaskType.MASTER
    priority: int = 3
    tags: list[str] = field(default_factory=list)
    parent_id: Optional[str] = None
    created_by: str = ""
    claimed_by: Optional[str] = None
    claimed_at: Optional[str] = None
    submitted_at: Optional[str] = None
    verified_by: Optional[str] = None
    verified_at: Optional[str] = None
    verify_comment: str = ""
    test_status: TestStatus = TestStatus.NOT_RUN
    test_report: dict = field(default_factory=dict)
    test_path: str = ""
    work_dir: str = ""
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict:
        """转换为字典（用于存储）"""
        d = asdict(self)
        d["status"] = self.status.value
        d["task_type"] = self.task_type.value
        d["test_status"] = self.test_status.value
        d["tags"] = json.dumps(self.tags, ensure_ascii=False)
        d["test_report"] = json.dumps(self.test_report, ensure_ascii=False)
        return d

    @classmethod
    def from_row(cls, row: dict) -> Task:
        """从数据库行字典创建 Task 实例"""
        return cls(
            id=row["id"],
            title=row["title"],
            description=row.get("description", ""),
            status=TaskStatus(row["status"]),
            task_type=TaskType(row["task_type"]),
            priority=row.get("priority", 3),
            tags=json.loads(row.get("tags", "[]")),
            parent_id=row.get("parent_id"),
            created_by=row.get("created_by", ""),
            claimed_by=row.get("claimed_by"),
            claimed_at=row.get("claimed_at"),
            submitted_at=row.get("submitted_at"),
            verified_by=row.get("verified_by"),
            verified_at=row.get("verified_at"),
            verify_comment=row.get("verify_comment", ""),
            test_status=TestStatus(row.get("test_status", "not_run")),
            test_report=json.loads(row.get("test_report", "{}")),
            test_path=row.get("test_path", ""),
            work_dir=row.get("work_dir", ""),
            created_at=row.get("created_at", ""),
            updated_at=row.get("updated_at", ""),
        )

    def can_transition_to(self, new_status: TaskStatus) -> bool:
        """检查是否可以转换到指定状态"""
        return new_status in VALID_TRANSITIONS.get(self.status, set())


@dataclass
class TaskLog:
    """任务操作日志"""
    id: Optional[int] = None
    task_id: str = ""
    action: str = ""
    terminal_id: str = ""
    old_value: str = ""
    new_value: str = ""
    detail: str = ""
    timestamp: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict:
        """转换为字典"""
        d = asdict(self)
        if d["id"] is None:
            del d["id"]  # 自增字段不需要手动设置
        return d

    @classmethod
    def from_row(cls, row: dict) -> TaskLog:
        """从数据库行字典创建"""
        return cls(
            id=row.get("id"),
            task_id=row["task_id"],
            action=row["action"],
            terminal_id=row.get("terminal_id", ""),
            old_value=row.get("old_value", ""),
            new_value=row.get("new_value", ""),
            detail=row.get("detail", ""),
            timestamp=row.get("timestamp", ""),
        )


@dataclass
class Terminal:
    """终端注册信息"""
    id: str = field(default_factory=_new_id)
    name: str = ""
    role: TerminalRole = TerminalRole.WORKER
    type: str = ""  # powershell / cmd / wsl / ssh
    pid: int = 0
    last_active: str = field(default_factory=_now_iso)
    registered_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict:
        """转换为字典"""
        d = asdict(self)
        d["role"] = self.role.value
        return d

    @classmethod
    def from_row(cls, row: dict) -> Terminal:
        """从数据库行字典创建"""
        return cls(
            id=row["id"],
            name=row.get("name", ""),
            role=TerminalRole(row.get("role", "worker")),
            type=row.get("type", ""),
            pid=row.get("pid", 0),
            last_active=row.get("last_active", ""),
            registered_at=row.get("registered_at", ""),
        )
