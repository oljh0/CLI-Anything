# Copilot CLI + Qwen CLI + Gemini CLI 多终端协同开发指南

> 使用 `copilot-cli` 作为主终端（Master），`qwen-cli` 和 `gemini-cli` 作为子终端（Worker），在同一个项目中协同完成开发任务。

---

## 📋 前置条件

### 1. 已安装的工具

确保以下工具已正确安装并可用：

| 工具 | 角色 | 用途 |
|------|------|------|
| `copilot-cli` | 主终端 (Master) | 任务管理、拆解、验收 |
| `qwen-cli` | 子终端 1 (Worker) | 领取子任务、开发实现 |
| `gemini-cli` | 子终端 2 (Worker) | 领取子任务、开发实现 |
| `cli-anything` | 协同系统 | 底层任务协同引擎 |

### 2. 安装 CLI-Anything

```bash
# 进入项目目录
cd F:\OpenAI\CLI-Anything

# 安装项目（开发模式）
pip install -e ".[dev]"

# 验证安装
cli-anything --version
```

### 3. 项目目录约定

假设我们正在开发一个 **Python Web 项目**，目录结构如下：

```
F:\Projects\my-web-app\
├── src\
│   ├── models\          # 数据模型
│   ├── routes\          # API 路由
│   └── utils\           # 工具函数
├── tests\
│   ├── test_models\
│   ├── test_routes\
│   └── test_utils\
└── requirements.txt
```

**所有终端都需要在同一个项目目录下工作**。

---

## 🎯 完整示例：开发一个用户管理系统

### 任务目标

在一个 Web 项目中实现用户管理系统，包括：
- 用户注册 API
- 用户登录 API
- 密码重置 API

### 角色分工

| 终端 | 角色 | 负责内容 |
|------|------|----------|
| Copilot CLI | Master（项目经理） | 创建任务、拆解子任务、监控进度、验收成果 |
| Qwen CLI | Worker-1（开发者 A） | 实现用户注册 API + 相关测试 |
| Gemini CLI | Worker-2（开发者 B） | 实现用户登录 API + 相关测试 |
| Master 终端 | Worker-3（可选） | 实现密码重置 API（如需更多人手） |

---

## 🚀 详细操作步骤

### 阶段一：环境初始化

#### 步骤 1：打开 3 个终端窗口

分别打开 3 个终端窗口（PowerShell/CMD/WSL 均可）：
- **终端 A**：Copilot CLI（将作为 Master）
- **终端 B**：Qwen CLI（将作为 Worker-1）
- **终端 C**：Gemini CLI（将作为 Worker-2）

#### 步骤 2：在每个终端中切换到项目目录

```powershell
# 在所有 3 个终端中执行
cd F:\Projects\my-web-app
```

#### 步骤 3：初始化 CLI-Anything

**终端 A（Master - Copilot CLI）**：
```bash
# 初始化为主终端
cli-anything init --role master --name "Copilot-Master"
```

**终端 B（Worker-1 - Qwen CLI）**：
```bash
# 初始化为子终端
cli-anything init --role worker --name "Qwen-Worker-1"
```

**终端 C（Worker-2 - Gemini CLI）**：
```bash
# 初始化为子终端
cli-anything init --role worker --name "Gemini-Worker-2"
```

**作用**：这会在 `~/.cli-anything/config.yaml` 中生成配置文件，记录终端角色和名称。

**验证**：
```bash
# 在任意终端执行
cli-anything terminals
```

你应该看到类似输出：
```
┌─────────────────────────────────────────────────────────────┐
│ 终端列表                                                     │
├──────────────┬──────────┬──────────────────┬────────────────┤
│ ID           │ 角色     │ 名称             │ 最后活跃时间    │
├──────────────┼──────────┼──────────────────┼────────────────┤
│ abc123...    │ master   │ Copilot-Master   │ 刚刚            │
│ def456...    │ worker   │ Qwen-Worker-1    │ 刚刚            │
│ ghi789...    │ worker   │ Gemini-Worker-2  │ 刚刚            │
└──────────────┴──────────┴──────────────────┴────────────────┘
```

---

### 阶段二：创建和拆解任务（Master 终端 - Copilot CLI）

#### 步骤 4：创建主任务

在 **终端 A（Copilot CLI）** 中执行：

```bash
cli-anything create "实现用户管理系统" \
  --description "包括用户注册、登录、密码重置功能，使用 JWT 认证和 bcrypt 密码加密" \
  --priority 1 \
  --tags "auth,security,api"
```

**输出示例**：
```
✅ 任务创建成功
   任务 ID: task-001
   标题: 实现用户管理系统
   优先级: 1 (紧急)
   标签: auth, security, api
```

**重要**：记住这个任务 ID（如 `task-001`），后续拆解时需要使用。

#### 步骤 5：拆解主任务为子任务

在 **终端 A（Copilot CLI）** 中执行：

```bash
cli-anything decompose task-001 '[
  {
    "title": "实现用户注册 API",
    "description": "创建 POST /api/register 接口，包含邮箱验证、密码强度检查、bcrypt 加密存储",
    "priority": 1,
    "tags": ["api", "register"]
  },
  {
    "title": "实现用户登录 API",
    "description": "创建 POST /api/login 接口，验证用户名密码，生成 JWT token",
    "priority": 1,
    "tags": ["api", "login", "jwt"]
  },
  {
    "title": "实现密码重置 API",
    "description": "创建 POST /api/password/reset 接口，发送重置邮件，验证 token 后更新密码",
    "priority": 2,
    "tags": ["api", "password"]
  }
]'
```

**输出示例**：
```
✅ 任务拆解成功，创建 3 个子任务
   ├─ task-001-1: 实现用户注册 API
   ├─ task-001-2: 实现用户登录 API
   └─ task-001-3: 实现密码重置 API
```

**重要**：记下这 3 个子任务的 ID，稍后会分配给不同的 Worker。

#### 步骤 6：查看任务状态

在 **终端 A（Copilot CLI）** 中执行：

```bash
# 查看所有子任务
cli-anything list --parent-id task-001

# 或查看单个主任务详情（含子任务进度）
cli-anything show task-001
```

**输出示例**：
```
任务: 实现用户管理系统
状态: pending
子任务进度: 0/3 完成

┌─────────────┬──────────────┬──────────┬──────────┐
│ 子任务 ID   │ 标题         │ 状态     │ 负责人   │
├─────────────┼──────────────┼──────────┼──────────┤
│ task-001-1  │ 用户注册 API │ pending  │ -        │
│ task-001-2  │ 用户登录 API │ pending  │ -        │
│ task-001-3  │ 密码重置 API │ pending  │ -        │
└─────────────┴──────────────┴──────────┴──────────┘
```

---

### 阶段三：领取和完成任务（Worker 终端）

#### 步骤 7：查看可领取的任务

在 **终端 B（Qwen CLI）** 和 **终端 C（Gemini CLI）** 中分别执行：

```bash
cli-anything available
```

**输出示例**：
```
┌─────────────────────────────────────────────────────────────┐
│ 可领取的任务                                                 │
├─────────────┬──────────────┬──────────┬─────────────────────┤
│ 任务 ID     │ 标题         │ 优先级   │ 描述                │
├─────────────┼──────────────┼──────────┼─────────────────────┤
│ task-001-1  │ 用户注册 API │ 1 (紧急) │ 创建注册接口...      │
│ task-001-2  │ 用户登录 API │ 1 (紧急) │ 创建登录接口...      │
│ task-001-3  │ 密码重置 API │ 2 (高)   │ 创建密码重置接口...  │
└─────────────┴──────────────┴──────────┴─────────────────────┘
```

#### 步骤 8：领取子任务

**终端 B（Qwen CLI）** 领取注册 API 任务：
```bash
cli-anything claim task-001-1
```

**终端 C（Gemini CLI）** 领取登录 API 任务：
```bash
cli-anything claim task-001-2
```

**输出示例**：
```
✅ 任务领取成功
   任务: task-001-1 - 实现用户注册 API
   状态: claimed → in_progress
   领取者: Qwen-Worker-1
```

**此时如果在 Master 终端查看**：
```bash
cli-anything show task-001
```

会看到：
```
┌─────────────┬──────────────┬─────────────┬──────────────────┐
│ 子任务 ID   │ 标题         │ 状态        │ 负责人           │
├─────────────┼──────────────┼─────────────┼──────────────────┤
│ task-001-1  │ 用户注册 API │ in_progress │ Qwen-Worker-1    │
│ task-001-2  │ 用户登录 API │ in_progress │ Gemini-Worker-2  │
│ task-001-3  │ 密码重置 API │ pending     │ -                │
└─────────────┴──────────────┴─────────────┴──────────────────┘
进度: 0/3 完成 (0%)
```

#### 步骤 9：开始开发

**此时两个 Worker 终端可以并行工作了**。

**终端 B（Qwen CLI）** - 开发用户注册 API：

你可以在 Qwen CLI 中进行正常的开发对话，例如：
```
请帮我实现用户注册 API，要求：
1. POST /api/register 接口
2. 验证邮箱格式
3. 检查密码强度（至少 8 位，包含字母和数字）
4. 使用 bcrypt 加密密码
5. 保存到数据库
6. 编写对应的单元测试
```

Qwen CLI 会帮你：
- 创建 `src/routes/auth.py` 中的注册接口
- 创建 `tests/test_routes/test_register.py` 单元测试
- 实现所有功能逻辑

**终端 C（Gemini CLI）** - 开发用户登录 API：

同样在 Gemini CLI 中：
```
请帮我实现用户登录 API，要求：
1. POST /api/login 接口
2. 验证邮箱和密码
3. 生成 JWT token（有效期 24 小时）
4. 返回用户信息和 token
5. 编写对应的单元测试
```

#### 步骤 10：完成任务并提交

**重要**：在提交之前，确保你已经：
1. ✅ 完成了所有功能代码
2. ✅ 编写了对应的单元测试
3. ✅ 本地运行测试确认通过

**终端 B（Qwen CLI）** 提交注册 API 任务：

```bash
# 设置测试文件路径（首次提交时需要指定）
cli-anything update task-001-1 \
  --test-path "tests/test_routes/test_register.py" \
  --work-dir "F:\Projects\my-web-app"

# 提交任务（会自动运行测试）
cli-anything submit task-001-1
```

**输出示例**：
```
🔄 正在运行测试...
   测试路径: tests/test_routes/test_register.py
   
✅ 测试通过！
   总计: 5 个测试
   通过: 5
   失败: 0
   耗时: 1.23s

✅ 任务提交成功
   任务: task-001-1 - 实现用户注册 API
   状态: submitted
   等待验收...
```

**终端 C（Gemini CLI）** 提交登录 API 任务：

```bash
# 设置测试文件路径
cli-anything update task-001-2 \
  --test-path "tests/test_routes/test_login.py" \
  --work-dir "F:\Projects\my-web-app"

# 提交任务
cli-anything submit task-001-2
```

**此时在 Master 终端查看**：
```bash
cli-anything show task-001
```

会看到：
```
┌─────────────┬──────────────┬───────────┬──────────────────┬────────────┐
│ 子任务 ID   │ 标题         │ 状态      │ 负责人           │ 测试结果   │
├─────────────┼──────────────┼───────────┼──────────────────┼────────────┤
│ task-001-1  │ 用户注册 API │ submitted │ Qwen-Worker-1    │ ✅ PASSED  │
│ task-001-2  │ 用户登录 API │ submitted │ Gemini-Worker-2  │ ✅ PASSED  │
│ task-001-3  │ 密码重置 API │ pending   │ -                │ -          │
└─────────────┴──────────────┴───────────┴──────────────────┴────────────┘
进度: 0/3 完成 (0%), 2/3 已提交待验收
```

---

### 阶段四：验收任务（Master 终端 - Copilot CLI）

#### 步骤 11：查看提交的任务详情

在 **终端 A（Copilot CLI）** 中查看提交的任务：

```bash
# 查看某个子任务的详情
cli-anything show task-001-1
```

**输出示例**：
```
任务详情: task-001-1 - 实现用户注册 API
状态: submitted
负责人: Qwen-Worker-1
提交时间: 2026-04-11 14:30
测试结果: ✅ PASSED (5/5 通过)

测试报告:
  - 总测试数: 5
  - 通过: 5
  - 失败: 0
  - 耗时: 1.23s

代码变更:
  - 新增文件: src/routes/auth.py, tests/test_routes/test_register.py
  - 修改文件: src/app.py (注册路由)
```

#### 步骤 12：验收通过

在 **终端 A（Copilot CLI）** 中执行：

```bash
# 验收通过 task-001-1
cli-anything verify task-001-1 --approve --comment "代码质量很好，测试覆盖全面"

# 验收通过 task-001-2
cli-anything verify task-001-2 --approve --comment "JWT 实现正确，安全性良好"
```

**输出示例**：
```
✅ 验收入库
   任务: task-001-1 - 实现用户注册 API
   状态: submitted → done
   验收意见: 代码质量很好，测试覆盖全面
```

**如果发现问题需要驳回**：
```bash
cli-anything verify task-001-1 --reject --comment "缺少邮箱唯一性检查，请补充"
```

被驳回的任务会回到 `rejected` 状态，Worker 需要修改后重新提交。

#### 步骤 13：查看最终进度

```bash
cli-anything show task-001
```

**输出示例**：
```
任务: 实现用户管理系统
状态: in_progress
子任务进度: 2/3 完成 (67%)

┌─────────────┬──────────────┬──────────┬──────────────────┬────────────┐
│ 子任务 ID   │ 标题         │ 状态     │ 负责人           │ 测试结果   │
├─────────────┼──────────────┼──────────┼──────────────────┼────────────┤
│ task-001-1  │ 用户注册 API │ done     │ Qwen-Worker-1    │ ✅ PASSED  │
│ task-001-2  │ 用户登录 API │ done     │ Gemini-Worker-2  │ ✅ PASSED  │
│ task-001-3  │ 密码重置 API │ pending  │ -                │ -          │
└─────────────┴──────────────┴──────────┴──────────────────┴────────────┘
```

**此时你可以**：
- 继续让某个 Worker 领取 `task-001-3` 完成剩余工作
- 或者自己领取并完成

```bash
# 在 Master 终端领取最后一个任务
cli-anything claim task-001-3
cli-anything start task-001-3

# 完成后提交
cli-anything update task-001-3 \
  --test-path "tests/test_routes/test_password_reset.py"
cli-anything submit task-001-3

# 自我验收
cli-anything verify task-001-3 --approve --comment "密码重置功能完成"
```

**最终状态**：
```
✅ 主任务完成！
   任务: task-001 - 实现用户管理系统
   状态: done
   子任务进度: 3/3 完成 (100%)
```

---

## 🎨 使用 Web 看板（可选但强烈推荐）

### 启动 Web 看板

在 **任意终端** 中执行：

```bash
cli-anything dashboard
```

**输出**：
```
🌐 Web 看板已启动
   访问地址: http://127.0.0.1:8080
   按 Ctrl+C 停止服务
```

浏览器会自动打开，你会看到一个 **Kanban 看板**，包含 6 列：

```
┌──────────┬──────────┬────────────┬──────────┬──────────┬──────────┐
│ 待处理   │ 已领取   │ 进行中     │ 已提交   │ 已完成   │ 已驳回   │
│          │          │            │          │          │          │
│ 密码重置 │          │            │ 注册API  │          │          │
│          │          │            │ 登录API  │          │          │
└──────────┴──────────┴────────────┴──────────┴──────────┴──────────┘
```

**看板特性**：
- ✅ **实时更新**：通过 WebSocket 自动刷新
- ✅ **统计卡片**：显示总任务数、完成数、终端数
- ✅ **操作日志**：实时显示所有终端的操作记录
- ✅ **深色主题**：舒适的开发体验

---

## 🔌 使用 AI Agent 通过 MCP 协议协同

除了直接使用 CLI，你还可以让 AI Agent 通过 MCP 协议参与协同。

### 配置 MCP Server

#### 步骤 1：启动 MCP Server

在 **Master 终端** 执行：

```bash
cli-anything serve
```

**输出**：
```
🤖 MCP Server 已启动
   传输方式: stdio
   等待 AI Agent 连接...
```

#### 步骤 2：在 Copilot CLI 中配置 MCP

在 Copilot CLI 的配置文件中添加 MCP Server 连接（具体配置方式取决于 Copilot CLI 的版本）。

示例配置：
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

#### 步骤 3：通过 Copilot CLI 使用 MCP 工具

现在你可以在 Copilot CLI 中直接调用任务管理功能：

```
# 示例对话
你: "帮我创建一个新任务，标题是实现支付功能"

Copilot CLI 会调用 MCP 工具:
  task_create(
    title="实现支付功能",
    description="",
    priority=3,
    tags=[]
  )

返回:
  {
    "success": true,
    "task_id": "task-002",
    "title": "实现支付功能"
  }

Copilot CLI 回复:
  ✅ 已创建任务 task-002: 实现支付功能
```

#### 可用的 MCP 工具列表

| 工具名 | 功能 | 使用场景 |
|--------|------|----------|
| `task_create` | 创建任务 | 主终端创建新任务 |
| `task_decompose` | 拆解子任务 | 主终端拆解任务 |
| `task_list` | 查询任务列表 | 查看所有任务或按条件过滤 |
| `task_show` | 获取任务详情 | 查看单个任务完整信息 |
| `task_claim` | 领取任务 | Worker 领取子任务 |
| `task_unclaim` | 释放任务 |  Worker 归还未开始的任务 |
| `task_start` | 开始任务 | claimed → in_progress |
| `task_submit` | 提交任务 | Worker 完成任务并提交 |
| `task_verify` | 验收任务 | Master 审核任务 |
| `task_progress` | 查看进度 | 获取主任务的子任务进度 |
| `task_update` | 更新任务属性 | 修改标题、描述、测试路径等 |
| `task_delete` | 删除任务 | 删除不需要的任务 |
| `task_log` | 查看操作日志 | 审计任务变更历史 |
| `task_test` | 运行测试 | 手动触发测试运行 |
| `task_health` | 健康检查 | 检查终端在线状态 |

---

## 📊 常用命令速查

### Master 终端常用命令

```bash
# 创建任务
cli-anything create "任务标题" --description "详细描述" --priority 1 --tags "tag1,tag2"

# 拆解任务
cli-anything decompose <task-id> '[{"title":"子任务1"},{"title":"子任务2"}]'

# 查看进度
cli-anything show <task-id>
cli-anything progress <task-id>

# 验收任务
cli-anything verify <subtask-id> --approve --comment "很好"
cli-anything verify <subtask-id> --reject --comment "需要修改"

# 查看所有终端
cli-anything terminals

# 启动 Web 看板
cli-anything dashboard

# 查看操作日志
cli-anything log <task-id>

# 导出所有任务
cli-anything export tasks_backup.json

# 健康检查
cli-anything health
```

### Worker 终端常用命令

```bash
# 查看可领取任务
cli-anything available

# 领取任务
cli-anything claim <subtask-id>

# 释放任务（如果做不了）
cli-anything unclaim <subtask-id>

# 开始工作
cli-anything start <subtask-id>

# 查看自己的任务
cli-anything my

# 设置测试路径
cli-anything update <subtask-id> --test-path "tests/test_xxx.py"

# 提交任务
cli-anything submit <subtask-id>

# 查看任务详情
cli-anything show <subtask-id>
```

---

## 🎯 实际工作流示例：时间线

以下是一个完整的协同开发时间线：

```
时间线     | Master (Copilot CLI)          | Worker-1 (Qwen CLI)        | Worker-2 (Gemini CLI)
-----------|-------------------------------|----------------------------|---------------------------
14:00      | init --role master            | init --role worker         | init --role worker
14:01      | create "用户管理系统"          |                            |
14:02      | decompose 为 3 个子任务        |                            |
14:03      |                               | claim task-001-1 (注册)    | claim task-001-2 (登录)
14:05      | show task-001 (监控进度)       | 开发注册 API                | 开发登录 API
14:30      |                               | submit task-001-1          |
14:31      |                               |                            | submit task-001-2
14:32      | show task-001 (查看提交)       |                            |
14:33      | verify task-001-1 --approve   |                            |
14:34      | verify task-001-2 --approve   |                            |
14:35      | claim task-001-3 (自己完成)    |                            |
14:50      | submit task-001-3             |                            |
14:51      | verify task-001-3 --approve   |                            |
15:00      | ✅ 所有任务完成！              |                            |
```

---

## ⚙️ 高级配置

### 配置文件位置

```
~/.cli-anything/config.yaml
```

### 常用配置项

```yaml
database:
  path: "~/.cli-anything/tasks.db"     # 数据库路径

terminal:
  role: "master"                        # master 或 worker
  name: "Copilot-Master"               # 终端名称
  auto_detect: true                     # 自动检测终端信息

testing:
  runner: "pytest"                      # 测试框架
  timeout: 300                          # 测试超时时间（秒）
  auto_run_on_submit: true              # 提交时自动运行测试
  test_dir: "tests/"                    # 测试目录

dashboard:
  port: 8080                            # Web 看板端口
  auto_open: true                       # 自动打开浏览器

notification:
  enabled: true                         # 启用通知
  type: "toast"                         # 通知类型（Windows toast）
  on_submit: true                       # 提交时通知
  on_verify: true                       # 验收时通知
```

### 自定义命令别名

在配置文件中添加：

```yaml
aliases:
  todo: "available"
  wip: "my --status in_progress"
  done: "my --status done"
  review: "list --status submitted"
```

然后你可以使用：
```bash
cli-anything todo        # 等同于 cli-anything available
cli-anything wip         # 查看自己进行中的任务
cli-anything review      # 查看待验收的任务
```

---

## 🐛 常见问题

### Q1: 多个终端同时操作会冲突吗？

**A**: 不会。CLI-Anything 使用 SQLite WAL 模式，支持多进程并发读写，保证数据一致性。

### Q2: Worker 终端断开连接怎么办？

**A**: 系统会自动检测终端心跳，超时后自动释放该终端领取的任务：

```bash
# 手动检查健康状态
cli-anything health

# 自动清理超时终端
cli-anything health --cleanup
```

### Q3: 如何备份任务数据？

**A**: 使用导出功能：

```bash
# 导出所有任务和日志
cli-anything export backup_20260411.json

# 导入（恢复到新环境）
cli-anything import backup_20260411.json
```

### Q4: 测试失败了怎么办？

**A**: 提交时如果测试失败，任务状态会变为 `submitted` 但测试状态为 `FAILED`。Master 可以选择：

```bash
# 驳回让 Worker 修复
cli-anything verify <subtask-id> --reject --comment "测试失败，请修复"

# 或者手动重新运行测试
cli-anything test <subtask-id>
```

Worker 修复后重新提交：
```bash
# Worker 修复代码后再次提交
cli-anything submit <subtask-id>
```

### Q5: 可以在不同机器上使用吗？

**A**: 当前版本仅支持本机多终端协同（共享同一个 SQLite 数据库）。如需跨机器，可考虑：
1. 将数据库文件放在网络共享目录
2. 使用导出/导入功能手动同步
3. 未来版本可能支持网络模式

---

## 📝 最佳实践

### 1. 任务粒度

- ✅ **好**：拆解为独立可测试的小任务（1-2 小时可完成）
- ❌ **差**：子任务仍然太大（"实现整个后端"）

### 2. 测试覆盖

- ✅ **好**：每个子任务都包含完整的单元测试
- ✅ **好**：提交前本地运行测试确保通过
- ❌ **差**：只实现功能不写测试

### 3. 提交频率

- ✅ **好**：完成一个子任务立即提交
- ❌ **差**：所有任务做完一起提交

### 4. 验收标准

- ✅ **好**：Master 仔细检查代码和测试结果
- ✅ **好**：提供具体的验收意见
- ❌ **差**：不看代码直接全部通过

### 5. 终端命名

- ✅ **好**：使用清晰的命名（如 `Qwen-Worker-1`, `Gemini-Worker-2`）
- ❌ **差**：使用默认名称或不命名

---

## 🎓 进阶：使用 TUI 界面

如果你喜欢终端 UI，可以启动 TUI 界面：

```bash
cli-anything tui
```

TUI 界面包含：
- 📊 **统计面板**：显示总任务数、完成数、进行中数
- 📋 **任务表格**：所有任务的实时状态
- 📝 **日志面板**：操作历史流

**快捷键**：
- `r` - 刷新
- `q` - 退出
- 自动 5 秒刷新

---

## 📚 相关文档

- [项目 README](../README.md) - 项目概览和安装指南
- [多终端协同设计文档](./多终端协同.md) - 完整的系统设计和技术细节
- [配置示例](../config/config.example.yaml) - 完整配置选项

---

## 💡 总结

通过 CLI-Anything，你可以：

1. ✅ **使用 Copilot CLI 作为项目经理**：负责任务规划、拆解和验收
2. ✅ **使用 Qwen CLI 和 Gemini CLI 作为开发者**：并行实现不同功能
3. ✅ **实时监控进度**：通过 CLI/Web/TUI 随时查看任务状态
4. ✅ **自动化测试**：提交时自动运行测试，保证代码质量
5. ✅ **严格的质量控制**：Master 验收审核机制

这种模式特别适合：
- 🤖 **AI 辅助开发**：多个 AI Agent 协同工作
- 👨‍💻 **单人多终端**：一个人在不同终端窗口并行开发
- 📚 **学习和实验**：同时尝试不同实现方案

**开始你的多终端协同开发之旅吧！** 🚀
