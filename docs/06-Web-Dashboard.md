# CLI-Anything — Web Dashboard 模块文档

> **源文件**: `src/cli_anything/web/dashboard.py`（~334 行）
> **框架**: [FastAPI](https://fastapi.tiangolo.com/) + [Uvicorn](https://www.uvicorn.org/)
> **前端**: 内嵌 HTML/CSS/JS（零外部依赖）
> **入口**: CLI 命令 `task dashboard`

---

## 目录

- [1. 模块概述](#1-模块概述)
- [2. 启动方式](#2-启动方式)
  - [2.1 CLI 命令](#21-cli-命令)
  - [2.2 run\_dashboard() 函数](#22-run_dashboard-函数)
  - [2.3 FastAPI app 实例](#23-fastapi-app-实例)
- [3. 全局状态与初始化](#3-全局状态与初始化)
  - [3.1 模块级全局变量](#31-模块级全局变量)
  - [3.2 \_init\_web()](#32-_init_web)
  - [3.3 \_get\_tm()](#33-_get_tm)
  - [3.4 lifespan 上下文管理器](#34-lifespan-上下文管理器)
- [4. REST API 端点](#4-rest-api-端点)
  - [4.1 GET / — 看板页面](#41-get---看板页面)
  - [4.2 GET /api/tasks — 任务列表](#42-get-apitasks--任务列表)
  - [4.3 GET /api/tasks/{task\_id} — 单任务详情](#43-get-apitaskstask_id--单任务详情)
  - [4.4 GET /api/tasks/{task\_id}/logs — 任务日志](#44-get-apitaskstask_idlogs--任务日志)
  - [4.5 GET /api/terminals — 终端列表](#45-get-apiterminals--终端列表)
  - [4.6 GET /api/dashboard/summary — 仪表板汇总](#46-get-apidashboardsummary--仪表板汇总)
  - [4.7 POST /api/tasks/{task\_id}/claim — 领取任务](#47-post-apitaskstask_idclaim--领取任务)
  - [4.8 POST /api/tasks/{task\_id}/submit — 提交任务](#48-post-apitaskstask_idsubmit--提交任务)
  - [4.9 POST /api/tasks/{task\_id}/verify — 验收任务](#49-post-apitaskstask_idverify--验收任务)
  - [4.10 POST /api/tasks/{task\_id}/review — 审阅任务](#410-post-apitaskstask_idreview--审阅任务)
  - [4.11 POST /api/tasks/{task\_id}/resubmit-review — 重新提交审阅](#411-post-apitaskstask_idresubmit-review--重新提交审阅)
- [5. WebSocket 实时通信](#5-websocket-实时通信)
  - [5.1 WS /ws — WebSocket 端点](#51-ws-ws--websocket-端点)
  - [5.2 broadcast() 广播函数](#52-broadcast-广播函数)
  - [5.3 当前集成状态](#53-当前集成状态)
- [6. 前端实现（内嵌 HTML/JS/CSS）](#6-前端实现内嵌-htmljscss)
  - [6.1 页面结构](#61-页面结构)
  - [6.2 CSS 设计系统](#62-css-设计系统)
  - [6.3 JavaScript 常量](#63-javascript-常量)
  - [6.4 看板视图](#64-看板视图)
  - [6.5 汇总卡片](#65-汇总卡片)
  - [6.6 操作日志](#66-操作日志)
  - [6.7 自动刷新机制](#67-自动刷新机制)
  - [6.8 WebSocket 客户端](#68-websocket-客户端)
- [7. 依赖关系](#7-依赖关系)
- [8. 设计要点](#8-设计要点)
- [9. 已知限制与后续改进](#9-已知限制与后续改进)
- [10. 快速参考](#10-快速参考)

---

## 1. 模块概述

`dashboard.py` 是一个基于 **FastAPI** 的 Web 仪表板模块，为 CLI-Anything 跨终端协同任务系统提供可视化的浏览器访问入口。

**核心特性：**

| 特性 | 说明 |
|------|------|
| **看板视图** | 按任务状态（9 种）分列展示，模仿 Trello/Jira 风格 |
| **REST API** | 提供任务列表、详情、日志、汇总、审阅等 JSON 接口 |
| **WebSocket** | 实时任务变更通知，所有 POST 端点自动广播 |
| **单文件全栈** | Python 后端 + 内嵌 HTML/CSS/JS，零额外前端依赖 |
| **深色主题** | 采用 Slate 色系深色 UI，适合开发者长时间使用 |

**架构位置：** 位于访问层（Access Layer），与 CLI (`cli.py`) 并列，通过 `TaskManager` 访问核心层，不直接操作数据库。

```
用户浏览器  ──HTTP/WS──▶  FastAPI (dashboard.py)  ──▶  TaskManager  ──▶  Database
```

---

## 2. 启动方式

### 2.1 CLI 命令

```bash
# 默认启动：127.0.0.1:8080，自动打开浏览器
task dashboard

# 指定 host 和 port
task dashboard --host 0.0.0.0 --port 9090

# 不自动打开浏览器
task dashboard --no-open
```

启动后访问 **http://localhost:8080** 即可看到看板仪表板。

### 2.2 run\_dashboard() 函数

```python
def run_dashboard(host: str = "127.0.0.1", port: int = 8080, auto_open: bool = True):
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `host` | `str` | `"127.0.0.1"` | 监听地址 |
| `port` | `int` | `8080` | 监听端口 |
| `auto_open` | `bool` | `True` | 启动后 1.5 秒自动在默认浏览器中打开 |

内部实现：
- 使用 `uvicorn.run()` 运行 FastAPI app
- `auto_open=True` 时，通过 `threading.Timer` + `webbrowser.open()` 延迟 1.5 秒自动打开浏览器
- 日志级别为 `info`

### 2.3 FastAPI app 实例

```python
web_app = FastAPI(title="CLI-Anything Dashboard", lifespan=lifespan)
```

- **title**: `CLI-Anything Dashboard`（显示在自动生成的 OpenAPI 文档中）
- **lifespan**: 使用 `@asynccontextmanager` 管理应用生命周期

FastAPI 自动提供 OpenAPI 文档：
- Swagger UI: `http://localhost:8080/docs`
- ReDoc: `http://localhost:8080/redoc`

---

## 3. 全局状态与初始化

### 3.1 模块级全局变量

```python
_db: Database | None = None        # 数据库实例
_tm: TaskManager | None = None     # 任务管理器实例
_ws_clients: set[WebSocket] = set()  # 当前活跃的 WebSocket 连接集合
```

使用模块级全局变量的原因：FastAPI 的路由函数需要访问共享的 `TaskManager` 实例，而 `dashboard.py` 作为独立进程运行，全局变量是最简单的共享方式。

### 3.2 \_init\_web()

```python
def _init_web():
    global _db, _tm
    if _db is not None:
        return
    config = Config()
    config.load()
    _db = Database(config.get("database.path"))
    _db.connect()
    _tm = TaskManager(_db, terminal_id="dashboard")
```

**初始化流程：**

1. 幂等检查：如果 `_db` 已存在则直接返回（防止重复初始化）
2. 加载配置：`Config().load()` 读取项目配置文件
3. 连接数据库：使用配置中的 `database.path` 建立连接
4. 创建 TaskManager：`terminal_id` 固定为 `"dashboard"`

### 3.3 \_get\_tm()

```python
def _get_tm() -> TaskManager:
    _init_web()
    assert _tm is not None
    return _tm
```

懒初始化的访问器。每个 API 端点通过调用 `_get_tm()` 获取 `TaskManager` 实例，确保首次访问时自动完成初始化。

### 3.4 lifespan 上下文管理器

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    _init_web()     # 启动时：初始化数据库和 TaskManager
    yield
    if _db:
        _db.close()  # 关闭时：释放数据库连接
```

FastAPI 应用生命周期管理器，确保：
- **启动时**：调用 `_init_web()` 初始化所有依赖
- **关闭时**：安全关闭数据库连接

---

## 4. REST API 端点

### 4.1 GET / — 看板页面

| 项 | 值 |
|----|-----|
| **路径** | `/` |
| **方法** | `GET` |
| **响应类型** | `HTMLResponse` |
| **说明** | 返回内嵌的完整 HTML 看板页面 |

返回 `_DASHBOARD_HTML` 字符串，包含完整的 HTML + CSS + JavaScript 前端界面。

---

### 4.2 GET /api/tasks — 任务列表

| 项 | 值 |
|----|-----|
| **路径** | `/api/tasks` |
| **方法** | `GET` |
| **响应类型** | `JSON` (数组) |

**查询参数：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `status` | `str` (可选) | `None` | 按状态过滤（如 `pending`、`done`） |
| `task_type` | `str` (可选) | `None` | 按类型过滤（`master` / `subtask`） |
| `parent_id` | `str` (可选) | `None` | 按父任务 ID 过滤 |
| `tag` | `str` (可选) | `None` | 按标签过滤 |
| `limit` | `int` | `100` | 返回条数上限 |

**响应示例：**

```json
[
  {
    "id": "task-001",
    "title": "实现用户登录",
    "status": "in_progress",
    "task_type": "subtask",
    "priority": 2,
    "tags": "[\"auth\", \"backend\"]",
    "reviewer": "copilot-1",
    "created_at": "2024-01-15T10:30:00"
  }
]
```

---

### 4.3 GET /api/tasks/{task\_id} — 单任务详情

| 项 | 值 |
|----|-----|
| **路径** | `/api/tasks/{task_id}` |
| **方法** | `GET` |
| **响应类型** | `JSON` |

**路径参数：**

| 参数 | 说明 |
|------|------|
| `task_id` | 任务 ID |

**特殊行为：**
- 如果任务有子任务，响应中额外包含 `subtasks`（子任务列表）和 `progress`（进度信息）
- 任务不存在时返回 `404 {"error": "not found"}`

**响应示例（含子任务）：**

```json
{
  "id": "master-001",
  "title": "用户模块",
  "status": "in_progress",
  "task_type": "master",
  "subtasks": [
    {"id": "sub-001", "title": "登录接口", "status": "done"},
    {"id": "sub-002", "title": "注册接口", "status": "pending"}
  ],
  "progress": {
    "total": 2,
    "done": 1,
    "percentage": 50.0
  }
}
```

---

### 4.4 GET /api/tasks/{task\_id}/logs — 任务日志

| 项 | 值 |
|----|-----|
| **路径** | `/api/tasks/{task_id}/logs` |
| **方法** | `GET` |
| **响应类型** | `JSON` (数组) |

**查询参数：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `limit` | `int` | `30` | 返回日志条数上限 |

返回指定任务的操作日志，每条日志包含 `timestamp`、`action`、`task_id`、`detail` 等字段。

---

### 4.5 GET /api/terminals — 终端列表

| 项 | 值 |
|----|-----|
| **路径** | `/api/terminals` |
| **方法** | `GET` |
| **响应类型** | `JSON` (数组) |

返回当前注册的所有终端信息。

---

### 4.6 GET /api/dashboard/summary — 仪表板汇总

| 项 | 值 |
|----|-----|
| **路径** | `/api/dashboard/summary` |
| **方法** | `GET` |
| **响应类型** | `JSON` |

**响应结构：**

```json
{
  "total_tasks": 42,
  "master_tasks": 8,
  "subtasks": 34,
  "status_counts": {
    "draft": 3,
    "pending": 5,
    "in_progress": 12,
    "done": 18,
    "rejected": 2,
    "blocked": 1,
    "cancelled": 1
  },
  "terminals": 3
}
```

**统计逻辑：**
- 查询所有任务（`limit=9999`）
- 按 `TaskType.MASTER` / `TaskType.SUBTASK` 分类计数
- 按 `status.value` 统计各状态分布
- 统计当前终端数量

---

### 4.7 POST /api/tasks/{task\_id}/claim — 领取任务

| 项 | 值 |
|----|-----|
| **路径** | `/api/tasks/{task_id}/claim` |
| **方法** | `POST` |
| **响应类型** | `JSON` |
| **请求体** | 无 |

**说明：** 将待处理任务标记为已领取，无需请求体。

**成功响应**：返回更新后的任务 JSON  
**失败响应**：`400 {"error": "错误描述"}` — 例如任务状态不允许领取

内部调用 `TaskManager.claim_task(task_id)`。操作完成后自动通过 WebSocket 广播 `task_updated` 事件。

---

### 4.8 POST /api/tasks/{task\_id}/submit — 提交任务

| 项 | 值 |
|----|-----|
| **路径** | `/api/tasks/{task_id}/submit` |
| **方法** | `POST` |
| **响应类型** | `JSON` |
| **请求体** | 无 |

**说明：** 将进行中的任务提交完成，无需请求体。

**成功响应**：返回更新后的任务 JSON  
**失败响应**：`400 {"error": "错误描述"}` — 例如任务状态不允许提交

内部调用 `TaskManager.submit_task(task_id)`。操作完成后自动通过 WebSocket 广播 `task_updated` 事件。

---

### 4.9 POST /api/tasks/{task\_id}/verify — 验收任务

| 项 | 值 |
|----|-----|
| **路径** | `/api/tasks/{task_id}/verify` |
| **方法** | `POST` |
| **响应类型** | `JSON` |
| **请求体** | `application/json` |

**请求体参数（使用 `Body()` 注解）：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `approved` | `bool` | ✅ 是 | `true` = 验收通过，`false` = 验收不通过 |
| `comment` | `str` | 否 | 验收意见，默认空字符串 |

**请求示例：**

```json
{
  "approved": true,
  "comment": "功能验收通过"
}
```

**成功响应**：返回更新后的任务 JSON  
**失败响应**：`400 {"error": "错误描述"}` — 例如任务状态不允许验收

内部调用 `TaskManager.verify_task(task_id, approved, comment)`。操作完成后自动通过 WebSocket 广播 `task_updated` 事件。

---

### 4.10 POST /api/tasks/{task\_id}/review — 审阅任务

| 项 | 值 |
|----|-----|
| **路径** | `/api/tasks/{task_id}/review` |
| **方法** | `POST` |
| **响应类型** | `JSON` |
| **请求体** | `application/json` |

**请求体参数（使用 `Body()` 注解）：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `approved` | `bool` | ✅ 是 | `true` = 通过审阅，`false` = 驳回 |
| `comment` | `str` | 否 | 审阅意见，默认空字符串 |

**请求示例：**

```json
{
  "approved": true,
  "comment": "代码质量良好，approve"
}
```

**成功响应**：返回更新后的任务 JSON  
**失败响应**：`400 {"error": "错误描述"}` — 例如任务状态不允许审阅

内部调用 `TaskManager.review_task(task_id, approved, comment)`。操作完成后自动通过 WebSocket 广播 `task_updated` 事件。

---

### 4.11 POST /api/tasks/{task\_id}/resubmit-review — 重新提交审阅

| 项 | 值 |
|----|-----|
| **路径** | `/api/tasks/{task_id}/resubmit-review` |
| **方法** | `POST` |
| **响应类型** | `JSON` |
| **请求体** | 无 |

**说明：** 将被驳回的草稿任务重新提交审阅，无需请求体。

**成功响应**：返回更新后的任务 JSON  
**失败响应**：`400 {"error": "错误描述"}`

内部调用 `TaskManager.resubmit_for_review(task_id)`。操作完成后自动通过 WebSocket 广播 `task_updated` 事件。

---

## 5. WebSocket 实时通信

### 5.1 WS /ws — WebSocket 端点

| 项 | 值 |
|----|-----|
| **路径** | `/ws` |
| **协议** | WebSocket |

```python
@web_app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    _ws_clients.add(ws)
    try:
        while True:
            await ws.receive_text()  # 保持连接存活
    except WebSocketDisconnect:
        _ws_clients.discard(ws)
```

**连接生命周期：**

1. 客户端发起 WebSocket 连接
2. 服务端 `accept()` 并加入 `_ws_clients` 集合
3. 持续等待客户端消息（保持连接存活）
4. 断开时从集合中移除

### 5.2 broadcast() 广播函数

```python
async def broadcast(event: str, data: dict):
    """向所有连接的客户端广播事件"""
    msg = json.dumps({"event": event, "data": data}, ensure_ascii=False)
    dead = set()
    for ws in _ws_clients:
        try:
            await ws.send_text(msg)
        except Exception:
            dead.add(ws)
    _ws_clients -= dead
```

**消息格式：**

```json
{
  "event": "task_updated",
  "data": {
    "task_id": "task-001",
    "status": "done"
  }
}
```

**特性：**
- 遍历所有活跃客户端发送消息
- 自动清理发送失败的"死连接"
- 使用 `ensure_ascii=False` 保留中文字符

### 5.3 当前集成状态

> ✅ **已集成**：所有 5 个 POST 端点（claim、submit、verify、review、resubmit-review）在操作成功后均调用 `await broadcast("task_updated", task.to_dict())`，实现真正的实时推送。

前端通过 `ws.onmessage` 监听广播事件并自动调用 `refresh()` 刷新看板。`setInterval(refresh, 5000)` 轮询作为 fallback 保留，确保即使 WebSocket 断开也能定期更新。

---

## 6. 前端实现（内嵌 HTML/JS/CSS）

整个前端页面以 Python 原始字符串 `_DASHBOARD_HTML` 的形式内嵌在模块末尾（约 134 行），包含完整的 HTML 结构、CSS 样式和 JavaScript 逻辑。

### 6.1 页面结构

```
┌─────────────────────────────────────────────────┐
│  header:  📋 CLI-Anything  [Dashboard]    ● WS  │
├─────────────────────────────────────────────────┤
│  summary: 总任务 | 主任务 | 子任务 | 草稿 | ... │
├─────────────────────────────────────────────────┤
│  📌 任务看板                                     │
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐  │
│  │ 草稿  │ │ 待处理│ │ 已领取│ │ 进行中│ │ ...  │  │
│  │      │ │      │ │      │ │      │ │      │  │
│  │ card │ │ card │ │ card │ │ card │ │ card │  │
│  │ card │ │      │ │      │ │ card │ │      │  │
│  └──────┘ └──────┘ └──────┘ └──────┘ └──────┘  │
├─────────────────────────────────────────────────┤
│  📝 操作日志                                     │
│  2024-01-15 10:30  claim    task-001  已领取     │
│  2024-01-15 10:25  create   task-001  创建任务   │
└─────────────────────────────────────────────────┘
```

**HTML 元素 ID 映射：**

| ID | 对应区域 |
|----|---------|
| `#summary` | 汇总卡片容器 |
| `#kanban` | 看板列容器 |
| `#logs` | 操作日志容器 |
| `#ws-status` | WebSocket 状态指示灯（header 右侧） |

### 6.2 CSS 设计系统

**主题色变量（CSS Custom Properties）：**

```css
:root {
  --bg:      #0f172a;   /* 页面背景（深蓝灰） */
  --card:    #1e293b;   /* 卡片背景 */
  --border:  #334155;   /* 边框颜色 */
  --text:    #e2e8f0;   /* 主文本色 */
  --muted:   #94a3b8;   /* 次要文本色 */
  --green:   #22c55e;   /* 已完成 / 低优先级 */
  --yellow:  #eab308;   /* 待处理 / 中优先级 */
  --blue:    #3b82f6;   /* 进行中 */
  --cyan:    #06b6d4;   /* 已领取 */
  --red:     #ef4444;   /* 驳回 / 高优先级 */
  --magenta: #a855f7;   /* 已提交 */
  --orange:  #f97316;   /* 草稿 / 次高优先级 */
}
```

**布局系统：**

- 汇总区域：`grid-template-columns: repeat(auto-fit, minmax(180px, 1fr))`（自适应网格）
- 看板区域：`grid-template-columns: repeat(auto-fit, minmax(240px, 1fr))`（响应式列）
- 最大宽度 `1400px`，居中显示

**优先级视觉标识：**

| CSS 类 | 含义 | 颜色 |
|--------|------|------|
| `.priority-1` | 最高优先级 | 🔴 红色左边框 |
| `.priority-2` | 高优先级 | 🟠 橙色左边框 |
| `.priority-3` | 中等优先级 | 🟡 黄色左边框 |
| `.priority-4` | 低优先级 | 🟢 绿色左边框 |
| `.priority-5` | 最低优先级 | ⚪ 灰色左边框 |

### 6.3 JavaScript 常量

#### STATUS\_COLORS — 状态颜色映射（9 种）

```javascript
const STATUS_COLORS = {
  draft:       'var(--orange)',   // 🟠 橙色
  pending:     'var(--yellow)',   // 🟡 黄色
  claimed:     'var(--cyan)',     // 🔵 青色
  in_progress: 'var(--blue)',     // 🔷 蓝色
  submitted:   'var(--magenta)',  // 🟣 紫色
  done:        'var(--green)',    // 🟢 绿色
  rejected:    'var(--red)',      // 🔴 红色
  blocked:     'var(--muted)',    // ⚪ 灰色
  cancelled:   '#666'            // ⚫ 深灰色
};
```

#### STATUS\_LABELS — 状态中文标签

```javascript
const STATUS_LABELS = {
  draft:       '草稿',
  pending:     '待处理',
  claimed:     '已领取',
  in_progress: '进行中',
  submitted:   '已提交',
  done:        '已完成',
  rejected:    '已驳回',
  blocked:     '已阻塞',
  cancelled:   '已取消'
};
```

#### PRIORITY\_LABELS — 优先级 Emoji 标签

```javascript
const PRIORITY_LABELS = {1: '🔴', 2: '🟠', 3: '🟡', 4: '🟢', 5: '⚪'};
```

#### KANBAN\_ORDER — 看板列顺序

```javascript
const KANBAN_ORDER = ['draft', 'pending', 'claimed', 'in_progress', 'submitted', 'done', 'rejected'];
```

> **注意**：`blocked` 和 `cancelled` 不在看板列中显示——这些状态的任务不会出现在看板上。

### 6.4 看板视图

**渲染流程（`loadKanban()` 函数）：**

1. 调用 `GET /api/tasks` 获取全部任务
2. 按 `KANBAN_ORDER` 初始化空列 `cols`
3. 将每个任务分配到对应状态列
4. 逐列生成 HTML：
   - 列标题：`<dot>` 状态色 + 中文状态名 + 数量
   - 任务卡片：优先级 emoji + 标题 + ID + 类型 + 审阅者 + 标签

**任务卡片结构：**

```
┌─────────────────────────┐
│ 🟠 实现用户登录          │  ← 优先级 emoji + 标题
│ task-001  subtask        │  ← ID + 类型
│ 🔍copilot-1  auth       │  ← 审阅者徽标 + 标签
└─────────────────────────┘
```

**卡片特殊标识：**
- 左边框颜色：对应 `priority-{1~5}` CSS 类
- `🔍` 前缀的审阅者徽标：仅当 `task.reviewer` 非空时显示
- 标签 `tag`：解析自 `task.tags`（JSON 数组字符串）

### 6.5 汇总卡片

**渲染流程（`loadSummary()` 函数）：**

调用 `GET /api/dashboard/summary`，生成 6 个汇总卡片：

| 卡片 | 数据来源 | 说明 |
|------|---------|------|
| 总任务 | `d.total_tasks` | 所有任务总数 |
| 主任务 | `d.master_tasks` | `task_type=master` 的数量 |
| 子任务 | `d.subtasks` | `task_type=subtask` 的数量 |
| 草稿/审阅中 | `d.status_counts.draft` | `status=draft` 的数量 |
| 已完成 | `d.status_counts.done` | `status=done` 的数量 |
| 终端 | `d.terminals` | 已注册终端数 |

### 6.6 操作日志

**渲染流程（`loadLogs()` 函数）：**

1. 获取前 10 个任务的最近 5 条日志（每任务）
2. 按 `timestamp` 降序排序
3. 截取前 20 条展示

**单条日志显示：**

```
时间戳            操作类型    任务ID      详情
2024-01-15 10:30  claim      task-001   已领取
```

如果没有日志，显示灰色占位文本 "暂无日志"。

### 6.7 自动刷新机制

```javascript
async function refresh() {
  await Promise.all([loadSummary(), loadKanban(), loadLogs()]);
}

refresh();                    // 页面加载时立即刷新一次
setInterval(refresh, 5000);   // 之后每 5 秒自动刷新
```

三个区域（汇总、看板、日志）并行加载，减少总刷新耗时。

### 6.8 WebSocket 客户端

```javascript
function connectWS() {
  const ws = new WebSocket(`ws://${location.host}/ws`);
  const dot = document.getElementById('ws-status');
  ws.onopen  = () => { dot.className = 'connected'; dot.title = 'WebSocket 已连接' };
  ws.onclose = () => { dot.className = ''; dot.title = 'WebSocket 未连接'; setTimeout(connectWS, 3000) };
  ws.onmessage = (e) => { const d = JSON.parse(e.data); if (d.event) refresh() };
}
```

**特性：**
- 页面加载时自动连接
- 连接状态通过 header 右侧圆点指示：🟢 已连接 / 🔴 未连接
- 断开后每 3 秒自动重连
- 收到任何带 `event` 字段的消息即触发全量刷新

---

## 7. 依赖关系

### Python 依赖

| 模块 | 来源 | 用途 |
|------|------|------|
| `FastAPI` | `fastapi` | Web 框架 |
| `WebSocket`, `WebSocketDisconnect` | `fastapi` | WebSocket 支持 |
| `Query`, `Body` | `fastapi` | 请求参数注解 |
| `HTMLResponse`, `JSONResponse` | `fastapi.responses` | 响应类型 |
| `StaticFiles` | `fastapi.staticfiles` | 静态文件（已导入，未使用） |
| `uvicorn` | `uvicorn` | ASGI 服务器（在 `run_dashboard` 内按需导入） |

### 项目内部依赖

| 模块 | 用途 |
|------|------|
| `cli_anything.core.models.TaskStatus` | 任务状态枚举 |
| `cli_anything.core.models.TaskType` | 任务类型枚举 |
| `cli_anything.core.models.ReviewStatus` | 审阅状态枚举（已导入，供后续扩展使用） |
| `cli_anything.core.task_manager.TaskManager` | 核心业务逻辑 |
| `cli_anything.core.task_manager.TaskManagerError` | 业务异常类 |
| `cli_anything.storage.database.Database` | 数据库访问层 |
| `cli_anything.utils.config.Config` | 配置管理 |

---

## 8. 设计要点

### 1. 单文件全栈架构

Python 后端代码与完整的 HTML/CSS/JS 前端共存于一个 `.py` 文件中。前端以 Python 原始字符串 `_DASHBOARD_HTML` 的形式嵌入，避免了静态文件服务的复杂性。

**优势：** 部署零配置，无需处理静态文件路径、打包构建  
**代价：** 前端修改需在 Python 字符串中编辑，不支持 IDE 前端高亮

### 2. 零依赖前端

前端不使用任何 JavaScript 框架（React、Vue 等）或 CSS 库（Bootstrap、Tailwind 等），全部使用原生 HTML + CSS + Vanilla JS。

### 3. 看板风格布局

模仿 Trello / Jira 的列式看板设计：
- 每种状态对应一列
- `draft`（草稿）列以橙色标识，排在最前
- CSS Grid 响应式布局，窄屏自动折叠

### 4. 审阅 API 使用 Body() 注解

`review` 端点使用 FastAPI 的 `Body(...)` 注解而非 Pydantic 模型来解析请求体：

```python
def api_review_task(
    task_id: str,
    approved: bool = Body(...),    # ... 表示必填
    comment: str = Body(""),       # 默认空字符串
):
```

这是一种轻量级做法，避免为仅有两个字段的请求定义独立的 Pydantic schema。

### 5. 懒初始化模式

数据库和 TaskManager 采用懒初始化：
- `lifespan` 在启动时触发 `_init_web()`
- 各 API 端点通过 `_get_tm()` 获取实例
- `_init_web()` 内部幂等检查，确保只初始化一次

### 6. WebSocket 实时推送架构

所有 POST 变更端点（claim/submit/verify/review/resubmit-review）在操作成功后自动调用 `await broadcast("task_updated", task.to_dict())`。前端通过 `ws.onmessage` 监听事件并触发看板刷新，实现毫秒级实时更新。轮询（5 秒间隔）作为 WebSocket 断线时的 fallback 保留。

---

## 9. 已知限制与后续改进

| 编号 | 限制 | 影响 | 可能的改进方向 |
|------|------|------|---------------|
| 1 | `StaticFiles` 已导入但未使用 | 无功能影响，冗余导入 | 移除或用于后续静态资源服务 |
| 2 | 日志加载逻辑效率低 | 需要 N+1 次请求（1 次列表 + N 次日志） | 增加聚合日志 API |
| 3 | `limit=9999` 硬编码 | summary 统计查询所有任务 | 添加专用统计 SQL 查询 |
| 4 | 前端无路由 / SPA | 无法通过 URL 直接访问特定任务 | 添加前端路由或详情弹窗 |
| 5 | 无认证/授权 | 任何人可访问 Dashboard | 添加 Basic Auth 或 Token |
| 6 | `blocked` 和 `cancelled` 不在看板中 | 这两种状态的任务在看板上不可见 | 添加"归档"列或过滤视图 |

---

## 10. 快速参考

### API 端点速查表

| 方法 | 路径 | 说明 | 请求体 |
|------|------|------|--------|
| `GET` | `/` | 看板 HTML 页面 | — |
| `GET` | `/api/tasks` | 任务列表 | — |
| `GET` | `/api/tasks/{id}` | 任务详情（含子任务） | — |
| `GET` | `/api/tasks/{id}/logs` | 任务日志 | — |
| `GET` | `/api/terminals` | 终端列表 | — |
| `GET` | `/api/dashboard/summary` | 仪表板统计汇总 | — |
| `POST` | `/api/tasks/{id}/claim` | 领取任务 | — |
| `POST` | `/api/tasks/{id}/submit` | 提交任务 | — |
| `POST` | `/api/tasks/{id}/verify` | 验收任务 | `{approved, comment}` |
| `POST` | `/api/tasks/{id}/review` | 审阅通过/驳回 | `{approved, comment}` |
| `POST` | `/api/tasks/{id}/resubmit-review` | 重新提交审阅 | — |
| `WS` | `/ws` | WebSocket 实时通道 | — |

### 启动命令速查

```bash
# 基础启动
task dashboard

# 局域网访问 + 自定义端口
task dashboard --host 0.0.0.0 --port 9090

# 使用 curl 测试 API
curl http://localhost:8080/api/tasks
curl http://localhost:8080/api/dashboard/summary
curl -X POST http://localhost:8080/api/tasks/task-001/review \
  -H "Content-Type: application/json" \
  -d '{"approved": true, "comment": "LGTM"}'
```

---

## 11. 自动化测试

> **测试文件**: `tests/test_dashboard.py`（18 项测试）

### 测试 Fixture

| Fixture | 说明 |
|---------|------|
| `db` | 跨线程安全的 SQLite 数据库（`check_same_thread=False`） |
| `tm` | 绑定测试 DB 的 TaskManager 实例 |
| `client` | 认证禁用的 FastAPI TestClient |
| `auth_client` | 认证启用的 FastAPI TestClient（admin/secret123） |

### 测试覆盖

#### Basic Auth 中间件（6 项）

- 认证禁用时请求直接通过
- 认证启用时无 Header 返回 401
- 错误密码返回 401
- 错误用户名返回 401
- 正确凭据返回 200
- 无效 Base64 返回 401

#### REST API 端点（12 项）

- GET /api/tasks — 空列表和有数据
- GET /api/tasks/{id} — 任务详情
- GET /api/dashboard/summary — 汇总统计
- POST /api/tasks/{id}/claim — 领取 + 非法领取 400
- POST /api/tasks/{id}/submit — 提交
- POST /api/tasks/{id}/verify — 通过/驳回
- POST /api/tasks/{id}/review — 审阅通过
- POST /api/tasks/{id}/resubmit-review — 重新提交审阅
- GET / — 返回 HTML 页面

### 关键实现细节

- 测试 fixture 通过重建 SQLite 连接并设置 `check_same_thread=False` 解决 FastAPI TestClient 的跨线程问题
- 直接注入模块级全局变量（`dash._db`、`dash._tm`、`dash._config`）绕过 `_init_web()` 初始化
- Mock Config 通过 `side_effect` 动态返回不同配置值
