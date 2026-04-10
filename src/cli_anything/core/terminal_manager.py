"""终端管理：注册、角色分配、活跃状态追踪"""

from __future__ import annotations

from typing import Optional

from cli_anything.core.models import Terminal, TerminalRole, _now_iso
from cli_anything.storage.database import Database
from cli_anything.utils.terminal import detect_terminal_type, generate_terminal_id, get_current_pid
from cli_anything.utils.config import Config


class TerminalManager:
    """终端注册与管理"""

    def __init__(self, db: Database, config: Config):
        self.db = db
        self.config = config
        self._current: Optional[Terminal] = None

    def register_current(self) -> Terminal:
        """注册当前终端，返回 Terminal 实例"""
        cfg = self.config.data.get("terminal", {})
        terminal_id = cfg.get("id") or generate_terminal_id()
        role_str = cfg.get("role", "worker")
        name = cfg.get("name", "")

        terminal = Terminal(
            id=terminal_id,
            name=name or f"{role_str}-{terminal_id[:4]}",
            role=TerminalRole(role_str),
            type=detect_terminal_type(),
            pid=get_current_pid(),
            last_active=_now_iso(),
        )

        self.db.upsert_terminal(terminal)
        self._current = terminal

        # 持久化终端 ID 到配置
        if not cfg.get("id"):
            self.config.set("terminal.id", terminal_id)

        return terminal

    @property
    def current(self) -> Terminal:
        """获取当前终端（懒注册）"""
        if self._current is None:
            self._current = self.register_current()
        return self._current

    def heartbeat(self) -> None:
        """更新活跃时间"""
        t = self.current
        t.last_active = _now_iso()
        self.db.upsert_terminal(t)

    def list_all(self) -> list[Terminal]:
        """列出所有注册终端"""
        return self.db.list_terminals()

    def is_master(self) -> bool:
        """当前终端是否为主终端"""
        return self.current.role == TerminalRole.MASTER
