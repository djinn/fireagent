"""Fireagent — Elastic agent sandbox platform powered by Firecracker microVMs.

Fireagent creates, manages, and destroys isolated Linux microVMs for AI agents,
coding tasks, and evaluation workloads. Each sandbox is a stateful session with
persistent file changes, resource limits, and network policies.
"""

__version__ = "0.1.0"
__author__ = "Supreet Sethi"
__license__ = "MIT"

from .client import FireagentClient, Sandbox
from .exceptions import (
    CommandOomKilledError,
    CommandTimeoutError,
    ConflictError,
    FireagentError,
    ForbiddenError,
    InternalServerError,
    InvalidRequestError,
    NetworkDenialError,
    NotFoundError,
    RateLimitError,
    SandboxFailedError,
    SandboxTimeoutError,
    ServiceUnavailableError,
    UnauthorizedError,
)
from .models import CommandResult, SandboxStatus

# ---------------------------------------------------------------------------
# Global convenience interface (single-client pattern)
# ---------------------------------------------------------------------------
_client: FireagentClient | None = None


def _get_client() -> FireagentClient:
    global _client
    if _client is None:
        _client = FireagentClient()
    return _client


def set_api_key(key: str) -> None:
    _get_client().set_api_key(key)


def set_base_url(url: str) -> None:
    _get_client().set_base_url(url)


def set_timeout(timeout: int) -> None:
    _get_client().set_timeout(timeout)


def set_retries(retries: int) -> None:
    _get_client().set_retries(retries)


def set_retry_delay(delay: float) -> None:
    _get_client().set_retry_delay(delay)


def create(
    image: str,
    vcpus: int,
    memory_mib: int,
    disk_mib: int,
    *,
    workspace: dict | None = None,
    ttl_seconds: int | None = None,
    idle_timeout_seconds: int | None = None,
    network_policy: dict | None = None,
    labels: dict | None = None,
    idempotency_key: str | None = None,
) -> Sandbox:
    """Create a new sandbox.

    Parameters
    ----------
    image:
        Guest image name and version (e.g. ``"ubuntu:24.04"``).
    vcpus:
        Number of virtual CPUs.
    memory_mib:
        Guest memory in MiB.
    disk_mib:
        Writable workspace capacity in MiB.
    workspace:
        Task workspace configuration (``{"type": "git", "url": "...", "ref": "..."}``).
    ttl_seconds:
        Maximum sandbox lifetime in seconds.
    idle_timeout_seconds:
        Stop after idle for this many seconds.
    network_policy:
        Network rules (``{"rules": [...]}``).
    labels:
        Caller-supplied metadata (e.g. ``{"job_id": "job-123"}``).
    idempotency_key:
        Idempotency key for retry safety.
    """
    return _get_client().create(
        image=image,
        vcpus=vcpus,
        memory_mib=memory_mib,
        disk_mib=disk_mib,
        workspace=workspace,
        ttl_seconds=ttl_seconds,
        idle_timeout_seconds=idle_timeout_seconds,
        network_policy=network_policy,
        labels=labels,
        idempotency_key=idempotency_key,
    )


def get(sandbox_id: str) -> Sandbox:
    """Get an existing sandbox by ID."""
    return _get_client().get(sandbox_id)


def list_sandboxes() -> list[Sandbox]:
    """List all sandboxes visible to the current API key."""
    return _get_client().list()


async def acreate(
    image: str,
    vcpus: int,
    memory_mib: int,
    disk_mib: int,
    **kwargs,
) -> Sandbox:
    """Async version of :func:`create`."""
    return await _get_client().acreate(
        image=image,
        vcpus=vcpus,
        memory_mib=memory_mib,
        disk_mib=disk_mib,
        **kwargs,
    )


from .cli import cli as main  # CLI entry point

__all__ = [
    "__version__",
    "__author__",
    "__license__",
    "set_api_key",
    "set_base_url",
    "set_timeout",
    "set_retries",
    "set_retry_delay",
    "create",
    "get",
    "list_sandboxes",
    "acreate",
    "Sandbox",
    "CommandResult",
    "SandboxStatus",
    "FireagentClient",
    "FireagentError",
    "InvalidRequestError",
    "UnauthorizedError",
    "ForbiddenError",
    "NotFoundError",
    "ConflictError",
    "RateLimitError",
    "InternalServerError",
    "ServiceUnavailableError",
    "SandboxFailedError",
    "SandboxTimeoutError",
    "CommandTimeoutError",
    "CommandOomKilledError",
    "NetworkDenialError",
]
