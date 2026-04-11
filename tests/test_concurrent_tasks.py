"""并发任务创建测试：验证 SQL 锁问题已修复"""

import threading
import tempfile
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

from cli_anything.storage.database import Database
from cli_anything.core.task_manager import TaskManager
from cli_anything.core.models import TaskType


class TestConcurrentTaskCreation:
    """测试并发创建任务，验证不会出现 SQL 锁错误"""

    @pytest.fixture
    def db(self):
        """创建临时数据库"""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        
        database = Database(db_path)
        database.connect()
        yield database
        database.close()
        if os.path.exists(db_path):
            os.unlink(db_path)

    @pytest.fixture
    def tm(self, db):
        """创建任务管理器"""
        return TaskManager(db, terminal_id="test-terminal")

    def test_concurrent_task_creation(self, tm):
        """并发创建多个任务，不应出现锁错误"""
        num_tasks = 20
        created_tasks = []
        errors = []

        def create_task(index):
            try:
                task = tm.create_task(
                    title=f"并发任务 {index}",
                    description=f"这是第 {index} 个并发创建的任务",
                    priority=(index % 5) + 1,
                    tags=[f"tag-{index}"],
                )
                created_tasks.append(task)
            except Exception as e:
                errors.append((index, str(e)))

        # 使用多线程并发创建任务
        threads = []
        for i in range(num_tasks):
            thread = threading.Thread(target=create_task, args=(i,))
            threads.append(thread)
            thread.start()

        # 等待所有线程完成
        for thread in threads:
            thread.join(timeout=30)

        # 验证结果
        assert len(errors) == 0, f"出现错误: {errors}"
        assert len(created_tasks) == num_tasks, f"只创建了 {len(created_tasks)} 个任务，预期 {num_tasks}"

        # 验证所有任务都已正确存储
        all_tasks = tm.list_tasks()
        assert len(all_tasks) == num_tasks

    def test_concurrent_with_thread_pool(self, tm):
        """使用线程池并发创建任务"""
        num_tasks = 30

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = []
            for i in range(num_tasks):
                future = executor.submit(
                    tm.create_task,
                    title=f"线程池任务 {i}",
                    description=f"任务描述 {i}",
                    priority=3,
                    tags=["pool", f"task-{i}"],
                )
                futures.append(future)

            # 收集结果
            created = []
            for future in as_completed(futures, timeout=60):
                try:
                    task = future.result()
                    created.append(task)
                except Exception as e:
                    pytest.fail(f"任务创建失败: {e}")

        assert len(created) == num_tasks, f"只创建了 {len(created)} 个任务"

    def test_concurrent_create_and_query(self, tm):
        """并发创建和查询任务"""
        # 先创建一些基础任务
        for i in range(5):
            tm.create_task(title=f"基础任务 {i}", priority=3)

        errors = []

        def create_and_query(index):
            try:
                # 创建新任务
                task = tm.create_task(title=f"并发任务 {index}")
                # 立即查询
                retrieved = tm.get_task(task.id)
                assert retrieved is not None
                assert retrieved.id == task.id
            except Exception as e:
                errors.append((index, str(e)))

        threads = []
        for i in range(10):
            thread = threading.Thread(target=create_and_query, args=(i,))
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join(timeout=30)

        assert len(errors) == 0, f"出现错误: {errors}"
