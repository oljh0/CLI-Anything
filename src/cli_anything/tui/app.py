"""TUI 终端界面：基于 Textual 的任务看板"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.widgets import Header, Footer, Static, DataTable, Label, ProgressBar, Button
from textual.reactive import reactive
from textual.timer import Timer
from textual import on

from cli_anything.core.models import TaskStatus, TaskType, TerminalRole, ReviewStatus
from cli_anything.core.task_manager import TaskManager
from cli_anything.storage.database import Database
from cli_anything.utils.config import Config


STATUS_ICONS = {
    "draft": "📝", "pending": "⏳", "claimed": "🔒", "in_progress": "🔨",
    "submitted": "📤", "done": "✅", "rejected": "❌",
    "blocked": "🚫", "cancelled": "🗑️",
}

PRIORITY_ICONS = {1: "🔴", 2: "🟠", 3: "🟡", 4: "🟢", 5: "⚪"}


class SummaryPanel(Static):
    """顶部统计面板"""

    def __init__(self, tm: TaskManager, **kwargs):
        super().__init__(**kwargs)
        self.tm = tm

    def compose(self) -> ComposeResult:
        yield Label("", id="summary-text")

    def refresh_data(self):
        tasks = self.tm.list_tasks(limit=9999)
        total = len(tasks)
        by_status = {}
        for t in tasks:
            sv = t.status.value
            by_status[sv] = by_status.get(sv, 0) + 1

        done = by_status.get("done", 0)
        in_prog = by_status.get("in_progress", 0)
        pending = by_status.get("pending", 0)
        draft = by_status.get("draft", 0)
        submitted = by_status.get("submitted", 0)

        text = (
            f"📊 总计: {total}  |  "
            f"📝 草稿: {draft}  |  "
            f"⏳ 待处理: {pending}  |  "
            f"🔨 进行中: {in_prog}  |  "
            f"📤 已提交: {submitted}  |  "
            f"✅ 已完成: {done}"
        )

        label = self.query_one("#summary-text", Label)
        label.update(text)


class TaskTable(Static):
    """任务数据表格"""

    def __init__(self, tm: TaskManager, **kwargs):
        super().__init__(**kwargs)
        self.tm = tm

    def compose(self) -> ComposeResult:
        yield DataTable(id="task-table")

    REVIEW_ICONS = {
        "not_required": "",
        "pending_review": "🔍",
        "approved": "✅",
        "rejected": "🚫",
    }

    def on_mount(self):
        table = self.query_one("#task-table", DataTable)
        table.add_columns("ID", "状态", "优先", "标题", "类型", "领取者", "审阅", "测试")
        table.cursor_type = "row"
        self.refresh_data()

    def refresh_data(self):
        table = self.query_one("#task-table", DataTable)
        table.clear()

        tasks = self.tm.list_tasks(limit=200)
        for t in tasks:
            icon = STATUS_ICONS.get(t.status.value, "?")
            pri = PRIORITY_ICONS.get(t.priority, str(t.priority))
            type_label = "📦" if t.task_type == TaskType.MASTER else "  └─"
            review_icon = self.REVIEW_ICONS.get(t.review_status.value, "") if t.review_status else ""
            table.add_row(
                t.id,
                f"{icon} {t.status.value}",
                pri,
                t.title[:40],
                type_label,
                t.claimed_by or "—",
                review_icon,
                t.test_status.value,
                key=t.id,
            )


class LogPanel(Static):
    """操作日志面板"""

    def __init__(self, tm: TaskManager, **kwargs):
        super().__init__(**kwargs)
        self.tm = tm

    def compose(self) -> ComposeResult:
        yield Label("📝 最近操作日志", classes="section-title")
        yield Static("", id="log-content")

    def refresh_data(self):
        # 获取所有任务的日志
        tasks = self.tm.list_tasks(limit=20)
        all_logs = []
        for t in tasks[:10]:
            logs = self.tm.get_logs(t.id, limit=3)
            all_logs.extend(logs)

        all_logs.sort(key=lambda l: l.timestamp, reverse=True)
        all_logs = all_logs[:15]

        lines = []
        for l in all_logs:
            lines.append(f"  {l.timestamp}  {l.action:<14}  {l.task_id}  {l.detail}")

        content = self.query_one("#log-content", Static)
        content.update("\n".join(lines) if lines else "  暂无日志")


class CliAnythingTUI(App):
    """CLI-Anything TUI 主应用"""

    CSS = """
    Screen {
        background: $surface;
    }
    #summary-panel {
        height: 3;
        padding: 0 2;
        background: $primary-background;
        color: $text;
    }
    #task-panel {
        height: 1fr;
        margin: 1 0;
    }
    #task-table {
        height: 100%;
    }
    #log-panel {
        height: 12;
        padding: 0 1;
        background: $panel;
    }
    .section-title {
        text-style: bold;
        margin-bottom: 1;
    }
    #bottom-bar {
        height: 3;
        padding: 0 2;
        background: $primary-background;
    }
    """

    BINDINGS = [
        ("r", "refresh", "刷新"),
        ("q", "quit", "退出"),
    ]

    def __init__(self):
        super().__init__()
        config = Config()
        config.load()
        self._db = Database(config.get("database.path"))
        self._db.connect()
        self._tm = TaskManager(self._db, terminal_id="tui")

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield SummaryPanel(self._tm, id="summary-panel")
        yield Container(
            TaskTable(self._tm, id="task-panel"),
        )
        yield LogPanel(self._tm, id="log-panel")
        yield Footer()

    def on_mount(self):
        self.title = "CLI-Anything"
        self.sub_title = "跨终端协同任务系统"
        self._refresh_all()
        self.set_interval(5, self._refresh_all)

    def _refresh_all(self):
        self.query_one("#summary-panel", SummaryPanel).refresh_data()
        self.query_one("#task-panel", TaskTable).refresh_data()
        self.query_one("#log-panel", LogPanel).refresh_data()

    def action_refresh(self):
        self._refresh_all()
        self.notify("已刷新", timeout=1)

    def on_unmount(self):
        if self._db:
            self._db.close()


def run_tui():
    """启动 TUI"""
    app = CliAnythingTUI()
    app.run()


if __name__ == "__main__":
    run_tui()
