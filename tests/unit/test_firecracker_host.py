"""Tests for the Firecracker API client and Mock Firecracker server."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from fireagent_host.firecracker_api import (
    FirecrackerAPI,
    FirecrackerAPIError,
    FirecrackerNotReadyError,
)
from fireagent_host.mock_firecracker import MockFirecrackerProcess, MockFirecrackerServer


# ---------------------------------------------------------------------------
# Mock Firecracker Server Tests
# ---------------------------------------------------------------------------
class TestMockFirecrackerServer:
    @pytest.fixture
    def sock_path(self) -> Path:
        with tempfile.TemporaryDirectory() as tmp:
            yield Path(tmp) / "firecracker.sock"

    @pytest.fixture
    def server(self, sock_path: Path) -> MockFirecrackerServer:
        s = MockFirecrackerServer(sock_path)
        s.start()
        yield s
        s.stop()

    def _api(self, server: MockFirecrackerServer) -> FirecrackerAPI:
        """Get an API client connected to the mock server (handles Unix/TCP)."""
        if server._use_unix:
            api = FirecrackerAPI(server._sock_path)
        else:
            api = FirecrackerAPI.from_tcp(host="127.0.0.1", port=server.port)
        return api

    def test_start_stop(self, sock_path: Path) -> None:
        server = MockFirecrackerServer(sock_path)
        server.start()
        assert server.port > 0 or sock_path.exists(), "Server should be listening"
        server.stop()
        if server._use_unix:
            assert not sock_path.exists(), "Socket should be cleaned up"

    def test_machine_config(self, server: MockFirecrackerServer) -> None:
        api = self._api(server)
        assert api.wait_ready(timeout=1.0)

        result = api.set_machine_config(vcpus=2, mem_size_mib=1024)
        assert result["status"] == 204

        config = api.get_machine_config()
        assert config["vcpus"] == 2
        assert config["mem_size_mib"] == 1024

    def test_boot_source(self, server: MockFirecrackerServer) -> None:
        api = self._api(server)
        api.wait_ready(timeout=1.0)

        result = api.set_boot_source(
            kernel_image_path="/test/vmlinux",
            boot_args="console=ttyS0",
        )
        assert result["status"] == 204

    def test_drives(self, server: MockFirecrackerServer) -> None:
        api = self._api(server)
        api.wait_ready(timeout=1.0)

        result = api.set_root_drive(path="/test/rootfs.ext4", is_read_only=True)
        assert result["status"] == 204

        result = api.set_workspace_drive(path="/test/workspace.img", is_read_only=False)
        assert result["status"] == 204

    def test_instance_start_stop(self, server: MockFirecrackerServer) -> None:
        api = self._api(server)
        api.wait_ready(timeout=1.0)

        result = api.instance_start()
        assert server.state["vm_state"] == "running"

        state = api.get_instance_state()
        assert state["state"] == "running"

        result = api.instance_stop()
        assert server.state["vm_state"] == "stopping"

    def test_full_boot_sequence(self, server: MockFirecrackerServer) -> None:
        api = self._api(server)
        api.wait_ready(timeout=1.0)

        result = api.configure_and_boot(
            kernel_path="/test/vmlinux",
            rootfs_path="/test/rootfs.ext4",
            vcpus=1,
            memory_mib=512,
            workspace_path="/test/workspace.img",
        )
        assert result["status"] == 204

        assert server.state["machine_config"]["vcpus"] == 1
        assert server.state["machine_config"]["mem_size_mib"] == 512
        assert server.state["boot_source"]["kernel_image_path"] == "/test/vmlinux"
        assert server.state["drives"]["root"]["is_read_only"] is True
        assert server.state["drives"]["workspace"]["is_read_only"] is False
        assert server.state["vm_state"] == "running"

    def test_vsock_config(self, server: MockFirecrackerServer) -> None:
        api = self._api(server)
        api.wait_ready(timeout=1.0)

        result = api.configure_vsock(guest_port=8001)
        assert result["status"] == 204

    def test_network_config(self, server: MockFirecrackerServer) -> None:
        api = self._api(server)
        api.wait_ready(timeout=1.0)

        result = api.configure_network(
            iface_id="eth0", host_ip="169.254.1.1", guest_ip="169.254.1.2"
        )
        assert result["status"] == 204

    def test_snapshot(self, server: MockFirecrackerServer) -> None:
        api = self._api(server)
        api.wait_ready(timeout=1.0)

        result = api.create_snapshot(
            snapshot_path="/tmp/snap",
            mem_path="/tmp/mem",
        )
        assert result["status"] == 204

    def test_not_found(self, server: MockFirecrackerServer) -> None:
        api = self._api(server)
        api.wait_ready(timeout=1.0)

        with pytest.raises(FirecrackerAPIError, match="not_found"):
            api._request("GET", "/nonexistent")

    def test_state_tracking(self, server: MockFirecrackerServer) -> None:
        api = self._api(server)
        api.wait_ready(timeout=1.0)

        # Track all state changes
        api.set_machine_config(vcpus=4, mem_size_mib=2048)
        assert server.state["machine_config"]["vcpus"] == 4
        assert server.state["machine_config"]["mem_size_mib"] == 2048

        api.set_boot_source(kernel_image_path="/kernels/vmlinux-6.8")
        assert server.state["boot_source"]["kernel_image_path"] == "/kernels/vmlinux-6.8"

        api.add_drive("extra", "/data/extra.img", is_read_only=True)
        assert server.state["drives"]["extra"]["path_on_host"] == "/data/extra.img"


# ---------------------------------------------------------------------------
# FirecrackerAPI Error Handling Tests
# ---------------------------------------------------------------------------
class TestFirecrackerAPIErrors:
    def test_socket_not_found(self) -> None:
        api = FirecrackerAPI("/tmp/nonexistent.sock")
        assert api.is_ready is False

    def test_wait_timeout(self) -> None:
        api = FirecrackerAPI("/tmp/nonexistent.sock")
        ready = api.wait_ready(timeout=0.1)
        assert ready is False

    def test_configure_before_ready(self) -> None:
        api = FirecrackerAPI("/tmp/nonexistent.sock")
        with pytest.raises(FirecrackerNotReadyError):
            api.configure_and_boot(
                kernel_path="/test/vmlinux",
                rootfs_path="/test/rootfs.ext4",
            )


# ---------------------------------------------------------------------------
# Guest Channel Tests (InProcessChannel)
# ---------------------------------------------------------------------------
class TestInProcessChannel:
    @pytest.fixture
    def channel(self):
        from fireagent_host.guest_channel import InProcessChannel

        return InProcessChannel()

    @pytest.mark.asyncio
    async def test_connect(self, channel) -> None:
        await channel.connect()
        assert channel.connected is True

    @pytest.mark.asyncio
    async def test_execute(self, channel) -> None:
        await channel.connect()
        result = await channel.execute("echo 'hello from test'")
        assert result["exit_code"] == 0
        assert "hello from test" in result["stdout"]

    @pytest.mark.asyncio
    async def test_execute_fail(self, channel) -> None:
        await channel.connect()
        result = await channel.execute("false")
        assert result["exit_code"] != 0

    @pytest.mark.asyncio
    async def test_execute_timeout(self, channel) -> None:
        await channel.connect()
        result = await channel.execute("sleep 5", execution_timeout_seconds=1)
        assert result["timed_out"] is True

    @pytest.mark.asyncio
    async def test_health_check(self, channel) -> None:
        await channel.connect()
        healthy = await channel.health_check()
        assert healthy is True

    @pytest.mark.asyncio
    async def test_disconnect(self, channel) -> None:
        await channel.connect()
        await channel.disconnect()
        assert channel.connected is False


# ---------------------------------------------------------------------------
# MicroVMManager Tests (mock mode)
# ---------------------------------------------------------------------------
class TestMicroVMManager:
    @pytest.fixture
    def manager(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = {
                "storage": {
                    "workspace_dir": tmp,
                    "image_dir": tmp,
                },
                "firecracker": {
                    "bin_path": "firecracker",
                },
            }
            # Need to create a minimal image dir
            image_dir = Path(tmp) / "ubuntu:24.04"
            image_dir.mkdir(parents=True, exist_ok=True)

            from fireagent_host.microvm import MicroVMManager

            m = MicroVMManager(config)
            # Force mock mode for testing
            m._use_mock = True
            yield m

    @pytest.mark.asyncio
    async def test_create_sandbox_mock(self, manager) -> None:
        instance = await manager.create_sandbox(
            sandbox_id="sb-test001",
            image="ubuntu:24.04",
            vcpus=1,
            memory_mib=512,
            disk_mib=1024,
        )
        assert instance.sandbox_id == "sb-test001"
        assert instance.is_alive

    @pytest.mark.asyncio
    async def test_exec_command_mock(self, manager) -> None:
        await manager.create_sandbox(
            sandbox_id="sb-test002",
            image="ubuntu:24.04",
            vcpus=1,
            memory_mib=512,
            disk_mib=1024,
        )
        result = await manager.exec_command("sb-test002", "echo 'test'")
        assert result["exit_code"] == 0

    @pytest.mark.asyncio
    async def test_health_check_mock(self, manager) -> None:
        await manager.create_sandbox(
            sandbox_id="sb-test003",
            image="ubuntu:24.04",
            vcpus=1,
            memory_mib=512,
            disk_mib=1024,
        )
        healthy = await manager.health_check("sb-test003")
        assert healthy is True

    @pytest.mark.asyncio
    async def test_stop_sandbox(self, manager) -> None:
        await manager.create_sandbox(
            sandbox_id="sb-test004",
            image="ubuntu:24.04",
            vcpus=1,
            memory_mib=512,
            disk_mib=1024,
        )
        result = await manager.stop_sandbox("sb-test004")
        assert result is True
        assert manager.active_sandbox_count == 0

    @pytest.mark.asyncio
    async def test_stop_nonexistent(self, manager) -> None:
        result = await manager.stop_sandbox("sb-nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_sandbox(self, manager) -> None:
        await manager.create_sandbox(
            sandbox_id="sb-test005",
            image="ubuntu:24.04",
            vcpus=1,
            memory_mib=512,
            disk_mib=1024,
        )
        result = await manager.delete_sandbox("sb-test005")
        assert result is True

    @pytest.mark.asyncio
    async def test_stop_all(self, manager) -> None:
        for i in range(3):
            await manager.create_sandbox(
                sandbox_id=f"sb-test{i:03d}",
                image="ubuntu:24.04",
                vcpus=1,
                memory_mib=128,
                disk_mib=256,
            )
        assert manager.active_sandbox_count == 3
        await manager.stop_all()
        assert manager.active_sandbox_count == 0

    @pytest.mark.asyncio
    async def test_is_mock_mode(self, manager) -> None:
        assert manager.is_mock_mode() is True


# ---------------------------------------------------------------------------
# MockFirecrackerProcess Tests
# ---------------------------------------------------------------------------
class TestMockFirecrackerProcess:
    def test_start_stop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mock = MockFirecrackerProcess(Path(tmp) / "sb-test")
            mock.start()
            assert mock.api_sock.exists()
            assert mock.is_running is True
            mock.stop()
            assert not mock.api_sock.exists()

    def test_state_access(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mock = MockFirecrackerProcess(Path(tmp) / "sb-test")
            mock.start()

            api = FirecrackerAPI(mock.api_sock)
            api.wait_ready(timeout=1.0)
            api.set_machine_config(vcpus=2, mem_size_mib=1024)

            assert mock.state["machine_config"]["vcpus"] == 2
            mock.stop()
