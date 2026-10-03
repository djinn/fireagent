"""Host agent tests — MicroVMManager and HostAgent classes."""

from __future__ import annotations

import os
import signal
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from fireagent_agent.agent import HostAgent, MicroVMManager, DEFAULT_CONFIG


# ---------------------------------------------------------------------------
# MicroVMManager tests
# ---------------------------------------------------------------------------
class TestMicroVMManager:
    @pytest.fixture
    def manager(self) -> MicroVMManager:
        config = DEFAULT_CONFIG.copy()
        config["storage"]["workspace_dir"] = "/tmp/fa-test-workspace"
        config["storage"]["image_dir"] = "/tmp/fa-test-images"
        Path("/tmp/fa-test-workspace").mkdir(parents=True, exist_ok=True)
        Path("/tmp/fa-test-images/ubuntu:24.04").mkdir(parents=True, exist_ok=True)
        return MicroVMManager(config)

    def test_init(self, manager: MicroVMManager) -> None:
        assert manager.active_sandbox_count == 0
        assert isinstance(manager.workspace_dir, Path)

    @patch("subprocess.Popen")
    @patch("subprocess.run")
    def test_create_sandbox(self, mock_run, mock_popen, manager: MicroVMManager) -> None:
        # Create dummy image files
        image_dir = Path("/tmp/fa-test-images/ubuntu:24.04")
        (image_dir / "kernel").write_text("fake kernel")
        (image_dir / "rootfs.ext4").write_text("fake rootfs")

        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_popen.return_value = mock_proc

        result = manager.create_sandbox(
            "sb-test001", "ubuntu:24.04", vcpus=1, memory_mib=512, disk_mib=1024,
        )
        assert result is True
        assert manager.active_sandbox_count == 1

    def test_create_sandbox_no_image(self, manager: MicroVMManager) -> None:
        result = manager.create_sandbox(
            "sb-test002", "nonexistent:1.0", vcpus=1, memory_mib=512, disk_mib=1024,
        )
        assert result is False

    @patch("subprocess.Popen")
    @patch("subprocess.run")
    def test_stop_sandbox(self, mock_run, mock_popen, manager: MicroVMManager) -> None:
        image_dir = Path("/tmp/fa-test-images/ubuntu:24.04")
        (image_dir / "kernel").write_text("fake kernel")
        (image_dir / "rootfs.ext4").write_text("fake rootfs")

        mock_proc = MagicMock()
        mock_popen.return_value = mock_proc
        manager.create_sandbox("sb-test003", "ubuntu:24.04", vcpus=1, memory_mib=512, disk_mib=1024)

        mock_proc.wait.return_value = 0
        result = manager.stop_sandbox("sb-test003")
        assert result is True
        assert manager.active_sandbox_count == 0

    def test_stop_nonexistent(self, manager: MicroVMManager) -> None:
        result = manager.stop_sandbox("sb-nonexistent")
        assert result is False

    @patch("subprocess.Popen")
    @patch("subprocess.run")
    def test_delete_sandbox(self, mock_run, mock_popen, manager: MicroVMManager) -> None:
        image_dir = Path("/tmp/fa-test-images/ubuntu:24.04")
        (image_dir / "kernel").write_text("fake kernel")
        (image_dir / "rootfs.ext4").write_text("fake rootfs")

        mock_proc = MagicMock()
        mock_popen.return_value = mock_proc
        manager.create_sandbox("sb-test004", "ubuntu:24.04", vcpus=1, memory_mib=512, disk_mib=1024)

        result = manager.delete_sandbox("sb-test004")
        assert result is True

    def test_get_process_none(self, manager: MicroVMManager) -> None:
        assert manager.get_process("sb-nonexistent") is None

    @patch("subprocess.run")
    def test_cleanup_orphans(self, mock_run, manager: MicroVMManager) -> None:
        mock_run.return_value.stdout = "12345\n67890\n"
        manager.cleanup_orphans()
        assert mock_run.call_count >= 1

    def test_cleanup_orphans_no_process(self, manager: MicroVMManager) -> None:
        manager.cleanup_orphans()  # Should not raise


# ---------------------------------------------------------------------------
# HostAgent tests
# ---------------------------------------------------------------------------
class TestHostAgent:
    @pytest.fixture
    def agent(self) -> HostAgent:
        config = DEFAULT_CONFIG.copy()
        config["agent"]["heartbeat_interval"] = 3600  # Don't heartbeat during tests
        config["agent"]["control_plane_url"] = "http://test:8000"
        return HostAgent(config)

    def test_init(self, agent: HostAgent) -> None:
        assert agent.config["agent"]["host_id"] == "host-01"
        assert agent.config["agent"]["heartbeat_interval"] == 3600

    @patch("httpx.AsyncClient")
    def test_register(self, mock_httpx, agent: HostAgent) -> None:
        import asyncio
        mock_resp = MagicMock()
        mock_resp.is_success = True
        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp
        mock_httpx.return_value = mock_client

        asyncio.run(agent._register())

    @patch("httpx.AsyncClient")
    def test_heartbeat(self, mock_httpx, agent: HostAgent) -> None:
        import asyncio
        mock_resp = MagicMock()
        mock_resp.is_success = True
        mock_client = MagicMock()
        mock_client.put.return_value = mock_resp
        mock_httpx.return_value = mock_client

        asyncio.run(agent._heartbeat())

    @patch("httpx.AsyncClient")
    def test_register_failure(self, mock_httpx, agent: HostAgent) -> None:
        import asyncio
        mock_resp = MagicMock()
        mock_resp.is_success = False
        mock_resp.status_code = 500
        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp
        mock_httpx.return_value = mock_client

        asyncio.run(agent._register())  # Should not raise

    @patch("httpx.AsyncClient")
    def test_register_connection_error(self, mock_httpx, agent: HostAgent) -> None:
        import asyncio
        mock_client = MagicMock()
        mock_client.post.side_effect = Exception("Connection refused")
        mock_httpx.return_value = mock_client

        asyncio.run(agent._register())  # Should not raise

    @patch("fireagent_agent.agent.os.statvfs")
    def test_get_disk_space(self, mock_statvfs) -> None:
        mock_stat = MagicMock()
        mock_stat.f_blocks = 1000000
        mock_stat.f_frsize = 4096
        mock_stat.f_bfree = 500000
        mock_statvfs.return_value = mock_stat
        total = HostAgent._get_disk_space()
        assert total > 0
        free = HostAgent._get_free_disk()
        assert free > 0

    @patch("builtins.open")
    def test_get_total_memory(self, mock_open) -> None:
        mock_open.return_value.__enter__.return_value = ["MemTotal:       16384000 kB\n"]
        mem = HostAgent._get_total_memory()
        assert mem == 16000  # 16384000 KiB / 1024 = 16000 MiB

    @patch("builtins.open")
    def test_get_memory_usage(self, mock_open) -> None:
        mock_open.return_value.__enter__.return_value = [
            "MemTotal:       16384000 kB\n",
            "MemAvailable:   10485760 kB\n",
        ]
        usage = HostAgent._get_memory_usage()
        assert 30.0 < usage < 40.0  # ~36%


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------
def teardown_module():
    import shutil
    for d in ["/tmp/fa-test-workspace", "/tmp/fa-test-images"]:
        if Path(d).exists():
            shutil.rmtree(d)