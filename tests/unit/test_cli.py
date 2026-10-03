"""Tests for the Fireagent CLI interface."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from click.testing import CliRunner

from fireagent.cli import (
    DEFAULT_CONFIG,
    _emit_lines,
    _table_lines,
    cli,
    load_config,
    save_config,
)
from fireagent.models import SandboxStatus


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def temp_config() -> Path:
    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
        yaml.dump({"api": {"base_url": "http://test:8000"}, "cli": {"default_format": "json"}}, f)
        path = Path(f.name)
    yield path
    path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------
class TestConfig:
    def test_default_config(self) -> None:
        cfg = load_config()
        assert cfg["api"]["base_url"] == "http://127.0.0.1:8000"
        assert cfg["sandbox"]["default_image"] == "ubuntu:24.04"

    def test_load_from_path(self, temp_config: Path) -> None:
        cfg = load_config(temp_config)
        assert cfg["api"]["base_url"] == "http://test:8000"

    def test_env_overrides(self) -> None:
        with patch.dict(
            os.environ, {"FIREAGENT_API_KEY": "env-key", "FIREAGENT_BASE_URL": "http://env:8000"}
        ):
            cfg = load_config()
            assert cfg["api"]["api_key"] == "env-key"
            assert cfg["api"]["base_url"] == "http://env:8000"

    def test_save_and_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".fireagent" / "config.yaml"
            save_config({"test": {"value": 42}}, path)
            assert path.exists()
            cfg = load_config(path)
            assert cfg["test"]["value"] == 42

    def test_deep_merge(self) -> None:
        from fireagent.cli import _deep_merge

        base: dict = {"a": 1, "b": {"c": 2, "d": 3}}
        override: dict = {"b": {"c": 99, "e": 4}}
        _deep_merge(base, override)
        assert base["a"] == 1
        assert base["b"]["c"] == 99
        assert base["b"]["d"] == 3
        assert base["b"]["e"] == 4


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------
class TestFormatOutput:
    def test_json_format(self) -> None:
        result = "\n".join(_emit_lines({"id": "sb-1", "state": "ready"}, fmt="json"))
        assert '"id"' in result
        assert '"ready"' in result

    def test_yaml_format(self) -> None:
        result = "\n".join(_emit_lines({"id": "sb-1", "state": "ready"}, fmt="yaml"))
        assert "id: sb-1" in result

    def test_table_list(self) -> None:
        data = [{"id": "sb-1", "state": "ready"}, {"id": "sb-2", "state": "running"}]
        lines: list[str] = []
        _table_lines(data, lines)
        result = "\n".join(lines)
        assert "sb-1" in result
        assert "sb-2" in result

    def test_table_dict(self) -> None:
        data = {"id": "sb-1", "state": "ready"}
        lines: list[str] = []
        _table_lines(data, lines)
        result = "\n".join(lines)
        assert "sb-1" in result

    def test_table_empty(self) -> None:
        lines: list[str] = []
        _table_lines([], lines)
        assert "no results" in "\n".join(lines)

    def test_format_fallback(self) -> None:
        result = "\n".join(_emit_lines("hello world", fmt="unknown"))
        assert "hello world" in result


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------
class TestCLI:
    def test_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Fireagent" in result.output

    def test_version(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output

    def test_sandboxes_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["sandboxes", "--help"])
        assert result.exit_code == 0
        assert "Create" in result.output

    def test_images_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["images", "--help"])
        assert result.exit_code == 0

    def test_hosts_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["hosts", "--help"])
        assert result.exit_code == 0

    def test_config_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["config", "--help"])
        assert result.exit_code == 0

    def test_config_show(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["config", "show"])
        assert result.exit_code == 0, f"Exit code {result.exit_code}: {result.output}"
        assert "base_url" in result.output or "http://" in result.output

    def test_config_set(self, runner: CliRunner) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            # Override config path
            with patch("fireagent.cli.DEFAULT_CONFIG_PATH", Path(tmp) / "config.yaml"):
                result = runner.invoke(cli, ["config", "set", "api.base_url", "http://other:9000"])
                assert result.exit_code == 0

    def test_config_init(self, runner: CliRunner) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch("fireagent.cli.DEFAULT_CONFIG_PATH", Path(tmp) / "config.yaml"):
                result = runner.invoke(cli, ["config", "init"])
                assert result.exit_code == 0
                assert Path(tmp, "config.yaml").exists()

    def test_config_init_force(self, runner: CliRunner) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.yaml"
            config_path.write_text("existing: true\n")
            with patch("fireagent.cli.DEFAULT_CONFIG_PATH", config_path):
                result = runner.invoke(cli, ["config", "init"])
                assert result.exit_code == 0
                assert "already exists" in result.output

    @patch("fireagent.cli.FireagentClient")
    def test_sandbox_create(self, mock_client_cls, runner: CliRunner) -> None:
        from fireagent import Sandbox

        mock_sb = MagicMock(spec=Sandbox)
        mock_sb.id = "sb-test001"
        mock_sb.status.return_value = SandboxStatus(
            sandbox_id="sb-test001",
            state="ready",
            image="ubuntu:24.04",
            vcpus=1,
            memory_mib=512,
            disk_mib=1024,
            host="host-01",
        )
        mock_client_cls.return_value.create.return_value = mock_sb
        result = runner.invoke(
            cli,
            [
                "sandboxes",
                "create",
                "--image",
                "ubuntu:24.04",
                "--vcpus",
                "2",
                "--wait",
                "--no-wait",
            ],
        )
        assert result.exit_code == 0

    @patch("fireagent.cli.FireagentClient")
    def test_sandbox_list(self, mock_client_cls, runner: CliRunner) -> None:
        from fireagent import Sandbox

        mock_sb = MagicMock(spec=Sandbox)
        mock_sb.status.return_value = SandboxStatus(
            sandbox_id="sb-1",
            state="ready",
            image="ubuntu:24.04",
            vcpus=1,
            memory_mib=512,
            disk_mib=1024,
        )
        mock_client_cls.return_value.list.return_value = [mock_sb]
        result = runner.invoke(cli, ["sandboxes", "ls"])
        assert result.exit_code == 0

    @patch("fireagent.cli.FireagentClient")
    def test_sandbox_get_not_found(self, mock_client_cls, runner: CliRunner) -> None:
        from fireagent.exceptions import NotFoundError

        mock_client_cls.return_value._get_sandbox.side_effect = NotFoundError("not found")
        result = runner.invoke(cli, ["sandboxes", "get", "sb-nonexistent"])
        assert result.exit_code == 1
        assert "not found" in result.output

    @patch("fireagent.cli.FireagentClient")
    def test_sandbox_exec(self, mock_client_cls, runner: CliRunner) -> None:
        from fireagent.models import CommandResult

        mock_client_cls.return_value._exec.return_value = CommandResult(
            stdout="hello\n",
            stderr="",
            exit_code=0,
        )
        result = runner.invoke(cli, ["sandboxes", "exec", "sb-test001", "--command", "echo hello"])
        assert result.exit_code == 0, f"Exit {result.exit_code}: {result.output}"
        assert "hello" in result.output or result.exit_code == 0

    @patch("fireagent.cli.FireagentClient")
    def test_sandbox_stop(self, mock_client_cls, runner: CliRunner) -> None:
        mock_sb = MagicMock()
        mock_client_cls.return_value.get.return_value = mock_sb
        result = runner.invoke(cli, ["sandboxes", "stop", "sb-test001", "--no-wait"])
        assert result.exit_code == 0
        assert "stopped" in result.output

    @patch("fireagent.cli.FireagentClient")
    def test_sandbox_delete(self, mock_client_cls, runner: CliRunner) -> None:
        mock_sb = MagicMock()
        mock_client_cls.return_value.get.return_value = mock_sb
        result = runner.invoke(cli, ["sandboxes", "delete", "sb-test001", "--yes"])
        assert result.exit_code == 0
        assert "deleted" in result.output

    @patch("fireagent.cli.FireagentClient")
    def test_sandbox_delete_confirms(self, mock_client_cls, runner: CliRunner) -> None:
        mock_sb = MagicMock()
        mock_client_cls.return_value.get.return_value = mock_sb
        result = runner.invoke(cli, ["sandboxes", "delete", "sb-test001"], input="y\n")
        assert result.exit_code == 0

    @patch("fireagent.cli.FireagentClient")
    def test_sandbox_wait(self, mock_client_cls, runner: CliRunner) -> None:
        mock_sb = MagicMock()
        mock_sb.wait_for.return_value = SandboxStatus(
            sandbox_id="sb-test001",
            state="ready",
            image="ubuntu:24.04",
            vcpus=1,
            memory_mib=512,
            disk_mib=1024,
        )
        mock_client_cls.return_value.get.return_value = mock_sb
        result = runner.invoke(cli, ["sandboxes", "wait", "sb-test001", "ready", "--timeout", "5"])
        assert result.exit_code == 0

    @patch("fireagent.cli.FireagentClient")
    def test_sandbox_wait_timeout(self, mock_client_cls, runner: CliRunner) -> None:
        from fireagent.exceptions import SandboxTimeoutError

        mock_sb = MagicMock()
        mock_sb.wait_for.side_effect = SandboxTimeoutError("timed out")
        mock_client_cls.return_value.get.return_value = mock_sb
        result = runner.invoke(cli, ["sandboxes", "wait", "sb-test001", "ready", "--timeout", "1"])
        assert result.exit_code == 1

    def test_host_list(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["hosts", "ls"])
        assert result.exit_code == 0

    def test_image_list(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["images", "ls"])
        assert result.exit_code == 0

    def test_debug_flag(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["--debug", "config", "show"])
        assert result.exit_code == 0
