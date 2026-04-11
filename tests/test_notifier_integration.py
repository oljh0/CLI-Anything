"""Notifier 集成测试：验证 TaskManager 与 Notifier 的交互"""

import pytest
from unittest.mock import MagicMock, patch, call

from cli_anything.core.models import TaskStatus, TaskType, ReviewStatus
from cli_anything.storage.database import Database
from cli_anything.core.task_manager import TaskManager, TaskManagerError
from cli_anything.notification.notifier import Notifier


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    database = Database(db_path)
    database.connect()
    yield database
    database.close()


@pytest.fixture
def mock_notifier():
    """创建 mock Notifier"""
    notifier = MagicMock(spec=Notifier)
    notifier.enabled = True
    return notifier


@pytest.fixture
def tm_with_notifier(db, mock_notifier):
    """创建带 Notifier 的 TaskManager"""
    return TaskManager(db, terminal_id="test-term", notifier=mock_notifier)


@pytest.fixture
def tm_without_notifier(db):
    """创建不带 Notifier 的 TaskManager"""
    return TaskManager(db, terminal_id="test-term")


class TestNotifierIntegration:
    """Notifier 与 TaskManager 的集成测试"""

    def test_status_change_triggers_notification(self, tm_with_notifier, mock_notifier):
        """change_status 应触发 on_status_change 通知"""
        task = tm_with_notifier.create_task("测试任务")
        tm_with_notifier.claim_task(task.id)
        # claim_task 直接设置状态不经过 change_status，所以用 start_task 触发
        tm_with_notifier.start_task(task.id)
        mock_notifier.on_status_change.assert_called()
        args = mock_notifier.on_status_change.call_args
        assert args[0][0] == task.id  # task_id
        assert args[0][2] == "in_progress"  # new_status

    def test_submit_triggers_notification(self, tm_with_notifier, mock_notifier):
        """提交任务应触发 on_submit 通知"""
        task = tm_with_notifier.create_task("测试任务")
        tm_with_notifier.claim_task(task.id)
        tm_with_notifier.change_status(task.id, TaskStatus.IN_PROGRESS)
        mock_notifier.reset_mock()

        tm_with_notifier.submit_task(task.id)
        mock_notifier.on_submit.assert_called_once()
        args = mock_notifier.on_submit.call_args
        assert args[0][0] == task.id
        assert args[0][1] == "测试任务"

    def test_verify_approved_triggers_notification(self, tm_with_notifier, mock_notifier):
        """验收通过应触发 on_verify 通知"""
        task = tm_with_notifier.create_task("测试任务")
        tm_with_notifier.claim_task(task.id)
        tm_with_notifier.change_status(task.id, TaskStatus.IN_PROGRESS)
        tm_with_notifier.submit_task(task.id)
        mock_notifier.reset_mock()

        tm_with_notifier.verify_task(task.id, approved=True, comment="LGTM")
        mock_notifier.on_verify.assert_called_once()
        args = mock_notifier.on_verify.call_args
        assert args[0][0] == task.id
        assert args[0][2] is True  # approved
        assert args[0][3] == "LGTM"  # comment

    def test_verify_rejected_triggers_notification(self, tm_with_notifier, mock_notifier):
        """验收驳回应触发 on_verify 通知"""
        task = tm_with_notifier.create_task("测试任务")
        tm_with_notifier.claim_task(task.id)
        tm_with_notifier.change_status(task.id, TaskStatus.IN_PROGRESS)
        tm_with_notifier.submit_task(task.id)
        mock_notifier.reset_mock()

        tm_with_notifier.verify_task(task.id, approved=False, comment="需要修改")
        mock_notifier.on_verify.assert_called_once()
        args = mock_notifier.on_verify.call_args
        assert args[0][2] is False  # rejected

    def test_no_notifier_no_error(self, tm_without_notifier):
        """没有 Notifier 时不应报错"""
        task = tm_without_notifier.create_task("测试任务")
        tm_without_notifier.claim_task(task.id)
        tm_without_notifier.change_status(task.id, TaskStatus.IN_PROGRESS)
        tm_without_notifier.submit_task(task.id)
        tm_without_notifier.verify_task(task.id, approved=True)
        # 不抛异常即为通过

    def test_notifier_default_is_none(self, db):
        """TaskManager 默认 notifier 为 None"""
        tm = TaskManager(db, terminal_id="t")
        assert tm._notifier is None


class TestNotifierUnit:
    """Notifier 类本身的单元测试"""

    def test_disabled_by_default(self):
        """默认配置下 Notifier 应禁用"""
        config = MagicMock()
        config.get.side_effect = lambda key, default=None: {
            "notification.enabled": False,
        }.get(key, default)

        notifier = Notifier(config)
        assert notifier.enabled is False

    def test_enabled_when_configured(self):
        """配置启用时 Notifier 应启用"""
        config = MagicMock()
        config.get.side_effect = lambda key, default=None: {
            "notification.enabled": True,
        }.get(key, default)

        notifier = Notifier(config)
        assert notifier.enabled is True

    def test_notify_skips_when_disabled(self):
        """禁用时 notify 不应调用平台方法"""
        config = MagicMock()
        config.get.side_effect = lambda key, default=None: {
            "notification.enabled": False,
        }.get(key, default)

        notifier = Notifier(config)
        with patch.object(Notifier, '_notify_windows') as mock_win:
            with patch.object(Notifier, '_notify_linux') as mock_linux:
                notifier.notify("test", "msg")
                mock_win.assert_not_called()
                mock_linux.assert_not_called()

    def test_on_status_change_respects_config(self):
        """on_status_change 应检查子开关"""
        config = MagicMock()
        config.get.side_effect = lambda key, default=None: {
            "notification.enabled": True,
            "notification.on_status_change": False,
            "notification.type": "toast",
        }.get(key, default)

        notifier = Notifier(config)
        with patch.object(notifier, 'notify') as mock_notify:
            notifier.on_status_change("T-1", "pending", "claimed", "测试")
            mock_notify.assert_not_called()

    def test_on_verify_urgency(self):
        """on_verify 驳回时应使用 critical 级别"""
        config = MagicMock()
        config.get.side_effect = lambda key, default=None: {
            "notification.enabled": True,
            "notification.on_verify": True,
            "notification.type": "toast",
        }.get(key, default)

        notifier = Notifier(config)
        with patch.object(notifier, 'notify') as mock_notify:
            notifier.on_verify("T-1", "测试", approved=False, comment="不行")
            mock_notify.assert_called_once()
            _, kwargs = mock_notify.call_args
            assert kwargs.get('urgency') == 'critical'
