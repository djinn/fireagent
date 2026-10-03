"""Sandbox service — state store and lifecycle manager.

Phase 1: In-memory store with direct command execution (for testing).
Phase 2: Delegates to HostAgent / MicroVMManager for real Firecracker ops.

In either mode, the service provides the same interface to the API layer.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# In-memory store (replace with PostgreSQL in Phase 2)
# ---------------------------------------------------------------------------
_sandboxes: dict[str, dict[str, Any]] = {}
_executions: dict[str, list[dict[str, Any]]] = {}
_hosts: dict[str, dict[str, Any]] = {}

# Lazy-loaded host agent
_host_agent = None


def _get_host_agent():
    """Get or create the host agent (real or mock)."""
    global _host_agent
    if _host_agent is None:
        try:
            from fireagent_host.agent import HostAgent

            _host_agent = HostAgent()
        except Exception:
            _host_agent = None
    return _host_agent


class SandboxService:
    """Service layer for sandbox lifecycle management.

    Delegates to HostAgent / MicroVMManager for VM-level operations.
    Falls back to direct execution when no Firecracker is available.
    """

    def __init__(self, use_host_agent: bool = False) -> None:
        self._use_host_agent = use_host_agent
        self._host_agent = _get_host_agent() if use_host_agent else None
        self._loop: asyncio.AbstractEventLoop | None = None

    def _get_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None or self._loop.is_closed():
            try:
                self._loop = asyncio.get_running_loop()
            except RuntimeError:
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)
        return self._loop

    def _run_async(self, coro):
        """Run an async coroutine, whether or not we're in an event loop."""
        try:
            loop = asyncio.get_running_loop()
            # We're in a running loop (e.g., FastAPI); create a task
            return asyncio.create_task(coro)
        except RuntimeError:
            # No running loop; run until complete
            return asyncio.run(coro)

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

        # Transition through lifecycle
        self._transition(sandbox_id, "creating")

        # Delegate to host agent if available
        if self._host_agent is not None:
            try:
                result = self._run_async(
                    self._host_agent.create_sandbox(
                        sandbox_id=sandbox_id,
                        image=image,
                        vcpus=vcpus,
                        memory_mib=memory_mib,
                        disk_mib=disk_mib,
                    )
                )
                if isinstance(result, dict) and result.get("state") == "ready":
                    self._transition(sandbox_id, "ready")
                    sandbox["started_at"] = datetime.now(timezone.utc).isoformat()
                    return sandbox
                else:
                    # If result is a coroutine, we need to await it
                    import asyncio as _a

                    try:
                        _a.get_running_loop()
                    except RuntimeError:
                        pass
            except Exception as exc:
                _sandboxes[sandbox_id]["failure_reason"] = str(exc)
                self._transition(sandbox_id, "failed")
                return sandbox

        # Fallback: simulate (Phase 1 behavior)
        self._transition(sandbox_id, "ready")
        sandbox["started_at"] = datetime.now(timezone.utc).isoformat()

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

        self._transition(sandbox_id, "running")
        start_time = datetime.now(timezone.utc)
        sandbox["last_activity_at"] = start_time.isoformat()

        # Try to delegate to host agent (Firecracker microVM)
        if self._host_agent is not None:
            try:
                result = self._run_async(
                    self._host_agent.exec_command(
                        sandbox_id=sandbox_id,
                        command=command,
                        working_dir=working_dir,
                        environment=environment,
                        execution_timeout_seconds=execution_timeout_seconds,
                        stdin=stdin,
                    )
                )
                if isinstance(result, dict):
                    self._transition(sandbox_id, "ready")
                    _executions[sandbox_id].append(result)
                    return result
            except Exception:
                # Fall through to direct execution
                pass

        # Fallback: execute directly on the host (for testing/dev)
        import subprocess  # nosec

        try:
            env = environment or {}
            env.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
            result = subprocess.run(
                ["sh", "-c", command],
                capture_output=True,
                text=True,
                timeout=execution_timeout_seconds or 300,
                cwd=working_dir or "/",
                input=stdin,
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

        # Delegate to host agent
        if self._host_agent is not None:
            try:
                self._run_async(self._host_agent.stop_sandbox(sandbox_id))
            except Exception:
                pass

        sandbox["stopped_at"] = datetime.now(timezone.utc).isoformat()
        self._transition(sandbox_id, "stopped")
        return True

    def delete(self, sandbox_id: str) -> bool:
        # Delegate to host agent first
        if self._host_agent is not None:
            try:
                self._run_async(self._host_agent.delete_sandbox(sandbox_id))
            except Exception:
                pass

        if sandbox_id not in _sandboxes:
            return False
        _executions.pop(sandbox_id, None)
        _sandboxes.pop(sandbox_id, None)
        return True

    def _transition(self, sandbox_id: str, new_state: str) -> None:
        sandbox = _sandboxes.get(sandbox_id)
        if sandbox is None:
            return
        old_state = sandbox["state"]
        sandbox["state"] = new_state
        logger_msg = f"[audit] sandbox={sandbox_id} {old_state} -> {new_state}"
        # In production: log to audit_log table

    # ------------------------------------------------------------------
    # Host management (Phase 2)
    # ------------------------------------------------------------------
    def register_host(self, host_id: str, host_info: dict) -> None:
        _hosts[host_id] = host_info

    def get_host(self, host_id: str) -> dict | None:
        return _hosts.get(host_id)

    def list_hosts(self) -> list[dict]:
        return list(_hosts.values())
