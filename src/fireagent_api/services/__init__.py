"""Sandbox service — in-memory state store and lifecycle manager."""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# In-memory store (replace with PostgreSQL in Phase 2)
# ---------------------------------------------------------------------------
_sandboxes: dict[str, dict[str, Any]] = {}
_executions: dict[str, list[dict[str, Any]]] = {}
_hosts: dict[str, dict[str, Any]] = {}


class SandboxService:
    """Service layer for sandbox lifecycle management.

    Phase 1 uses an in-memory store. Phase 2 replaces this with PostgreSQL
    without changing the interface.
    """

    # ------------------------------------------------------------------
    # Sandbox creation
    # ------------------------------------------------------------------
    def create(
        self,
        sandbox_id: str,
        tenant_id: str,
        image: str,
        vcpus: int,
        memory_mib: int,
        disk_mib: int,
        workspace: Any | None = None,
        ttl_seconds: int | None = None,
        idle_timeout_seconds: int | None = None,
        network_policy: Any | None = None,
        labels: dict | None = None,
    ) -> dict:
        now = datetime.now(timezone.utc).isoformat()

        sandbox = {
            "id": sandbox_id,
            "state": "queued",
            "image": image,
            "vcpus": vcpus,
            "memory_mib": memory_mib,
            "disk_mib": disk_mib,
            "workspace": workspace.model_dump() if hasattr(workspace, "model_dump") else workspace,
            "ttl_seconds": ttl_seconds,
            "idle_timeout_seconds": idle_timeout_seconds,
            "network_policy": (
                network_policy.model_dump()
                if hasattr(network_policy, "model_dump")
                else network_policy
            ),
            "labels": labels or {},
            "created_at": now,
            "started_at": None,
            "stopped_at": None,
            "last_activity_at": None,
            "host": "host-01",
            "failure_reason": None,
            "tenant_id": tenant_id,
            "effective_limits": {
                "cpu": vcpus,
                "memory_mib": memory_mib,
                "disk_mib": disk_mib,
            },
        }
        _sandboxes[sandbox_id] = sandbox
        _executions[sandbox_id] = []

        # Simulate host agent assignment (sync for Phase 1)
        self._transition(sandbox_id, "creating")
        self._transition(sandbox_id, "ready")

        return sandbox

    # ------------------------------------------------------------------
    # Sandbox retrieval
    # ------------------------------------------------------------------
    def get(self, sandbox_id: str) -> dict | None:
        return _sandboxes.get(sandbox_id)

    def list(self) -> list[dict]:
        return list(_sandboxes.values())

    # ------------------------------------------------------------------
    # Command execution
    # ------------------------------------------------------------------
    def exec(
        self,
        sandbox_id: str,
        command: str,
        working_dir: str | None = None,
        environment: dict | None = None,
        execution_timeout_seconds: int | None = None,
        stdin: str | None = None,
    ) -> dict | None:
        sandbox = _sandboxes.get(sandbox_id)
        if sandbox is None:
            return None

        if sandbox["state"] not in ("ready", "running"):
            return {
                "stdout": "",
                "stderr": f"Sandbox is in state {sandbox['state']!r}, not ready or running",
                "exit_code": -1,
                "start_time": datetime.now(timezone.utc).isoformat(),
                "finish_time": datetime.now(timezone.utc).isoformat(),
                "timed_out": False,
                "oom_killed": False,
            }

        # Update state to running
        self._transition(sandbox_id, "running")

        start_time = datetime.now(timezone.utc)
        sandbox["last_activity_at"] = start_time.isoformat()

        # Simulate command execution
        # In production, this is forwarded to the host agent / guest agent
        import shlex
        import subprocess  # nosec

        try:
            result = subprocess.run(
                ["sh", "-c", command],
                capture_output=True,
                text=True,
                timeout=execution_timeout_seconds or 300,
                cwd=working_dir or "/",
            )
            exit_code = result.returncode
            stdout = result.stdout
            stderr = result.stderr
            timed_out = False
            oom_killed = False
        except subprocess.TimeoutExpired:
            stdout = ""
            stderr = "Command timed out"
            exit_code = -1
            timed_out = True
            oom_killed = False
        except Exception as exc:
            stdout = ""
            stderr = str(exc)
            exit_code = -1
            timed_out = False
            oom_killed = False

        finish_time = datetime.now(timezone.utc)

        exec_record = {
            "command": command,
            "working_dir": working_dir,
            "environment": environment,
            "timeout_seconds": execution_timeout_seconds,
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": exit_code,
            "start_time": start_time.isoformat(),
            "finish_time": finish_time.isoformat(),
            "timed_out": timed_out,
            "oom_killed": oom_killed,
        }
        _executions[sandbox_id].append(exec_record)

        # Return to ready after execution
        self._transition(sandbox_id, "ready")

        return exec_record

    # ------------------------------------------------------------------
    # Lifecycle transitions
    # ------------------------------------------------------------------
    def stop(self, sandbox_id: str) -> bool:
        sandbox = _sandboxes.get(sandbox_id)
        if sandbox is None:
            return False

        self._transition(sandbox_id, "stopping")
        sandbox["stopped_at"] = datetime.now(timezone.utc).isoformat()
        self._transition(sandbox_id, "stopped")
        return True

    def delete(self, sandbox_id: str) -> bool:
        if sandbox_id not in _sandboxes:
            return False
        # Clean up
        _executions.pop(sandbox_id, None)
        _sandboxes.pop(sandbox_id, None)
        return True

    def _transition(self, sandbox_id: str, new_state: str) -> None:
        sandbox = _sandboxes.get(sandbox_id)
        if sandbox is None:
            return
        old_state = sandbox["state"]
        sandbox["state"] = new_state
        # In production: log to audit_log table
        # INSERT INTO audit_log (sandbox_id, event, from_state, to_state, ...)
        print(f"[audit] sandbox={sandbox_id} {old_state} -> {new_state}")

    # ------------------------------------------------------------------
    # Host management (Phase 2)
    # ------------------------------------------------------------------
    def register_host(self, host_id: str, host_info: dict) -> None:
        _hosts[host_id] = host_info

    def get_host(self, host_id: str) -> dict | None:
        return _hosts.get(host_id)

    def list_hosts(self) -> list[dict]:
        return list(_hosts.values())
