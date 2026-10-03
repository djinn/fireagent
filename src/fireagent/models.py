"""Data models for the Fireagent SDK."""

from __future__ import annotations

import dataclasses
from datetime import datetime
from typing import Any


@dataclasses.dataclass
class CommandResult:
    """Result of a command execution inside a sandbox."""

    stdout: str
    """Standard output."""
    stderr: str
    """Standard error."""
    exit_code: int
    """Command exit code (0 = success)."""
    start_time: datetime | None = None
    """ISO 8601 timestamp of command start."""
    finish_time: datetime | None = None
    """ISO 8601 timestamp of command finish."""
    timed_out: bool = False
    """Whether the command was killed by timeout."""
    oom_killed: bool = False
    """Whether the command was killed by OOM."""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CommandResult:
        return cls(
            stdout=data.get("stdout", ""),
            stderr=data.get("stderr", ""),
            exit_code=data.get("exit_code", -1),
            start_time=_parse_ts(data.get("start_time")),
            finish_time=_parse_ts(data.get("finish_time")),
            timed_out=data.get("timed_out", False),
            oom_killed=data.get("oom_killed", False),
        )


@dataclasses.dataclass
class SandboxStatus:
    """Snapshot of a sandbox's current state."""

    sandbox_id: str
    """Unique sandbox identifier."""
    state: str
    """Current lifecycle state (queued, creating, ready, running, stopping, stopped, failed, expired)."""
    image: str
    """Guest image name and version."""
    vcpus: int
    memory_mib: int
    disk_mib: int
    ttl_seconds: int | None = None
    idle_timeout_seconds: int | None = None
    network_policy: dict | None = None
    labels: dict | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    stopped_at: datetime | None = None
    last_activity_at: datetime | None = None
    host: str | None = None
    failure_reason: str | None = None
    effective_limits: dict | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SandboxStatus:
        return cls(
            sandbox_id=data.get("id", ""),
            state=data.get("state", "unknown"),
            image=data.get("image", ""),
            vcpus=data.get("vcpus", 0),
            memory_mib=data.get("memory_mib", 0),
            disk_mib=data.get("disk_mib", 0),
            ttl_seconds=data.get("ttl_seconds"),
            idle_timeout_seconds=data.get("idle_timeout_seconds"),
            network_policy=data.get("network_policy"),
            labels=data.get("labels"),
            created_at=_parse_ts(data.get("created_at")),
            started_at=_parse_ts(data.get("started_at")),
            stopped_at=_parse_ts(data.get("stopped_at")),
            last_activity_at=_parse_ts(data.get("last_activity_at")),
            host=data.get("host"),
            failure_reason=data.get("failure_reason"),
            effective_limits=data.get("effective_limits"),
        )


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        from datetime import datetime as dt

        try:
            return dt.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None
