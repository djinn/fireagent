"""Operator SDK — govern remote worker hosts from code.

High-level API for managing remote hosts, deploying SSH keys,
creating sandboxes, and monitoring capacity.

Usage::

    operator = Operator()
    host = operator.add_host("worker-01.example.com")
    operator.deploy_keys(host.id)
    sb = operator.create_sandbox(host.id, "sb-abc", "ubuntu:24.04", 2, 1024, 2048)
    result = operator.exec_command(host.id, "sb-abc", "echo hello")
    health = operator.host_health(host.id)
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .secure_host import SecureHost
from .registry import HostRegistry

logger = logging.getLogger("fireagent.remote.operator")

# ---------------------------------------------------------------------------
# Lazy imports (allow mock mode without asyncssh)
# ---------------------------------------------------------------------------

_ssh_transport = None
_remote_manager = None
_key_deployer = None
_mock_ssh = None


def _import_ssh():
    global _ssh_transport, _remote_manager, _key_deployer
    from . import ssh_transport as _st
    from . import remote_manager as _rm

    _ssh_transport = _st
    _remote_manager = _rm
    _key_deployer = _st.KeyDeployer


def _import_mock():
    global _mock_ssh
    from . import mock_ssh as _ms

    _mock_ssh = _ms


# ---------------------------------------------------------------------------
# Operator
# ---------------------------------------------------------------------------


class Operator:
    """Govern remote worker hosts.

    The Operator is the primary interface for adding, removing, inspecting,
    and managing remote Firecracker hosts.

    Modes:
        - auto:  Real SSH if asyncssh installed, mock otherwise
        - real:  Forces real SSH (raises ImportError if missing)
        - mock:  Forces mock transport (for CI/testing)
    """

    def __init__(
        self,
        mode: str = "auto",
        registry_path: str | Path | None = None,
    ) -> None:
        if mode not in ("auto", "real", "mock"):
            raise ValueError(f"Invalid mode: {mode!r}")

        self._mode = mode
        self._use_mock = self._resolve_mock(mode)
        self._registry = HostRegistry(path=registry_path)
        self._managers: dict[str, Any] = {}

        if not self._use_mock:
            _import_ssh()

        logger.info(
            "Operator initialized (mode=%s, mock=%s, hosts=%d)",
            mode,
            self._use_mock,
            self._registry.count,
        )

    @staticmethod
    def _resolve_mock(mode: str) -> bool:
        if mode == "mock":
            return True
        if mode == "real":
            return False
        # auto: mock if asyncssh missing
        try:
            import asyncssh  # noqa: F401

            return False
        except ImportError:
            return True

    @property
    def is_mock(self) -> bool:
        return self._use_mock

    # ------------------------------------------------------------------
    # Host management
    # ------------------------------------------------------------------

    def add_host(
        self,
        hostname: str,
        *,
        port: int = 22,
        user: str = "fireagent",
        key_path: str | None = None,
        label: str | None = None,
        fingerprint: str | None = None,
        tags: dict[str, str] | None = None,
        deploy_key: bool = False,
    ) -> SecureHost:
        """Add a remote host to the registry."""
        host = SecureHost(
            hostname=hostname,
            port=port,
            user=user,
            key_path=key_path,
            label=label,
            fingerprint=fingerprint,
            tags=tags or {},
            status="registered",
        )
        self._registry.add(host)
        logger.info("Host added: %s (%s)", host.id, host.display_name)
        if deploy_key:
            self.deploy_keys(host.id)
        return host

    def remove_host(self, host_id: str) -> bool:
        """Remove a host from the registry."""
        if host_id in self._managers:
            try:
                self._run_async(self._managers[host_id].disconnect())
            except Exception:
                pass
            del self._managers[host_id]
        return self._registry.remove(host_id)

    def list_hosts(self, status: str | None = None) -> list[SecureHost]:
        """List registered hosts, optionally filtered by status."""
        return self._registry.list(status=status)

    def get_host(self, host_id: str) -> SecureHost | None:
        return self._registry.get(host_id)

    # ------------------------------------------------------------------
    # SSH key management
    # ------------------------------------------------------------------

    def deploy_keys(
        self,
        host_id: str,
        *,
        key_path: str | None = None,
        password: str | None = None,
    ) -> dict[str, Any]:
        """Deploy SSH public key to a remote host."""
        host = self._registry.get(host_id)
        if host is None:
            raise KeyError(f"Host not found: {host_id}")

        if self._use_mock:
            _import_mock()
            deployer = _mock_ssh.MockKeyDeployer(key_path)
        else:
            deployer = _key_deployer(key_path)

        pubkey = deployer.public_key
        result = self._run_async(deployer.deploy(host, password=password))
        if key_path:
            host.key_path = key_path
            self._registry.add(host)
        verified = self._run_async(deployer.verify(host))

        return {
            "host_id": host_id,
            "key": pubkey,
            "verified": verified,
            "result": result.stdout if hasattr(result, "stdout") else str(result),
        }

    def generate_key(self, key_path: str | None = None) -> str:
        """Generate a new SSH key pair (ed25519)."""
        if self._use_mock:
            _import_mock()
            return _mock_ssh.MockKeyDeployer.generate_key(key_path)
        return _key_deployer.generate_key(key_path)

    # ------------------------------------------------------------------
    # Host health & discovery
    # ------------------------------------------------------------------

    def host_health(self, host_id: str) -> dict[str, Any]:
        """Run a comprehensive health check on a remote host."""
        host = self._registry.get(host_id)
        if host is None:
            raise KeyError(f"Host not found: {host_id}")

        if self._use_mock:
            _import_mock()
            conn = _mock_ssh.MockSSHConnection(host)
            self._run_async(conn.connect())
            capabilities = self._run_async(conn.health_check())
        else:
            conn = self._run_async(_ssh_transport.SSHTransport.connect(host))
            capabilities = self._run_async(conn.health_check())
            self._run_async(conn.disconnect())

        # Update host
        for key in [
            "cpu_cores",
            "total_memory_mib",
            "total_disk_gb",
            "free_disk_gb",
            "has_kvm",
            "firecracker_version",
            "kernel_version",
            "os_version",
        ]:
            if key in capabilities:
                setattr(host, key, capabilities[key])
        host.last_heartbeat_at = datetime.now(timezone.utc)
        host.status = "connected" if capabilities.get("firecracker_version") else "partial"
        self._registry.add(host)

        return {
            "host_id": host_id,
            "hostname": host.hostname,
            "status": host.status,
            **capabilities,
        }

    def health_all(self) -> list[dict[str, Any]]:
        """Run health checks on all registered hosts."""
        return [self.host_health(h.id) for h in self._registry.list()]

    def discover_hosts(
        self,
        *,
        cidr: str | None = None,
        port: int = 22,
        user: str = "fireagent",
        timeout: float = 3.0,
        max_workers: int = 20,
    ) -> list[SecureHost]:
        """Discover Firecracker hosts on the network."""
        if cidr is None:
            cidr = self._detect_local_network()
            if cidr is None:
                raise ValueError("Cannot auto-detect network. Specify a CIDR range.")

        import ipaddress
        import concurrent.futures
        import socket as _socket

        network = ipaddress.IPv4Network(cidr, strict=False)
        logger.info("Discovering hosts on %s...", cidr)
        discovered: list[SecureHost] = []

        def scan(ip: str) -> SecureHost | None:
            s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
            s.settimeout(timeout)
            result = s.connect_ex((str(ip), port))
            s.close()
            if result != 0:
                return None
            return SecureHost(hostname=str(ip), port=port, user=user, label=f"discovered-{ip}")

        hosts_to_scan = list(network.hosts())[:254]
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
            for result in pool.map(scan, hosts_to_scan):
                if result is not None:
                    if not self._registry.get(result.id):
                        self._registry.add(result)
                        discovered.append(result)

        logger.info("Discovery: %d hosts found", len(discovered))
        return discovered

    @staticmethod
    def _detect_local_network() -> str | None:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            return ".".join(local_ip.split(".")[:3]) + ".0/24"
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Remote sandbox operations
    # ------------------------------------------------------------------

    def _get_manager(self, host: SecureHost) -> Any:
        if host.id not in self._managers:
            if self._use_mock:
                _import_mock()
                from .remote_manager import RemoteMicroVMManager

                m = RemoteMicroVMManager(host)
                # Inject mock connection
                conn = _mock_ssh.MockSSHConnection(host)
                self._run_async(conn.connect())
                m._conn = conn
                self._managers[host.id] = m
            else:
                from .remote_manager import RemoteMicroVMManager

                m = RemoteMicroVMManager(host)
                self._managers[host.id] = m
        return self._managers[host.id]

    async def _connect_manager(self, host_id: str) -> Any:
        host = self._registry.get(host_id)
        if host is None:
            raise KeyError(f"Host not found: {host_id}")
        manager = self._get_manager(host)
        if not self._use_mock:
            await manager.connect(max_retries=1)
        return manager

    @staticmethod
    def _run_async(coro):
        """Run an async coroutine, safely handling existing event loops."""
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(asyncio.run, coro)
                    return future.result()
        except RuntimeError:
            pass
        return asyncio.run(coro)

    def create_sandbox(
        self,
        host_id: str,
        sandbox_id: str,
        image: str,
        vcpus: int,
        memory_mib: int,
        disk_mib: int,
    ) -> dict[str, Any]:
        """Create a sandbox on a remote host."""
        return self._run_async(
            self._create_sandbox_async(
                host_id,
                sandbox_id,
                image,
                vcpus,
                memory_mib,
                disk_mib,
            )
        )

    async def _create_sandbox_async(
        self,
        host_id,
        sandbox_id,
        image,
        vcpus,
        memory_mib,
        disk_mib,
    ) -> dict[str, Any]:
        manager = await self._connect_manager(host_id)
        return await manager.create_sandbox(
            sandbox_id=sandbox_id,
            image=image,
            vcpus=vcpus,
            memory_mib=memory_mib,
            disk_mib=disk_mib,
        )

    def exec_command(
        self,
        host_id: str,
        sandbox_id: str,
        command: str,
        *,
        working_dir=None,
        environment=None,
        execution_timeout_seconds=None,
        stdin=None,
    ) -> dict[str, Any]:
        """Execute a command in a sandbox on a remote host."""
        return self._run_async(
            self._exec_command_async(
                host_id,
                sandbox_id,
                command,
                working_dir=working_dir,
                environment=environment,
                execution_timeout_seconds=execution_timeout_seconds,
                stdin=stdin,
            )
        )

    async def _exec_command_async(self, host_id, sandbox_id, command, **kw):
        manager = await self._connect_manager(host_id)
        return await manager.exec_command(sandbox_id=sandbox_id, command=command, **kw)

    def stop_sandbox(self, host_id: str, sandbox_id: str) -> bool:
        return self._run_async(self._stop_sandbox_async(host_id, sandbox_id))

    async def _stop_sandbox_async(self, host_id, sandbox_id):
        manager = await self._connect_manager(host_id)
        return await manager.stop_sandbox(sandbox_id)

    def delete_sandbox(self, host_id: str, sandbox_id: str) -> bool:
        return self._run_async(self._delete_sandbox_async(host_id, sandbox_id))

    async def _delete_sandbox_async(self, host_id, sandbox_id):
        manager = await self._connect_manager(host_id)
        return await manager.delete_sandbox(sandbox_id)

    def list_sandboxes(self, host_id: str) -> list[dict[str, Any]]:
        return self._run_async(self._list_sandboxes_async(host_id))

    async def _list_sandboxes_async(self, host_id):
        manager = await self._connect_manager(host_id)
        return await manager.list_sandboxes()

    def get_resource_usage(self, host_id: str) -> dict[str, Any]:
        return self._run_async(self._resource_usage_async(host_id))

    async def _resource_usage_async(self, host_id):
        manager = await self._connect_manager(host_id)
        return await manager.get_resource_usage()
