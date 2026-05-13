"""终端管理：注册、角色分配、活跃状态追踪"""

from __future__ import annotations

import os
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

    def register_current(
        self,
        role: Optional[str] = None,
        name: Optional[str] = None,
        terminal_id: Optional[str] = None,
        capabilities: Optional[list[str]] = None,
        persist_id: bool = False,
    ) -> Terminal:
        """注册当前终端，返回 Terminal 实例"""
        cfg = self.config.data.get("terminal", {})
        env_id = os.environ.get("CLI_ANYTHING_TERMINAL_ID", "")
        env_role = os.environ.get("CLI_ANYTHING_TERMINAL_ROLE", "")
        env_name = os.environ.get("CLI_ANYTHING_TERMINAL_NAME", "")

        terminal_id = terminal_id or env_id or cfg.get("id") or generate_terminal_id()
        role_str = role or env_role or cfg.get("role", "worker")
        terminal_name = name or env_name or cfg.get("name", "")
        existing = self.db.get_terminal(terminal_id)

        terminal = Terminal(
            id=terminal_id,
            name=terminal_name or (existing.name if existing else "") or f"{role_str}-{terminal_id[:4]}",
            role=TerminalRole(role_str),
            type=detect_terminal_type(),
            pid=get_current_pid(),
            capabilities=capabilities if capabilities is not None else (existing.capabilities if existing else []),
            last_active=_now_iso(),
            registered_at=existing.registered_at if existing else _now_iso(),
        )

        self.db.upsert_terminal(terminal)
        self._current = terminal

        # 持久化终端 ID 到配置
        if persist_id or (not cfg.get("id") and not env_id):
            self.config.set("terminal.id", terminal_id)
        if persist_id and role:
            self.config.set("terminal.role", role)
        if persist_id and name:
            self.config.set("terminal.name", name)

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
