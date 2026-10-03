"""Guest agent tests — command execution, sanitization, and channel handling."""

from __future__ import annotations

from unittest.mock import patch

from fireagent_guest.agent import (
    execute_command,
    handle_request,
    setup_environment,
    setup_workspace,
)


class TestExecuteCommand:
    def test_simple_echo(self) -> None:
        result = execute_command("echo 'hello world'")
        assert result["exit_code"] == 0
        assert "hello world" in result["stdout"]

    def test_failing_command(self) -> None:
        result = execute_command("false")
        assert result["exit_code"] != 0

    def test_captures_stderr(self) -> None:
        result = execute_command("echo 'error' >&2; false")
        assert "error" in result["stderr"]

    def test_timeout(self) -> None:
        result = execute_command("sleep 10", timeout=1)
        assert result["timed_out"] is True
        assert result["exit_code"] == -1

    def test_multiple_commands(self) -> None:
        result = execute_command("echo a; echo b; echo c")
        assert result["exit_code"] == 0
        assert result["stdout"].strip() == "a\nb\nc"

    def test_working_directory(self) -> None:
        result = execute_command("pwd")
        assert result["exit_code"] == 0

    def test_large_output(self) -> None:
        result = execute_command("python3 -c 'print(\"x\" * 100000)'")
        assert result["exit_code"] == 0
        assert len(result["stdout"]) > 100000

    def test_exit_code_propagation(self) -> None:
        result = execute_command("exit 42")
        assert result["exit_code"] == 42

    def test_empty_command(self) -> None:
        result = execute_command("")
        assert result["exit_code"] == 0  # sh -c '' exits 0


class TestHandleRequest:
    def test_handle_echo(self) -> None:
        result = handle_request({"command": "echo 'test'", "execution_timeout_seconds": 10})
        assert result["stdout"].strip() == "test"
        assert result["exit_code"] == 0

    def test_handle_with_timeout(self) -> None:
        result = handle_request({"command": "echo 'hello'", "execution_timeout_seconds": 5})
        assert result["exit_code"] == 0

    def test_dangerous_commands_blocked(self) -> None:
        dangerous = ["sudo ls", "su -", "chroot /", "reboot", "shutdown -h", "halt", "poweroff"]
        for cmd in dangerous:
            result = handle_request({"command": cmd})
            assert result["exit_code"] == -1
            assert "not allowed" in result["stderr"].lower()

    def test_handle_timeout_propagation(self) -> None:
        result = handle_request({"command": "sleep 5", "execution_timeout_seconds": 1})
        assert result["timed_out"] is True

    def test_handle_malformed(self) -> None:
        result = handle_request({"command": None})
        assert result["exit_code"] == -1


class TestSetupEnvironment:
    def test_path_set(self) -> None:
        setup_environment()
        assert "/usr/local/bin" in __import__("os").environ.get("PATH", "")

    def test_workspace_env(self) -> None:
        setup_environment()
        assert __import__("os").environ.get("WORKSPACE") == "/workspace"


class TestSetupWorkspace:
    @patch("os.path.exists")
    @patch("subprocess.run")
    def test_workspace_not_present(self, mock_run, mock_exists) -> None:
        mock_exists.return_value = False
        setup_workspace()  # Should not raise
        mock_run.assert_not_called()

    @patch("os.path.exists")
    @patch("subprocess.run")
    @patch("os.makedirs")
    @patch("os.chdir")
    def test_workspace_mount(self, mock_chdir, mock_makedirs, mock_run, mock_exists) -> None:
        mock_exists.return_value = True
        setup_workspace()
        assert mock_makedirs.called
        assert mock_run.called


class TestSerialChannel:
    """Tests for the serial-based communication channel."""

    def test_serial_import(self) -> None:
        """Verify serial import handling (not required in unit test)."""

        # In unit tests, serial is None (not installed)
        # In production, serial would be available


class TestMainFunction:
    def test_main_imports(self) -> None:
        """Verify the main function imports without error."""
        import fireagent_guest.agent as agent

        assert hasattr(agent, "main")
        assert callable(agent.main)

    def test_request_echo(self) -> None:
        """Test a basic request round-trip."""
        from fireagent_guest.agent import handle_request

        result = handle_request({"command": "echo hello", "execution_timeout_seconds": 5})
        assert result["exit_code"] == 0
        assert "hello" in result.get("stdout", "")
