# CLI-Anything

> 跨终端协同任务系统 — Master/Worker 模式，多终端窗口协同开发

CLI-Anything 让你在本机多个终端窗口之间协同管理开发任务。主终端创建并拆解任务，子终端领取并实现，提交时自动运行测试，主终端审核验收。

## ✨ 特性

- **Master/Worker 协同** — 主终端拆解任务，子终端领取实现
- **完整状态机** — pending → claimed → in_progress → submitted → done/rejected
- **自动测试** — 提交时集成 pytest 自动运行，收集测试报告
- **Web 看板** — Kanban 视图 + WebSocket 实时推送
- **TUI 界面** — 基于 Textual 的终端 UI
- **MCP Server** — 10 个工具供 AI Agent（Copilot CLI / Claude）直接调用
- **SQLite WAL** — 零部署，多终端并发安全
- **导入导出** — JSON 格式，方便备份和迁移

## 📦 安装

```bash
# 克隆项目
git clone <repo-url>
cd CLI-Anything

# 安装（含开发依赖）
pip install -e ".[dev]"
```

## 🚀 快速开始

### 1. 初始化

```bash
# 主终端
cli-anything init --role master --name "主控台"

# 子终端（另一个窗口）
cli-anything init --role worker --name "开发-1"
```

### 2. 创建并拆解任务（Master）

```bash
# 创建主任务
cli-anything create "实现用户认证" -d "JWT + bcrypt" -p 1 -t "auth,security"

# 拆解为子任务
cli-anything decompose <task-id> '[{"title":"登录接口"},{"title":"注册接口"},{"title":"Token刷新"}]'

# 查看进度
cli-anything show <task-id>
```

### 3. 领取并完成任务（Worker）

```bash
# 查看可领取的任务
cli-anything available

# 领取
cli-anything claim <subtask-id>

# 开始工作
cli-anything start <subtask-id>

# 提交（自动运行测试）
cli-anything submit <subtask-id>
```

### 4. 审核验收（Master）

```bash
# 验收通过
cli-anything verify <subtask-id> --approve -c "LGTM"

# 驳回
cli-anything verify <subtask-id> --reject -c "缺少边界测试"
```

## 📋 全部命令

| 命令 | 说明 | 角色 |
|------|------|------|
| `init` | 初始化配置与数据库 | 通用 |
| `create` | 创建新任务 | Master |
| `decompose` | 拆解为子任务 | Master |
| `list` | 列出任务（支持过滤） | 通用 |
| `show` | 查看任务详情 | 通用 |
| `claim` | 领取任务 | Worker |
| `unclaim` | 释放任务 | Worker |
| `start` | 开始工作 | Worker |
| `submit` | 提交任务 | Worker |
| `verify` | 验收任务 | Master |
| `progress` | 查看进度 | 通用 |
| `log` | 查看操作日志 | 通用 |
| `available` | 可领取的任务 | Worker |
| `my` | 我的任务 | Worker |
| `test` | 运行测试 | Worker |
| `update` | 更新任务属性 | 通用 |
| `delete` | 删除任务 | 通用 |
| `terminals` | 查看终端列表 | 通用 |
| `health` | 终端健康检查 | 通用 |
| `export` | 导出为 JSON | 通用 |
| `import` | 从 JSON 导入 | 通用 |
| `dashboard` | 启动 Web 看板 | 通用 |
| `tui` | 启动 TUI 界面 | 通用 |
| `serve` | 启动 MCP Server | 通用 |

## 🌐 Web Dashboard

```bash
cli-anything dashboard
# 自动打开 http://127.0.0.1:8080
```

功能：Kanban 看板、任务统计、操作日志、WebSocket 实时刷新。

## 🖥️ TUI 终端界面

```bash
cli-anything tui
```

快捷键：`r` 刷新 | `q` 退出

## 🤖 MCP Server（AI Agent 集成）

```bash
cli-anything serve
```

在 MCP 配置中添加：

```json
{
  "mcpServers": {
    "cli-anything": {
      "command": "cli-anything",
      "args": ["serve"]
    }
  }
}
```

提供 10 个 MCP 工具：`task_create`, `task_decompose`, `task_list`, `task_claim`, `task_submit`, `task_verify`, `task_progress`, `task_update`, `task_delete`, `task_log`

## 🧪 测试

```bash
# 运行所有测试
pytest

# 运行特定测试
pytest tests/test_task_manager.py -v
```

## ⚙️ 配置

配置文件位于 `~/.cli-anything/config.yaml`，首次运行 `init` 自动创建。

```yaml
database:
  path: ~/.cli-anything/tasks.db
  wal_mode: true

terminal:
  role: worker  # master / worker
  name: "开发终端"

mcp_server:
  transport: stdio

dashboard:
  port: 8080
  auto_open: true

testing:
  runner: pytest
  timeout: 300
  auto_run_on_submit: true

notification:
  enabled: false
  type: toast
```

## 📁 项目结构

```
src/cli_anything/
├── cli.py                     # 24 条 CLI 命令
├── core/
│   ├── models.py              # 数据模型 + 状态机
│   ├── task_manager.py        # 核心业务逻辑
│   ├── test_runner.py         # pytest 集成
│   ├── terminal_manager.py    # 终端管理
│   └── health_checker.py      # 心跳检测
├── storage/database.py        # SQLite WAL 存储层
├── mcp_server/server.py       # MCP Server (10 tools)
├── web/dashboard.py           # Web Dashboard
├── tui/app.py                 # TUI 终端界面
├── notification/notifier.py   # 跨平台通知
└── utils/
    ├── config.py              # 配置管理
    ├── terminal.py            # 终端检测
    └── export_import.py       # 导入导出
```

## 📄 License

MIT
