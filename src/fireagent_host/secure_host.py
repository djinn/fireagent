"""SecureHost model — host identity and connection parameters.

Tracks hostname, port, auth method, fingerprint, and capabilities.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class SecureHost:
    """Represents a remote worker host that can run Firecracker microVMs.

    Examples::

        host = SecureHost(
            hostname="worker-01.example.com",
            port=22,
            user="fireagent",
            key_path="/home/user/.ssh/id_ed25519",
            label="us-east-1a",
        )
    """

    hostname: str
    """Hostname or IP address."""
    port: int = 22
    """SSH port (default: 22)."""
    user: str = "fireagent"
    """SSH username (default: fireagent)."""
    key_path: str | None = None
    """Path to SSH private key (optional; uses agent if None)."""
    fingerprint: str | None = None
    """Expected SSH host key fingerprint (optional; for verification)."""
    label: str | None = None
    """Human-readable label (e.g. 'us-east-1a', 'gpu-pool')."""

    # --- capabilities (populated on register/health check) ---
    cpu_cores: int = 0
    total_memory_mib: int = 0
    total_disk_gb: int = 0
    free_disk_gb: int = 0
    has_kvm: bool = False
    firecracker_version: str | None = None
    kernel_version: str | None = None
    os_version: str | None = None

    # --- runtime state ---
    connected_at: datetime | None = None
    last_heartbeat_at: datetime | None = None
    status: str = "unknown"
    """Current status: unknown, connecting, connected, unhealthy, disconnected."""
    active_sandbox_count: int = 0
    error_count: int = 0

    # --- metadata ---
    tags: dict[str, str] = field(default_factory=dict)
    """Arbitrary tags (e.g. {"region": "us-east-1", "pool": "gpu"})."""

    @property
    def id(self) -> str:
        """Unique identifier for this host."""
        return f"{self.user}@{self.hostname}:{self.port}"

    @property
    def is_ip(self) -> bool:
        """Check if hostname is an IP address."""
        try:
            ipaddress.ip_address(self.hostname)
            return True
        except ValueError:
            return False

    @property
    def display_name(self) -> str:
        """Human-readable display name."""
        if self.label:
            return f"{self.label} ({self.hostname})"
        return self.hostname

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dictionary (for storage)."""
        return {
            "hostname": self.hostname,
            "port": self.port,
            "user": self.user,
            "key_path": self.key_path,
            "fingerprint": self.fingerprint,
            "label": self.label,
            "cpu_cores": self.cpu_cores,
            "total_memory_mib": self.total_memory_mib,
            "total_disk_gb": self.total_disk_gb,
            "free_disk_gb": self.free_disk_gb,
            "has_kvm": self.has_kvm,
            "firecracker_version": self.firecracker_version,
            "kernel_version": self.kernel_version,
            "os_version": self.os_version,
            "status": self.status,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SecureHost":
        """Deserialize from a dictionary."""
        return cls(
            hostname=data["hostname"],
            port=data.get("port", 22),
            user=data.get("user", "fireagent"),
            key_path=data.get("key_path"),
            fingerprint=data.get("fingerprint"),
            label=data.get("label"),
            cpu_cores=data.get("cpu_cores", 0),
            total_memory_mib=data.get("total_memory_mib", 0),
            total_disk_gb=data.get("total_disk_gb", 0),
            free_disk_gb=data.get("free_disk_gb", 0),
            has_kvm=data.get("has_kvm", False),
            firecracker_version=data.get("firecracker_version"),
            kernel_version=data.get("kernel_version"),
            os_version=data.get("os_version"),
            status=data.get("status", "unknown"),
            tags=data.get("tags", {}),
        )

    def __repr__(self) -> str:
        return (
            f"<SecureHost {self.id} "
            f"cpu={self.cpu_cores} mem={self.total_memory_mib}MiB "
            f"status={self.status}>"
        )
