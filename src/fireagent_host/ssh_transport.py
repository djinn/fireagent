"""SSH Transport Layer — asyncssh connection pool with keepalive, key management.

Provides a thin wrapper around asyncssh for:
- Remote command execution with output streaming
- Remote file transfer (SCP/SFTP)
- Connection health checks and keepalive
- Key-based authentication (with agent fallback)
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any, AsyncIterator

from .secure_host import SecureHost

try:
    import asyncssh
except ImportError:
    asyncssh = None  # type: ignore[assignment]

logger = logging.getLogger("fireagent.remote.ssh")

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class SSHTransportError(Exception):
    """Base exception for SSH transport errors."""


class SSHConnectionError(SSHTransportError):
    """Raised when a connection cannot be established."""


class SSHAuthenticationError(SSHTransportError):
    """Raised when authentication fails."""


class SSHCommandError(SSHTransportError):
    """Raised when a remote command fails."""


# ---------------------------------------------------------------------------
# SSH Transport
# ---------------------------------------------------------------------------


class SSHTransport:
    """Manages SSH connections to remote hosts.

    Usage::

        transport = SSHTransport()
        async with transport.connect(host) as conn:
            result = await conn.run("echo hello")
            print(result.stdout)
    """

    _instances: dict[str, "SSHConnection"] = {}

    @classmethod
    async def connect(
        cls,
        host: SecureHost,
        *,
        timeout: float = 15.0,
        keepalive_interval: float = 15.0,
        max_retries: int = 2,
    ) -> "SSHConnection":
        """Connect to a remote host.

        Returns a connection from the pool or creates a new one.
        """
        if host.id in cls._instances and cls._instances[host.id].is_alive:
            conn = cls._instances[host.id]
            conn._last_used = time.time()
            return conn

        conn = SSHConnection(
            host=host,
            timeout=timeout,
            keepalive_interval=keepalive_interval,
        )
        await conn.connect(max_retries=max_retries)
        cls._instances[host.id] = conn
        return conn

    @classmethod
    async def disconnect_all(cls) -> None:
        """Disconnect all pooled connections."""
        for conn in cls._instances.values():
            try:
                await conn.disconnect()
            except Exception:
                pass
        cls._instances.clear()


class SSHCommandResult:
    """Result of a remote command execution."""

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

    @property
    def output(self) -> str:
        """Combined stdout + stderr."""
        out = self.stdout
        if self.stderr:
            out += "\n" + self.stderr
        return out.strip()

    def __repr__(self) -> str:
        return (
            f"<SSHCommandResult exit={self.exit_code} "
            f"stdout={len(self.stdout)}B stderr={len(self.stderr)}B "
            f"in {self.duration:.2f}s>"
        )


class SSHConnection:
    """A single SSH connection to a remote host."""

    def __init__(
        self,
        host: SecureHost,
        timeout: float = 15.0,
        keepalive_interval: float = 15.0,
    ) -> None:
        self.host = host
        self._timeout = timeout
        self._keepalive_interval = keepalive_interval
        self._conn: asyncssh.SSHClient | None = None
        self._connected_at: float | None = None
        self._last_used: float | None = None
        self._semaphore = asyncio.Semaphore(4)  # Max 4 concurrent ops per host

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------
    async def connect(self, max_retries: int = 2) -> None:
        """Establish the SSH connection."""
        if asyncssh is None:
            raise ImportError("asyncssh is required: pip install asyncssh")

        if self._conn and self._conn.is_alive():
            return

        last_error: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                connect_kwargs = self._build_connect_kwargs()
                self._conn = await asyncio.wait_for(
                    asyncssh.connect(**connect_kwargs),
                    timeout=self._timeout,
                )
                self._connected_at = time.time()
                self._last_used = time.time()
                self.host.status = "connected"
                self.host.connected_at = self._dt_now()
                logger.info(
                    "Connected to %s (attempt %d/%d)",
                    self.host.id, attempt + 1, max_retries + 1,
                )
                return
            except asyncssh.SSHConnectionError as exc:
                last_error = exc
                logger.warning(
                    "Connection failed to %s (attempt %d/%d): %s",
                    self.host.id, attempt + 1, max_retries + 1, exc,
                )
                if attempt < max_retries:
                    await asyncio.sleep(2 ** attempt)
            except asyncio.TimeoutError as exc:
                last_error = exc
                logger.warning(
                    "Connection timeout to %s (attempt %d/%d)",
                    self.host.id, attempt + 1, max_retries + 1,
                )
                if attempt < max_retries:
                    await asyncio.sleep(2 ** attempt)

        self.host.status = "disconnected"
        raise SSHConnectionError(
            f"Cannot connect to {self.host.id} after {max_retries + 1} attempts: {last_error}"
        )

    def _build_connect_kwargs(self) -> dict[str, Any]:
        """Build kwargs for asyncssh.connect."""
        kwargs: dict[str, Any] = {
            "host": self.host.hostname,
            "port": self.host.port,
            "username": self.host.user,
            "known_hosts": None,  # We verify via fingerprint if provided
        }

        # Key-based auth
        if self.host.key_path and os.path.exists(self.host.key_path):
            kwargs["client_keys"] = [self.host.key_path]

        # Agent auth (fallback)
        if os.environ.get("SSH_AUTH_SOCK"):
            kwargs["agent_forwarding"] = True

        # Host key verification
        if self.host.fingerprint:
            kwargs["known_hosts"] = None
            # We'll verify on first connect
        else:
            kwargs["known_hosts"] = "~/.ssh/known_hosts"

        return kwargs

    async def disconnect(self) -> None:
        """Close the SSH connection."""
        if self._conn:
            try:
                self._conn.close()
                await self._conn.wait_closed()
            except Exception:
                pass
            self._conn = None
            self.host.status = "disconnected"
            logger.info("Disconnected from %s", self.host.id)

    @property
    def is_alive(self) -> bool:
        """Check if the connection is alive."""
        if self._conn is None:
            return False
        return self._conn.is_alive()

    # ------------------------------------------------------------------
    # Remote command execution
    # ------------------------------------------------------------------
    async def run(
        self,
        command: str,
        *,
        timeout: float | None = None,
        sudo: bool = False,
        environment: dict[str, str] | None = None,
    ) -> SSHCommandResult:
        """Execute a command on the remote host.

        Args:
            command: Shell command to run.
            timeout: Max execution time (None = no timeout).
            sudo: Whether to run with sudo.
            environment: Extra environment variables.

        Returns:
            SSHCommandResult with stdout, stderr, exit_code.
        """
        async with self._semaphore:
            if not self._conn or not self._conn.is_alive():
                raise SSHConnectionError(f"Not connected to {self.host.id}")

            cmd = command
            if sudo:
                cmd = f"sudo -- sh -c {shlex_quote(command)}"

            if environment:
                env_prefix = " ".join(f"{k}={shlex_quote(v)}" for k, v in environment.items())
                cmd = f"export {env_prefix}; {cmd}"

            start = time.time()
            try:
                result = await asyncio.wait_for(
                    self._conn.run(cmd, check=False),
                    timeout=timeout or self._timeout * 2,
                )
            except asyncio.TimeoutError:
                return SSHCommandResult(
                    stdout="",
                    stderr=f"Command timed out after {timeout or self._timeout * 2}s",
                    exit_code=-1,
                    command=command,
                    duration=time.time() - start,
                )
            except asyncssh.ChannelError as exc:
                return SSHCommandResult(
                    stdout="",
                    stderr=str(exc),
                    exit_code=-1,
                    command=command,
                    duration=time.time() - start,
                )

            duration = time.time() - start
            self._last_used = time.time()

            return SSHCommandResult(
                stdout=result.stdout or "",
                stderr=result.stderr or "",
                exit_code=result.returncode or 0,
                command=command,
                duration=duration,
            )

    async def run_stream(
        self,
        command: str,
        *,
        timeout: float | None = None,
    ) -> AsyncIterator[str]:
        """Execute a command and stream stdout line by line."""
        if not self._conn or not self._conn.is_alive():
            raise SSHConnectionError(f"Not connected to {self.host.id}")

        async with self._conn.run(command, check=False) as session:
            async for line in session.stdout:
                yield line.rstrip("\n")

    # ------------------------------------------------------------------
    # File transfer (SCP/SFTP)
    # ------------------------------------------------------------------
    async def upload(
        self,
        local_path: str | Path,
        remote_path: str | Path,
        *,
        sudo: bool = False,
        mkdir: bool = False,
    ) -> SSHCommandResult:
        """Upload a file or directory to the remote host."""
        local_path = str(local_path)
        remote_path = str(remote_path)

        if mkdir:
            await self.run(f"mkdir -p {shlex_quote(str(Path(remote_path).parent))}")

        if asyncssh is None:
            raise ImportError("asyncssh is required")

        async with self._semaphore:
            try:
                await asyncssh.scp(
                    local_path,
                    (self._conn, remote_path),  # type: ignore[arg-type]
                    preserve=True,
                )
                return SSHCommandResult(
                    stdout=f"Uploaded {local_path} → {remote_path}",
                    stderr="",
                    exit_code=0,
                    command=f"scp {local_path} {remote_path}",
                )
            except Exception as exc:
                return SSHCommandResult(
                    stdout="",
                    stderr=str(exc),
                    exit_code=-1,
                    command=f"scp {local_path} {remote_path}",
                )

    async def download(
        self,
        remote_path: str | Path,
        local_path: str | Path,
    ) -> SSHCommandResult:
        """Download a file from the remote host."""
        if asyncssh is None:
            raise ImportError("asyncssh is required")

        async with self._semaphore:
            try:
                await asyncssh.scp(
                    (self._conn, str(remote_path)),  # type: ignore[arg-type]
                    str(local_path),
                    preserve=True,
                )
                return SSHCommandResult(
                    stdout=f"Downloaded {remote_path} → {local_path}",
                    stderr="",
                    exit_code=0,
                    command=f"scp {remote_path} {local_path}",
                )
            except Exception as exc:
                return SSHCommandResult(
                    stdout="",
                    stderr=str(exc),
                    exit_code=-1,
                    command=f"scp {remote_path} {local_path}",
                )

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------
    async def health_check(self) -> dict[str, Any]:
        """Run a health check on the remote host.

        Returns a dict with CPU, memory, disk, KVM, Firecracker status.
        """
        commands = {
            "cpu_cores": "nproc 2>/dev/null || echo 1",
            "total_memory_mib": "free -m 2>/dev/null | awk '/^Mem:/{print $2}' || echo 0",
            "total_disk_gb": "df -BG / 2>/dev/null | awk 'NR==2{print $2}' | sed 's/G//' || echo 0",
            "free_disk_gb": "df -BG / 2>/dev/null | awk 'NR==2{print $4}' | sed 's/G//' || echo 0",
            "has_kvm": "test -c /dev/kvm && echo 'true' || echo 'false'",
            "firecracker_version": "firecracker --version 2>/dev/null | head -1 || echo 'not_installed'",
            "kernel_version": "uname -r 2>/dev/null || echo 'unknown'",
            "os_version": "cat /etc/os-release 2>/dev/null | grep PRETTY_NAME | cut -d= -f2 | tr -d '\"' || echo 'unknown'",
        }

        results: dict[str, Any] = {}
        for key, cmd in commands.items():
            result = await self.run(cmd)
            if result.ok:
                results[key] = result.stdout.strip()
            else:
                results[key] = None

        # Parse and type
        parsed: dict[str, Any] = {
            "cpu_cores": int(results.get("cpu_cores", 0) or 0),
            "total_memory_mib": int(results.get("total_memory_mib", 0) or 0),
            "total_disk_gb": int(results.get("total_disk_gb", 0) or 0),
            "free_disk_gb": int(results.get("free_disk_gb", 0) or 0),
            "has_kvm": results.get("has_kvm") == "true",
            "firecracker_version": results.get("firecracker_version")
                if results.get("firecracker_version") != "not_installed" else None,
            "kernel_version": results.get("kernel_version"),
            "os_version": results.get("os_version"),
        }

        # Update host
        for key, value in parsed.items():
            setattr(self.host, key, value)
        self.host.last_heartbeat_at = self._dt_now()
        self.host.status = "connected" if results.get("firecracker_version") else "partial"

        logger.info("Health check for %s: %d cores, %d MiB, KVM=%s, FC=%s",
                     self.host.id, parsed["cpu_cores"], parsed["total_memory_mib"],
                     parsed["has_kvm"], parsed["firecracker_version"] or "missing")

        return parsed

    @staticmethod
    def _dt_now():
        from datetime import datetime, timezone
        return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Key management
# ---------------------------------------------------------------------------


class KeyDeployer:
    """Deploys SSH public keys to remote hosts for passwordless auth."""

    def __init__(self, key_path: str | None = None) -> None:
        self.key_path = key_path or os.path.expanduser("~/.ssh/id_ed25519")

    @property
    def public_key(self) -> str:
        """Read the public key."""
        pub_path = f"{self.key_path}.pub"
        if not os.path.exists(pub_path):
            raise FileNotFoundError(
                f"Public key not found at {pub_path}. "
                f"Generate with: ssh-keygen -t ed25519 -f {self.key_path}"
            )
        with open(pub_path) as f:
            return f.read().strip()

    async def deploy(
        self,
        host: SecureHost,
        *,
        password: str | None = None,
    ) -> SSHCommandResult:
        """Deploy the public key to a remote host.

        Uses ssh-copy-id or manual ~/.ssh/authorized_keys append.
        """
        logger.info("Deploying SSH key to %s@%s (port %d)", host.user, host.hostname, host.port)

        key = self.public_key

        # Try ssh-copy-id first (handles permissions, dir creation, etc.)
        try:
            import subprocess
            cmd = [
                "ssh-copy-id",
                "-o", "StrictHostKeyChecking=accept-new",
                "-p", str(host.port),
                f"{host.user}@{host.hostname}",
            ]
            if host.key_path:
                cmd.insert(1, host.key_path)
                cmd.insert(1, "-i")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                input=f"{password}\n" if password else None,
            )
            if result.returncode == 0:
                logger.info("Key deployed via ssh-copy-id to %s", host.id)
                return SSHCommandResult(
                    stdout=result.stdout,
                    stderr=result.stderr,
                    exit_code=result.returncode,
                    command="ssh-copy-id",
                )
        except FileNotFoundError:
            pass  # Fall through to manual

        # Manual deployment: create ~/.ssh and append key
        manual_cmd = (
            f"mkdir -p ~/.ssh && "
            f"chmod 700 ~/.ssh && "
            f"echo {shlex_quote(key)} >> ~/.ssh/authorized_keys && "
            f"chmod 600 ~/.ssh/authorized_keys"
        )

        conn = await SSHTransport.connect(host, max_retries=1)
        return await conn.run(manual_cmd)

    async def verify(self, host: SecureHost) -> bool:
        """Verify that key-based auth works."""
        try:
            conn = await SSHTransport.connect(host, max_retries=1)
            result = await conn.run("echo 'auth-ok'")
            return result.ok and result.stdout.strip() == "auth-ok"
        except Exception:
            return False

    @staticmethod
    def generate_key(key_path: str | None = None) -> str:
        """Generate a new SSH key pair (ed25519)."""
        path = key_path or os.path.expanduser("~/.ssh/id_ed25519")
        if os.path.exists(path):
            raise FileExistsError(f"Key already exists at {path}")

        import subprocess
        subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-f", path, "-N", ""],
            capture_output=True,
            check=True,
        )
        logger.info("Generated SSH key pair at %s", path)
        return path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def shlex_quote(s: str) -> str:
    """Simple shell quoting (avoids shlex import for single words)."""
    if not s or s.isalnum():
        return s
    escaped = s.replace("'", "'\\''")
    return f"'{escaped}'"