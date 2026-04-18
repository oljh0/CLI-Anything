"""P2 任务依赖图（DAG）单元测试"""

import pytest

from cli_anything.core.models import TaskStatus, TaskType
from cli_anything.storage.database import Database
from cli_anything.core.task_manager import TaskManager, TaskManagerError


@pytest.fixture
def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    database.connect()
    yield database
    database.close()


@pytest.fixture
def tm(db):
    return TaskManager(db, terminal_id="test-terminal")


@pytest.fixture
def parent_and_subtasks(tm):
    """创建一个主任务和三个子任务，返回 (parent, [a, b, c])"""
    parent = tm.create_task("主任务", task_type=TaskType.MASTER)
    subs = tm.decompose_task(parent.id, [
        {"title": "子任务A"},
        {"title": "子任务B"},
        {"title": "子任务C"},
    ])
    return parent, subs


class TestAddDependency:
    def test_normal_add(self, tm, parent_and_subtasks):
        _, (a, b, c) = parent_and_subtasks
        tm.add_dependency(b.id, a.id)
        deps = tm.get_dependencies(b.id)
        assert any(d["id"] == a.id for d in deps["depends_on"])

    def test_add_idempotent(self, tm, parent_and_subtasks):
        """重复添加同一依赖不报错（幂等）"""
        _, (a, b, c) = parent_and_subtasks
        tm.add_dependency(b.id, a.id)
        tm.add_dependency(b.id, a.id)  # 再次添加不抛出异常
        deps = tm.get_dependencies(b.id)
        assert len(deps["depends_on"]) == 1

    def test_self_dependency_forbidden(self, tm, parent_and_subtasks):
        _, (a, b, c) = parent_and_subtasks
        with pytest.raises(TaskManagerError, match="不能依赖自身"):
            tm.add_dependency(a.id, a.id)

    def test_direct_cycle_forbidden(self, tm, parent_and_subtasks):
        """A→B，再加 B→A 应该报错"""
        _, (a, b, c) = parent_and_subtasks
        tm.add_dependency(a.id, b.id)
        with pytest.raises(TaskManagerError, match="循环"):
            tm.add_dependency(b.id, a.id)

    def test_indirect_cycle_forbidden(self, tm, parent_and_subtasks):
        """A→B→C，再加 C→A 应该报错"""
        _, (a, b, c) = parent_and_subtasks
        tm.add_dependency(b.id, a.id)
        tm.add_dependency(c.id, b.id)
        with pytest.raises(TaskManagerError, match="循环"):
            tm.add_dependency(a.id, c.id)

    def test_task_not_found(self, tm):
        with pytest.raises(TaskManagerError):
            tm.add_dependency("nonexistent-a", "nonexistent-b")


class TestRemoveDependency:
    def test_normal_remove(self, tm, parent_and_subtasks):
        _, (a, b, c) = parent_and_subtasks
        tm.add_dependency(b.id, a.id)
        tm.remove_dependency(b.id, a.id)
        deps = tm.get_dependencies(b.id)
        assert deps["depends_on"] == []

    def test_remove_nonexistent_raises(self, tm, parent_and_subtasks):
        _, (a, b, c) = parent_and_subtasks
        with pytest.raises(TaskManagerError, match="不存在"):
            tm.remove_dependency(b.id, a.id)


class TestGetDependencies:
    def test_no_deps(self, tm, parent_and_subtasks):
        _, (a, b, c) = parent_and_subtasks
        info = tm.get_dependencies(a.id)
        assert info["depends_on"] == []
        assert info["blocking"] == []
        assert info["is_blocked"] is False

    def test_deps_with_incomplete(self, tm, parent_and_subtasks):
        """b 依赖 a（a 还是 pending），b 应被阻塞"""
        _, (a, b, c) = parent_and_subtasks
        tm.add_dependency(b.id, a.id)
        info = tm.get_dependencies(b.id)
        assert a.id in info["blocking"]
        assert info["is_blocked"] is True

    def test_deps_resolved_after_done(self, tm, parent_and_subtasks):
        """a 完成后，b 不再被阻塞"""
        _, (a, b, c) = parent_and_subtasks
        tm.add_dependency(b.id, a.id)

        # 推进 a 到 done
        tm.claim_task(a.id)
        tm.start_task(a.id)
        tm.submit_task(a.id)
        tm.verify_task(a.id, approved=True)

        info = tm.get_dependencies(b.id)
        assert info["blocking"] == []
        assert info["is_blocked"] is False

    def test_depended_by(self, tm, parent_and_subtasks):
        """检查 depended_by 字段（下游依赖）"""
        _, (a, b, c) = parent_and_subtasks
        tm.add_dependency(b.id, a.id)
        tm.add_dependency(c.id, a.id)
        info = tm.get_dependencies(a.id)
        downstream_ids = [d["id"] for d in info["depended_by"]]
        assert b.id in downstream_ids
        assert c.id in downstream_ids


class TestClaimWithDeps:
    def test_claim_blocked_raises(self, tm, parent_and_subtasks):
        """b 依赖 a（a 未完成），领取 b 应报错"""
        _, (a, b, c) = parent_and_subtasks
        tm.add_dependency(b.id, a.id)
        with pytest.raises(TaskManagerError, match="前置依赖"):
            tm.claim_task(b.id)

    def test_claim_after_dep_done(self, tm, parent_and_subtasks):
        """a 完成后，b 可以被正常领取"""
        _, (a, b, c) = parent_and_subtasks
        tm.add_dependency(b.id, a.id)

        # a: pending → done
        tm.claim_task(a.id)
        tm.start_task(a.id)
        tm.submit_task(a.id)
        tm.verify_task(a.id, approved=True)

        # b 现在可以领取
        claimed_b = tm.claim_task(b.id)
        assert claimed_b.status == TaskStatus.CLAIMED

    def test_claim_no_deps_unaffected(self, tm, parent_and_subtasks):
        """没有依赖的任务不受影响"""
        _, (a, b, c) = parent_and_subtasks
        # a 没有依赖，可以直接领取
        claimed = tm.claim_task(a.id)
        assert claimed.status == TaskStatus.CLAIMED

    def test_multiple_deps_all_must_complete(self, tm, parent_and_subtasks):
        """c 同时依赖 a 和 b，两者都完成才能领取"""
        _, (a, b, c) = parent_and_subtasks
        tm.add_dependency(c.id, a.id)
        tm.add_dependency(c.id, b.id)

        # 完成 a
        tm.claim_task(a.id)
        tm.start_task(a.id)
        tm.submit_task(a.id)
        tm.verify_task(a.id, approved=True)

        # b 还没完成，c 仍然阻塞
        with pytest.raises(TaskManagerError, match="前置依赖"):
            tm.claim_task(c.id)

        # 完成 b
        tm.claim_task(b.id)
        tm.start_task(b.id)
        tm.submit_task(b.id)
        tm.verify_task(b.id, approved=True)

        # 现在可以领取 c
        claimed_c = tm.claim_task(c.id)
        assert claimed_c.status == TaskStatus.CLAIMED


class TestDatabaseLayer:
    def test_add_and_list(self, db):
        """直接测试数据库层"""
        # 先插入任务记录（FK 约束需要任务存在）
        from cli_anything.core.models import Task, TaskStatus, TaskType
        import datetime
        now = datetime.datetime.now().isoformat()
        for i in range(3):
            t = Task(
                id=f"t{i}",
                title=f"任务{i}",
                status=TaskStatus.PENDING,
                task_type=TaskType.SUBTASK,
                created_at=now,
                updated_at=now,
            )
            db.insert_task(t)

        db.add_dependency("t1", "t0")
        db.add_dependency("t2", "t0")

        assert "t0" in db.list_dependencies("t1")
        assert "t1" in db.list_dependents("t0")
        assert "t2" in db.list_dependents("t0")

    def test_remove_dep(self, db):
        from cli_anything.core.models import Task, TaskStatus, TaskType
        import datetime
        now = datetime.datetime.now().isoformat()
        for i in range(2):
            t = Task(id=f"u{i}", title=f"任务{i}", status=TaskStatus.PENDING,
                     task_type=TaskType.SUBTASK, created_at=now, updated_at=now)
            db.insert_task(t)
        db.add_dependency("u1", "u0")
        assert db.remove_dependency("u1", "u0") is True
        assert db.list_dependencies("u1") == []

    def test_remove_nonexistent(self, db):
        from cli_anything.core.models import Task, TaskStatus, TaskType
        import datetime
        now = datetime.datetime.now().isoformat()
        t = Task(id="v0", title="任务", status=TaskStatus.PENDING,
                 task_type=TaskType.SUBTASK, created_at=now, updated_at=now)
        db.insert_task(t)
        assert db.remove_dependency("v0", "nonexistent") is False
