"""Pydantic models for the Fireagent API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------
class NetworkRule(BaseModel):
    action: str = Field(..., pattern="^(allow|deny)$")
    protocol: str = Field(..., pattern="^(tcp|udp|icmp)$")
    destination: str = Field(..., min_length=1)
    port: int = Field(..., ge=1, le=65535)
    description: str | None = None


class NetworkPolicy(BaseModel):
    rules: list[NetworkRule] = []


class WorkspaceConfig(BaseModel):
    type: str = Field(..., pattern="^(git|upload|none)$")
    url: str | None = None
    ref: str | None = None
    files: dict[str, str] | None = None


class SandboxCreateRequest(BaseModel):
    image: str = Field(
        ..., min_length=1, description="Guest image name and version (e.g. ubuntu:24.04)"
    )
    workspace: WorkspaceConfig | None = None
    vcpus: int = Field(..., ge=1, le=16)
    memory_mib: int = Field(..., ge=64, le=65536)
    disk_mib: int = Field(..., ge=256, le=1048576)
    ttl_seconds: int | None = Field(None, ge=60, le=86400)
    idle_timeout_seconds: int | None = Field(None, ge=60, le=86400)
    network_policy: NetworkPolicy | None = None
    labels: dict[str, str] | None = None

    @field_validator("image")
    @classmethod
    def validate_image_format(cls, v: str) -> str:
        if ":" not in v:
            raise ValueError("image must be in format 'name:version' (e.g. ubuntu:24.04)")
        return v


class SandboxExecRequest(BaseModel):
    command: str = Field(..., min_length=1)
    working_dir: str | None = None
    environment: dict[str, str] | None = None
    execution_timeout_seconds: int | None = Field(None, ge=1, le=3600)
    stdin: str | None = None


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------
class SandboxResponse(BaseModel):
    id: str
    state: str = "queued"
    image: str
    vcpus: int
    memory_mib: int
    disk_mib: int
    ttl_seconds: int | None = None
    idle_timeout_seconds: int | None = None
    network_policy: dict | None = None
    workspace: dict | None = None
    labels: dict | None = None
    created_at: str | None = None
    started_at: str | None = None
    stopped_at: str | None = None
    last_activity_at: str | None = None
    host: str | None = None
    failure_reason: str | None = None
    effective_limits: dict | None = None


class ExecResponse(BaseModel):
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    start_time: str | None = None
    finish_time: str | None = None
    timed_out: bool = False
    oom_killed: bool = False
    network_denial: str | None = None


class ErrorResponse(BaseModel):
    error: dict[str, Any]
