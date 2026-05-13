"""配置加载与管理"""

from __future__ import annotations

import os
import shutil
import copy
from pathlib import Path
from typing import Any, Optional

import yaml


# 默认配置目录
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".cli-anything")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.yaml")
CONFIG_ENV_VAR = "CLI_ANYTHING_CONFIG"
# 项目内示例配置的可能路径
_EXAMPLE_CONFIG_CANDIDATES = [
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "config", "config.example.yaml"),
]

# 内嵌默认配置
_DEFAULT_CONFIG: dict[str, Any] = {
    "database": {
        "path": os.path.join(CONFIG_DIR, "tasks.db"),
        "wal_mode": True,
        "busy_timeout": 5000,
    },
    "terminal": {
        "role": "worker",
        "name": "",
        "auto_detect": True,
        "id": "",
    },
    "mcp_server": {
        "transport": "stdio",
        "sse_port": 8000,
        "sse_host": "127.0.0.1",
    },
    "dashboard": {
        "port": 8080,
        "host": "127.0.0.1",
        "auto_open": True,
        "refresh_interval": 5,
        "auth": {
            "enabled": False,
            "username": "admin",
            "password": "",
        },
    },
    "testing": {
        "runner": "pytest",
        "default_args": ["-v", "--tb=short"],
        "timeout": 300,
        "auto_run_on_submit": True,
        "test_dir": "tests/",
    },
    "display": {
        "color": True,
        "table_format": "rich",
        "date_format": "%Y-%m-%d %H:%M",
    },
    "notification": {
        "enabled": False,
        "type": "toast",
        "on_status_change": True,
        "on_submit": True,
        "on_verify": True,
    },
    "aliases": {},
}


def _deep_merge(base: dict, override: dict) -> dict:
    """深度合并两个字典，override 覆盖 base"""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


class Config:
    """CLI-Anything 配置管理器"""

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = os.path.expanduser(
            config_path or os.environ.get(CONFIG_ENV_VAR, CONFIG_FILE)
        )
        self._data: dict[str, Any] = {}
        self._loaded = False

    def load(self) -> dict[str, Any]:
        """加载配置文件，与默认值合并"""
        self._data = copy.deepcopy(_DEFAULT_CONFIG)

        if os.path.exists(self.config_path):
            with open(self.config_path, "r", encoding="utf-8") as f:
                user_config = yaml.safe_load(f) or {}
            self._data = _deep_merge(self._data, user_config)

        # 展开路径中的 ~
        db_path = self._data.get("database", {}).get("path", "")
        if db_path.startswith("~"):
            self._data["database"]["path"] = os.path.expanduser(db_path)

        self._loaded = True
        return self._data

    @property
    def data(self) -> dict[str, Any]:
        """获取配置数据（懒加载）"""
        if not self._loaded:
            self.load()
        return self._data

    def get(self, key: str, default: Any = None) -> Any:
        """按点号路径获取配置值，如 'database.path'"""
        parts = key.split(".")
        current = self.data
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return default
        return current

    def set(self, key: str, value: Any) -> None:
        """按点号路径设置配置值并保存"""
        parts = key.split(".")
        current = self.data
        for part in parts[:-1]:
            if part not in current or not isinstance(current[part], dict):
                current[part] = {}
            current = current[part]
        current[parts[-1]] = value
        self.save()

    def save(self) -> None:
        """保存配置到文件"""
        config_dir = os.path.dirname(self.config_path)
        if config_dir:
            os.makedirs(config_dir, exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump(
                self._data,
                f,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
            )

    def init_config(self, role: str = "worker", name: str = "") -> str:
        """初始化配置文件（首次使用），返回配置文件路径"""
        config_dir = os.path.dirname(self.config_path)
        if config_dir:
            os.makedirs(config_dir, exist_ok=True)

        if not os.path.exists(self.config_path):
            # 尝试复制示例配置
            copied = False
            for candidate in _EXAMPLE_CONFIG_CANDIDATES:
                real_path = os.path.normpath(candidate)
                if os.path.exists(real_path):
                    shutil.copy2(real_path, self.config_path)
                    copied = True
                    break
            if not copied:
                # 使用默认配置
                self._data = copy.deepcopy(_DEFAULT_CONFIG)

        self.load()
        if role:
            self.set("terminal.role", role)
        if name:
            self.set("terminal.name", name)
        self.save()
        return self.config_path
