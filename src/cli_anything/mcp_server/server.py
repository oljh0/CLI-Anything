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
def task_submit(
    task_id: str,
    summary: str = "",
    changed_files: list = None,
    test_note: str = "",
    risks: str = "",
) -> dict:
    """提交已完成的任务，可附带结构化交付信封（ATL Envelope 规范）

    Args:
        task_id: 任务 ID
        summary: 实现内容摘要（推荐填写），如"实现了用户登录接口，支持 OAuth2"
        changed_files: 本次修改的文件列表，如 ["src/auth.py", "tests/test_auth.py"]
        test_note: 测试通过情况说明，如"全部 12 个测试通过，覆盖率 87%"
        risks: 发现的风险或副作用，如"修改了 API 签名，需更新调用方"；无风险填 "None"
    """
    tm = _get_tm()
    try:
        task = tm.get_task(task_id)
        if not task:
            return {"success": False, "error": f"任务 {task_id} 不存在"}
        # 如果还在 claimed，自动过渡到 in_progress
        if task.status == TaskStatus.CLAIMED:
            tm.start_task(task_id)
        task = tm.submit_task(task_id, summary=summary, changed_files=changed_files, test_note=test_note, risks=risks)
        result: dict = {"success": True, "task_id": task_id, "status": "submitted"}
        if task.test_report:
            envelope = {k: v for k, v in task.test_report.items() if k.startswith("submit_")}
            if envelope:
                result["envelope"] = envelope
        return result
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


@mcp.tool()
def task_judgment_day(task_id: str, project_standards: str = "") -> dict:
    """为 submitted 状态的任务启动双盲对抗审查（Judgment Day）

    创建两个独立的 REVIEW 任务（Judge A 和 Judge B），
    供不同 Worker 独立认领并审查，互不知晓对方结论。

    项目规范自动注入（Skill Registry 风格）：
    若未传 project_standards，将自动按优先级扫描项目中的规范文件：
    .atl/skill-registry.md → CLAUDE.md → AGENTS.md →
    .github/copilot-instructions.md → .copilot/instructions.md。
    找到内容则自动注入到两个 judge 任务描述中。

    Args:
        task_id: 待审查的任务 ID（必须处于 submitted 状态）
        project_standards: 可选的项目规范摘要（代码风格/约定/禁忌），
                           若留空则自动从任务的 work_dir 读取规范文件。
                           示例: "使用 Python 3.10+类型注解，函数注释用中文，
                                  禁止直接操作 DB 绕过 TaskManager"
    """
    tm = _get_tm()
    try:
        judge_a, judge_b = tm.trigger_judgment_day(task_id, project_standards=project_standards)
        # 记录实际是否注入了规范（可能来自自动扫描）
        auto_scanned = not bool(project_standards.strip())
        standards_injected = bool(judge_a.description and "项目规范" in judge_a.description)
        return {
            "success": True,
            "task_id": task_id,
            "judge_a": {"id": judge_a.id, "title": judge_a.title, "status": judge_a.status.value},
            "judge_b": {"id": judge_b.id, "title": judge_b.title, "status": judge_b.status.value},
            "message": "双盲审查已启动，请由两个不同的 Worker 分别认领 judge_a 和 judge_b 任务",
            "standards_injected": standards_injected,
            "standards_auto_scanned": auto_scanned and standards_injected,
        }
    except TaskManagerError as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
def task_get_project_standards(work_dir: str = "") -> dict:
    """扫描项目规范文件并返回内容（Skill Registry 风格）

    按优先级扫描项目根目录中的规范文件：
    .atl/skill-registry.md → CLAUDE.md → AGENTS.md →
    .github/copilot-instructions.md → .copilot/instructions.md

    可用于在手动调用 task_judgment_day 前预览将要注入的规范内容。

    Args:
        work_dir: 项目根目录路径。为空时使用当前工作目录。
    """
    tm = _get_tm()
    content = tm.get_project_standards(work_dir)
    return {
        "found": bool(content),
        "content": content,
        "work_dir": work_dir or str(__import__("pathlib").Path.cwd()),
    }


@mcp.tool()
def task_add_note(task_id: str, note: str, note_type: str = "general") -> dict:
    """为任务追加上下文笔记（Engram 风格）

    记录任务执行过程中的关键决策、技术发现、潜在风险等信息，
    供后续 Worker 或 Master 查阅。笔记不影响任务状态。

    Args:
        task_id: 任务 ID
        note: 笔记内容
        note_type: 类型，建议值：
                   "discovery"（技术发现）、"decision"（设计决策）、
                   "warning"（潜在风险）、"context"（上下文背景）、"general"（通用）
    """
    tm = _get_tm()
    try:
        task = tm.add_task_note(task_id, note, note_type)
        notes = task.test_report.get("task_notes", [])
        return {
            "success": True,
            "task_id": task_id,
            "notes_count": len(notes),
            "latest_note": notes[-1] if notes else None,
        }
    except TaskManagerError as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
def task_get_notes(task_id: str) -> dict:
    """获取任务的所有上下文笔记

    Args:
        task_id: 任务 ID
    """
    tm = _get_tm()
    try:
        notes = tm.get_task_notes(task_id)
        return {
            "success": True,
            "task_id": task_id,
            "notes_count": len(notes),
            "notes": notes,
        }
    except TaskManagerError as e:
        return {"success": False, "error": str(e)}



@mcp.tool()
def task_submit_verdict(
    review_task_id: str,
    verdict: str,
    findings: list = None,
    summary: str = "",
) -> dict:
    """提交审查裁决（在 claimed 或 in_progress 的 review 任务上调用）

    Args:
        review_task_id: 审查任务 ID（task_type 为 review）
        verdict: "clean"（无问题）或 "issues"（发现问题）
        findings: 发现的问题列表，每项格式:
                  [{"desc": "问题描述", "severity": "CRITICAL|WARNING|SUGGESTION", "location": "文件:行号"}]
        summary: 一句话审查总结
    """
    tm = _get_tm()
    try:
        task = tm.submit_verdict(
            review_task_id=review_task_id,
            verdict=verdict,
            findings=findings,
            summary=summary,
        )
        return {
            "success": True,
            "review_task_id": review_task_id,
            "verdict": verdict,
            "findings_count": len(findings or []),
            "status": task.status.value,
        }
    except TaskManagerError as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
def task_get_reviews(task_id: str) -> dict:
    """获取某任务的所有审查任务

    Args:
        task_id: 被审查的原始任务 ID
    """
    tm = _get_tm()
    reviews = tm.get_review_tasks(task_id)
    return {
        "success": True,
        "task_id": task_id,
        "count": len(reviews),
        "reviews": [
            {
                "id": t.id,
                "title": t.title,
                "status": t.status.value,
                "tags": t.tags,
                "verdict": (t.test_report or {}).get("verdict"),
            }
            for t in reviews
        ],
    }


@mcp.tool()
def task_synthesize(task_id: str) -> dict:
    """综合两份审查裁决，生成对比分析报告

    对比 Judge A 和 Judge B 的发现，分类为 confirmed / suspect_a / suspect_b，
    并给出 recommendation（approve / fix / escalated）。

    Args:
        task_id: 被审查的原始任务 ID
    """
    tm = _get_tm()
    try:
        result = tm.synthesize_judgment(task_id)
        return {"success": True, **result}
    except TaskManagerError as e:
        return {"success": False, "error": str(e)}


# ── 任务依赖图（DAG）────────────────────────────────────────────

@mcp.tool()
def task_add_dep(task_id: str, depends_on: str) -> dict:
    """为任务添加前置依赖（task_id 必须等待 depends_on 完成后才能被领取）

    Args:
        task_id: 需要等待前置任务的任务 ID
        depends_on: 前置任务 ID（必须先 done）

    Returns:
        操作确认信息
    """
    tm = _get_tm()
    try:
        tm.add_dependency(task_id, depends_on)
        return {"ok": True, "task_id": task_id, "depends_on": depends_on,
                "message": f"已添加依赖：{task_id} 依赖 {depends_on}"}
    except TaskManagerError as e:
        return {"ok": False, "error": str(e)}


@mcp.tool()
def task_remove_dep(task_id: str, depends_on: str) -> dict:
    """移除任务的前置依赖

    Args:
        task_id: 任务 ID
        depends_on: 要移除的前置任务 ID

    Returns:
        操作确认信息
    """
    tm = _get_tm()
    try:
        tm.remove_dependency(task_id, depends_on)
        return {"ok": True, "task_id": task_id, "depends_on": depends_on,
                "message": f"已移除依赖：{task_id} 不再依赖 {depends_on}"}
    except TaskManagerError as e:
        return {"ok": False, "error": str(e)}


@mcp.tool()
def task_get_deps(task_id: str) -> dict:
    """获取任务的依赖关系详情（前置依赖、下游依赖、当前阻塞状态）

    Args:
        task_id: 任务 ID

    Returns:
        依赖关系信息：depends_on（前置）、depended_by（下游）、blocking（阻塞列表）、is_blocked
    """
    tm = _get_tm()
    try:
        return tm.get_dependencies(task_id)
    except TaskManagerError as e:
        return {"ok": False, "error": str(e)}


# ── 工具 25~26：Supervisor 自动路由 ──────────────────────────────────


@mcp.tool()
def task_route(task_id: str) -> dict:
    """【工具 25】为任务推荐候选终端（Supervisor 视角）

    根据任务 tags 与终端 capabilities 的交集，返回最适合处理该任务的 Worker 终端列表。
    若任务无 tags 则返回所有活跃 Worker 终端。

    Args:
        task_id: 任务 ID

    Returns:
        candidates：候选终端列表，每项含 terminal_id、name、role、matched_tags、capabilities
    """
    tm = _get_tm()
    try:
        candidates = tm.route_task(task_id)
        return {"ok": True, "candidates": candidates}
    except TaskManagerError as e:
        return {"ok": False, "error": str(e)}


@mcp.tool()
def task_suggest(terminal_id: str | None = None, limit: int = 10) -> dict:
    """【工具 26】为终端推荐候选任务（Worker 视角）

    根据终端 capabilities 与任务 tags 的交集过滤 pending 任务，按优先级排序。
    capabilities 为空时返回全量 pending 任务。无交集时 fallback 到全量。

    Args:
        terminal_id: 终端 ID，默认使用当前 mcp-agent 终端
        limit: 最多返回条数，默认 10

    Returns:
        tasks：推荐任务列表（Task 字典）
    """
    tm = _get_tm()
    tid = terminal_id or _get_agent_terminal_id()
    try:
        tasks = tm.suggest_tasks(tid, limit=limit)
        return {"ok": True, "tasks": [t.to_dict() for t in tasks]}
    except TaskManagerError as e:
        return {"ok": False, "error": str(e)}


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
