"""Unit tests for the Fireagent SDK client."""

import json
import os
import time
from unittest.mock import MagicMock, patch

import httpx
import pytest

from fireagent import (
    CommandOomKilledError,
    CommandTimeoutError,
    FireagentClient,
    Sandbox,
    set_api_key,
    set_base_url,
    set_retries,
    set_timeout,
)
from fireagent.exceptions import (
    ConflictError,
    FireagentError,
    ForbiddenError,
    InternalServerError,
    InvalidRequestError,
    NotFoundError,
    RateLimitError,
    ServiceUnavailableError,
    UnauthorizedError,
)
from fireagent.models import CommandResult, SandboxStatus


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def client() -> FireagentClient:
    return FireagentClient(
        base_url="http://test:8000",
        api_key="test-key",
        timeout=5,
        retries=0,
        retry_delay=0,
    )


@pytest.fixture
def sandbox(client: FireagentClient) -> Sandbox:
    return Sandbox(client, "sb-test001")


# ---------------------------------------------------------------------------
# Client configuration
# ---------------------------------------------------------------------------
class TestClientConfig:
    def test_default_base_url(self) -> None:
        c = FireagentClient()
        assert c._base_url == "http://127.0.0.1:8000"

    def test_set_api_key(self, client: FireagentClient) -> None:
        client.set_api_key("new-key")
        assert "Bearer new-key" in str(client._headers()["Authorization"])

    def test_set_base_url(self, client: FireagentClient) -> None:
        client.set_base_url("http://other:9000")
        assert client._base_url == "http://other:9000"

    def test_set_timeout(self, client: FireagentClient) -> None:
        client.set_timeout(60)
        assert client._timeout == 60

    def test_set_retries(self, client: FireagentClient) -> None:
        client.set_retries(5)
        assert client._retries == 5

    def test_global_config_functions(self) -> None:
        set_api_key("global-key")
        set_base_url("http://global:8000")
        set_timeout(30)
        set_retries(3)


# ---------------------------------------------------------------------------
# Sandbox model
# ---------------------------------------------------------------------------
class TestSandbox:
    def test_sandbox_id(self, sandbox: Sandbox) -> None:
        assert sandbox.id == "sb-test001"

    def test_repr(self, sandbox: Sandbox) -> None:
        assert repr(sandbox) == "<Sandbox sb-test001>"


# ---------------------------------------------------------------------------
# CommandResult model
# ---------------------------------------------------------------------------
class TestCommandResult:
    def test_from_dict(self) -> None:
        data = {
            "stdout": "hello",
            "stderr": "",
            "exit_code": 0,
            "start_time": "2026-10-03T17:00:00Z",
            "finish_time": "2026-10-03T17:00:01Z",
            "timed_out": False,
            "oom_killed": False,
        }
        result = CommandResult.from_dict(data)
        assert result.stdout == "hello"
        assert result.exit_code == 0
        assert result.start_time is not None
        assert result.timed_out is False

    def test_from_dict_with_timeout(self) -> None:
        data = {"stdout": "", "stderr": "", "exit_code": -1, "timed_out": True, "oom_killed": False}
        result = CommandResult.from_dict(data)
        assert result.timed_out is True

    def test_from_dict_with_oom(self) -> None:
        data = {"stdout": "", "stderr": "", "exit_code": -1, "timed_out": False, "oom_killed": True}
        result = CommandResult.from_dict(data)
        assert result.oom_killed is True


# ---------------------------------------------------------------------------
# SandboxStatus model
# ---------------------------------------------------------------------------
class TestSandboxStatus:
    def test_from_dict(self) -> None:
        data = {
            "id": "sb-test001",
            "state": "ready",
            "image": "ubuntu:24.04",
            "vcpus": 2,
            "memory_mib": 1024,
            "disk_mib": 2048,
            "created_at": "2026-10-03T17:00:00Z",
            "host": "host-01",
            "effective_limits": {"cpu": 2, "memory_mib": 1024, "disk_mib": 2048},
        }
        status = SandboxStatus.from_dict(data)
        assert status.sandbox_id == "sb-test001"
        assert status.state == "ready"
        assert status.vcpus == 2

    def test_from_dict_empty(self) -> None:
        status = SandboxStatus.from_dict({})
        assert status.state == "unknown"


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------
class TestExceptions:
    def test_inheritance(self) -> None:
        assert issubclass(InvalidRequestError, FireagentError)
        assert issubclass(UnauthorizedError, FireagentError)
        assert issubclass(ForbiddenError, FireagentError)
        assert issubclass(NotFoundError, FireagentError)
        assert issubclass(ConflictError, FireagentError)
        assert issubclass(RateLimitError, FireagentError)
        assert issubclass(InternalServerError, FireagentError)
        assert issubclass(ServiceUnavailableError, FireagentError)

    def test_map_http_status(self) -> None:
        from fireagent.exceptions import map_http_status

        assert map_http_status(400) == InvalidRequestError
        assert map_http_status(401) == UnauthorizedError
        assert map_http_status(403) == ForbiddenError
        assert map_http_status(404) == NotFoundError
        assert map_http_status(429) == RateLimitError
        assert map_http_status(500) == InternalServerError
        assert map_http_status(503) == ServiceUnavailableError
        assert map_http_status(418) == FireagentError  # Unknown status


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------
class TestValidation:
    def test_image_format_validation(self) -> None:
        from fireagent_api.models import SandboxCreateRequest

        # Valid
        req = SandboxCreateRequest(
            image="ubuntu:24.04",
            vcpus=1,
            memory_mib=512,
            disk_mib=1024,
        )
        assert req.image == "ubuntu:24.04"

        # Invalid — missing version
        with pytest.raises(ValueError, match="must be in format"):
            SandboxCreateRequest(
                image="ubuntu", vcpus=1, memory_mib=512, disk_mib=1024
            )

    def test_resource_ranges(self) -> None:
        from fireagent_api.models import SandboxCreateRequest

        # Valid minimal
        req = SandboxCreateRequest(image="ubuntu:24.04", vcpus=1, memory_mib=64, disk_mib=256)
        assert req.vcpus == 1

        # Invalid vcpus (0)
        with pytest.raises(ValueError):
            SandboxCreateRequest(image="ubuntu:24.04", vcpus=0, memory_mib=64, disk_mib=256)

        # Invalid memory (too low)
        with pytest.raises(ValueError):
            SandboxCreateRequest(image="ubuntu:24.04", vcpus=1, memory_mib=32, disk_mib=256)

    def test_network_policy_validation(self) -> None:
        from fireagent_api.models import NetworkRule, NetworkPolicy

        # Valid rule
        rule = NetworkRule(action="allow", protocol="tcp", destination="github.com", port=443)
        assert rule.action == "allow"

        # Invalid action
        with pytest.raises(ValueError):
            NetworkRule(action="maybe", protocol="tcp", destination="test.com", port=80)

        # Invalid protocol
        with pytest.raises(ValueError):
            NetworkRule(action="deny", protocol="ssh", destination="test.com", port=22)

        # Valid policy
        policy = NetworkPolicy(rules=[rule])
        assert len(policy.rules) == 1