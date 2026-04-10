"""CLI 命令层：使用 typer 实现角色化命令"""

from __future__ import annotations

import json
import os
import sys
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

from cli_anything.core.models import TaskStatus, TaskType, TestStatus, TerminalRole
from cli_anything.core.task_manager import TaskManager, TaskManagerError
from cli_anything.core.terminal_manager import TerminalManager
from cli_anything.core.test_runner import run_tests_simple
from cli_anything.storage.database import Database
from cli_anything.utils.config import Config

app = typer.Typer(
    name="cli-anything",
    help="跨终端协同任务系统 — Master/Worker 协同开发",
    no_args_is_help=True,
)

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
    _tm = TaskManager(_db, terminal_id=_term_mgr.current.id)


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


# ── init 命令 ───────────────────────────────────────────────

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
    t = tm.register_current()
    console.print(f"[green]✓[/green] 终端已注册: {t.id} ({t.role.value})")
    db.close()


# ── 任务操作命令 ─────────────────────────────────────────────

@app.command()
def create(
    title: str = typer.Argument(..., help="任务标题"),
    desc: str = typer.Option("", "--desc", "-d", help="任务描述"),
    priority: int = typer.Option(3, "--priority", "-p", help="优先级 1-5"),
    tags: Optional[str] = typer.Option(None, "--tags", "-t", help="标签，逗号分隔"),
):
    """创建新任务（Master）"""
    tm = _get_tm()
    tag_list = [t.strip() for t in tags.split(",")] if tags else []
    try:
        task = tm.create_task(title, desc, priority, tag_list)
        console.print(f"[green]✓[/green] 任务已创建: [bold]{task.id}[/bold] — {task.title}")
    except TaskManagerError as e:
        console.print(f"[red]✗[/red] {e}")
        raise typer.Exit(1)


@app.command()
def decompose(
    parent_id: str = typer.Argument(..., help="父任务 ID"),
    subtasks_json: str = typer.Argument(..., help='子任务 JSON，如 \'[{"title":"子任务1"},{"title":"子任务2"}]\''),
):
    """拆解任务为子任务（Master）"""
    tm = _get_tm()
    try:
        subs = json.loads(subtasks_json)
        results = tm.decompose_task(parent_id, subs)
        console.print(f"[green]✓[/green] 已拆解为 {len(results)} 个子任务:")
        for s in results:
            console.print(f"  • {s.id} — {s.title}")
    except (json.JSONDecodeError, TaskManagerError) as e:
        console.print(f"[red]✗[/red] {e}")
        raise typer.Exit(1)


@app.command(name="list")
def list_tasks(
    status: Optional[str] = typer.Option(None, "--status", "-s", help="按状态过滤"),
    task_type: Optional[str] = typer.Option(None, "--type", help="按类型过滤: master/subtask"),
    parent: Optional[str] = typer.Option(None, "--parent", help="按父任务 ID 过滤"),
    tag: Optional[str] = typer.Option(None, "--tag", help="按标签过滤"),
):
    """列出任务"""
    tm = _get_tm()
    tasks = tm.list_tasks(
        status=status,
        task_type=task_type,
        parent_id=parent,
        tag=tag,
    )

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
        f"[bold]测试状态:[/bold] {task.test_status.value}\n"
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


@app.command()
def submit(
    task_id: str = typer.Argument(..., help="任务 ID"),
    run_test: bool = typer.Option(True, "--test/--no-test", help="提交前是否运行测试"),
):
    """提交任务（Worker）"""
    tm = _get_tm()
    task = tm.get_task(task_id)
    if not task:
        console.print(f"[red]✗[/red] 任务 {task_id} 不存在")
        raise typer.Exit(1)

    # 运行测试
    if run_test and task.test_path:
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
        tm.submit_task(task_id)
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
def my():
    """查看我领取的任务（Worker）"""
    tm = _get_tm()
    term_mgr = _get_term_mgr()
    tasks = tm.list_tasks(claimed_by=term_mgr.current.id)
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
    console.print("[cyan]🚀 启动 MCP Server...[/cyan]")
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


# ── 入口 ────────────────────────────────────────────────────

def main():
    app()


if __name__ == "__main__":
    main()
