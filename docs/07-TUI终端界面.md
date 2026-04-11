# 07 — TUI 终端界面

> **源文件**: `src/cli_anything/tui/app.py`（约 226 行）
> **框架**: [Textual](https://textual.textualize.io/) — 现代化 Python 终端 UI 框架
> **功能**: 提供交互式任务管理看板，支持键盘快捷键操作与实时刷新

---

## 目录

- [1. 模块概述](#1-模块概述)
- [2. 启动方式](#2-启动方式)
- [3. 常量定义](#3-常量定义)
  - [3.1 STATUS\_ICONS — 任务状态图标](#31-status_icons--任务状态图标)
  - [3.2 PRIORITY\_ICONS — 优先级图标](#32-priority_icons--优先级图标)
  - [3.3 REVIEW\_ICONS — 审阅状态图标](#33-review_icons--审阅状态图标)
- [4. 组件类](#4-组件类)
  - [4.1 SummaryPanel — 统计面板](#41-summarypanel--统计面板)
  - [4.2 TaskTable — 任务表格](#42-tasktable--任务表格)
  - [4.3 LogPanel — 操作日志面板](#43-logpanel--操作日志面板)
- [5. CliAnythingTUI 主应用类](#5-clianythingtui-主应用类)
  - [5.1 继承关系](#51-继承关系)
  - [5.2 内嵌 CSS 样式](#52-内嵌-css-样式)
  - [5.3 键绑定](#53-键绑定)
  - [5.4 初始化流程](#54-初始化流程)
  - [5.5 UI 组件树](#55-ui-组件树)
  - [5.6 方法清单](#56-方法清单)
- [6. 审阅列（新增功能）](#6-审阅列新增功能)
- [7. run\_tui() 入口函数](#7-run_tui-入口函数)
- [8. 设计要点](#8-设计要点)
- [9. 界面布局示意](#9-界面布局示意)
- [10. 常见问题与故障排查](#10-常见问题与故障排查)

---

## 1. 模块概述

`tui/app.py` 是 CLI-Anything 项目的**终端用户界面（TUI）模块**，基于 Textual 框架构建了一个交互式任务管理看板。该看板在终端中渲染出类图形化界面，包含任务统计摘要、数据表格和操作日志三大区域，支持键盘快捷键驱动所有操作，并以 5 秒间隔自动刷新数据。

**核心能力**：

| 能力 | 说明 |
|------|------|
| 任务总览 | 展示所有任务的状态、优先级、类型、审阅状态等 |
| 统计面板 | 实时显示草稿、待处理、进行中、已提交、已完成的数量 |
| 操作日志 | 显示最近 15 条操作日志，按时间倒序排列 |
| 键盘操作 | 快捷键 `r` 刷新、`q` 退出 |
| 自动刷新 | 每 5 秒自动拉取最新数据 |

**依赖导入**：

```python
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
```

---

## 2. 启动方式

### 2.1 通过 CLI 命令启动

在终端中执行：

```bash
task tui
```

该命令在 `cli.py` 中注册为 Typer 子命令：

```python
@app.command()
def tui():
    """启动 TUI 终端界面"""
    from cli_anything.tui.app import run_tui
    run_tui()
```

### 2.2 直接运行模块

```bash
python -m cli_anything.tui.app
```

模块末尾的 `if __name__ == "__main__"` 守卫会直接调用 `run_tui()`。

### 2.3 程序化调用

```python
from cli_anything.tui.app import run_tui
run_tui()
```

---

## 3. 常量定义

### 3.1 STATUS_ICONS — 任务状态图标

模块级常量，将 9 种 `TaskStatus` 枚举值映射为对应的 emoji 图标：

```python
STATUS_ICONS = {
    "draft":       "📝",  # 草稿
    "pending":     "⏳",  # 待处理
    "claimed":     "🔒",  # 已领取
    "in_progress": "🔨",  # 进行中
    "submitted":   "📤",  # 已提交
    "done":        "✅",  # 已完成
    "rejected":    "❌",  # 已驳回
    "blocked":     "🚫",  # 已阻塞
    "cancelled":   "🗑️",  # 已取消
}
```

| 状态值 | 图标 | 含义 |
|--------|------|------|
| `draft` | 📝 | 任务草稿，尚未发布 |
| `pending` | ⏳ | 已发布，等待领取 |
| `claimed` | 🔒 | 已被某终端锁定领取 |
| `in_progress` | 🔨 | 正在执行中 |
| `submitted` | 📤 | 已提交等待审核 |
| `done` | ✅ | 已完成（终态） |
| `rejected` | ❌ | 审核被驳回 |
| `blocked` | 🚫 | 任务被阻塞 |
| `cancelled` | 🗑️ | 已取消 |

### 3.2 PRIORITY_ICONS — 优先级图标

模块级常量，将 1–5 优先级映射为彩色圆点：

```python
PRIORITY_ICONS = {1: "🔴", 2: "🟠", 3: "🟡", 4: "🟢", 5: "⚪"}
```

| 优先级 | 图标 | 含义 |
|--------|------|------|
| 1 | 🔴 | 最高优先级（紧急） |
| 2 | 🟠 | 高优先级 |
| 3 | 🟡 | 中等优先级（默认） |
| 4 | 🟢 | 低优先级 |
| 5 | ⚪ | 最低优先级 |

### 3.3 REVIEW_ICONS — 审阅状态图标

定义在 `TaskTable` 类内部，将 `ReviewStatus` 枚举映射为图标：

```python
REVIEW_ICONS = {
    "not_required":   "",    # 不需要审阅 — 不显示图标
    "pending_review":  "🔍",  # 待审阅
    "approved":        "✅",  # 审阅通过
    "rejected":        "🚫",  # 审阅驳回
}
```

| 审阅状态 | 图标 | 含义 |
|----------|------|------|
| `not_required` | （空） | 该任务不需要审阅 |
| `pending_review` | 🔍 | 等待审阅 |
| `approved` | ✅ | 审阅已通过 |
| `rejected` | 🚫 | 审阅被驳回 |

---

## 4. 组件类

TUI 界面由三个独立的自定义组件类构成，均继承自 `textual.widgets.Static`。

### 4.1 SummaryPanel — 统计面板

```
类名: SummaryPanel(Static)
位置: 屏幕顶部，高度 3 行
功能: 显示任务分类统计数字
```

#### 构造方法

```python
def __init__(self, tm: TaskManager, **kwargs)
```

接收 `TaskManager` 实例，用于查询任务数据。

#### compose()

生成一个 `Label` 子组件（ID: `summary-text`），用于显示统计文本。

#### refresh_data()

1. 调用 `self.tm.list_tasks(limit=9999)` 获取全部任务
2. 按 `status.value` 分组计数
3. 拼接统计文本并更新 `Label`

**统计维度**：

| 维度 | 前缀 | 说明 |
|------|------|------|
| 总计 | 📊 | 所有任务总数 |
| 草稿 | 📝 | `status == draft` |
| 待处理 | ⏳ | `status == pending` |
| 进行中 | 🔨 | `status == in_progress` |
| 已提交 | 📤 | `status == submitted` |
| 已完成 | ✅ | `status == done` |

**输出示例**：

```
📊 总计: 12  |  📝 草稿: 2  |  ⏳ 待处理: 3  |  🔨 进行中: 4  |  📤 已提交: 1  |  ✅ 已完成: 2
```

### 4.2 TaskTable — 任务表格

```
类名: TaskTable(Static)
位置: 屏幕中央主内容区，弹性高度 (1fr)
功能: 展示任务列表，支持行选择
```

#### 构造方法

```python
def __init__(self, tm: TaskManager, **kwargs)
```

#### compose()

生成一个 `DataTable` 子组件（ID: `task-table`）。

#### on_mount()

挂载时配置表格：

1. 添加 8 列表头：

| 列名 | 说明 |
|------|------|
| ID | 任务唯一标识符 |
| 状态 | 状态图标 + 状态值（如 `🔨 in_progress`） |
| 优先 | 优先级彩色图标 |
| 标题 | 任务标题（截取前 40 字符） |
| 类型 | 📦 表示主任务，`└─` 表示子任务 |
| 领取者 | `claimed_by` 字段，未领取时显示 `—` |
| 审阅 | 审阅状态图标（详见 [第 6 节](#6-审阅列新增功能)） |
| 测试 | `test_status` 值 |

2. 设置 `cursor_type = "row"`（行级光标选择）
3. 调用 `refresh_data()` 加载初始数据

#### refresh_data()

1. 清空现有表格行
2. 调用 `self.tm.list_tasks(limit=200)` 获取最多 200 条任务
3. 遍历任务，逐行写入表格：

```python
for t in tasks:
    icon = STATUS_ICONS.get(t.status.value, "?")
    pri = PRIORITY_ICONS.get(t.priority, str(t.priority))
    type_label = "📦" if t.task_type == TaskType.MASTER else "  └─"
    review_icon = self.REVIEW_ICONS.get(
        t.review_status.value, ""
    ) if t.review_status else ""
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
```

> **注意**：每行以 `t.id` 作为 `key`，确保行可被唯一标识。

### 4.3 LogPanel — 操作日志面板

```
类名: LogPanel(Static)
位置: 屏幕底部（Footer 上方），固定高度 12 行
功能: 显示最近操作日志
```

#### 构造方法

```python
def __init__(self, tm: TaskManager, **kwargs)
```

#### compose()

生成两个子组件：
- `Label("📝 最近操作日志")` — 区域标题（带 `section-title` CSS 类）
- `Static("", id="log-content")` — 日志内容容器

#### refresh_data()

1. 获取最新 20 条任务（`list_tasks(limit=20)`）
2. 对前 10 条任务各获取 3 条日志（`get_logs(t.id, limit=3)`）
3. 合并所有日志，按 `timestamp` 倒序排列
4. 截取前 15 条
5. 格式化输出：

```
  {timestamp}  {action:<14}  {task_id}  {detail}
```

无日志时显示 `暂无日志`。

---

## 5. CliAnythingTUI 主应用类

### 5.1 继承关系

```
textual.app.App
    └── CliAnythingTUI
```

`CliAnythingTUI` 是 Textual App 的子类，作为整个 TUI 的入口应用。

### 5.2 内嵌 CSS 样式

通过类变量 `CSS` 定义内嵌样式表：

```css
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
```

**布局策略**：

| 区域 | CSS 选择器 | 高度 | 说明 |
|------|-----------|------|------|
| 统计面板 | `#summary-panel` | 固定 3 行 | 顶部统计栏 |
| 任务表格 | `#task-panel` | `1fr`（弹性填充） | 中央主内容区 |
| 日志面板 | `#log-panel` | 固定 12 行 | 底部操作日志 |

- 使用 Textual 的 CSS 变量（如 `$surface`、`$primary-background`、`$panel`）实现主题适配
- 表格高度设为 `100%` 以填满父容器

### 5.3 键绑定

通过类变量 `BINDINGS` 定义快捷键：

```python
BINDINGS = [
    ("r", "refresh", "刷新"),
    ("q", "quit", "退出"),
]
```

| 快捷键 | 动作名 | 功能 | 说明 |
|--------|--------|------|------|
| `r` | `action_refresh` | 刷新 | 手动触发全面数据刷新并弹出通知 |
| `q` | `action_quit` | 退出 | 退出 TUI 应用（Textual 内置） |

快捷键提示会自动显示在 Footer 组件中。

### 5.4 初始化流程

```python
def __init__(self):
    super().__init__()
    config = Config()
    config.load()
    self._db = Database(config.get("database.path"))
    self._db.connect()
    self._tm = TaskManager(self._db, terminal_id="tui")
```

初始化步骤：

1. 调用父类 `App.__init__()`
2. 创建并加载 `Config` 配置
3. 从配置中获取数据库路径，创建 `Database` 实例并连接
4. 创建 `TaskManager` 实例，`terminal_id` 固定为 `"tui"`

### 5.5 UI 组件树

`compose()` 方法定义的组件树结构：

```
CliAnythingTUI
├── Header(show_clock=True)          # 标题栏（含时钟）
├── SummaryPanel(id="summary-panel") # 统计面板
├── Container                        # 主内容容器
│   └── TaskTable(id="task-panel")   # 任务表格
├── LogPanel(id="log-panel")         # 日志面板
└── Footer()                         # 底部快捷键提示栏
```

### 5.6 方法清单

| 方法 | 触发方式 | 功能 |
|------|---------|------|
| `__init__()` | 实例化 | 初始化配置、数据库连接、任务管理器 |
| `compose()` | Textual 框架自动调用 | 构建 UI 组件树 |
| `on_mount()` | 组件挂载后 | 设置标题与副标题，执行首次刷新，启动 5 秒定时刷新 |
| `_refresh_all()` | 定时器 / 手动 | 依次刷新统计面板、任务表格、日志面板 |
| `action_refresh()` | 按 `r` 键 | 调用 `_refresh_all()` 并弹出 `已刷新` 通知 |
| `on_unmount()` | 应用退出 | 关闭数据库连接 |

#### on_mount() 详解

```python
def on_mount(self):
    self.title = "CLI-Anything"
    self.sub_title = "跨终端协同任务系统"
    self._refresh_all()
    self.set_interval(5, self._refresh_all)
```

- 设置应用标题为 `CLI-Anything`
- 设置副标题为 `跨终端协同任务系统`（显示在 Header 中）
- 立即执行一次全面刷新
- 注册 5 秒间隔定时器，持续自动刷新

#### _refresh_all() 详解

```python
def _refresh_all(self):
    self.query_one("#summary-panel", SummaryPanel).refresh_data()
    self.query_one("#task-panel", TaskTable).refresh_data()
    self.query_one("#log-panel", LogPanel).refresh_data()
```

按顺序刷新三个面板的数据，使用 `query_one()` 通过 CSS ID 查找子组件。

#### on_unmount() — 资源清理

```python
def on_unmount(self):
    if self._db:
        self._db.close()
```

应用退出时安全关闭数据库连接，避免资源泄漏。

---

## 6. 审阅列（新增功能）

任务表格中新增了**"审阅"列**，集成了 `ReviewStatus` 审阅状态的可视化展示。

### 6.1 审阅状态枚举

来自 `core/models.py` 的 `ReviewStatus`：

```python
class ReviewStatus(str, Enum):
    NOT_REQUIRED = "not_required"    # 不需要审阅
    PENDING      = "pending_review"  # 待审阅
    APPROVED     = "approved"        # 审阅通过
    REJECTED     = "rejected"        # 审阅驳回
```

### 6.2 图标渲染逻辑

```python
review_icon = self.REVIEW_ICONS.get(
    t.review_status.value, ""
) if t.review_status else ""
```

- 如果任务有 `review_status` 属性，根据其 `.value` 查询 `REVIEW_ICONS` 获取图标
- 如果 `review_status` 为 `None`（或 `not_required`），不显示图标（空字符串）
- 当查询不到匹配的图标时，也返回空字符串作为默认值

### 6.3 显示效果

| 场景 | 审阅列显示 |
|------|-----------|
| 任务不需要审阅 | （空白） |
| 等待审阅 | 🔍 |
| 审阅通过 | ✅ |
| 审阅被驳回 | 🚫 |

---

## 7. run_tui() 入口函数

```python
def run_tui():
    """启动 TUI"""
    app = CliAnythingTUI()
    app.run()
```

极简入口函数：

1. 创建 `CliAnythingTUI` 实例（触发数据库连接等初始化）
2. 调用 `app.run()` 进入 Textual 事件循环（阻塞直到退出）

同时支持直接运行：

```python
if __name__ == "__main__":
    run_tui()
```

---

## 8. 设计要点

### 8.1 Textual 框架

采用 [Textual](https://textual.textualize.io/) 作为 TUI 框架，它提供：

- **声明式组件** — 通过 `compose()` 方法声明组件树，类似 React
- **CSS 布局** — 支持类 Web 的 CSS 样式系统（flex、grid、主题变量）
- **响应式属性** — `reactive` 机制自动触发界面更新
- **内置组件** — Header、Footer、DataTable 等开箱即用

### 8.2 响应式布局

- 统计面板和日志面板使用固定高度（`height: 3` / `height: 12`）
- 任务表格使用弹性高度（`height: 1fr`），自动填充剩余空间
- 使用 Textual CSS 变量（`$surface`、`$primary-background` 等）适配不同终端主题

### 8.3 实时刷新策略

| 方式 | 触发条件 | 间隔 |
|------|---------|------|
| 自动刷新 | `set_interval(5, ...)` | 每 5 秒 |
| 手动刷新 | 按 `r` 键 | 即时 |

每次刷新时，三个面板（统计、表格、日志）**同步依次更新**。

### 8.4 键盘驱动

所有操作通过 Textual `BINDINGS` 机制绑定快捷键：

- Footer 自动渲染快捷键提示
- `action_*` 方法名与 Binding 的 action 参数自动映射
- DataTable 内置方向键导航和行选择

### 8.5 审阅状态集成

- 统计面板新增**草稿计数**（`📝 草稿: N`）
- 任务表格新增**审阅列**，使用 `REVIEW_ICONS` 图标直观展示审阅进度
- 审阅图标仅在 `review_status` 非空且非 `not_required` 时显示

### 8.6 资源管理

- `__init__` 中创建数据库连接
- `on_unmount` 中安全关闭连接
- `terminal_id` 固定为 `"tui"`，便于日志追踪

---

## 9. 界面布局示意

```
┌──────────────────────────────────────────────────────────────┐
│  Header:  CLI-Anything — 跨终端协同任务系统           🕐    │
├──────────────────────────────────────────────────────────────┤
│  📊 总计: 12  |  📝 草稿: 2  |  ⏳ 待处理: 3  |  ...      │  ← SummaryPanel
├──────────────────────────────────────────────────────────────┤
│  ID     状态           优先  标题              类型  领取者  审阅  测试   │
│  ──────────────────────────────────────────────────────────  │
│  t-001  🔨 in_progress  🔴   实现用户认证模块    📦   copilot  🔍   not_run│
│  t-002  ⏳ pending       🟡   添加日志功能         └─   —      ✅   passed │
│  t-003  📝 draft         🟢   重构配置系统        📦   —             not_run│  ← TaskTable
│  ...                                                         │
├──────────────────────────────────────────────────────────────┤
│  📝 最近操作日志                                              │
│  2025-01-15 10:30:00  claim          t-001  copilot 领取任务  │  ← LogPanel
│  2025-01-15 10:28:00  create         t-003  创建草稿任务      │
│  ...                                                         │
├──────────────────────────────────────────────────────────────┤
│  Footer:   r 刷新  q 退出                                    │
└──────────────────────────────────────────────────────────────┘
```

---

## 10. 常见问题与故障排查

### Q1: 执行 `task tui` 报错 `ModuleNotFoundError: No module named 'textual'`

**原因**：未安装 Textual 依赖。

**解决**：

```bash
pip install textual
```

或通过项目依赖安装：

```bash
pip install -e ".[tui]"
```

---

### Q2: 启动后界面空白，不显示任何任务

**可能原因**：

1. **数据库路径错误** — 配置文件中 `database.path` 指向了不存在的数据库文件
2. **数据库为空** — 尚未创建任何任务

**排查步骤**：

```bash
# 检查配置中的数据库路径
task config show

# 确认数据库文件存在
ls -la <database_path>

# 查看是否有任务
task list
```

---

### Q3: emoji 图标显示为方块 / 乱码

**原因**：终端不支持 Unicode emoji 字符或字体缺少 emoji 支持。

**解决**：

| 平台 | 建议 |
|------|------|
| Windows Terminal | 确保使用 Windows Terminal（而非 cmd.exe），它默认支持 emoji |
| macOS Terminal | 默认支持，若有问题尝试 iTerm2 |
| Linux | 安装 `noto-fonts-emoji` 或 `fonts-noto-color-emoji` 包 |
| SSH 远程 | 确保本地终端支持 Unicode，且 `LANG` / `LC_ALL` 设为 UTF-8 |

可通过以下命令验证终端 emoji 支持：

```bash
echo "📝 ⏳ 🔒 🔨 📤 ✅ ❌ 🚫 🗑️"
```

---

### Q4: 界面不刷新 / 数据过时

**说明**：TUI 默认每 5 秒自动刷新。如果数据未更新：

1. 按 `r` 键手动强制刷新
2. 检查是否有其他进程锁定了数据库文件（SQLite 并发限制）
3. 确认其他终端的操作已正确写入数据库

---

### Q5: 表格行过多导致滚动卡顿

**说明**：`TaskTable.refresh_data()` 默认加载最多 200 条任务。如果任务量极大：

- 当前版本每次刷新会清空并重新渲染所有行
- 对于超过 200 条任务的场景，较旧的任务不会显示
- 未来版本可考虑增加分页或虚拟滚动支持

---

### Q6: 按 `q` 退出后终端显示异常

**说明**：Textual 接管了终端的原始模式（raw mode）。正常退出时会恢复终端状态。

**如果退出异常**：

```bash
# 重置终端
reset
# 或者
stty sane
```

---

### Q7: 数据库连接未正确关闭

**说明**：`CliAnythingTUI` 在 `on_unmount()` 生命周期钩子中关闭数据库连接：

```python
def on_unmount(self):
    if self._db:
        self._db.close()
```

如果通过 `Ctrl+C` 强制中断（而非按 `q`），Textual 框架通常仍会触发清理流程。但如果终端直接被关闭（如关闭窗口），可能导致连接未正常关闭。对于 SQLite，这通常不会造成数据损坏，但可能留下 `-wal` / `-shm` 临时文件。

---

### Q8: 日志面板显示 "暂无日志"

**原因**：`LogPanel` 只获取前 10 条任务各 3 条日志。如果：

1. 任务列表为空 → 无日志来源
2. 所有任务均无操作记录 → 日志为空

**解决**：先通过 CLI 创建任务并执行操作，日志会自动出现。

---

### Q9: 如何自定义刷新间隔？

当前刷新间隔硬编码为 5 秒（`self.set_interval(5, self._refresh_all)`）。如需修改：

编辑 `src/cli_anything/tui/app.py` 中 `on_mount()` 方法的 `set_interval` 参数：

```python
# 改为 10 秒刷新
self.set_interval(10, self._refresh_all)
```

> ⚠️ 刷新间隔过短可能增加数据库负载，过长则影响数据实时性。建议 3–15 秒。
