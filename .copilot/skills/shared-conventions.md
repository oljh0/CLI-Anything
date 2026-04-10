# 项目共享约定

本文件定义 CLI-Anything 项目的通用规范，主终端和子终端均需遵守。

## 代码规范

### Python 代码风格
- 遵循 PEP 8
- 使用类型注解（Python 3.10+ 语法）
- 函数/方法文档字符串使用中文
- 模块级别的常量使用 UPPER_SNAKE_CASE
- 私有方法以单下划线开头

### 命名规范
- 文件名：snake_case（如 `task_manager.py`）
- 类名：PascalCase（如 `TaskManager`）
- 函数/方法名：snake_case（如 `create_task`）
- 常量：UPPER_SNAKE_CASE（如 `DEFAULT_PRIORITY`）

### 注释与文档
- 关键逻辑添加中文注释
- 公开 API 必须有文档字符串
- 复杂算法需注释说明思路

## 任务规范

### 任务标题
- 使用动词开头：「实现 xxx」「修复 xxx」「优化 xxx」「添加 xxx」
- 简洁明确，不超过 30 字

### 任务描述模板
```
## 目标
简要描述要实现的功能

## 实现要求
- 具体要求 1
- 具体要求 2

## 涉及文件
- src/cli_anything/xxx.py

## 测试要求
- 测试场景 1
- 测试场景 2

## 验收标准
- 条件 1
- 条件 2
```

### 优先级使用规范
| 优先级 | 含义 | 使用场景 |
|--------|------|----------|
| 1 | 紧急 | 阻塞其他任务的关键路径 |
| 2 | 高 | 核心功能，需优先完成 |
| 3 | 中（默认） | 正常功能开发 |
| 4 | 低 | 改进优化，不影响主流程 |
| 5 | 最低 | Nice-to-have，有空再做 |

## 测试规范

### 测试文件位置
- 所有测试放在 `tests/` 目录下
- 命名格式：`test_<对应模块名>.py`

### 测试运行
```bash
# 运行全部测试
pytest tests/ -v

# 运行特定测试文件
pytest tests/test_task_manager.py -v

# 运行特定测试方法
pytest tests/test_task_manager.py::TestCreateTask::test_normal -v
```

## Git 规范

### Commit 消息格式
```
<type>: <简述>

<详细说明（可选）>

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
```

### Type 枚举
- `feat`: 新功能
- `fix`: 修复缺陷
- `test`: 测试相关
- `docs`: 文档更新
- `refactor`: 重构
- `chore`: 构建/工具变更
