"""Unit tests for the Fireagent API service layer."""

import pytest

from fireagent_api.services import SandboxService


@pytest.fixture
def service() -> SandboxService:
    return SandboxService()


class TestSandboxService:
    def test_create_sandbox(self, service: SandboxService) -> None:
        result = service.create(
            sandbox_id="sb-test001",
            tenant_id="ten-000001",
            image="ubuntu:24.04",
            vcpus=1,
            memory_mib=512,
            disk_mib=1024,
            ttl_seconds=3600,
            labels={"env": "test"},
        )
        assert result["id"] == "sb-test001"
        assert result["state"] == "ready"
        assert result["vcpus"] == 1
        assert result["memory_mib"] == 512
        assert result["disk_mib"] == 1024
        assert result["labels"] == {"env": "test"}
        assert result["created_at"] is not None

    def test_get_sandbox(self, service: SandboxService) -> None:
        service.create(
            sandbox_id="sb-test002",
            tenant_id="ten-000001",
            image="ubuntu:24.04",
            vcpus=2,
            memory_mib=1024,
            disk_mib=2048,
        )
        result = service.get("sb-test002")
        assert result is not None
        assert result["id"] == "sb-test002"

    def test_get_nonexistent(self, service: SandboxService) -> None:
        result = service.get("sb-nonexistent")
        assert result is None

    def test_list_sandboxes(self, service: SandboxService) -> None:
        service.create(
            sandbox_id="sb-test003",
            tenant_id="ten-000001",
            image="ubuntu:24.04",
            vcpus=1,
            memory_mib=256,
            disk_mib=512,
        )
        service.create(
            sandbox_id="sb-test004",
            tenant_id="ten-000001",
            image="ubuntu:24.04",
            vcpus=2,
            memory_mib=512,
            disk_mib=1024,
        )
        sandboxes = service.list()
        assert len(sandboxes) >= 2

    def test_exec_command(self, service: SandboxService) -> None:
        service.create(
            sandbox_id="sb-test005",
            tenant_id="ten-000001",
            image="ubuntu:24.04",
            vcpus=1,
            memory_mib=512,
            disk_mib=1024,
        )
        result = service.exec("sb-test005", command="echo hello")
        assert result is not None
        assert result["exit_code"] == 0

    def test_exec_on_stopped_sandbox(self, service: SandboxService) -> None:
        service.create(
            sandbox_id="sb-test006",
            tenant_id="ten-000001",
            image="ubuntu:24.04",
            vcpus=1,
            memory_mib=512,
            disk_mib=1024,
        )
        service.stop("sb-test006")
        result = service.exec("sb-test006", command="echo hello")
        assert result is not None
        assert "not ready" in result["stderr"].lower()

    def test_stop_sandbox(self, service: SandboxService) -> None:
        service.create(
            sandbox_id="sb-test007",
            tenant_id="ten-000001",
            image="ubuntu:24.04",
            vcpus=1,
            memory_mib=512,
            disk_mib=1024,
        )
        ok = service.stop("sb-test007")
        assert ok is True

        sandbox = service.get("sb-test007")
        assert sandbox["state"] == "stopped"

    def test_delete_sandbox(self, service: SandboxService) -> None:
        service.create(
            sandbox_id="sb-test008",
            tenant_id="ten-000001",
            image="ubuntu:24.04",
            vcpus=1,
            memory_mib=512,
            disk_mib=1024,
        )
        ok = service.delete("sb-test008")
        assert ok is True
        assert service.get("sb-test008") is None

    def test_delete_nonexistent(self, service: SandboxService) -> None:
        ok = service.delete("sb-nonexistent")
        assert ok is False

    def test_stop_nonexistent(self, service: SandboxService) -> None:
        ok = service.stop("sb-nonexistent")
        assert ok is False

    def test_exec_on_nonexistent(self, service: SandboxService) -> None:
        result = service.exec("sb-nonexistent", command="echo hello")
        assert result is None

    def test_lifecycle_transitions(self, service: SandboxService) -> None:
        service.create(
            sandbox_id="sb-test009",
            tenant_id="ten-000001",
            image="ubuntu:24.04",
            vcpus=1,
            memory_mib=512,
            disk_mib=1024,
        )
        sandbox = service.get("sb-test009")

        # Created → queued → creating → ready
        ordered_states = ["queued", "creating", "ready"]
        # The in-memory service transitions quickly so we just check final state
        assert sandbox["state"] == "ready"

        # ready → running → ready (on exec)
        service.exec("sb-test009", command="true")
        sandbox = service.get("sb-test009")
        assert sandbox["state"] == "ready"

        # ready → stopping → stopped
        service.stop("sb-test009")
        sandbox = service.get("sb-test009")
        assert sandbox["state"] == "stopped"