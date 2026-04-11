"""命令别名解析和 MCP SSE 配置测试"""

import sys
import pytest
from unittest.mock import MagicMock, patch

from cli_anything.utils.config import Config


class TestAliasResolution:
    """_resolve_aliases() 别名解析测试"""

    def test_simple_alias(self):
        """简单别名替换"""
        from cli_anything.cli import _resolve_aliases

        mock_config = MagicMock(spec=Config)
        mock_config.get.return_value = {"todo": "available"}

        with patch("cli_anything.cli.Config", return_value=mock_config):
            mock_config.load = MagicMock()
            original_argv = ["cli-anything", "todo"]
            with patch.object(sys, "argv", list(original_argv)):
                _resolve_aliases()
                assert sys.argv == ["cli-anything", "available"]

    def test_multi_word_alias(self):
        """带参数的别名展开"""
        from cli_anything.cli import _resolve_aliases

        mock_config = MagicMock(spec=Config)
        mock_config.get.return_value = {"wip": "my --status in_progress"}

        with patch("cli_anything.cli.Config", return_value=mock_config):
            mock_config.load = MagicMock()
            with patch.object(sys, "argv", ["cli-anything", "wip"]):
                _resolve_aliases()
                assert sys.argv == ["cli-anything", "my", "--status", "in_progress"]

    def test_no_alias_match(self):
        """无匹配别名时 argv 不变"""
        from cli_anything.cli import _resolve_aliases

        mock_config = MagicMock(spec=Config)
        mock_config.get.return_value = {"todo": "available"}

        with patch("cli_anything.cli.Config", return_value=mock_config):
            mock_config.load = MagicMock()
            original = ["cli-anything", "list"]
            with patch.object(sys, "argv", list(original)):
                _resolve_aliases()
                assert sys.argv == original

    def test_empty_aliases(self):
        """空别名配置时不影响 argv"""
        from cli_anything.cli import _resolve_aliases

        mock_config = MagicMock(spec=Config)
        mock_config.get.return_value = {}

        with patch("cli_anything.cli.Config", return_value=mock_config):
            mock_config.load = MagicMock()
            original = ["cli-anything", "list"]
            with patch.object(sys, "argv", list(original)):
                _resolve_aliases()
                assert sys.argv == original

    def test_no_args_no_error(self):
        """无参数时不报错"""
        from cli_anything.cli import _resolve_aliases

        mock_config = MagicMock(spec=Config)
        mock_config.get.return_value = {"todo": "available"}

        with patch("cli_anything.cli.Config", return_value=mock_config):
            mock_config.load = MagicMock()
            with patch.object(sys, "argv", ["cli-anything"]):
                _resolve_aliases()
                assert sys.argv == ["cli-anything"]

    def test_config_error_graceful(self):
        """配置加载失败时静默处理"""
        from cli_anything.cli import _resolve_aliases

        with patch("cli_anything.cli.Config", side_effect=Exception("boom")):
            original = ["cli-anything", "todo"]
            with patch.object(sys, "argv", list(original)):
                _resolve_aliases()  # 不应抛异常
                assert sys.argv == original


class TestMCPTransportConfig:
    """MCP SSE 传输配置测试"""

    def test_default_transport_is_stdio(self):
        """默认传输应为 stdio"""
        config = Config()
        assert config.get("mcp_server.transport") == "stdio"

    def test_sse_config_defaults(self):
        """SSE 配置默认值"""
        config = Config()
        assert config.get("mcp_server.sse_host") == "127.0.0.1"
        assert config.get("mcp_server.sse_port") == 8000

    def test_serve_stdio_mode(self):
        """stdio 模式下 mcp.run 应传 transport='stdio'"""
        from cli_anything.mcp_server import server as mcp_mod

        mock_config = MagicMock()
        mock_config.get.side_effect = lambda key, default=None: {
            "mcp_server.transport": "stdio",
        }.get(key, default)

        with patch.object(mcp_mod, "_config", mock_config), \
             patch.object(mcp_mod, "_db", MagicMock()), \
             patch.object(mcp_mod, "_tm", MagicMock()), \
             patch.object(mcp_mod.mcp, "run") as mock_run:
            mcp_mod.serve()
            mock_run.assert_called_once_with(transport="stdio")

    def test_serve_sse_mode(self):
        """SSE 模式下 mcp.run 应传 transport='sse' + host + port"""
        from cli_anything.mcp_server import server as mcp_mod

        mock_config = MagicMock()
        mock_config.get.side_effect = lambda key, default=None: {
            "mcp_server.transport": "sse",
            "mcp_server.sse_host": "0.0.0.0",
            "mcp_server.sse_port": 9000,
        }.get(key, default)

        with patch.object(mcp_mod, "_config", mock_config), \
             patch.object(mcp_mod, "_db", MagicMock()), \
             patch.object(mcp_mod, "_tm", MagicMock()), \
             patch.object(mcp_mod.mcp, "run") as mock_run:
            mcp_mod.serve()
            mock_run.assert_called_once_with(transport="sse", host="0.0.0.0", port=9000)


class TestDashboardAuthConfig:
    """Dashboard 认证配置默认值测试"""

    def test_auth_disabled_by_default(self):
        """认证默认关闭"""
        config = Config()
        assert config.get("dashboard.auth.enabled") is False

    def test_auth_default_username(self):
        """默认用户名为 admin"""
        config = Config()
        assert config.get("dashboard.auth.username") == "admin"

    def test_auth_default_password_empty(self):
        """默认密码为空"""
        config = Config()
        assert config.get("dashboard.auth.password") == ""
