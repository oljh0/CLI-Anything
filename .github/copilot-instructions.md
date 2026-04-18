# Copilot Instructions — CLI-Anything

## 项目概述

CLI-Anything 是一个 Python 跨终端协同任务系统，采用 Master/Worker 模式，在本机多个终端窗口之间协同管理开发任务。AI Agent 可通过 MCP Server 作为 Worker 参与协同。

## 构建与测试

```bash
# 安装（含开发依赖）
pip install -e ".[dev]"

# 运行全部测试
pytest

# 运行单个测试文件
pytest tests/test_task_manager.py -v

# 运行单个测试方法
pytest tests/test_task_manager.py::TestCreateTask::test_normal -v
```

项目无独立的 lint 或 build 步骤，pytest 是唯一的测试入口。pyproject.toml 中已配置 `testpaths = ["tests"]` 和 `pythonpath = ["src"]`。

## 启动各访问层

```bash
# CLI（已安装的命令为 cli-anything；文档中 task 为系统级别名）
cli-anything list

# MCP Server（供 AI Agent 调用）
cli-anything serve

# Web 看板（默认 http://127.0.0.1:8080）
cli-anything dashboard

# TUI 终端界面
cli-anything tui
```

> **注意**：README 及 docs 中使用的 `task` 命令是对 `cli-anything` 的 shell 别名（`alias task=cli-anything`），并非独立脚本。

## 架构

### 四层设计

```
访问层 → CLI (Typer) / MCP Server (FastMCP) / Web Dashboard (FastAPI) / TUI (Textual)
核心层 → TaskManager（业务逻辑入口）/ TerminalManager / HealthChecker / TestRunner
存储层 → Database (SQLite WAL，3 张表：tasks / task_logs / terminals)
辅助层 → Config (YAML) / Notifier / ExportImport / Terminal 检测
```

**所有四个访问层共享同一个 `TaskManager` 实例**，`TaskManager` 是唯一的业务逻辑入口，直接操作 `Database` 类。不要绕过 `TaskManager` 直接写 SQL。

### 9 态状态机

任务状态流转严格受 `VALID_TRANSITIONS` 字典约束（定义在 `core/models.py`）：

```
draft → pending → claimed → in_progress → submitted → done
                                        ↘ blocked ↗
                  submitted → rejected → in_progress（重新提交）
cancelled → pending（可重新激活）
```

- `draft`：可选的审阅前置流程，审阅通过后进入 `pending`
- `done` 是终态（`VALID_TRANSITIONS[DONE] = set()`），`cancelled` 可通过 `→ pending` 重新激活
- 新增状态流转必须更新 `VALID_TRANSITIONS` 字典
- `task.can_transition_to(new_status)` 是校验状态流转的标准方法

### MCP Server

`mcp_server/server.py` 使用 FastMCP 暴露 17 个工具。每个工具函数内部调用 `_get_tm()` 获取延迟初始化的 `TaskManager`（线程安全，带 `_init_lock`）。MCP 工具的函数签名即为 AI Agent 可见的接口契约。

## 关键约定

### 代码风格
- Python 3.10+ 类型注解语法（`list[str]` 而非 `List[str]`，`X | None` 而非 `Optional[X]`）
- 文件名 snake_case，类名 PascalCase
- 函数文档字符串和关键逻辑注释使用**中文**
- 业务异常统一抛出 `TaskManagerError`

### 测试规范
- 测试文件放在 `tests/`，命名 `test_<模块名>.py`
- 测试类按功能分组（如 `TestCreateTask`、`TestDecompose`），方法名 `test_<场景>`
- 异步测试使用 `pytest-asyncio`
- 标准测试 fixture 模式（参考 `tests/test_task_manager.py`）：

```python
@pytest.fixture
def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    database.connect()
    yield database
    database.close()

@pytest.fixture
def tm(db):
    return TaskManager(db, terminal_id="test-terminal")
```

- 不同 terminal_id 的 TaskManager 共享同一个 `db` 实例来模拟多终端场景

### 数据库
- SQLite WAL 模式，带 `retry_on_lock` 装饰器处理锁冲突（指数退避重试，最多 MAX_RETRIES 次）
- 数据模型使用 `dataclass`，通过 `to_dict()` / `from_row()` 与数据库交互
- `tags` 和 `test_report` 字段在数据库中存储为 JSON 字符串
- 默认数据库路径：`~/.cli-anything/tasks.db`
- 任务 ID 为 8 位 hex 字符串（`uuid4().hex[:8]`），引用时可使用前缀匹配

### 任务描述模板

创建任务时推荐使用以下结构：

```
## 目标
简要描述要实现的功能

## 实现要求
- 具体要求 1

## 涉及文件
- src/cli_anything/xxx.py

## 测试要求
- 测试场景 1

## 验收标准
- 条件 1
```

优先级含义：1=紧急 / 2=高 / 3=中（默认）/ 4=低 / 5=最低

### Git 提交格式
```
<type>: <简述>

<详细说明（可选）>

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
```
type 枚举：`feat` / `fix` / `test` / `docs` / `refactor` / `chore`

### Web Dashboard REST API

所有端点挂载在 `/api/` 前缀下，返回 `task.to_dict()` 或其列表：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/tasks` | 列出任务（支持 `status`/`task_type`/`parent_id`/`tag`/`limit` 查询参数） |
| GET | `/api/tasks/{id}` | 获取单任务（含子任务列表 + 进度） |
| GET | `/api/tasks/{id}/logs` | 获取操作日志 |
| GET | `/api/dashboard/summary` | 统计概览（各状态计数） |
| POST | `/api/tasks/{id}/claim` | 领取 |
| POST | `/api/tasks/{id}/submit` | 提交 |
| POST | `/api/tasks/{id}/verify` | 验收（body: `approved: bool, comment: str`） |
| POST | `/api/tasks/{id}/review` | 审阅草稿（body 同上） |
| POST | `/api/tasks/{id}/resubmit-review` | 重新提交审阅 |

- **错误响应**：`TaskManagerError` 统一返回 `{"error": "..."}`，HTTP 400
- **WebSocket**：`/ws` 广播格式为 `{"event": "task_updated", "data": task_dict}`，每次变更后自动推送
- **Basic Auth**：由 `dashboard.auth.enabled` 配置控制，默认关闭

### TUI 快捷键

| 按键 | 操作 |
|------|------|
| `r` | 手动刷新所有面板 |
| `q` | 退出 TUI |

TUI 每 5 秒自动轮询刷新（`self.set_interval(5, self._refresh_all)`），包含统计面板、任务表格和操作日志三个区域。在 TUI 代码中添加新绑定须在 `BINDINGS` 列表中声明（Textual 约定）。

### 文档维护
`docs/` 目录按编号组织模块文档（00-11）。修改功能后需同步更新对应编号的文档。

## 多终端协同角色

- **Master 终端**：创建/拆解任务、审阅草稿、验收提交，不编写实现代码
- **Worker 终端**：领取/实现/测试/提交任务，提交前必须本地测试通过
- 角色行为规范详见 `.copilot/skills/` 下的 `master-terminal.md` 和 `worker-terminal.md`
