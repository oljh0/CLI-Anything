"""MCP Server 终端注册与推荐测试"""

import pytest

from cli_anything.core.models import Terminal, TerminalRole
from cli_anything.core.task_manager import TaskManager
from cli_anything.storage.database import Database


@pytest.fixture
def mcp_env(tmp_path):
    from cli_anything.mcp_server import server as mcp_mod

    db = Database(str(tmp_path / "test.db"))
    db.connect()
    tm = TaskManager(db, terminal_id="mcp-agent")
    tm.register_terminal(Terminal(id="mcp-agent", name="MCP", role=TerminalRole.WORKER))

    mcp_mod._db = db
    mcp_mod._tm = tm
    mcp_mod._config = None
    mcp_mod._agent_terminal_id = "mcp-agent"
    yield mcp_mod, tm, db
    mcp_mod._db = None
    mcp_mod._tm = None
    mcp_mod._config = None
    mcp_mod._agent_terminal_id = "mcp-agent"
    db.close()


def test_task_suggest_uses_default_agent_terminal(mcp_env):
    """task_suggest 不传 terminal_id 时应使用当前 MCP Agent"""
    mcp_mod, tm, _ = mcp_env
    tm.update_capabilities("mcp-agent", ["python"])
    task = tm.create_task("Python 任务", tags=["python"])

    result = mcp_mod.task_suggest()

    assert result["ok"] is True
    assert result["tasks"][0]["id"] == task.id
    assert result["tasks"][0]["tags"] == ["python"]


def test_task_update_capabilities_defaults_to_agent(mcp_env):
    """task_update_capabilities 留空 terminal_id 时更新当前 MCP Agent"""
    mcp_mod, _, db = mcp_env

    result = mcp_mod.task_update_capabilities(capabilities=["backend", "api"])

    assert result == {
        "success": True,
        "terminal_id": "mcp-agent",
        "capabilities": ["backend", "api"],
    }
    assert db.get_terminal("mcp-agent").capabilities == ["backend", "api"]


def test_task_register_terminal(mcp_env):
    """task_register_terminal 应注册指定终端"""
    mcp_mod, _, db = mcp_env

    result = mcp_mod.task_register_terminal(
        terminal_id="agent-2",
        role="worker",
        name="Agent 2",
        capabilities=["docs"],
    )

    assert result["success"] is True
    terminal = db.get_terminal("agent-2")
    assert terminal.name == "Agent 2"
    assert terminal.capabilities == ["docs"]
