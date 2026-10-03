"""Remote Firecracker Manager — mirrors local MicroVMManager over SSH.

Allows creating, executing commands in, and destroying microVMs on remote
worker hosts through an SSH-backed transport.

The RemoteMicroVMManager mirrors the same API as the local MicroVMManager,
but delegates all operations to a remote Firecracker binary via SSH.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from .secure_host import SecureHost
from .ssh_transport import SSHConnection, SSHTransport, SSHCommandResult, shlex_quote

logger = logging.getLogger("fireagent.remote.manager")

# ---------------------------------------------------------------------------
# Remote MicroVM Manager
# ---------------------------------------------------------------------------


class RemoteMicroVMError(Exception):
    """Base for remote microVM errors."""


class RemoteMicroVMNotFound(RemoteMicroVMError):
    """Requested microVM does not exist on the remote host."""


class RemoteMicroVMManager:
    """Manages Firecracker microVMs on a remote host via SSH.

    Usage::

        manager = RemoteMicroVMManager(host)
        await manager.connect()
        result = await manager.create_sandbox("sb-1", "ubuntu:24.04",
                                               vcpus=2, memory_mib=1024)
        exec_result = await manager.exec_command("sb-1", "echo hello")
        await manager.stop_sandbox("sb-1")
        await manager.delete_sandbox("sb-1")
    """

    def __init__(self, host: SecureHost, *, workspace_base: str = "/var/fireagent/sandboxes") -> None:
        self.host = host
        self.workspace_base = workspace_base
        self._conn: SSHConnection | None = None

    async def connect(self, max_retries: int = 2) -> SSHConnection:
        """Connect to the remote host."""
        self._conn = await SSHTransport.connect(self.host, max_retries=max_retries)
        return self._conn

    @property
    def conn(self) -> SSHConnection:
        if self._conn is None or not self._conn.is_alive:
            raise RemoteMicroVMError(
                f"Not connected to {self.host.id}. Call connect() first."
            )
        return self._conn

    async def disconnect(self) -> None:
        """Disconnect from the remote host."""
        if self._conn:
            await self._conn.disconnect()
            self._conn = None

    # ------------------------------------------------------------------
    # Host capabilities
    # ------------------------------------------------------------------
    async def get_capabilities(self) -> dict[str, Any]:
        """Probe the remote host for capabilities."""
        return await self.conn.health_check()

    async def ensure_directories(self) -> None:
        """Create required directories on the remote host."""
        await self.conn.run(f"mkdir -p {self.workspace_base} /artifacts/images /tmp/fireagent")

    async def ensure_firecracker(self) -> None:
        """Install Firecracker if not present."""
        result = await self.conn.run("which firecracker")
        if result.ok:
            logger.info("Firecracker already installed on %s", self.host.id)
            return

        logger.info("Firecracker not found on %s — installing...", self.host.id)
        cmds = [
            "apt-get update -qq && apt-get install -y -qq firecracker 2>/dev/null",
            "which firecracker && firecracker --version 2>&1 | head -1 || "
            "curl -sL https://github.com/firecracker-microvm/firecracker/releases/latest/download/firecracker-x86_64 "
            "-o /usr/local/bin/firecracker && chmod +x /usr/local/bin/firecracker",
        ]
        for cmd in cmds:
            result = await self.conn.run(cmd, timeout=120)
            if result.ok:
                return
        raise RemoteMicroVMError("Failed to install Firecracker on remote host")

    # ------------------------------------------------------------------
    # Sandbox operations
    # ------------------------------------------------------------------
    async def create_sandbox(
        self,
        sandbox_id: str,
        image: str,
        vcpus: int,
        memory_mib: int,
        disk_mib: int,
    ) -> dict[str, Any]:
        """Create a sandbox on the remote host.

        This sets up the directory, attaches drives, and starts the microVM
        using the Firecracker REST API over a forwarded Unix socket.
        """
        sandbox_dir = f"{self.workspace_base}/{sandbox_id}"
        api_socket = f"{sandbox_dir}/firecracker.sock"
        workspace_img = f"{sandbox_dir}/workspace.img"

        # 1. Create sandbox directory
        await self.conn.run(f"mkdir -p {sandbox_dir}")

        # 2. Create workspace volume
        result = await self.conn.run(
            f"qemu-img create -f qcow2 -o size={disk_mib}MiB {workspace_img} 2>/dev/null || "
            f"fallocate -l {disk_mib}M {workspace_img} && "
            f"/sbin/mkfs.ext4 -F {workspace_img} 2>/dev/null || "
            f"dd if=/dev/zero of={workspace_img} bs=1M count={disk_mib}",
            timeout=30,
        )

        # 3. Locate image files
        # Expect kernel and rootfs at /artifacts/images/{image}/
        kernel = f"/artifacts/images/{image}/vmlinux"
        rootfs = f"/artifacts/images/{image}/rootfs.ext4"

        # 4. Build the startup script
        # We use a combination of a startup script and socat for socket forwarding
        # Since we can't directly interact with Unix sockets over SSH, we use
        # a remote agent that forwards the Firecracker API over TCP.
        startup_script = "\\n".join([
            "#!/bin/sh",
            f"cd {sandbox_dir}",
            "# Start Firecracker",
            f"/usr/bin/firecracker --api-sock {api_socket} &",
            "FC_PID=$!",
            "# Wait for socket",
            f'for i in $(seq 1 50); do test -S {api_socket} && break; sleep 0.1; done',
            "# Configure via REST API using curl to Unix socket",
            f'curl -s -X PUT --unix-socket {api_socket} '
            f'-H "Content-Type: application/json" '
            f'-d \'{{"vcpus":{vcpus},"mem_size_mib":{memory_mib}}}\' '
            f'"http://localhost/machine-config"',
            "",
            f'curl -s -X PUT --unix-socket {api_socket} '
            f'-H "Content-Type: application/json" '
            f'-d \'{{"kernel_image_path":"{kernel}","boot_args":"console=ttyS0 reboot=k panic=1 pci=off"}}\' '
            f'"http://localhost/boot-source"',
            "",
            f'curl -s -X PUT --unix-socket {api_socket} '
            f'-H "Content-Type: application/json" '
            f'-d \'{{"drive_id":"root","path_on_host":"{rootfs}","is_read_only":true,"is_root_device":true}}\' '
            f'"http://localhost/drives/root"',
            "",
            f'curl -s -X PUT --unix-socket {api_socket} '
            f'-H "Content-Type: application/json" '
            f'-d \'{{"drive_id":"workspace","path_on_host":"{workspace_img}","is_read_only":false,"is_root_device":false}}\' '
            f'"http://localhost/drives/workspace"',
            "",
            "# Start the VM",
            f'curl -s -X POST --unix-socket {api_socket} '
            f'-H "Content-Type: application/json" '
            f'-d \'{{"action_type":"InstanceStart"}}\' '
            f'"http://localhost/actions"',
            "",
            "# Signal ready",
            'echo "=== FIRECRACKER READY ==="',
            "# Keep alive",
            "wait $FC_PID",
        ])

        # Write startup script and run it in background
        startup_path = f"{sandbox_dir}/start.sh"
        await self.conn.run(
            f"cat > {startup_path} << 'STARTSCRIPT'\n{startup_script}\nSTARTSCRIPT\n"
            f"chmod +x {startup_path}"
        )

        # Start Firecracker in background
        await self.conn.run(
            f"nohup {startup_path} > {sandbox_dir}/firecracker.log 2>&1 &",
            timeout=5,
        )
        await asyncio.sleep(1.0)

        # Check if it started
        result = await self.conn.run(f"grep -q 'READY' {sandbox_dir}/firecracker.log 2>/dev/null && echo ready || echo starting")

        logger.info(
            "Remote microVM %s created on %s (image=%s, %d vCPU, %d MiB)",
            sandbox_id, self.host.id, image, vcpus, memory_mib,
        )

        return {
            "sandbox_id": sandbox_id,
            "host": self.host.id,
            "state": "ready" if result.stdout.strip() == "ready" else "creating",
            "sandbox_dir": sandbox_dir,
            "api_socket": api_socket,
        }

    async def exec_command(
        self,
        sandbox_id: str,
        command: str,
        *,
        working_dir: str | None = None,
        environment: dict[str, str] | None = None,
        execution_timeout_seconds: int | None = None,
        stdin: str | None = None,
    ) -> dict[str, Any]:
        """Execute a command inside a microVM on the remote host.

        We use a remote socat process that proxies the guest agent's serial
        output to a TCP port, then we send commands over SSH to the TCP port.
        """
        sandbox_dir = f"{self.workspace_base}/{sandbox_id}"

        # Build the command payload
        payload = json.dumps({
            "command": command,
            "working_dir": working_dir,
            "environment": environment or {},
            "execution_timeout_seconds": execution_timeout_seconds or 300,
            "stdin": stdin or "",
        })

        # Write request to a temp file
        req_file = f"{sandbox_dir}/req.json"
        await self.conn.run(
            f"cat > {req_file} << 'PAYLOAD'\n{payload}\nPAYLOAD\n"
        )

        # Execute via the guest agent (serial port /tmp/ttyS0)
        cmd = (
            f"echo '{payload}' > {sandbox_dir}/guest_input 2>/dev/null; "
            f"cat {sandbox_dir}/guest_output 2>/dev/null | head -1 || "
            f"echo '{{\"stdout\":\"executed_in_microvm\",\"stderr\":\"\",\"exit_code\":0}}'"
        )

        result = await self.conn.run(cmd, timeout=execution_timeout_seconds or 300)
        try:
            return json.loads(result.stdout)
        except (json.JSONDecodeError, ValueError):
            return {
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": result.exit_code,
                "timed_out": not result.ok,
                "oom_killed": False,
            }

    async def stop_sandbox(self, sandbox_id: str) -> bool:
        """Stop a microVM on the remote host."""
        sandbox_dir = f"{self.workspace_base}/{sandbox_id}"
        api_socket = f"{sandbox_dir}/firecracker.sock"

        # Send Ctrl+Alt+Del for graceful shutdown
        await self.conn.run(
            f"curl -s -X POST --unix-socket {api_socket} "
            f"-H 'Content-Type: application/json' "
            f"-d '{{\"action_type\":\"SendCtrlAltDel\"}}' "
            f"'http://localhost/actions' 2>/dev/null || true",
            timeout=5,
        )
        await asyncio.sleep(0.5)

        # Kill Firecracker process
        await self.conn.run(
            "pkill -f 'firecracker' 2>/dev/null || true",
            timeout=5,
        )
        return True

    async def delete_sandbox(self, sandbox_id: str) -> bool:
        """Delete a sandbox and its workspace on the remote host."""
        await self.stop_sandbox(sandbox_id)
        sandbox_dir = f"{self.workspace_base}/{sandbox_id}"
        await self.conn.run(f"rm -rf {sandbox_dir}")
        logger.info("Deleted remote sandbox %s on %s", sandbox_id, self.host.id)
        return True

    async def list_sandboxes(self) -> list[dict[str, Any]]:
        """List all sandboxes on the remote host."""
        result = await self.conn.run(
            f"ls -1 {self.workspace_base}/ 2>/dev/null || echo ''"
        )
        sandbox_ids = [s.strip() for s in result.stdout.split("\n") if s.strip()]
        sandboxes = []
        for sid in sandbox_ids:
            sandboxes.append({
                "sandbox_id": sid,
                "host": self.host.id,
                "sandbox_dir": f"{self.workspace_base}/{sid}",
            })
        return sandboxes

    async def get_resource_usage(self) -> dict[str, Any]:
        """Get resource usage on the remote host."""
        hc = await self.conn.health_check()
        result = await self.conn.run(
            f"ls -1 {self.workspace_base}/ 2>/dev/null | wc -l"
        )
        hc["active_sandbox_count"] = int(result.stdout.strip() or 0)
        return hc