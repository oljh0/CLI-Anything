"""终端检测与标识"""

from __future__ import annotations

import hashlib
import os
import platform
import sys


def detect_terminal_type() -> str:
    """自动检测当前终端类型"""
    # 检查 SSH
    if os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_CLIENT"):
        return "ssh"

    # 检查 WSL
    if "microsoft" in platform.uname().release.lower():
        return "wsl"

    if sys.platform == "win32":
        # 检查 PowerShell
        ps_env = os.environ.get("PSModulePath", "")
        if ps_env:
            return "powershell"
        return "cmd"

    # Linux / macOS
    shell = os.environ.get("SHELL", "")
    if "zsh" in shell:
        return "zsh"
    if "bash" in shell:
        return "bash"
    return "unknown"


def generate_terminal_id() -> str:
    """生成基于机器和进程信息的终端 ID"""
    raw = f"{platform.node()}-{os.getpid()}-{os.environ.get('TERM_SESSION_ID', '')}"
    return hashlib.md5(raw.encode()).hexdigest()[:8]


def get_current_pid() -> int:
    """获取当前进程 PID"""
    return os.getpid()
