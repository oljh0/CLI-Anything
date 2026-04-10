"""终端热重连与心跳检测"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Optional

from cli_anything.core.models import Terminal, _now_iso
from cli_anything.storage.database import Database


class TerminalHealthChecker:
    """终端存活检测与断线重连"""

    def __init__(self, db: Database, timeout_seconds: int = 60):
        self.db = db
        self.timeout_seconds = timeout_seconds

    def check_alive(self, terminal_id: str) -> bool:
        """检查终端是否在线（基于 last_active 时间）"""
        terminal = self.db.get_terminal(terminal_id)
        if not terminal or not terminal.last_active:
            return False

        try:
            last = datetime.fromisoformat(terminal.last_active)
            return (datetime.now() - last).total_seconds() < self.timeout_seconds
        except ValueError:
            return False

    def list_stale_terminals(self) -> list[Terminal]:
        """获取已超时的终端列表"""
        all_terminals = self.db.list_terminals()
        stale = []
        for t in all_terminals:
            if not self.check_alive(t.id):
                stale.append(t)
        return stale

    def cleanup_stale_claims(self) -> list[dict]:
        """清理超时终端的领取状态，释放被占用的任务"""
        from cli_anything.core.models import TaskStatus
        from cli_anything.core.task_manager import TaskManager

        stale = self.list_stale_terminals()
        if not stale:
            return []

        stale_ids = {t.id for t in stale}
        released = []

        # 查找被超时终端领取的任务
        tm = TaskManager(self.db, terminal_id="health-checker")
        for terminal_id in stale_ids:
            tasks = self.db.list_tasks(claimed_by=terminal_id)
            for task in tasks:
                if task.status in (TaskStatus.CLAIMED, TaskStatus.IN_PROGRESS):
                    old_status = task.status.value
                    task.status = TaskStatus.PENDING
                    task.claimed_by = None
                    task.claimed_at = None
                    self.db.update_task(task)
                    released.append({
                        "task_id": task.id,
                        "title": task.title,
                        "old_status": old_status,
                        "stale_terminal": terminal_id,
                    })
                    tm._log(
                        task.id, "unclaimed",
                        detail=f"终端 {terminal_id} 超时，自动释放任务",
                    )

        return released

    def heartbeat(self, terminal_id: str):
        """更新终端心跳时间"""
        terminal = self.db.get_terminal(terminal_id)
        if terminal:
            terminal.last_active = _now_iso()
            self.db.upsert_terminal(terminal)
