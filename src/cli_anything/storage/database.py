"""SQLite 存储层：数据库初始化、CRUD 操作"""

from __future__ import annotations

import os
import sqlite3
import time
import logging
import threading
from pathlib import Path
from typing import Optional, Callable, Any

from cli_anything.core.models import Task, TaskLog, Terminal

# 日志记录器
logger = logging.getLogger(__name__)


def retry_on_lock(func: Callable) -> Callable:
    """数据库操作重试装饰器：遇到锁时自动重试"""
    def wrapper(*args, **kwargs):
        delay = INITIAL_RETRY_DELAY
        last_error = None
        
        for attempt in range(MAX_RETRIES + 1):
            try:
                return func(*args, **kwargs)
            except sqlite3.OperationalError as e:
                last_error = e
                error_msg = str(e).lower()
                
                # 只重试锁相关错误
                if any(keyword in error_msg for keyword in ['locked', 'busy', 'database is locked']):
                    if attempt < MAX_RETRIES:
                        logger.warning(
                            f"数据库锁冲突，{attempt + 1}/{MAX_RETRIES} 次重试，"
                            f"等待 {delay:.2f}s: {e}"
                        )
                        time.sleep(delay)
                        delay *= 2  # 指数退避
                    else:
                        logger.error(f"数据库操作失败，已达最大重试次数: {e}")
                        raise
                else:
                    # 非锁相关错误直接抛出
                    raise
        
        # 理论上不会到这里，但为了类型安全
        raise last_error
    
    return wrapper


# 默认数据库路径
DEFAULT_DB_PATH = os.path.join(os.path.expanduser("~"), ".cli-anything", "tasks.db")

# SQLite 优化配置
# 连接超时（秒）- 等待获取锁的时间
SQLITE_CONNECT_TIMEOUT = 15.0
# busy_timeout（毫秒）- 等待锁的超时时间
SQLITE_BUSY_TIMEOUT = 15000
# 最大重试次数
MAX_RETRIES = 3
# 初始重试延迟（秒）
INITIAL_RETRY_DELAY = 0.1

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
    reviewer        TEXT DEFAULT NULL,
    review_status   TEXT DEFAULT 'not_required',
    review_comment  TEXT DEFAULT '',
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
    capabilities  TEXT NOT NULL DEFAULT '[]',
    last_active   TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    registered_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS task_deps (
    task_id     TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    depends_on  TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    PRIMARY KEY (task_id, depends_on)
);

CREATE INDEX IF NOT EXISTS idx_task_deps_task ON task_deps(task_id);
CREATE INDEX IF NOT EXISTS idx_task_deps_on ON task_deps(depends_on);
"""


class Database:
    """SQLite 数据库管理器（线程安全：每线程独立连接）"""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        self._local = threading.local()
        self._lock = threading.Lock()
        self._schema_initialized = False

    def connect(self) -> sqlite3.Connection:
        """获取当前线程的数据库连接，自动创建目录和表"""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            return conn

        # 确保目录存在
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        conn = sqlite3.connect(
            self.db_path,
            timeout=SQLITE_CONNECT_TIMEOUT,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT}")
        conn.execute("PRAGMA wal_autocheckpoint=1000")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-64000")

        # 首次连接时初始化表结构（全局只做一次）
        with self._lock:
            if not self._schema_initialized:
                conn.executescript(_SCHEMA_SQL)
                conn.commit()
                self._migrate_review_columns_on(conn)
                self._migrate_task_deps_on(conn)
                self._schema_initialized = True

        self._local.conn = conn
        return conn

    def _migrate_review_columns_on(self, conn: sqlite3.Connection):
        """为已有数据库添加 reviewer/review_status/review_comment 列"""
        cursor = conn.execute("PRAGMA table_info(tasks)")
        columns = {row["name"] for row in cursor.fetchall()}
        migrations = [
            ("reviewer", "TEXT DEFAULT NULL"),
            ("review_status", "TEXT DEFAULT 'not_required'"),
            ("review_comment", "TEXT DEFAULT ''"),
        ]
        for col_name, col_def in migrations:
            if col_name not in columns:
                conn.execute(f"ALTER TABLE tasks ADD COLUMN {col_name} {col_def}")
        conn.commit()

    def _migrate_review_columns(self):
        """兼容旧调用"""
        self._migrate_review_columns_on(self.conn)

    def _migrate_task_deps_on(self, conn: sqlite3.Connection):
        """为已有数据库创建 task_deps 表（幂等）"""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS task_deps (
                task_id     TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                depends_on  TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                PRIMARY KEY (task_id, depends_on)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_task_deps_task ON task_deps(task_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_task_deps_on ON task_deps(depends_on)")
        # 为已有数据库添加 capabilities 列
        existing = {row[1] for row in conn.execute("PRAGMA table_info(terminals)").fetchall()}
        if "capabilities" not in existing:
            conn.execute("ALTER TABLE terminals ADD COLUMN capabilities TEXT NOT NULL DEFAULT '[]'")
        conn.commit()

    def close(self):
        """关闭当前线程的数据库连接"""
        conn = getattr(self._local, "conn", None)
        if conn:
            conn.close()
            self._local.conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        """获取当前线程的活跃连接（懒初始化）"""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            return self.connect()
        return conn

    def execute_in_transaction(self, operations: list[tuple[str, list]]) -> None:
        """在单个事务中执行多个操作（线程安全）
        
        Args:
            operations: 操作列表，每项为 (sql, params)
        """
        with self._lock:
            try:
                for sql, params in operations:
                    self.conn.execute(sql, params)
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise

    @retry_on_lock
    def execute_with_retry(self, sql: str, params: list = None) -> sqlite3.Cursor:
        """执行 SQL 并带锁重试机制"""
        if params is None:
            return self.conn.execute(sql)
        return self.conn.execute(sql, params)

    @retry_on_lock
    def commit_with_retry(self) -> None:
        """提交事务并带锁重试机制"""
        self.conn.commit()

    # ── Task CRUD ───────────────────────────────────────────

    @retry_on_lock
    def insert_task(self, task: Task) -> Task:
        """插入新任务"""
        with self._lock:
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

    @retry_on_lock
    def update_task(self, task: Task) -> Task:
        """更新任务（按 ID）"""
        from datetime import datetime
        with self._lock:
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

    @retry_on_lock
    def insert_log(self, log: TaskLog) -> TaskLog:
        """插入操作日志"""
        with self._lock:
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

    @retry_on_lock
    def upsert_terminal(self, terminal: Terminal) -> Terminal:
        """插入或更新终端信息"""
        with self._lock:
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

    # ── TaskDep CRUD ─────────────────────────────────────────

    @retry_on_lock
    def add_dependency(self, task_id: str, depends_on: str) -> None:
        """添加任务依赖关系（幂等）"""
        with self._lock:
            self.conn.execute(
                "INSERT OR IGNORE INTO task_deps (task_id, depends_on) VALUES (?, ?)",
                (task_id, depends_on),
            )
            self.conn.commit()

    @retry_on_lock
    def remove_dependency(self, task_id: str, depends_on: str) -> bool:
        """删除任务依赖关系，返回是否删除了记录"""
        with self._lock:
            cur = self.conn.execute(
                "DELETE FROM task_deps WHERE task_id = ? AND depends_on = ?",
                (task_id, depends_on),
            )
            self.conn.commit()
        return cur.rowcount > 0

    def list_dependencies(self, task_id: str) -> list[str]:
        """获取 task_id 依赖的所有任务 ID 列表"""
        cur = self.conn.execute(
            "SELECT depends_on FROM task_deps WHERE task_id = ?", (task_id,)
        )
        return [row["depends_on"] for row in cur.fetchall()]

    def list_dependents(self, task_id: str) -> list[str]:
        """获取所有依赖 task_id 的任务 ID 列表（下游任务）"""
        cur = self.conn.execute(
            "SELECT task_id FROM task_deps WHERE depends_on = ?", (task_id,)
        )
        return [row["task_id"] for row in cur.fetchall()]

    def list_blocking_deps(self, task_id: str) -> list[str]:
        """获取阻塞 task_id 的依赖任务 ID（即尚未 done 的前置任务）"""
        cur = self.conn.execute(
            """
            SELECT td.depends_on
            FROM task_deps td
            JOIN tasks t ON td.depends_on = t.id
            WHERE td.task_id = ? AND t.status != 'done'
            """,
            (task_id,),
        )
        return [row["depends_on"] for row in cur.fetchall()]
