"""通知系统：任务状态变更通知"""

from __future__ import annotations

import os
import sys
import subprocess
from typing import Optional

from cli_anything.utils.config import Config


class Notifier:
    """跨平台通知发送器"""

    def __init__(self, config: Config):
        self.config = config
        self._enabled = config.get("notification.enabled", False)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def notify(self, title: str, message: str, urgency: str = "normal"):
        """发送通知

        Args:
            title: 通知标题
            message: 通知内容
            urgency: 紧急程度 (low/normal/critical)
        """
        if not self._enabled:
            return

        ntype = self.config.get("notification.type", "toast")
        if sys.platform == "win32":
            self._notify_windows(title, message)
        elif sys.platform == "darwin":
            self._notify_macos(title, message)
        else:
            self._notify_linux(title, message, urgency)

    def on_status_change(self, task_id: str, old_status: str, new_status: str, title: str):
        """任务状态变更通知"""
        if not self.config.get("notification.on_status_change", True):
            return
        self.notify(
            f"任务状态变更",
            f"[{task_id}] {title}\n{old_status} → {new_status}",
        )

    def on_submit(self, task_id: str, title: str, terminal_id: str):
        """任务提交通知"""
        if not self.config.get("notification.on_submit", True):
            return
        self.notify(
            "📤 任务已提交",
            f"[{task_id}] {title}\n来自终端: {terminal_id}",
        )

    def on_verify(self, task_id: str, title: str, approved: bool, comment: str):
        """验收结果通知"""
        if not self.config.get("notification.on_verify", True):
            return
        status = "✅ 通过" if approved else "❌ 驳回"
        self.notify(
            f"验收结果: {status}",
            f"[{task_id}] {title}\n{comment}" if comment else f"[{task_id}] {title}",
            urgency="critical" if not approved else "normal",
        )

    # ── 平台实现 ────────────────────────────────────────────

    @staticmethod
    def _notify_windows(title: str, message: str):
        """Windows Toast 通知"""
        try:
            ps_script = f'''
            [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null
            [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, ContentType=WindowsRuntime] | Out-Null
            $template = @"
            <toast>
                <visual><binding template="ToastGeneric">
                    <text>{title}</text>
                    <text>{message}</text>
                </binding></visual>
            </toast>
"@
            $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
            $xml.LoadXml($template)
            $toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
            [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("CLI-Anything").Show($toast)
            '''
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                capture_output=True, timeout=5,
            )
        except Exception:
            # 回退到简单方案
            try:
                subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     f'[System.Windows.Forms.MessageBox]::Show("{message}", "{title}")'],
                    capture_output=True, timeout=5,
                )
            except Exception:
                pass

    @staticmethod
    def _notify_macos(title: str, message: str):
        """macOS 通知"""
        try:
            subprocess.run(
                ["osascript", "-e",
                 f'display notification "{message}" with title "{title}"'],
                capture_output=True, timeout=5,
            )
        except Exception:
            pass

    @staticmethod
    def _notify_linux(title: str, message: str, urgency: str = "normal"):
        """Linux 通知"""
        try:
            subprocess.run(
                ["notify-send", f"--urgency={urgency}", title, message],
                capture_output=True, timeout=5,
            )
        except Exception:
            pass
