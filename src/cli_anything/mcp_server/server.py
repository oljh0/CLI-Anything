"""MCP Server：暴露任务管理工具给 AI Agent"""

from __future__ import annotations

import json
from typing import Optional

from fastmcp import FastMCP

from cli_anything.core.models import TaskStatus, TaskType, TestStatus
from cli_anything.core.task_manager import TaskManager, TaskManagerError
from cli_anything.storage.database import Database
from cli_anything.utils.config import Config

mcp = FastMCP("CLI-Anything", instructions="跨终端协同任务系统 MCP Server")

# 全局组件（在 serve 时初始化）
_db: Database | None = None
_tm: TaskManager | None = None


def _init_mcp():
    global _db, _tm
    if _db is not None:
        return
    config = Config()
    config.load()
    _db = Database(config.get("database.path"))
    _db.connect()
    _tm = TaskManager(_db, terminal_id="mcp-agent")


def _get_tm() -> TaskManager:
    _init_mcp()
    assert _tm is not None
    return _tm


# ── MCP 工具定义 ─────────────────────────────────────────────

@mcp.tool()
def task_create(
    title: str,
    description: str = "",
    priority: int = 3,
    tags: list[str] | None = None,
) -> dict:
    """创建新任务

    Args:
        title: 任务标题
        description: 任务描述
        priority: 优先级 1-5（1最高）
        tags: 标签列表
    """
    tm = _get_tm()
    try:
        task = tm.create_task(title, description, priority, tags)
        return {"success": True, "task_id": task.id, "title": task.title}
    except TaskManagerError as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
def task_decompose(
    parent_id: str,
    subtasks: list[dict],
) -> dict:
    """将主任务拆解为子任务

    Args:
        parent_id: 父任务 ID
        subtasks: 子任务列表，每项包含 title 和可选的 description, priority, tags
    """
    tm = _get_tm()
    try:
        results = tm.decompose_task(parent_id, subtasks)
        return {
            "success": True,
            "count": len(results),
            "subtasks": [{"id": s.id, "title": s.title} for s in results],
        }
    except TaskManagerError as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
def task_list(
    status: str | None = None,
    task_type: str | None = None,
    parent_id: str | None = None,
    tag: str | None = None,
    limit: int = 50,
) -> dict:
    """列出任务（支持过滤）

    Args:
        status: 按状态过滤 (pending/claimed/in_progress/submitted/done/rejected/blocked/cancelled)
        task_type: 按类型过滤 (master/subtask)
        parent_id: 按父任务 ID 过滤
        tag: 按标签过滤
        limit: 返回数量限制
    """
    tm = _get_tm()
    tasks = tm.list_tasks(
        status=status, task_type=task_type,
        parent_id=parent_id, tag=tag, limit=limit,
    )
    return {
        "count": len(tasks),
        "tasks": [
            {
                "id": t.id, "title": t.title, "status": t.status.value,
                "type": t.task_type.value, "priority": t.priority,
                "tags": t.tags, "parent_id": t.parent_id,
                "claimed_by": t.claimed_by, "test_status": t.test_status.value,
            }
            for t in tasks
        ],
    }


@mcp.tool()
def task_claim(task_id: str) -> dict:
    """领取一个待认领的子任务

    Args:
        task_id: 任务 ID
    """
    tm = _get_tm()
    try:
        task = tm.claim_task(task_id)
        return {"success": True, "task_id": task.id, "status": task.status.value}
    except TaskManagerError as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
def task_submit(task_id: str) -> dict:
    """提交已完成的任务

    Args:
        task_id: 任务 ID
    """
    tm = _get_tm()
    try:
        task = tm.get_task(task_id)
        if not task:
            return {"success": False, "error": f"任务 {task_id} 不存在"}
        # 如果还在 claimed，自动过渡到 in_progress
        if task.status == TaskStatus.CLAIMED:
            tm.start_task(task_id)
        tm.submit_task(task_id)
        return {"success": True, "task_id": task_id, "status": "submitted"}
    except TaskManagerError as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
def task_verify(
    task_id: str,
    approved: bool,
    comment: str = "",
) -> dict:
    """验收任务（通过或驳回）

    Args:
        task_id: 任务 ID
        approved: True=通过, False=驳回
        comment: 验收意见
    """
    tm = _get_tm()
    try:
        task = tm.verify_task(task_id, approved, comment)
        return {
            "success": True, "task_id": task.id,
            "status": task.status.value, "comment": comment,
        }
    except TaskManagerError as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
def task_progress(parent_id: str) -> dict:
    """获取主任务的子任务进度

    Args:
        parent_id: 主任务 ID
    """
    tm = _get_tm()
    return tm.get_progress(parent_id)


@mcp.tool()
def task_update(
    task_id: str,
    title: str | None = None,
    description: str | None = None,
    priority: int | None = None,
    tags: list[str] | None = None,
    test_path: str | None = None,
    work_dir: str | None = None,
) -> dict:
    """更新任务属性

    Args:
        task_id: 任务 ID
        title: 新标题
        description: 新描述
        priority: 新优先级
        tags: 新标签列表
        test_path: 测试文件路径
        work_dir: 工作目录
    """
    tm = _get_tm()
    try:
        task = tm.update_task(
            task_id, title=title, description=description,
            priority=priority, tags=tags,
            test_path=test_path, work_dir=work_dir,
        )
        return {"success": True, "task_id": task.id}
    except TaskManagerError as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
def task_delete(task_id: str) -> dict:
    """删除任务

    Args:
        task_id: 任务 ID
    """
    tm = _get_tm()
    ok = tm.delete_task(task_id)
    return {"success": ok, "task_id": task_id}


@mcp.tool()
def task_log(
    task_id: str | None = None,
    limit: int = 30,
) -> dict:
    """查看任务操作日志

    Args:
        task_id: 任务 ID（留空显示全部）
        limit: 返回条数
    """
    tm = _get_tm()
    logs = tm.get_logs(task_id, limit=limit)
    return {
        "count": len(logs),
        "logs": [
            {
                "timestamp": l.timestamp, "task_id": l.task_id,
                "action": l.action, "terminal_id": l.terminal_id,
                "detail": l.detail,
            }
            for l in logs
        ],
    }


# ── 启动入口 ────────────────────────────────────────────────

def serve():
    """启动 MCP Server"""
    _init_mcp()
    mcp.run()


if __name__ == "__main__":
    serve()
