"""CLI 命令层：使用 typer 实现角色化命令"""

from __future__ import annotations

import json
import os
import sys
from typing import Optional

import typer
import yaml
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

from cli_anything import __version__
from cli_anything.core.models import TaskStatus, TaskType, TestStatus, ReviewStatus, TerminalRole
from cli_anything.core.task_manager import TaskManager, TaskManagerError
from cli_anything.core.terminal_manager import TerminalManager
from cli_anything.core.test_runner import run_tests_simple
from cli_anything.storage.database import Database
from cli_anything.utils.config import Config
from cli_anything.notification.notifier import Notifier

app = typer.Typer(
    name="cli-anything",
    help="跨终端协同任务系统 — Master/Worker 协同开发",
    no_args_is_help=True,
)

config_app = typer.Typer(help="查看和修改配置")
app.add_typer(config_app, name="config")

console = Console()

# ── 全局上下文 ──────────────────────────────────────────────

_db: Database | None = None
_config: Config | None = None
_tm: TaskManager | None = None
_term_mgr: TerminalManager | None = None


def _init():
    """初始化全局组件"""
    global _db, _config, _tm, _term_mgr
    if _db is not None:
        return

    _config = Config()
    _config.load()
    db_path = _config.get("database.path")
    _db = Database(db_path)
    _db.connect()
    _term_mgr = TerminalManager(_db, _config)
    notifier = Notifier(_config)
    _tm = TaskManager(_db, terminal_id=_term_mgr.current.id, notifier=notifier)


def _get_tm() -> TaskManager:
    _init()
    assert _tm is not None
    return _tm


def _get_term_mgr() -> TerminalManager:
    _init()
    assert _term_mgr is not None
    return _term_mgr


# ── 状态颜色映射 ────────────────────────────────────────────

STATUS_COLORS = {
    "draft": "bright_yellow",
    "pending": "yellow",
    "claimed": "cyan",
    "in_progress": "blue",
    "submitted": "magenta",
    "done": "green",
    "rejected": "red",
    "blocked": "bright_black",
    "cancelled": "dim",
}

PRIORITY_LABELS = {1: "🔴 紧急", 2: "🟠 高", 3: "🟡 中", 4: "🟢 低", 5: "⚪ 最低"}

REVIEW_STATUS_LABELS = {
    "not_required": "—",
    "pending_review": "⏳ 待审阅",
    "approved": "✅ 已通过",
    "rejected": "❌ 已驳回",
}


def _select_reviewer() -> Optional[str]:
    """交互式选择审阅者终端"""
    _init()
    assert _db is not None
    terminals = _db.list_terminals()
    current_id = _term_mgr.current.id if _term_mgr else ""

    # 排除当前终端（不能审阅自己的任务）
    candidates = [t for t in terminals if t.id != current_id]
    if not candidates:
        console.print("[yellow]⚠[/yellow] 没有其他已注册的终端可供选择")
        return None

    console.print("\n[bold]选择审阅者终端:[/bold]")
    for i, t in enumerate(candidates, 1):
        role_badge = "👑" if t.role.value == "master" else "🔧"
        console.print(f"  {i}. {role_badge} {t.id} ({t.name or '未命名'}) — {t.role.value}")
    console.print(f"  0. 跳过（不审阅）")

    try:
        choice = typer.prompt("请输入编号", type=int, default=0)
        if choice == 0:
            return None
        if 1 <= choice <= len(candidates):
            selected = candidates[choice - 1]
            console.print(f"  → 已选择: [cyan]{selected.id}[/cyan]")
            return selected.id
        console.print("[red]无效的编号[/red]")
        return None
    except (ValueError, typer.Abort):
        return None


# ── 终端注册与 init 命令 ─────────────────────────────────────

@app.command()
def register(
    role: str = typer.Option("worker", help="终端角色: master / worker"),
    name: str = typer.Option("", help="终端名称"),
    terminal_id: Optional[str] = typer.Option(None, "--id", help="终端 ID（留空自动生成）"),
    capabilities: Optional[str] = typer.Option(None, "--capabilities", help="技能/标签，逗号分隔"),
):
    """注册当前终端"""
    config = Config()
    config.load()
    db = Database(config.get("database.path"))
    db.connect()
    term_mgr = TerminalManager(db, config)
    cap_list = [c.strip() for c in capabilities.split(",") if c.strip()] if capabilities else None
    try:
        terminal = term_mgr.register_current(
            role=role,
            name=name,
            terminal_id=terminal_id,
            capabilities=cap_list,
            persist_id=True,
        )
        console.print(
            f"[green]✓[/green] 终端已注册: [bold]{terminal.id}[/bold] "
            f"({terminal.role.value}) — {terminal.name}"
        )
        if terminal.capabilities:
            console.print(f"  能力: {', '.join(terminal.capabilities)}")
    except ValueError as e:
        console.print(f"[red]✗[/red] 无效终端角色: {role}")
        raise typer.Exit(1) from e
    finally:
        db.close()


@app.command()
def heartbeat():
    """发送当前终端心跳"""
    term_mgr = _get_term_mgr()
    term_mgr.heartbeat()
    console.print(f"[green]✓[/green] 心跳已更新: {term_mgr.current.id}")

@app.command()
def init(
    role: str = typer.Option("worker", help="终端角色: master / worker"),
    name: str = typer.Option("", help="终端名称"),
):
    """初始化配置与数据库"""
    config = Config()
    path = config.init_config(role=role, name=name)
    console.print(f"[green]✓[/green] 配置文件已创建: {path}")

    # 初始化数据库
    config.load()
    db = Database(config.get("database.path"))
    db.connect()
    console.print(f"[green]✓[/green] 数据库已初始化: {config.get('database.path')}")

    # 注册终端
    tm = TerminalManager(db, config)
    t = tm.register_current(role=role, name=name, persist_id=True)
    console.print(f"[green]✓[/green] 终端已注册: {t.id} ({t.role.value})")
    db.close()


# ── 任务操作命令 ─────────────────────────────────────────────

@app.command()
def create(
    title: str = typer.Argument(..., help="任务标题"),
    desc: str = typer.Option("", "--desc", "-d", help="任务描述"),
    priority: int = typer.Option(3, "--priority", "-p", help="优先级 1-5"),
    tags: Optional[str] = typer.Option(None, "--tags", "-t", help="标签，逗号分隔"),
    review: bool = typer.Option(False, "--review", "-r", help="创建后发送审阅"),
    reviewer: Optional[str] = typer.Option(None, "--reviewer", help="指定审阅者终端 ID"),
):
    """创建新任务（Master）"""
    tm = _get_tm()
    tag_list = [t.strip() for t in tags.split(",")] if tags else []

    reviewer_id = reviewer
    if review and not reviewer_id:
        reviewer_id = _select_reviewer()
        if not reviewer_id:
            console.print("[yellow]⚠[/yellow] 未选择审阅者，任务将直接进入 pending 状态")

    try:
        task = tm.create_task(title, desc, priority, tag_list, reviewer=reviewer_id)
        status_label = f"[bright_yellow]draft（待审阅）[/bright_yellow]" if reviewer_id else "[yellow]pending[/yellow]"
        console.print(f"[green]✓[/green] 任务已创建: [bold]{task.id}[/bold] — {task.title}  {status_label}")
        if reviewer_id:
            console.print(f"  📋 审阅者: {reviewer_id}")
    except TaskManagerError as e:
        console.print(f"[red]✗[/red] {e}")
        raise typer.Exit(1)


@app.command()
def decompose(
    parent_id: str = typer.Argument(..., help="父任务 ID"),
    subtasks_json: str = typer.Argument(..., help='子任务 JSON，如 \'[{"title":"子任务1"},{"title":"子任务2"}]\''),
    review: bool = typer.Option(False, "--review", "-r", help="子任务创建后发送审阅"),
    reviewer: Optional[str] = typer.Option(None, "--reviewer", help="指定审阅者终端 ID"),
):
    """拆解任务为子任务（Master）"""
    tm = _get_tm()

    reviewer_id = reviewer
    if review and not reviewer_id:
        reviewer_id = _select_reviewer()
        if not reviewer_id:
            console.print("[yellow]⚠[/yellow] 未选择审阅者，子任务将直接进入 pending 状态")

    try:
        subs = json.loads(subtasks_json)
        results = tm.decompose_task(parent_id, subs, reviewer=reviewer_id)
        status_label = "draft（待审阅）" if reviewer_id else "pending"
        console.print(f"[green]✓[/green] 已拆解为 {len(results)} 个子任务 [{status_label}]:")
        for s in results:
            console.print(f"  • {s.id} — {s.title}")
        if reviewer_id:
            console.print(f"  📋 审阅者: {reviewer_id}")
    except (json.JSONDecodeError, TaskManagerError) as e:
        console.print(f"[red]✗[/red] {e}")
        raise typer.Exit(1)


@app.command(name="ls")
@app.command(name="list")
def list_tasks(
    status: Optional[str] = typer.Option(None, "--status", "-s", help="按状态过滤"),
    task_type: Optional[str] = typer.Option(None, "--type", help="按类型过滤: master/subtask/review"),
    parent: Optional[str] = typer.Option(None, "--parent", help="按父任务 ID 过滤"),
    tag: Optional[str] = typer.Option(None, "--tag", help="按标签过滤"),
    json_output: bool = typer.Option(False, "--json", help="输出 JSON"),
):
    """列出任务"""
    tm = _get_tm()
    tasks = tm.list_tasks(
        status=status,
        task_type=task_type,
        parent_id=parent,
        tag=tag,
    )

    if json_output:
        console.print(json.dumps([t.to_api_dict() for t in tasks], ensure_ascii=False, indent=2))
        return

    if not tasks:
        console.print("[dim]没有匹配的任务[/dim]")
        return

    table = Table(title="任务列表", show_lines=True)
    table.add_column("ID", style="bold", width=10)
    table.add_column("标题", width=30)
    table.add_column("状态", width=12)
    table.add_column("优先级", width=8)
    table.add_column("类型", width=8)
    table.add_column("领取者", width=10)

    for t in tasks:
        color = STATUS_COLORS.get(t.status.value, "white")
        table.add_row(
            t.id,
            t.title,
            f"[{color}]{t.status.value}[/{color}]",
            PRIORITY_LABELS.get(t.priority, str(t.priority)),
            t.task_type.value,
            t.claimed_by or "—",
        )

    console.print(table)


@app.command()
def show(task_id: str = typer.Argument(..., help="任务 ID")):
    """查看任务详情"""
    tm = _get_tm()
    task = tm.get_task(task_id)
    if not task:
        console.print(f"[red]✗[/red] 任务 {task_id} 不存在")
        raise typer.Exit(1)

    color = STATUS_COLORS.get(task.status.value, "white")
    review_line = ""
    if task.review_status.value != "not_required":
        review_label = REVIEW_STATUS_LABELS.get(task.review_status.value, task.review_status.value)
        review_line = (
            f"\n[bold]审阅状态:[/bold] {review_label}"
            f"\n[bold]审阅者:[/bold] {task.reviewer or '未指定'}"
        )
        if task.review_comment:
            review_line += f"\n[bold]审阅意见:[/bold] {task.review_comment}"

    panel_content = (
        f"[bold]标题:[/bold] {task.title}\n"
        f"[bold]描述:[/bold] {task.description or '无'}\n"
        f"[bold]状态:[/bold] [{color}]{task.status.value}[/{color}]\n"
        f"[bold]类型:[/bold] {task.task_type.value}\n"
        f"[bold]优先级:[/bold] {PRIORITY_LABELS.get(task.priority, str(task.priority))}\n"
        f"[bold]标签:[/bold] {', '.join(task.tags) or '无'}\n"
        f"[bold]父任务:[/bold] {task.parent_id or '无'}\n"
        f"[bold]创建者:[/bold] {task.created_by}\n"
        f"[bold]领取者:[/bold] {task.claimed_by or '无'}\n"
        f"[bold]测试状态:[/bold] {task.test_status.value}"
        f"{review_line}\n"
        f"[bold]创建时间:[/bold] {task.created_at}\n"
        f"[bold]更新时间:[/bold] {task.updated_at}"
    )
    console.print(Panel(panel_content, title=f"任务 {task.id}", border_style=color))

    # 如有子任务，显示进度
    subtasks = tm.list_subtasks(task.id)
    if subtasks:
        progress = tm.get_progress(task.id)
        console.print(f"\n📊 进度: {progress['done']}/{progress['total']} ({progress['progress']}%)")
        for s in subtasks:
            c = STATUS_COLORS.get(s.status.value, "white")
            console.print(f"  [{c}]●[/{c}] {s.id} — {s.title} [{c}]{s.status.value}[/{c}]")


@app.command()
def claim(task_id: str = typer.Argument(..., help="任务 ID")):
    """领取任务（Worker）"""
    tm = _get_tm()
    try:
        task = tm.claim_task(task_id)
        console.print(f"[green]✓[/green] 已领取任务: {task.id} — {task.title}")
    except TaskManagerError as e:
        console.print(f"[red]✗[/red] {e}")
        raise typer.Exit(1)


@app.command()
def unclaim(task_id: str = typer.Argument(..., help="任务 ID")):
    """释放已领取的任务（Worker）"""
    tm = _get_tm()
    try:
        task = tm.unclaim_task(task_id)
        console.print(f"[green]✓[/green] 已释放任务: {task.id}")
    except TaskManagerError as e:
        console.print(f"[red]✗[/red] {e}")
        raise typer.Exit(1)


@app.command()
def start(task_id: str = typer.Argument(..., help="任务 ID")):
    """开始工作（claimed → in_progress）"""
    tm = _get_tm()
    try:
        task = tm.start_task(task_id)
        console.print(f"[blue]▶[/blue] 开始工作: {task.id} — {task.title}")
    except TaskManagerError as e:
        console.print(f"[red]✗[/red] {e}")
        raise typer.Exit(1)


# ── 审阅命令 ─────────────────────────────────────────────────

@app.command()
def review(
    task_id: str = typer.Argument(..., help="任务 ID"),
    approve: bool = typer.Option(False, "--approve", "-a", help="通过审阅"),
    reject: bool = typer.Option(False, "--reject", help="驳回审阅"),
    comment: str = typer.Option("", "--comment", "-c", help="审阅意见"),
):
    """审阅任务定义（draft → pending 或标记驳回）"""
    if not approve and not reject:
        console.print("[red]✗[/red] 请指定 --approve 或 --reject")
        raise typer.Exit(1)
    if approve and reject:
        console.print("[red]✗[/red] --approve 和 --reject 不能同时使用")
        raise typer.Exit(1)

    tm = _get_tm()
    try:
        task = tm.review_task(task_id, approved=approve, comment=comment)
        if approve:
            console.print(f"[green]✓[/green] 审阅通过: {task.id} — {task.title} → [yellow]pending[/yellow]")
        else:
            console.print(f"[red]✗[/red] 审阅驳回: {task.id} — {task.title}")
        if comment:
            console.print(f"  💬 意见: {comment}")
    except TaskManagerError as e:
        console.print(f"[red]✗[/red] {e}")
        raise typer.Exit(1)


@app.command(name="resubmit-review")
def resubmit_review(
    task_id: str = typer.Argument(..., help="任务 ID"),
    reviewer: Optional[str] = typer.Option(None, "--reviewer", help="更换审阅者终端 ID"),
):
    """重新提交审阅（被驳回后修改再提交）"""
    tm = _get_tm()

    reviewer_id = reviewer
    if not reviewer_id:
        # 交互式选择是否更换审阅者
        change = typer.confirm("是否更换审阅者?", default=False)
        if change:
            reviewer_id = _select_reviewer()

    try:
        task = tm.resubmit_for_review(task_id, reviewer=reviewer_id)
        console.print(f"[green]✓[/green] 已重新提交审阅: {task.id} — {task.title}")
        console.print(f"  📋 审阅者: {task.reviewer}")
    except TaskManagerError as e:
        console.print(f"[red]✗[/red] {e}")
        raise typer.Exit(1)


@app.command()
def submit(
    task_id: str = typer.Argument(..., help="任务 ID"),
    run_test: Optional[bool] = typer.Option(None, "--test/--no-test", help="提交前是否运行测试"),
    summary: str = typer.Option("", "--summary", help="实现内容摘要"),
    changed_files: Optional[str] = typer.Option(None, "--changed-files", help="修改文件，逗号分隔"),
    test_note: str = typer.Option("", "--test-note", help="测试说明"),
    risks: str = typer.Option("", "--risks", help="风险或副作用说明"),
):
    """提交任务（Worker）"""
    tm = _get_tm()
    should_run_test = run_test
    if should_run_test is None:
        assert _config is not None
        should_run_test = _config.get("testing.auto_run_on_submit", True)
    task = tm.get_task(task_id)
    if not task:
        console.print(f"[red]✗[/red] 任务 {task_id} 不存在")
        raise typer.Exit(1)

    # 运行测试
    if should_run_test and task.test_path:
        console.print("[cyan]🧪 运行测试中...[/cyan]")
        report = run_tests_simple(task.test_path, task.work_dir or None)
        test_status = TestStatus.PASSED if report.success else TestStatus.FAILED
        tm.update_test_result(task_id, test_status, report.to_dict())

        if report.success:
            console.print(f"[green]✓[/green] 测试通过 ({report.passed}/{report.total})")
        else:
            console.print(f"[red]✗[/red] 测试失败 ({report.failed} failed, {report.errors} errors)")
            if not typer.confirm("测试未通过，仍要提交？"):
                raise typer.Exit(0)

    try:
        files = [f.strip() for f in changed_files.split(",") if f.strip()] if changed_files else None
        tm.submit_task(
            task_id,
            summary=summary,
            changed_files=files,
            test_note=test_note,
            risks=risks,
        )
        console.print(f"[magenta]📤[/magenta] 任务已提交: {task_id}")
    except TaskManagerError as e:
        console.print(f"[red]✗[/red] {e}")
        raise typer.Exit(1)


@app.command()
def verify(
    task_id: str = typer.Argument(..., help="任务 ID"),
    approve: bool = typer.Option(True, "--approve/--reject", help="通过或驳回"),
    comment: str = typer.Option("", "--comment", "-c", help="验收意见"),
):
    """验收任务（Master）"""
    tm = _get_tm()
    try:
        task = tm.verify_task(task_id, approved=approve, comment=comment)
        if approve:
            console.print(f"[green]✓[/green] 已验收通过: {task_id}")
        else:
            console.print(f"[red]↩[/red] 已驳回: {task_id} — {comment}")
    except TaskManagerError as e:
        console.print(f"[red]✗[/red] {e}")
        raise typer.Exit(1)


@app.command(name="change-status")
def change_status(
    task_id: str = typer.Argument(..., help="任务 ID"),
    status: str = typer.Argument(..., help="新状态"),
):
    """按状态机规则变更任务状态"""
    tm = _get_tm()
    try:
        new_status = TaskStatus(status)
        task = tm.change_status(task_id, new_status)
        console.print(f"[green]✓[/green] 状态已更新: {task.id} → {task.status.value}")
    except ValueError as e:
        valid = ", ".join(s.value for s in TaskStatus)
        console.print(f"[red]✗[/red] 无效状态: {status}。可选: {valid}")
        raise typer.Exit(1) from e
    except TaskManagerError as e:
        console.print(f"[red]✗[/red] {e}")
        raise typer.Exit(1)


@app.command()
def progress(parent_id: str = typer.Argument(..., help="主任务 ID")):
    """查看主任务进度"""
    tm = _get_tm()
    p = tm.get_progress(parent_id)
    console.print(Panel(
        f"总计: {p['total']} | 完成: {p['done']} | 进度: {p['progress']}%\n"
        + "\n".join(f"  {k}: {v}" for k, v in p['by_status'].items()),
        title=f"进度 — {parent_id}",
    ))


@app.command()
def log(
    task_id: Optional[str] = typer.Argument(None, help="任务 ID（留空显示全部）"),
    limit: int = typer.Option(20, "--limit", "-n", help="显示条数"),
):
    """查看操作日志"""
    tm = _get_tm()
    logs = tm.get_logs(task_id, limit=limit)
    if not logs:
        console.print("[dim]暂无日志[/dim]")
        return

    table = Table(title="操作日志")
    table.add_column("时间", width=19)
    table.add_column("任务", width=10)
    table.add_column("操作", width=14)
    table.add_column("终端", width=10)
    table.add_column("详情", width=40)

    for l in logs:
        table.add_row(l.timestamp, l.task_id, l.action, l.terminal_id, l.detail)

    console.print(table)


@app.command()
def available():
    """列出可领取的任务（Worker）"""
    tm = _get_tm()
    tasks = tm.list_tasks(status="pending", task_type="subtask")
    if not tasks:
        console.print("[dim]暂无可领取的子任务[/dim]")
        return

    table = Table(title="可领取的子任务")
    table.add_column("ID", width=10)
    table.add_column("标题", width=30)
    table.add_column("优先级", width=8)
    table.add_column("父任务", width=10)

    for t in tasks:
        table.add_row(t.id, t.title, PRIORITY_LABELS.get(t.priority, "?"), t.parent_id or "—")

    console.print(table)


@app.command()
def my(
    status: Optional[str] = typer.Option(None, "--status", "-s", help="按状态过滤"),
):
    """查看我领取的任务（Worker）"""
    tm = _get_tm()
    term_mgr = _get_term_mgr()
    tasks = tm.list_tasks(claimed_by=term_mgr.current.id, status=status)
    if not tasks:
        console.print("[dim]你还没有领取任何任务[/dim]")
        return

    table = Table(title=f"我的任务（{term_mgr.current.id}）")
    table.add_column("ID", width=10)
    table.add_column("标题", width=30)
    table.add_column("状态", width=12)
    table.add_column("测试", width=10)

    for t in tasks:
        color = STATUS_COLORS.get(t.status.value, "white")
        table.add_row(
            t.id, t.title,
            f"[{color}]{t.status.value}[/{color}]",
            t.test_status.value,
        )

    console.print(table)


@app.command()
def terminals():
    """查看所有注册终端"""
    term_mgr = _get_term_mgr()
    all_t = term_mgr.list_all()

    table = Table(title="终端列表")
    table.add_column("ID", width=10)
    table.add_column("名称", width=15)
    table.add_column("角色", width=8)
    table.add_column("类型", width=12)
    table.add_column("PID", width=8)
    table.add_column("最后活跃", width=19)

    for t in all_t:
        role_color = "green" if t.role == TerminalRole.MASTER else "cyan"
        table.add_row(
            t.id, t.name,
            f"[{role_color}]{t.role.value}[/{role_color}]",
            t.type, str(t.pid), t.last_active,
        )

    console.print(table)


@app.command(name="test")
def run_test(
    task_id: str = typer.Argument(..., help="任务 ID"),
):
    """运行任务关联的测试（Worker）"""
    tm = _get_tm()
    task = tm.get_task(task_id)
    if not task:
        console.print(f"[red]✗[/red] 任务 {task_id} 不存在")
        raise typer.Exit(1)

    if not task.test_path:
        console.print("[yellow]⚠[/yellow] 该任务未配置测试路径 (test_path)")
        raise typer.Exit(1)

    console.print(f"[cyan]🧪 运行测试: {task.test_path}[/cyan]")
    report = run_tests_simple(task.test_path, task.work_dir or None)
    test_status = TestStatus.PASSED if report.success else TestStatus.FAILED
    tm.update_test_result(task_id, test_status, report.to_dict())

    if report.success:
        console.print(f"[green]✓ 全部通过[/green] — {report.passed}/{report.total}")
    else:
        console.print(f"[red]✗ 测试失败[/red] — passed: {report.passed}, failed: {report.failed}, errors: {report.errors}")
        if report.output:
            console.print(Panel(report.output[-2000:], title="测试输出", border_style="red"))


@app.command()
def update(
    task_id: str = typer.Argument(..., help="任务 ID"),
    title: Optional[str] = typer.Option(None, "--title", help="新标题"),
    desc: Optional[str] = typer.Option(None, "--desc", help="新描述"),
    priority: Optional[int] = typer.Option(None, "--priority", "-p", help="新优先级"),
    tags: Optional[str] = typer.Option(None, "--tags", help="新标签，逗号分隔"),
    test_path: Optional[str] = typer.Option(None, "--test-path", help="测试路径"),
    work_dir: Optional[str] = typer.Option(None, "--work-dir", help="工作目录"),
):
    """更新任务属性"""
    tm = _get_tm()
    tag_list = [t.strip() for t in tags.split(",")] if tags else None
    try:
        task = tm.update_task(
            task_id, title=title, description=desc, priority=priority,
            tags=tag_list, test_path=test_path, work_dir=work_dir,
        )
        console.print(f"[green]✓[/green] 已更新: {task.id}")
    except TaskManagerError as e:
        console.print(f"[red]✗[/red] {e}")
        raise typer.Exit(1)


@app.command()
def delete(
    task_id: str = typer.Argument(..., help="任务 ID"),
    force: bool = typer.Option(False, "--force", "-f", help="跳过确认"),
):
    """删除任务"""
    tm = _get_tm()
    task = tm.get_task(task_id)
    if not task:
        console.print(f"[red]✗[/red] 任务 {task_id} 不存在")
        raise typer.Exit(1)

    if not force and not typer.confirm(f"确认删除任务 {task_id} ({task.title})?"):
        raise typer.Exit(0)

    tm.delete_task(task_id)
    console.print(f"[green]✓[/green] 已删除: {task_id}")


@app.command()
def serve():
    """启动 MCP Server（供 AI Agent 调用）"""
    _init()
    transport = _config.get("mcp_server.transport", "stdio")
    if transport == "sse":
        host = _config.get("mcp_server.sse_host", "127.0.0.1")
        port = _config.get("mcp_server.sse_port", 8000)
        console.print(f"[cyan]🚀 启动 MCP Server (SSE): http://{host}:{port}/sse[/cyan]")
    else:
        console.print("[cyan]🚀 启动 MCP Server (stdio)...[/cyan]")
    from cli_anything.mcp_server.server import serve as mcp_serve
    mcp_serve()


@app.command()
def dashboard(
    host: str = typer.Option("127.0.0.1", "--host", help="监听地址"),
    port: int = typer.Option(8080, "--port", help="监听端口"),
    no_open: bool = typer.Option(False, "--no-open", help="不自动打开浏览器"),
):
    """启动 Web 可视化看板"""
    console.print(f"[cyan]🌐 启动 Dashboard: http://{host}:{port}[/cyan]")
    from cli_anything.web.dashboard import run_dashboard
    run_dashboard(host=host, port=port, auto_open=not no_open)


@app.command()
def tui():
    """启动 TUI 终端界面"""
    from cli_anything.tui.app import run_tui
    run_tui()


@app.command(name="export")
def export_data(
    output: str = typer.Argument("tasks_export.json", help="输出文件路径"),
    parent: Optional[str] = typer.Option(None, "--parent", help="仅导出指定主任务"),
    no_logs: bool = typer.Option(False, "--no-logs", help="不导出日志"),
):
    """导出任务数据为 JSON"""
    tm = _get_tm()
    from cli_anything.utils.export_import import export_tasks
    result = export_tasks(tm, output, parent_id=parent, include_logs=not no_logs)
    console.print(
        f"[green]✓[/green] 导出完成: {result['tasks_count']} 个任务, "
        f"{result['logs_count']} 条日志 → {result['path']}"
    )


@app.command(name="import")
def import_data(
    input_file: str = typer.Argument(..., help="输入 JSON 文件路径"),
    overwrite: bool = typer.Option(False, "--overwrite", help="已存在的任务是否覆盖"),
):
    """从 JSON 导入任务数据"""
    tm = _get_tm()
    from cli_anything.utils.export_import import import_tasks
    result = import_tasks(tm, input_file, overwrite=overwrite)
    console.print(
        f"[green]✓[/green] 导入完成: {result['imported']} 个任务, "
        f"{result['skipped']} 个跳过, {result['logs_imported']} 条日志"
    )
    if result['errors']:
        for err in result['errors']:
            console.print(f"[red]  ⚠ {err}[/red]")


@app.command()
def health(
    cleanup: bool = typer.Option(False, "--cleanup", help="自动清理超时终端的领取状态"),
    timeout: int = typer.Option(60, "--timeout", help="超时阈值（秒）"),
):
    """检查终端健康状态"""
    _init()
    from cli_anything.core.health_checker import TerminalHealthChecker
    checker = TerminalHealthChecker(_db, timeout_seconds=timeout)

    stale = checker.list_stale_terminals()
    if not stale:
        console.print("[green]✓[/green] 所有终端在线")
    else:
        console.print(f"[yellow]⚠[/yellow] {len(stale)} 个终端已超时:")
        for t in stale:
            console.print(f"  • {t.id} ({t.name}) — 最后活跃: {t.last_active}")

    if cleanup and stale:
        released = checker.cleanup_stale_claims()
        if released:
            console.print(f"\n[green]✓[/green] 已释放 {len(released)} 个被占用的任务:")
            for r in released:
                console.print(f"  • {r['task_id']} — {r['title']}")
        else:
            console.print("[dim]没有需要释放的任务[/dim]")


@app.command()
def version():
    """显示版本信息"""
    console.print(f"cli-anything {__version__}")


@config_app.command(name="show")
def config_show():
    """显示完整配置"""
    config = Config()
    data = config.load()
    console.print(yaml.safe_dump(data, allow_unicode=True, sort_keys=False))


@config_app.command(name="get")
def config_get(
    key: str = typer.Argument(..., help="配置键，如 database.path"),
):
    """读取配置项"""
    config = Config()
    value = config.get(key)
    if value is None:
        raise typer.Exit(1)
    if isinstance(value, (dict, list)):
        console.print(yaml.safe_dump(value, allow_unicode=True, sort_keys=False))
    else:
        console.print(str(value))


@config_app.command(name="set")
def config_set(
    key: str = typer.Argument(..., help="配置键，如 terminal.role"),
    value: str = typer.Argument(..., help="配置值，支持 YAML 标量/列表/对象"),
):
    """写入配置项"""
    config = Config()
    parsed = yaml.safe_load(value)
    config.set(key, parsed)
    console.print(f"[green]✓[/green] 已设置 {key}")


# ── 入口 ────────────────────────────────────────────────────

def _resolve_aliases():
    """解析命令别名：将 sys.argv 中的别名替换为实际命令"""
    if len(sys.argv) < 2:
        return
    try:
        config = Config()
        config.load()
        aliases = config.get("aliases", {})
        if not aliases:
            return
        cmd = sys.argv[1]
        if cmd in aliases:
            expanded = aliases[cmd].split()
            sys.argv = [sys.argv[0]] + expanded + sys.argv[2:]
    except Exception:
        pass  # 别名解析失败不影响正常流程


def main():
    _resolve_aliases()
    app()


if __name__ == "__main__":
    main()
