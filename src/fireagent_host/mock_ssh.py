"""Mock SSH Transport — simulates remote hosts for CI/testing.

Provides a lightweight in-process mock that mirrors the SSHTransport API
without requiring actual SSH or asyncssh.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .secure_host import SecureHost

logger = logging.getLogger("fireagent.remote.mock_ssh")

# ---------------------------------------------------------------------------
# Mock SSH Command Result
# ---------------------------------------------------------------------------


class MockSSHCommandResult:
    """Matches SSHCommandResult interface."""

    def __init__(
        self,
        stdout: str = "",
        stderr: str = "",
        exit_code: int = 0,
        command: str = "",
        duration: float = 0.0,
    ) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code
        self.command = command
        self.duration = duration

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


# ---------------------------------------------------------------------------
# Mock SSH Connection
# ---------------------------------------------------------------------------


class MockSSHConnection:
    """Simulates an SSH connection to a remote host."""

    def __init__(self, host: SecureHost) -> None:
        self.host = host
        self._connected = False
        self._connected_at: float | None = None
        self._files: dict[str, str] = {}
        self._sandbox_dirs: set[str] = set()
        self._firecracker_running: set[str] = set()
        self._capabilities = {
            "cpu_cores": 8,
            "total_memory_mib": 32768,
            "total_disk_gb": 500,
            "free_disk_gb": 350,
            "has_kvm": True,
            "firecracker_version": "1.2.0",
            "kernel_version": "6.8.0-generic",
            "os_version": "Ubuntu 24.04 LTS",
        }

    async def connect(self, max_retries: int = 2) -> None:
        await asyncio.sleep(0.05)
        self._connected = True
        self._connected_at = time.time()
        self.host.status = "connected"
        self.host.connected_at = datetime.now(timezone.utc)

    async def disconnect(self) -> None:
        self._connected = False
        self.host.status = "disconnected"

    @property
    def is_alive(self) -> bool:
        return self._connected

    async def run(
        self,
        command: str,
        *,
        timeout: float | None = None,
        sudo: bool = False,
        environment: dict[str, str] | None = None,
    ) -> MockSSHCommandResult:
        if not self._connected:
            return MockSSHCommandResult(
                stdout="",
                stderr="Not connected",
                exit_code=-1,
                command=command,
            )

        await asyncio.sleep(0.01)  # Simulate network latency

        # Route command based on patterns
        cmd = command.strip()

        # Health check commands
        if cmd == "nproc 2>/dev/null || echo 1":
            return MockSSHCommandResult(stdout=str(self._capabilities["cpu_cores"]), command=cmd)
        if "free -m" in cmd:
            return MockSSHCommandResult(
                stdout=f"Mem:{self._capabilities['total_memory_mib']}", command=cmd
            )
        if "df -BG" in cmd:
            return MockSSHCommandResult(
                stdout=f"/ {self._capabilities['total_disk_gb']}G\n", command=cmd
            )
        if "test -c /dev/kvm" in cmd:
            return MockSSHCommandResult(
                stdout="true" if self._capabilities["has_kvm"] else "false", command=cmd
            )
        if "firecracker --version" in cmd:
            return MockSSHCommandResult(
                stdout=self._capabilities.get("firecracker_version", ""), command=cmd
            )
        if "uname -r" in cmd:
            return MockSSHCommandResult(stdout=self._capabilities["kernel_version"], command=cmd)
        if "cat /etc/os-release" in cmd:
            return MockSSHCommandResult(
                stdout=f'PRETTY_NAME="{self._capabilities["os_version"]}"', command=cmd
            )
        if "echo 'auth-ok'" in cmd:
            return MockSSHCommandResult(stdout="auth-ok", command=cmd)
        if "echo 'health-ok'" in cmd:
            return MockSSHCommandResult(stdout="health-ok", command=cmd)

        # mkdir
        if cmd.startswith("mkdir -p"):
            path = cmd.replace("mkdir -p ", "")
            self._files[path] = "directory"
            # Track sandbox directories for list_sandboxes support
            import re

            for part in cmd.split():
                for pattern in ["/var/fireagent/sandboxes/", "/tmp/fireagent/"]:
                    if pattern in part:
                        sid = part.split(pattern)[-1].split("/")[0]
                        if sid:
                            self._sandbox_dirs.add(sid)
            return MockSSHCommandResult(stdout="", command=cmd)

        # File write (cat > file << EOF)
        if "cat > " in cmd and "<< 'PAYLOAD'" in cmd:
            # Extract file path and payload
            import re

            m = re.search(r"cat > (\S+) << 'PAYLOAD'", cmd)
            if m:
                path = m.group(1)
                payload_start = cmd.find("PAYLOAD\n") + len("PAYLOAD\n")
                payload_end = cmd.rfind("\nPAYLOAD")
                if payload_end > payload_start:
                    self._files[path] = cmd[payload_start:payload_end]
                    return MockSSHCommandResult(stdout="", command=cmd)
            return MockSSHCommandResult(stdout="", command=cmd)

        # File write (heredoc)
        if "cat > " in cmd and "<< 'STARTSCRIPT'" in cmd:
            import re

            m = re.search(r"cat > (\S+) << 'STARTSCRIPT'", cmd)
            if m:
                path = m.group(1)
                self._files[path] = cmd
                return MockSSHCommandResult(stdout="", command=cmd)
            return MockSSHCommandResult(stdout="", command=cmd)

        # chmod
        if cmd.startswith("chmod +x"):
            return MockSSHCommandResult(stdout="", command=cmd)

        # nohup
        if cmd.startswith("nohup "):
            return MockSSHCommandResult(stdout="", command=cmd)

        # grep for READY
        if "grep -q 'READY'" in cmd:
            return MockSSHCommandResult(stdout="ready", command=cmd)

        # pkill
        if cmd.startswith("pkill -f"):
            return MockSSHCommandResult(stdout="", command=cmd)

        # rm -rf
        if cmd.startswith("rm -rf"):
            return MockSSHCommandResult(stdout="", command=cmd)

        # ls -1
        if cmd.startswith("ls -1"):
            sandboxes = "\n".join(sorted(self._sandbox_dirs)) if self._sandbox_dirs else ""
            return MockSSHCommandResult(stdout=sandboxes, command=cmd)

        # qemu-img / fallocate / dd / mkfs
        if any(x in cmd for x in ["qemu-img", "fallocate", "mkfs.ext4", "dd if=/dev/zero"]):
            return MockSSHCommandResult(stdout="", command=cmd)

        # echo payload
        if cmd.startswith("echo '") and cmd.count("'") >= 2:
            import re

            m = re.search(r"echo '(.+)' > ", cmd)
            if m:
                pass
            return MockSSHCommandResult(stdout="", command=cmd)

        # Default: treat as shell command
        return MockSSHCommandResult(
            stdout=f"mock: {cmd[:80]}",
            command=cmd,
        )

    async def upload(
        self,
        local_path: str,
        remote_path: str,
        *,
        sudo: bool = False,
        mkdir: bool = False,
    ) -> MockSSHCommandResult:
        self._files[remote_path] = f"mock upload from {local_path}"
        return MockSSHCommandResult(
            stdout=f"Uploaded {local_path} → {remote_path}",
            command=f"scp {local_path} {remote_path}",
        )

    async def download(
        self,
        remote_path: str,
        local_path: str,
    ) -> MockSSHCommandResult:
        return MockSSHCommandResult(
            stdout=f"Downloaded {remote_path} → {local_path}",
            command=f"scp {remote_path} {local_path}",
        )

    async def health_check(self) -> dict[str, Any]:
        return dict(self._capabilities)


# ---------------------------------------------------------------------------
# Mock SSH Transport
# ---------------------------------------------------------------------------


class MockSSHTransport:
    """Matches SSHTransport interface but uses MockSSHConnection."""

    _instances: dict[str, MockSSHConnection] = {}

    @classmethod
    async def connect(
        cls,
        host: SecureHost,
        *,
        timeout: float = 15.0,
        keepalive_interval: float = 15.0,
        max_retries: int = 2,
    ) -> MockSSHConnection:
        if host.id in cls._instances and cls._instances[host.id].is_alive:
            return cls._instances[host.id]

        conn = MockSSHConnection(host)
        await conn.connect(max_retries=max_retries)
        cls._instances[host.id] = conn
        return conn

    @classmethod
    async def disconnect_all(cls) -> None:
        for conn in cls._instances.values():
            await conn.disconnect()
        cls._instances.clear()


# ---------------------------------------------------------------------------
# Mock Key Deployer
# ---------------------------------------------------------------------------


class MockKeyDeployer:
    """Matches KeyDeployer interface but simulates key deployment."""

    def __init__(self, key_path: str | None = None) -> None:
        self.key_path = key_path or "/tmp/.ssh/id_ed25519"

    @property
    def public_key(self) -> str:
        return "ssh-ed25519 AAAAMockKey mock@fireagent"

    async def deploy(
        self,
        host: SecureHost,
        *,
        password: str | None = None,
    ) -> MockSSHCommandResult:
        return MockSSHCommandResult(stdout=f"Key deployed to {host.id}", command="ssh-copy-id")

    async def verify(self, host: SecureHost) -> bool:
        return True

    @staticmethod
    def generate_key(key_path: str | None = None) -> str:
        path = key_path or "/tmp/.ssh/id_ed25519"
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text("-----BEGIN MOCK KEY-----\nMOCK-PRIVATE-KEY\n-----END MOCK KEY-----")
        Path(f"{path}.pub").write_text("ssh-ed25519 AAAAMockKey mock@fireagent")
        return path
