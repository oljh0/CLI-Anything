"""MCP Server：暴露任务管理工具给 AI Agent"""

from __future__ import annotations

import json
import threading
from typing import Optional

from fastmcp import FastMCP

from cli_anything.core.models import TaskStatus, TaskType, TestStatus, ReviewStatus
from cli_anything.core.task_manager import TaskManager, TaskManagerError
from cli_anything.storage.database import Database
from cli_anything.utils.config import Config

mcp = FastMCP("CLI-Anything", instructions="跨终端协同任务系统 MCP Server")

# 全局组件（在 serve 时初始化）
_db: Database | None = None
_config: Config | None = None
_tm: TaskManager | None = None
_init_lock = threading.Lock()


def _init_mcp():
    global _db, _config, _tm
    if _db is not None:
        return
    with _init_lock:
        if _db is not None:
            return
        _config = Config()
        _config.load()
        _db = Database(_config.get("database.path"))
        _db.connect()
        _tm = TaskManager(_db, terminal_id="mcp-agent")


def _get_tm() -> TaskManager:
    _init_mcp()
    assert _tm is not None
    return _tm


def _get_db() -> Database:
    _init_mcp()
    assert _db is not None
    return _db


# ── MCP 工具定义 ─────────────────────────────────────────────

@mcp.tool()
def task_create(
    title: str,
    description: str = "",
    priority: int = 3,
    tags: list[str] | None = None,
    reviewer: str | None = None,
) -> dict:
    """创建新任务

    Args:
        title: 任务标题
        description: 任务描述
        priority: 优先级 1-5（1最高）
        tags: 标签列表
        reviewer: 审阅者终端 ID（指定后任务进入 draft 状态等待审阅）
    """
    tm = _get_tm()
    try:
        task = tm.create_task(title, description, priority, tags, reviewer=reviewer)
        result = {"success": True, "task_id": task.id, "title": task.title, "status": task.status.value}
        if reviewer:
            result["reviewer"] = reviewer
            result["review_status"] = task.review_status.value
        return result
    except TaskManagerError as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
def task_decompose(
    parent_id: str,
    subtasks: list[dict],
    reviewer: str | None = None,
) -> dict:
    """将主任务拆解为子任务

    Args:
        parent_id: 父任务 ID
        subtasks: 子任务列表，每项包含 title 和可选的 description, priority, tags
        reviewer: 审阅者终端 ID（指定后子任务进入 draft 状态）
    """
    tm = _get_tm()
    try:
        results = tm.decompose_task(parent_id, subtasks, reviewer=reviewer)
        result = {
            "success": True,
            "count": len(results),
            "subtasks": [{"id": s.id, "title": s.title, "status": s.status.value} for s in results],
        }
        if reviewer:
            result["reviewer"] = reviewer
        return result
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
def task_show(task_id: str) -> dict:
    """获取单个任务的完整详情（含子任务列表）

    Args:
        task_id: 任务 ID
    """
    tm = _get_tm()
    task = tm.get_task(task_id)
    if not task:
        return {"success": False, "error": f"任务 {task_id} 不存在"}

    result = {
        "success": True,
        "task": {
            "id": task.id, "title": task.title, "description": task.description,
            "status": task.status.value, "type": task.task_type.value,
            "priority": task.priority, "tags": task.tags,
            "parent_id": task.parent_id,
            "created_by": task.created_by, "claimed_by": task.claimed_by,
            "claimed_at": task.claimed_at, "submitted_at": task.submitted_at,
            "verified_by": task.verified_by, "verified_at": task.verified_at,
            "verify_comment": task.verify_comment,
            "test_status": task.test_status.value, "test_report": task.test_report,
            "test_path": task.test_path, "work_dir": task.work_dir,
            "created_at": task.created_at, "updated_at": task.updated_at,
        },
    }

    subtasks = tm.list_subtasks(task.id)
    if subtasks:
        progress = tm.get_progress(task.id)
        result["subtasks"] = [
            {"id": s.id, "title": s.title, "status": s.status.value, "priority": s.priority}
            for s in subtasks
        ]
        result["progress"] = progress

    return result


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
def task_unclaim(task_id: str) -> dict:
    """释放已领取的任务（归还为 pending 状态）

    Args:
        task_id: 任务 ID
    """
    tm = _get_tm()
    try:
        task = tm.unclaim_task(task_id)
        return {"success": True, "task_id": task.id, "status": task.status.value}
    except TaskManagerError as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
def task_start(task_id: str) -> dict:
    """开始工作（claimed/rejected → in_progress）

    Args:
        task_id: 任务 ID
    """
    tm = _get_tm()
    try:
        task = tm.start_task(task_id)
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
    try:
        task = tm.get_task(parent_id)
        if not task:
            return {"success": False, "error": f"任务 {parent_id} 不存在"}
        result = tm.get_progress(parent_id)
        result["success"] = True
        return result
    except TaskManagerError as e:
        return {"success": False, "error": str(e)}


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
    if ok:
        return {"success": True, "task_id": task_id}
    return {"success": False, "error": f"任务 {task_id} 不存在或删除失败"}


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


@mcp.tool()
def task_review(
    task_id: str,
    approved: bool,
    comment: str = "",
) -> dict:
    """审阅任务定义（通过后进入 pending 可领取，驳回则留在 draft）

    Args:
        task_id: 任务 ID
        approved: True=通过, False=驳回
        comment: 审阅意见
    """
    tm = _get_tm()
    try:
        task = tm.review_task(task_id, approved, comment)
        return {
            "success": True, "task_id": task.id,
            "status": task.status.value,
            "review_status": task.review_status.value,
            "comment": comment,
        }
    except TaskManagerError as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
def task_resubmit_review(
    task_id: str,
    reviewer: str | None = None,
) -> dict:
    """重新提交审阅（审阅被驳回后修改再提交）

    Args:
        task_id: 任务 ID
        reviewer: 新审阅者终端 ID（留空沿用原审阅者）
    """
    tm = _get_tm()
    try:
        task = tm.resubmit_for_review(task_id, reviewer=reviewer)
        return {
            "success": True, "task_id": task.id,
            "reviewer": task.reviewer,
            "review_status": task.review_status.value,
        }
    except TaskManagerError as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
def task_test(
    task_id: str,
    timeout: int = 300,
) -> dict:
    """运行任务关联的测试

    Args:
        task_id: 任务 ID（需提前设置 test_path）
        timeout: 测试超时秒数（默认300）
    """
    tm = _get_tm()
    try:
        task = tm.get_task(task_id)
        if not task:
            return {"success": False, "error": f"任务 {task_id} 不存在"}
        if not task.test_path:
            return {"success": False, "error": "任务未设置 test_path，请先用 task_update 设置"}

        from cli_anything.core.test_runner import run_tests_simple

        report = run_tests_simple(
            test_path=task.test_path,
            work_dir=task.work_dir or None,
            timeout=timeout,
        )

        test_status = TestStatus.PASSED if report.success else TestStatus.FAILED
        tm.update_test_result(task_id, test_status, report.to_dict())

        return {
            "success": True,
            "task_id": task_id,
            "test_status": test_status.value,
            "report": {
                "total": report.total, "passed": report.passed,
                "failed": report.failed, "errors": report.errors,
                "skipped": report.skipped, "duration": round(report.duration, 2),
                "exit_code": report.exit_code,
            },
            "details": report.details,
        }
    except TaskManagerError as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
def task_health(
    timeout: int = 60,
    cleanup: bool = False,
) -> dict:
    """检查终端健康状态，可选自动清理超时终端的任务占用

    Args:
        timeout: 终端超时阈值（秒，默认60）
        cleanup: 是否自动释放超时终端占用的任务
    """
    db = _get_db()
    from cli_anything.core.health_checker import TerminalHealthChecker

    checker = TerminalHealthChecker(db, timeout_seconds=timeout)
    stale = checker.list_stale_terminals()

    result = {
        "success": True,
        "stale_count": len(stale),
        "stale_terminals": [
            {"id": t.id, "name": t.name, "last_active": t.last_active}
            for t in stale
        ],
    }

    if cleanup and stale:
        released = checker.cleanup_stale_claims()
        result["released_tasks"] = released
        result["released_count"] = len(released)

    return result


# ── 启动入口 ────────────────────────────────────────────────

def serve():
    """启动 MCP Server（支持 stdio / sse 传输）"""
    _init_mcp()
    transport = _config.get("mcp_server.transport", "stdio")
    if transport == "sse":
        host = _config.get("mcp_server.sse_host", "127.0.0.1")
        port = _config.get("mcp_server.sse_port", 8000)
        mcp.run(transport="sse", host=host, port=port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    serve()
