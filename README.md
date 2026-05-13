# CLI-Anything

> 跨终端协同任务系统 — Master/Worker 模式，多终端窗口协同开发

CLI-Anything 让你在本机多个终端窗口之间协同管理开发任务。主终端创建并拆解任务，子终端领取并实现，提交时自动运行测试，主终端审核验收。支持可选的草稿审阅流程，任务创建后可先由指定审阅者审核通过后再进入待领取状态。

## ✨ 特性

- **Master/Worker 协同** — 主终端拆解任务，子终端领取实现
- **9 态状态机** — draft → pending → claimed → in_progress → submitted → done，支持驳回、阻塞、取消
- **草稿审阅流程** — 可选的 draft → 审阅通过 → pending 前置审核机制
- **自动测试** — 提交时集成 pytest 自动运行，收集测试报告
- **Web 看板** — Kanban 视图 + WebSocket 实时推送，含审阅状态展示
- **TUI 界面** — 基于 Textual 的终端 UI，支持快捷键操作
- **MCP Server** — 31 个工具供 AI Agent（Copilot CLI / Claude / GPT）直接调用
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

### 1. 注册终端

```bash
# 主终端
cli-anything register --name "主控台" --role master

# 子终端（另一个窗口）
cli-anything register --name "开发-1" --role worker --capabilities "python,backend"
```

### 2. 创建并拆解任务（Master）

```bash
# 创建主任务
cli-anything create "实现用户认证" --desc "JWT + bcrypt" --priority 1 --tags "auth,security"

# 创建需要审阅的任务（可选）
cli-anything create "敏感接口重构" --desc "需审核后执行" --review

# 拆解为子任务
cli-anything decompose <task-id> '[{"title":"登录接口"},{"title":"注册接口"},{"title":"Token刷新"}]'

# 查看进度
cli-anything show <task-id>
```

### 3. 审阅草稿（可选，Reviewer）

```bash
# 审阅通过 → 任务进入 pending
cli-anything review <task-id> --approve --comment "方案可行"

# 审阅驳回 → 保持 draft，可重新提交
cli-anything review <task-id> --reject --comment "需要补充方案"

# 重新提交审阅
cli-anything resubmit-review <task-id>
```

### 4. 领取并完成任务（Worker）

```bash
# 列出待领取任务
cli-anything list --status pending

# 领取
cli-anything claim <subtask-id>

# 开始工作
cli-anything start <subtask-id>

# 提交（自动运行测试）
cli-anything submit <subtask-id> --summary "完成认证流程" --risks "None"
```

### 5. 审核验收（Master）

```bash
# 验收通过
cli-anything verify <subtask-id> --approve --comment "LGTM"

# 驳回
cli-anything verify <subtask-id> --reject --comment "缺少边界测试"
```

## 📋 全部命令

| 命令 | 说明 | 角色 |
|------|------|------|
| `create` | 创建新任务（支持 `--review`/`--reviewer`） | Master |
| `decompose` | 拆解为子任务（支持 `--review`/`--reviewer`） | Master |
| `list` / `ls` | 列出任务（支持过滤和 `--json`） | 通用 |
| `show` | 查看任务详情（含审阅信息） | 通用 |
| `claim` | 领取任务 | Worker |
| `unclaim` | 释放任务 | Worker |
| `start` | 开始工作 | Worker |
| `submit` | 提交任务 | Worker |
| `verify` | 验收任务 | Master |
| `review` | 审阅草稿任务 | Reviewer |
| `resubmit-review` | 重新提交审阅 | 通用 |
| `change-status` | 通用状态变更 | 通用 |
| `progress` | 查看进度 | 通用 |
| `log` | 查看操作日志 | 通用 |
| `update` | 更新任务属性 | 通用 |
| `delete` | 删除任务 | 通用 |
| `test` | 运行测试 | Worker |
| `register` | 注册终端 | 通用 |
| `terminals` | 查看终端列表 | 通用 |
| `heartbeat` | 发送心跳 | 通用 |
| `health` | 终端健康检查（`--cleanup`） | 通用 |
| `export` | 导出为 JSON | 通用 |
| `import` | 从 JSON 导入 | 通用 |
| `dashboard` | 启动 Web 看板 | 通用 |
| `tui` | 启动 TUI 界面 | 通用 |
| `config show/get/set` | 查看或修改配置 | 通用 |
| `version` | 版本信息 | 通用 |

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

提供 **31 个 MCP 工具**：

| 类别 | 工具 |
|------|------|
| 创建 | `task_create`, `task_decompose` |
| 查询 | `task_list`, `task_show`, `task_progress` |
| 流转 | `task_claim`, `task_unclaim`, `task_start`, `task_submit`, `task_verify`, `task_change_status` |
| 审阅 | `task_review`, `task_resubmit_review` |
| 更新 | `task_update`, `task_delete` |
| 运维 | `task_test`, `task_health`, `task_register_terminal`, `task_update_capabilities` |
| Judgment Day | `task_judgment_day`, `task_submit_verdict`, `task_get_reviews`, `task_synthesize` |
| 依赖与路由 | `task_add_dep`, `task_remove_dep`, `task_get_deps`, `task_route`, `task_suggest` |
| 上下文 | `task_get_project_standards`, `task_add_note`, `task_get_notes` |

> 如偏好短命令，可自行设置 shell alias：`alias task=cli-anything`。

## 🧪 测试

```bash
# 运行所有测试
pytest

# 运行特定测试
pytest tests/test_task_manager.py -v
```

## ⚙️ 配置

配置文件位于 `~/.cli-anything/config.yaml`，首次运行 `init` 自动创建。
可用 `CLI_ANYTHING_CONFIG` 指向独立配置文件；也可用
`CLI_ANYTHING_TERMINAL_ID` / `CLI_ANYTHING_TERMINAL_ROLE` /
`CLI_ANYTHING_TERMINAL_NAME` 为单个终端或 Agent 覆盖身份，适合多终端并行协作。

```yaml
database:
  path: ~/.cli-anything/tasks.db
  wal_mode: true

terminal:
  role: worker  # master / worker
  name: "开发终端"

mcp_server:
  transport: stdio
  sse_host: 127.0.0.1
  sse_port: 8000

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
├── cli.py                     # 30+ CLI 命令（Typer + Rich）
├── core/
│   ├── models.py              # 数据模型 + 9 态状态机 + ReviewStatus
│   ├── task_manager.py        # 核心业务逻辑（含审阅流程）
│   ├── test_runner.py         # pytest 集成
│   ├── terminal_manager.py    # 终端管理
│   └── health_checker.py      # 心跳检测 + 过期清理
├── storage/database.py        # SQLite WAL 存储层（含迁移）
├── mcp_server/server.py       # MCP Server（31 个工具）
├── web/dashboard.py           # Web Dashboard（含审阅 REST API）
├── tui/app.py                 # TUI 终端界面（含审阅列）
├── notification/notifier.py   # 跨平台通知（状态变更/提交/验收触发）
└── utils/
    ├── config.py              # YAML 配置管理（深度合并）
    ├── terminal.py            # 终端类型检测 + ID 生成
    └── export_import.py       # JSON 导入导出
```

## 📚 模块文档

详尽的模块级文档位于 [`docs/`](docs/) 目录，每个模块一个文档：

| 编号 | 文档 | 内容 |
|------|------|------|
| 00 | [架构总览](docs/00-架构总览.md) | 分层设计、模块关系、数据流、设计模式 |
| 01 | [数据模型](docs/01-数据模型.md) | TaskStatus(9 态)、ReviewStatus、Task/TaskLog/Terminal、状态机转换表 |
| 02 | [任务管理器](docs/02-任务管理器.md) | TaskManager 全部方法、审阅流程、使用示例 |
| 03 | [存储层](docs/03-存储层.md) | SQLite WAL、表结构、索引、迁移机制、CRUD 操作 |
| 04 | [CLI 命令行](docs/04-CLI命令行.md) | CLI 命令详解、参数表、输出格式、使用示例 |
| 05 | [MCP Server](docs/05-MCP-Server.md) | 31 个工具详解、参数/返回格式、AI Agent 集成 |
| 06 | [Web Dashboard](docs/06-Web-Dashboard.md) | REST API、WebSocket、看板前端、审阅端点 |
| 07 | [TUI 终端界面](docs/07-TUI终端界面.md) | Textual 组件、快捷键、审阅列、布局 |
| 08 | [通知系统](docs/08-通知系统.md) | 跨平台通知、平台实现、集成建议 |
| 09 | [工具模块](docs/09-工具模块.md) | 配置管理、导入导出、终端检测 |
| 10 | [健康检查与测试](docs/10-健康检查与测试.md) | HealthChecker、TestRunner、pytest 集成 |
| 11 | [配置与部署](docs/11-配置与部署.md) | 安装指南、配置项、MCP 部署、故障排查 |

> **维护提示**：修改功能后，请同步更新对应编号的文档。文档按模块独立组织，方便定位和局部更新。

## 📄 License

MIT
