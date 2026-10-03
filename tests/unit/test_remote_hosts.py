"""Tests for remote host management — SSH, registry, operator, and CLI."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from fireagent_host.secure_host import SecureHost
from fireagent_host.registry import HostRegistry
from fireagent_host.mock_ssh import MockSSHConnection, MockSSHTransport, MockSSHCommandResult


# ---------------------------------------------------------------------------
# SecureHost tests
# ---------------------------------------------------------------------------
class TestSecureHost:
    def test_init(self) -> None:
        h = SecureHost(hostname="worker-01.example.com")
        assert h.hostname == "worker-01.example.com"
        assert h.port == 22
        assert h.user == "fireagent"
        assert h.status == "unknown"

    def test_id(self) -> None:
        h = SecureHost(hostname="10.0.0.1", port=2222, user="admin")
        assert h.id == "admin@10.0.0.1:2222"

    def test_is_ip(self) -> None:
        h = SecureHost(hostname="192.168.1.1")
        assert h.is_ip is True
        h2 = SecureHost(hostname="worker.example.com")
        assert h2.is_ip is False

    def test_display_name_with_label(self) -> None:
        h = SecureHost(hostname="10.0.0.1", label="us-east-1a")
        assert "us-east-1a" in h.display_name
        assert "10.0.0.1" in h.display_name

    def test_to_dict_roundtrip(self) -> None:
        h = SecureHost(
            hostname="worker-01",
            port=2222,
            user="admin",
            label="test",
            cpu_cores=8,
            has_kvm=True,
            tags={"env": "prod"},
        )
        d = h.to_dict()
        h2 = SecureHost.from_dict(d)
        assert h2.hostname == "worker-01"
        assert h2.port == 2222
        assert h2.user == "admin"
        assert h2.label == "test"
        assert h2.cpu_cores == 8
        assert h2.has_kvm is True
        assert h2.tags == {"env": "prod"}

    def test_repr(self) -> None:
        h = SecureHost(hostname="test-host", cpu_cores=4, total_memory_mib=16384)
        r = repr(h)
        assert "test-host" in r
        assert "4" in r
        assert "16384" in r


# ---------------------------------------------------------------------------
# HostRegistry tests
# ---------------------------------------------------------------------------
class TestHostRegistry:
    @pytest.fixture
    def registry(self) -> HostRegistry:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hosts.json"
            yield HostRegistry(path=path)

    def test_add_and_get(self, registry: HostRegistry) -> None:
        h = SecureHost(hostname="worker-01")
        registry.add(h)
        assert registry.get(h.id) is h

    def test_add_updates(self, registry: HostRegistry) -> None:
        h = SecureHost(hostname="worker-01", cpu_cores=4)
        registry.add(h)
        h2 = SecureHost(hostname="worker-01", cpu_cores=8)
        registry.add(h2)
        assert registry.get(h.id).cpu_cores == 8

    def test_remove(self, registry: HostRegistry) -> None:
        h = SecureHost(hostname="worker-01")
        registry.add(h)
        assert registry.remove(h.id) is True
        assert registry.get(h.id) is None

    def test_remove_nonexistent(self, registry: HostRegistry) -> None:
        assert registry.remove("nonexistent") is False

    def test_list(self, registry: HostRegistry) -> None:
        registry.add(SecureHost(hostname="a", status="connected"))
        registry.add(SecureHost(hostname="b", status="disconnected"))
        registry.add(SecureHost(hostname="c", status="connected"))

        all_h = registry.list()
        assert len(all_h) == 3

        connected = registry.list(status="connected")
        assert len(connected) == 2

    def test_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hosts.json"
            r1 = HostRegistry(path=path)
            r1.add(SecureHost(hostname="persist-test", cpu_cores=16))
            del r1

            r2 = HostRegistry(path=path)
            assert r2.count == 1
            h = r2.get("fireagent@persist-test:22")
            assert h is not None
            assert h.cpu_cores == 16

    def test_contains(self, registry: HostRegistry) -> None:
        h = SecureHost(hostname="worker-01")
        registry.add(h)
        assert h.id in registry

    def test_len(self, registry: HostRegistry) -> None:
        assert len(registry) == 0
        registry.add(SecureHost(hostname="w1"))
        assert len(registry) == 1

    def test_clear(self, registry: HostRegistry) -> None:
        registry.add(SecureHost(hostname="w1"))
        registry.add(SecureHost(hostname="w2"))
        registry.clear()
        assert registry.count == 0

    def test_iteration(self, registry: HostRegistry) -> None:
        hosts = [SecureHost(hostname=f"w{i}") for i in range(3)]
        for h in hosts:
            registry.add(h)
        recovered = list(registry)
        assert len(recovered) == 3


# ---------------------------------------------------------------------------
# Mock SSH Transport tests
# ---------------------------------------------------------------------------
class TestMockSSHConnection:
    @pytest.fixture
    async def conn(self) -> MockSSHConnection:
        host = SecureHost(hostname="mock-host")
        c = MockSSHConnection(host)
        await c.connect()
        return c

    @pytest.mark.asyncio
    async def test_connect(self) -> None:
        host = SecureHost(hostname="test-host")
        conn = MockSSHConnection(host)
        assert conn.is_alive is False
        await conn.connect()
        assert conn.is_alive is True
        assert host.status == "connected"

    @pytest.mark.asyncio
    async def test_disconnect(self, conn: MockSSHConnection) -> None:
        await conn.disconnect()
        assert conn.is_alive is False

    @pytest.mark.asyncio
    async def test_run_basic(self, conn: MockSSHConnection) -> None:
        result = await conn.run("echo hello")
        assert result.exit_code == 0

    @pytest.mark.asyncio
    async def test_run_not_connected(self) -> None:
        host = SecureHost(hostname="test")
        conn = MockSSHConnection(host)
        result = await conn.run("echo test")
        assert result.exit_code == -1

    @pytest.mark.asyncio
    async def test_health_check(self, conn: MockSSHConnection) -> None:
        health = await conn.health_check()
        assert health["cpu_cores"] == 8
        assert health["has_kvm"] is True
        assert health["firecracker_version"] == "1.2.0"

    @pytest.mark.asyncio
    async def test_mkdir(self, conn: MockSSHConnection) -> None:
        result = await conn.run("mkdir -p /test/path")
        assert result.ok

    @pytest.mark.asyncio
    async def test_upload(self, conn: MockSSHConnection) -> None:
        result = await conn.upload("/local/path", "/remote/path")
        assert result.ok

    @pytest.mark.asyncio
    async def test_download(self, conn: MockSSHConnection) -> None:
        result = await conn.download("/remote/path", "/local/path")
        assert result.ok


# ---------------------------------------------------------------------------
# Operator tests (mock mode)
# ---------------------------------------------------------------------------
class TestOperator:
    @pytest.fixture
    def operator(self):
        with tempfile.TemporaryDirectory() as tmp:
            from fireagent_host.operator import Operator

            op = Operator(mode="mock", registry_path=Path(tmp) / "hosts.json")
            yield op

    def test_init_mock_mode(self, operator) -> None:
        assert operator.is_mock is True

    def test_add_host(self, operator) -> None:
        host = operator.add_host("test-host-01", label="test-cluster")
        assert host.hostname == "test-host-01"
        assert host.label == "test-cluster"
        assert operator.get_host(host.id) is not None

    def test_add_host_with_tags(self, operator) -> None:
        host = operator.add_host("test-host-02", tags={"env": "staging", "region": "us"})
        assert host.tags == {"env": "staging", "region": "us"}

    def test_remove_host(self, operator) -> None:
        host = operator.add_host("test-host-03")
        assert operator.remove_host(host.id) is True
        assert operator.get_host(host.id) is None

    def test_remove_nonexistent(self, operator) -> None:
        assert operator.remove_host("nonexistent") is False

    def test_list_hosts(self, operator) -> None:
        operator.add_host("a.example.com")
        operator.add_host("b.example.com")
        operator.add_host("c.example.com")
        hosts = operator.list_hosts()
        assert len(hosts) == 3

    def test_list_hosts_filtered(self, operator) -> None:
        operator.add_host("a.example.com")
        hosts = operator.list_hosts(status="registered")
        assert len(hosts) == 1
        hosts = operator.list_hosts(status="connected")
        assert len(hosts) == 0

    def test_generate_key(self, operator) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            key_path = f"{tmp}/id_ed25519"
            path = operator.generate_key(key_path)
            assert os.path.exists(path)

    def test_deploy_keys(self, operator) -> None:
        host = operator.add_host("test-deploy")
        result = operator.deploy_keys(host.id)
        assert result["verified"] is True
        assert "key" in result

    def test_host_health(self, operator) -> None:
        host = operator.add_host("test-health")
        health = operator.host_health(host.id)
        assert health["status"] == "connected"
        assert health["cpu_cores"] == 8
        assert health["has_kvm"] is True
        assert health["firecracker_version"] == "1.2.0"

    def test_health_all(self, operator) -> None:
        operator.add_host("h1.example.com")
        operator.add_host("h2.example.com")
        results = operator.health_all()
        assert len(results) == 2
        for r in results:
            assert r["status"] == "connected"

    def test_create_sandbox(self, operator) -> None:
        host = operator.add_host("test-sandbox-create")
        result = operator.create_sandbox(
            host_id=host.id,
            sandbox_id="sb-remote-001",
            image="ubuntu:24.04",
            vcpus=2,
            memory_mib=1024,
            disk_mib=2048,
        )
        assert result["sandbox_id"] == "sb-remote-001"
        assert result["host"] == host.id

    def test_exec_command(self, operator) -> None:
        host = operator.add_host("test-exec")
        operator.create_sandbox(host.id, "sb-exec-test", "ubuntu:24.04", 1, 512, 1024)
        result = operator.exec_command(host.id, "sb-exec-test", "echo hello")
        assert "mock" in result["stdout"].lower() or result["exit_code"] == 0

    def test_stop_sandbox(self, operator) -> None:
        host = operator.add_host("test-stop")
        operator.create_sandbox(host.id, "sb-stop-test", "ubuntu:24.04", 1, 512, 1024)
        result = operator.stop_sandbox(host.id, "sb-stop-test")
        assert result is True

    def test_delete_sandbox(self, operator) -> None:
        host = operator.add_host("test-delete-vm")
        operator.create_sandbox(host.id, "sb-del-test", "ubuntu:24.04", 1, 512, 1024)
        result = operator.delete_sandbox(host.id, "sb-del-test")
        assert result is True

    def test_list_sandboxes(self, operator) -> None:
        host = operator.add_host("test-list")
        operator.create_sandbox(host.id, "sb-list-1", "ubuntu:24.04", 1, 512, 1024)
        sandboxes = operator.list_sandboxes(host.id)
        assert len(sandboxes) == 1

    def test_get_resource_usage(self, operator) -> None:
        host = operator.add_host("test-resources")
        usage = operator.get_resource_usage(host.id)
        assert "cpu_cores" in usage
        assert "active_sandbox_count" in usage


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------
class TestCLIHosts:
    @pytest.fixture
    def runner(self) -> CliRunner:
        return CliRunner()

    def test_hosts_help(self, runner: CliRunner) -> None:
        from fireagent.cli import cli

        result = runner.invoke(cli, ["hosts", "--help"])
        assert result.exit_code == 0
        assert "add" in result.output
        assert "remove" in result.output
        assert "ls" in result.output

    @patch("fireagent.cli._get_operator")
    def test_host_add(self, mock_op, runner: CliRunner) -> None:
        from fireagent_host.secure_host import SecureHost

        mock_op.return_value.add_host.return_value = SecureHost(
            hostname="test.example.com",
            port=22,
            user="fireagent",
        )
        from fireagent.cli import cli

        result = runner.invoke(cli, ["hosts", "add", "test.example.com", "--label", "test"])
        assert result.exit_code == 0

    @patch("fireagent.cli._get_operator")
    def test_host_remove(self, mock_op, runner: CliRunner) -> None:
        mock_op.return_value.remove_host.return_value = True
        from fireagent.cli import cli

        result = runner.invoke(cli, ["hosts", "remove", "fireagent@test:22", "--yes"])
        assert result.exit_code == 0
        assert "removed" in result.output

    @patch("fireagent.cli._get_operator")
    def test_host_list(self, mock_op, runner: CliRunner) -> None:
        from fireagent_host.secure_host import SecureHost

        mock_op.return_value.list_hosts.return_value = [
            SecureHost(
                hostname="h1.example.com",
                status="connected",
                cpu_cores=8,
                total_memory_mib=32768,
                has_kvm=True,
                firecracker_version="1.2.0",
            ),
            SecureHost(
                hostname="h2.example.com",
                status="connected",
                cpu_cores=16,
                total_memory_mib=65536,
                has_kvm=True,
                firecracker_version="1.2.0",
            ),
        ]
        from fireagent.cli import cli

        result = runner.invoke(cli, ["hosts", "ls"])
        assert result.exit_code == 0
        assert "h1.example.com" in result.output
        assert "h2.example.com" in result.output

    @patch("fireagent.cli._get_operator")
    def test_host_status(self, mock_op, runner: CliRunner) -> None:
        mock_op.return_value.host_health.return_value = {
            "host_id": "fireagent@test:22",
            "hostname": "test.example.com",
            "status": "connected",
            "cpu_cores": 8,
            "total_memory_mib": 32768,
            "has_kvm": True,
            "firecracker_version": "1.2.0",
        }
        from fireagent.cli import cli

        result = runner.invoke(cli, ["hosts", "status", "fireagent@test:22"])
        assert result.exit_code == 0
        assert "connected" in result.output
        assert "test.example.com" in result.output

    @patch("fireagent.cli._get_operator")
    def test_host_health_all(self, mock_op, runner: CliRunner) -> None:
        mock_op.return_value.health_all.return_value = [
            {"host_id": "h1", "status": "connected"},
            {"host_id": "h2", "status": "connected"},
        ]
        from fireagent.cli import cli

        result = runner.invoke(cli, ["hosts", "health-all"])
        assert result.exit_code == 0

    @patch("fireagent.cli._get_operator")
    def test_host_push_keys(self, mock_op, runner: CliRunner) -> None:
        mock_op.return_value.deploy_keys.return_value = {
            "host_id": "fireagent@test:22",
            "key": "ssh-ed25519 AAA...",
            "verified": True,
            "result": "ok",
        }
        from fireagent.cli import cli

        result = runner.invoke(cli, ["hosts", "push-keys", "fireagent@test:22"])
        assert result.exit_code == 0
        assert "Key deployed" in result.output
        assert "Verified" in result.output

    @patch("fireagent.cli._get_operator")
    def test_host_generate_key(self, mock_op, runner: CliRunner) -> None:
        mock_op.return_value.generate_key.return_value = "/tmp/.ssh/id_ed25519"
        from fireagent.cli import cli

        result = runner.invoke(cli, ["hosts", "generate-key"])
        assert result.exit_code == 0

    @patch("fireagent.cli._get_operator")
    def test_host_discover(self, mock_op, runner: CliRunner) -> None:
        from fireagent_host.secure_host import SecureHost

        mock_op.return_value.discover_hosts.return_value = [
            SecureHost(hostname="10.0.0.1", port=22, user="fireagent", label="discovered-10.0.0.1"),
        ]
        from fireagent.cli import cli

        result = runner.invoke(cli, ["hosts", "discover", "--cidr", "10.0.0.0/30"])
        assert result.exit_code == 0

    @patch("fireagent.cli._get_operator")
    def test_host_sandboxes(self, mock_op, runner: CliRunner) -> None:
        mock_op.return_value.list_sandboxes.return_value = [
            {"sandbox_id": "sb-remote-001", "host": "fireagent@test:22"},
        ]
        from fireagent.cli import cli

        result = runner.invoke(cli, ["hosts", "sandboxes", "fireagent@test:22"])
        assert result.exit_code == 0

    @patch("fireagent.cli._get_operator")
    def test_host_resource_usage(self, mock_op, runner: CliRunner) -> None:
        mock_op.return_value.get_resource_usage.return_value = {
            "cpu_cores": 8,
            "total_memory_mib": 32768,
            "active_sandbox_count": 3,
        }
        from fireagent.cli import cli

        result = runner.invoke(cli, ["hosts", "resource-usage", "fireagent@test:22"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# MockSSHTransport tests
# ---------------------------------------------------------------------------
class TestMockSSHTransport:
    @pytest.mark.asyncio
    async def test_connect_pool(self) -> None:
        host = SecureHost(hostname="pool-test-host")
        conn1 = await MockSSHTransport.connect(host)
        conn2 = await MockSSHTransport.connect(host)
        assert conn1 is conn2  # Should return cached connection

    @pytest.mark.asyncio
    async def test_disconnect_all(self) -> None:
        host1 = SecureHost(hostname="h1")
        host2 = SecureHost(hostname="h2")
        await MockSSHTransport.connect(host1)
        await MockSSHTransport.connect(host2)
        await MockSSHTransport.disconnect_all()
        assert len(MockSSHTransport._instances) == 0
