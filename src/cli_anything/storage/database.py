"""SQLite 存储层：数据库初始化、CRUD 操作"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Optional

from cli_anything.core.models import Task, TaskLog, Terminal


# 默认数据库路径
DEFAULT_DB_PATH = os.path.join(os.path.expanduser("~"), ".cli-anything", "tasks.db")

# 建表 SQL
_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS tasks (
    id              TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    description     TEXT DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'pending',
    task_type       TEXT NOT NULL DEFAULT 'master',
    priority        INTEGER DEFAULT 3 CHECK (priority BETWEEN 1 AND 5),
    tags            TEXT DEFAULT '[]',
    parent_id       TEXT REFERENCES tasks(id) ON DELETE CASCADE,
    created_by      TEXT NOT NULL DEFAULT '',
    claimed_by      TEXT DEFAULT NULL,
    claimed_at      TEXT DEFAULT NULL,
    submitted_at    TEXT DEFAULT NULL,
    verified_by     TEXT DEFAULT NULL,
    verified_at     TEXT DEFAULT NULL,
    verify_comment  TEXT DEFAULT '',
    test_status     TEXT DEFAULT 'not_run',
    test_report     TEXT DEFAULT '{}',
    test_path       TEXT DEFAULT '',
    work_dir        TEXT DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_type ON tasks(task_type);
CREATE INDEX IF NOT EXISTS idx_tasks_parent ON tasks(parent_id);
CREATE INDEX IF NOT EXISTS idx_tasks_claimed_by ON tasks(claimed_by);
CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(priority);

CREATE TABLE IF NOT EXISTS task_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    action      TEXT NOT NULL,
    terminal_id TEXT DEFAULT '',
    old_value   TEXT DEFAULT '',
    new_value   TEXT DEFAULT '',
    detail      TEXT DEFAULT '',
    timestamp   TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_task_logs_task ON task_logs(task_id);
CREATE INDEX IF NOT EXISTS idx_task_logs_action ON task_logs(action);
CREATE INDEX IF NOT EXISTS idx_task_logs_time ON task_logs(timestamp);

CREATE TABLE IF NOT EXISTS terminals (
    id            TEXT PRIMARY KEY,
    name          TEXT DEFAULT '',
    role          TEXT NOT NULL DEFAULT 'worker',
    type          TEXT DEFAULT '',
    pid           INTEGER DEFAULT 0,
    last_active   TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    registered_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
"""


class Database:
    """SQLite 数据库管理器"""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None

    def connect(self) -> sqlite3.Connection:
        """建立数据库连接，自动创建目录和表"""
        if self._conn is not None:
            return self._conn

        # 确保目录存在
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        self._conn = sqlite3.connect(self.db_path, timeout=5.0)
        self._conn.row_factory = sqlite3.Row
        # 启用 WAL 模式和外键约束
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=5000")
        # 初始化表结构
        self._conn.executescript(_SCHEMA_SQL)
        self._conn.commit()
        return self._conn

    def close(self):
        """关闭数据库连接"""
        if self._conn:
            self._conn.close()
            self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        """获取活跃连接（懒初始化）"""
        if self._conn is None:
            return self.connect()
        return self._conn

    # ── Task CRUD ───────────────────────────────────────────

    def insert_task(self, task: Task) -> Task:
        """插入新任务"""
        d = task.to_dict()
        cols = ", ".join(d.keys())
        placeholders = ", ".join(["?"] * len(d))
        self.conn.execute(
            f"INSERT INTO tasks ({cols}) VALUES ({placeholders})",
            list(d.values()),
        )
        self.conn.commit()
        return task

    def get_task(self, task_id: str) -> Optional[Task]:
        """根据 ID 获取任务"""
        cur = self.conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        row = cur.fetchone()
        return Task.from_row(dict(row)) if row else None

    def list_tasks(
        self,
        status: Optional[str] = None,
        task_type: Optional[str] = None,
        parent_id: Optional[str] = None,
        claimed_by: Optional[str] = None,
        tag: Optional[str] = None,
        limit: int = 100,
    ) -> list[Task]:
        """查询任务列表，支持多条件过滤"""
        conditions: list[str] = []
        params: list = []

        if status:
            conditions.append("status = ?")
            params.append(status)
        if task_type:
            conditions.append("task_type = ?")
            params.append(task_type)
        if parent_id:
            conditions.append("parent_id = ?")
            params.append(parent_id)
        if claimed_by:
            conditions.append("claimed_by = ?")
            params.append(claimed_by)
        if tag:
            conditions.append("tags LIKE ?")
            params.append(f'%"{tag}"%')

        where = " AND ".join(conditions) if conditions else "1=1"
        params.append(limit)

        cur = self.conn.execute(
            f"SELECT * FROM tasks WHERE {where} ORDER BY priority ASC, created_at DESC LIMIT ?",
            params,
        )
        return [Task.from_row(dict(row)) for row in cur.fetchall()]

    def update_task(self, task: Task) -> Task:
        """更新任务（按 ID）"""
        from datetime import datetime
        task.updated_at = datetime.now().isoformat(timespec="seconds")
        d = task.to_dict()
        task_id = d.pop("id")
        set_clause = ", ".join(f"{k} = ?" for k in d.keys())
        self.conn.execute(
            f"UPDATE tasks SET {set_clause} WHERE id = ?",
            [*d.values(), task_id],
        )
        self.conn.commit()
        return task

    def delete_task(self, task_id: str) -> bool:
        """删除任务（级联删除子任务和日志）"""
        cur = self.conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def count_subtasks_by_status(self, parent_id: str) -> dict[str, int]:
        """统计子任务各状态数量"""
        cur = self.conn.execute(
            "SELECT status, COUNT(*) as cnt FROM tasks WHERE parent_id = ? GROUP BY status",
            (parent_id,),
        )
        return {row["status"]: row["cnt"] for row in cur.fetchall()}

    # ── TaskLog CRUD ────────────────────────────────────────

    def insert_log(self, log: TaskLog) -> TaskLog:
        """插入操作日志"""
        d = log.to_dict()
        cols = ", ".join(d.keys())
        placeholders = ", ".join(["?"] * len(d))
        cur = self.conn.execute(
            f"INSERT INTO task_logs ({cols}) VALUES ({placeholders})",
            list(d.values()),
        )
        self.conn.commit()
        log.id = cur.lastrowid
        return log

    def list_logs(
        self,
        task_id: Optional[str] = None,
        action: Optional[str] = None,
        limit: int = 50,
    ) -> list[TaskLog]:
        """查询操作日志"""
        conditions: list[str] = []
        params: list = []

        if task_id:
            conditions.append("task_id = ?")
            params.append(task_id)
        if action:
            conditions.append("action = ?")
            params.append(action)

        where = " AND ".join(conditions) if conditions else "1=1"
        params.append(limit)

        cur = self.conn.execute(
            f"SELECT * FROM task_logs WHERE {where} ORDER BY timestamp DESC LIMIT ?",
            params,
        )
        return [TaskLog.from_row(dict(row)) for row in cur.fetchall()]

    # ── Terminal CRUD ───────────────────────────────────────

    def upsert_terminal(self, terminal: Terminal) -> Terminal:
        """插入或更新终端信息"""
        d = terminal.to_dict()
        cols = ", ".join(d.keys())
        placeholders = ", ".join(["?"] * len(d))
        update_set = ", ".join(f"{k} = excluded.{k}" for k in d.keys() if k != "id")
        self.conn.execute(
            f"INSERT INTO terminals ({cols}) VALUES ({placeholders}) "
            f"ON CONFLICT(id) DO UPDATE SET {update_set}",
            list(d.values()),
        )
        self.conn.commit()
        return terminal

    def get_terminal(self, terminal_id: str) -> Optional[Terminal]:
        """根据 ID 获取终端"""
        cur = self.conn.execute("SELECT * FROM terminals WHERE id = ?", (terminal_id,))
        row = cur.fetchone()
        return Terminal.from_row(dict(row)) if row else None

    def list_terminals(self) -> list[Terminal]:
        """获取所有终端"""
        cur = self.conn.execute("SELECT * FROM terminals ORDER BY last_active DESC")
        return [Terminal.from_row(dict(row)) for row in cur.fetchall()]
