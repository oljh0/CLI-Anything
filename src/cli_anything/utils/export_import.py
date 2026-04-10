"""数据导入导出：JSON 格式"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Optional

from cli_anything.core.models import Task, TaskLog
from cli_anything.core.task_manager import TaskManager
from cli_anything.storage.database import Database


def export_tasks(
    tm: TaskManager,
    output_path: str,
    parent_id: Optional[str] = None,
    include_logs: bool = True,
) -> dict:
    """导出任务数据为 JSON

    Args:
        tm: TaskManager 实例
        output_path: 输出文件路径
        parent_id: 仅导出指定父任务及其子任务
        include_logs: 是否包含操作日志

    Returns:
        导出摘要 {tasks_count, logs_count, path}
    """
    if parent_id:
        parent = tm.get_task(parent_id)
        tasks = [parent] if parent else []
        tasks.extend(tm.list_subtasks(parent_id))
    else:
        tasks = tm.list_tasks(limit=9999)

    export_data = {
        "version": "1.0",
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "tasks": [t.to_dict() for t in tasks],
        "logs": [],
    }

    if include_logs:
        all_logs = []
        for t in tasks:
            logs = tm.get_logs(t.id, limit=999)
            all_logs.extend([l.to_dict() for l in logs])
        export_data["logs"] = all_logs

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(export_data, f, ensure_ascii=False, indent=2)

    return {
        "tasks_count": len(export_data["tasks"]),
        "logs_count": len(export_data["logs"]),
        "path": output_path,
    }


def import_tasks(
    tm: TaskManager,
    input_path: str,
    overwrite: bool = False,
) -> dict:
    """从 JSON 导入任务数据

    Args:
        tm: TaskManager 实例
        input_path: 输入文件路径
        overwrite: 已存在的任务是否覆盖

    Returns:
        导入摘要 {imported, skipped, errors}
    """
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    imported = 0
    skipped = 0
    errors = []

    for td in data.get("tasks", []):
        try:
            task_id = td.get("id", "")
            existing = tm.get_task(task_id)

            if existing and not overwrite:
                skipped += 1
                continue

            task = Task.from_row(td)
            if existing:
                tm.db.update_task(task)
            else:
                tm.db.insert_task(task)
            imported += 1
        except Exception as e:
            errors.append(f"任务 {td.get('id', '?')}: {e}")

    # 导入日志
    logs_imported = 0
    for ld in data.get("logs", []):
        try:
            log = TaskLog.from_row(ld)
            log.id = None  # 重新生成 ID
            tm.db.insert_log(log)
            logs_imported += 1
        except Exception:
            pass

    return {
        "imported": imported,
        "skipped": skipped,
        "logs_imported": logs_imported,
        "errors": errors,
    }
