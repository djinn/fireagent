"""Refactored MicroVMManager — manages Firecracker microVM instances.

Uses the Firecracker REST API over Unix socket (not CLI flags).
Supports both real Firecracker and MockFirecracker for CI/testing.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from .firecracker_api import FirecrackerAPI, FirecrackerNotReadyError
from .guest_channel import GuestAgentChannel, InProcessChannel
from .mock_firecracker import MockFirecrackerProcess

logger = logging.getLogger("fireagent.host.microvm")

# ---------------------------------------------------------------------------
# MicroVM instance
# ---------------------------------------------------------------------------


class MicroVMInstance:
    """Represents a running Firecracker microVM instance."""

    def __init__(
        self,
        sandbox_id: str,
        working_dir: Path,
        channel: GuestAgentChannel | None = None,
    ) -> None:
        self.sandbox_id = sandbox_id
        self.working_dir = working_dir
        self.api_socket = working_dir / "firecracker.sock"
        self.channel = channel or InProcessChannel()
        self.process: subprocess.Popen | None = None
        self.created_at = time.time()

    @property
    def is_alive(self) -> bool:
        if self.process is None:
            return False
        return self.process.poll() is None


class MicroVMManager:
    """Manages Firecracker microVM processes on this host.

    Usage::

        manager = MicroVMManager(config)
        instance = await manager.create_sandbox("sb-1", "ubuntu:24.04", ...)
        result = await manager.exec_command("sb-1", "echo hello")
        await manager.stop_sandbox("sb-1")
    """

    def __init__(self, config: dict | None = None) -> None:
        from fireagent_agent.agent import DEFAULT_CONFIG as _DC

        self.config = config or _DC.copy()
        self.workspace_dir = Path(self.config["storage"]["workspace_dir"])
        self.image_dir = Path(self.config["storage"]["image_dir"])
        self.firecracker_bin = self.config["firecracker"]["bin_path"]
        self._instances: dict[str, MicroVMInstance] = {}
        self._use_mock = not self._check_firecracker()

    @staticmethod
    def _check_firecracker() -> bool:
        """Check if the real Firecracker binary is available."""
        try:
            result = subprocess.run(
                ["which", "firecracker"],
                capture_output=True,
                text=True,
            )
            return result.returncode == 0 and result.stdout.strip()
        except FileNotFoundError:
            return False

    # ------------------------------------------------------------------
    # Create / Boot
    # ------------------------------------------------------------------
    async def create_sandbox(
        self,
        sandbox_id: str,
        image: str,
        vcpus: int,
        memory_mib: int,
        disk_mib: int,
    ) -> MicroVMInstance:
        """Launch and boot a Firecracker microVM.

        Returns the MicroVMInstance when the guest agent is responsive.
        """
        logger.info(
            "Creating microVM %s (image=%s, %d vCPU, %d MiB, %d MiB disk)",
            sandbox_id,
            image,
            vcpus,
            memory_mib,
            disk_mib,
        )

        sandbox_dir = self.workspace_dir / sandbox_id
        sandbox_dir.mkdir(parents=True, exist_ok=True)
        api_socket = sandbox_dir / "firecracker.sock"
        workspace_img = sandbox_dir / "workspace.img"

        # Create workspace volume
        if not await self._create_workspace(workspace_img, disk_mib):
            raise RuntimeError(f"Failed to create workspace volume for {sandbox_id}")

        # Locate image files
        image_path = self.image_dir / image
        kernel_path = image_path / "vmlinux"
        rootfs_path = image_path / f"{image.replace(':', '-')}.img"

        if not kernel_path.exists() and not self._use_mock:
            # Try alternate names
            kernel_path = image_path / "kernel"
        if not rootfs_path.exists() and not self._use_mock:
            rootfs_path = image_path / "rootfs.ext4"

        # Decide: real or mock?
        if self._use_mock:
            instance = await self._launch_mock(sandbox_id, sandbox_dir)
        else:
            instance = await self._launch_real(
                sandbox_id,
                sandbox_dir,
                api_socket,
                kernel_path,
                rootfs_path,
                workspace_img,
                vcpus,
                memory_mib,
            )

        self._instances[sandbox_id] = instance
        logger.info("MicroVM %s ready (%s)", sandbox_id, "mock" if self._use_mock else "real")
        return instance

    async def _create_workspace(self, path: Path, size_mib: int) -> bool:
        """Create a workspace image.

        Prefers qcow2 (copy-on-write) with mkfs.ext4 for a real filesystem,
        falling back to a sparse raw file when tools are unavailable (e.g. CI,
        macOS, minimal containers).
        """
        size_bytes = size_mib * 1024 * 1024

        # 1. Try qemu-img (qcow2) + mkfs.ext4
        if shutil.which("qemu-img"):
            try:
                result = subprocess.run(
                    ["qemu-img", "create", "-f", "qcow2", "-o", f"size={size_mib}MiB", str(path)],
                    capture_output=True,
                    text=True,
                )
                if result.returncode == 0:
                    self._mkfs(path)
                    return True
            except Exception as exc:
                logger.debug("qemu-img failed, falling back: %s", exc)

        # 2. Try creating a sparse raw file + mkfs.ext4
        if shutil.which("mkfs.ext4"):
            try:
                with open(path, "wb") as f:
                    f.truncate(size_bytes)
                self._mkfs(path)
                return True
            except Exception as exc:
                logger.debug("mkfs.ext4 failed, falling back: %s", exc)

        # 3. Fallback: pure-Python sparse raw image (no filesystem)
        #    Sufficient for mock mode and as a writable block device.
        try:
            with open(path, "wb") as f:
                f.truncate(size_bytes)
            return True
        except Exception as exc:
            logger.error("Failed to create workspace: %s", exc)
            return False

    @staticmethod
    def _mkfs(path: Path) -> None:
        """Best-effort filesystem creation on a workspace image."""
        if shutil.which("mkfs.ext4"):
            try:
                subprocess.run(["mkfs.ext4", "-F", str(path)], capture_output=True)
            except Exception:
                pass

    async def _launch_real(
        self,
        sandbox_id: str,
        sandbox_dir: Path,
        api_socket: Path,
        kernel_path: Path,
        rootfs_path: Path,
        workspace_path: Path,
        vcpus: int,
        memory_mib: int,
    ) -> MicroVMInstance:
        """Launch a real Firecracker process and configure it via REST API."""
        if not kernel_path.exists():
            raise FileNotFoundError(f"Kernel not found: {kernel_path}")
        if not rootfs_path.exists():
            raise FileNotFoundError(f"Rootfs not found: {rootfs_path}")
        if not workspace_path.exists():
            raise FileNotFoundError(f"Workspace not found: {workspace_path}")

        # Start Firecracker process (no CLI args for machine config)
        cmd = [
            self.firecracker_bin,
            "--api-sock",
            str(api_socket),
        ]

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            cwd=str(sandbox_dir),
        )

        # Wait for API socket
        api = FirecrackerAPI(api_socket)
        if not api.wait_ready(timeout=10.0):
            proc.kill()
            raise TimeoutError("Firecracker API socket did not appear")

        # Configure and boot via REST API
        try:
            api.configure_and_boot(
                kernel_path=str(kernel_path),
                rootfs_path=str(rootfs_path),
                vcpus=vcpus,
                memory_mib=memory_mib,
                workspace_path=str(workspace_path),
            )
        except Exception as exc:
            proc.kill()
            raise RuntimeError(f"Failed to configure Firecracker: {exc}")

        instance = MicroVMInstance(
            sandbox_id=sandbox_id,
            working_dir=sandbox_dir,
        )
        instance.process = proc
        return instance

    async def _launch_mock(
        self,
        sandbox_id: str,
        sandbox_dir: Path,
    ) -> MicroVMInstance:
        """Launch a mock Firecracker process for CI/testing."""
        mock = MockFirecrackerProcess(sandbox_dir)
        mock.start()
        instance = MicroVMInstance(
            sandbox_id=sandbox_id,
            working_dir=sandbox_dir,
        )
        instance.process = subprocess.Popen(["true"])  # Dummy process
        # Store mock ref for cleanup
        instance._mock = mock  # type: ignore[attr-defined]
        return instance

    # ------------------------------------------------------------------
    # Command execution
    # ------------------------------------------------------------------
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
        """Execute a command inside the microVM's guest agent."""
        instance = self._instances.get(sandbox_id)
        if instance is None:
            raise KeyError(f"Sandbox {sandbox_id} not found")

        if not instance.is_alive:
            raise RuntimeError(f"MicroVM {sandbox_id} is not running")

        return await instance.channel.execute(
            command=command,
            working_dir=working_dir,
            environment=environment,
            execution_timeout_seconds=execution_timeout_seconds,
            stdin=stdin,
        )

    async def health_check(self, sandbox_id: str) -> bool:
        """Check if the guest agent is responsive."""
        instance = self._instances.get(sandbox_id)
        if instance is None:
            return False
        return await instance.channel.health_check()

    # ------------------------------------------------------------------
    # Stop / Delete
    # ------------------------------------------------------------------
    async def stop_sandbox(self, sandbox_id: str, grace_period: int = 5) -> bool:
        """Gracefully stop a microVM."""
        instance = self._instances.pop(sandbox_id, None)
        if instance is None:
            return False

        logger.info("Stopping microVM %s", sandbox_id)

        try:
            # Try graceful shutdown via API
            api = FirecrackerAPI(instance.api_socket)
            if api.wait_ready(timeout=1.0):
                api.instance_stop()
        except Exception:
            pass

        # Terminate process
        if instance.process and instance.process.poll() is None:
            instance.process.terminate()
            try:
                instance.process.wait(timeout=grace_period)
            except subprocess.TimeoutExpired:
                instance.process.kill()
                instance.process.wait()

        # Cleanup mock
        mock = getattr(instance, "_mock", None)
        if mock:
            mock.stop()

        # Clean up working dir
        self._cleanup_sandbox(sandbox_id)
        return True

    async def delete_sandbox(self, sandbox_id: str) -> bool:
        """Delete a sandbox: stop VM and remove workspace."""
        await self.stop_sandbox(sandbox_id)
        sandbox_dir = self.workspace_dir / sandbox_id
        if sandbox_dir.exists():
            import shutil

            shutil.rmtree(sandbox_dir)
            logger.info("Deleted sandbox directory %s", sandbox_dir)
        return True

    def _cleanup_sandbox(self, sandbox_id: str) -> None:
        """Remove Firecracker socket and TAP interface."""
        sandbox_dir = self.workspace_dir / sandbox_id
        socket_file = sandbox_dir / "firecracker.sock"
        if socket_file.exists():
            try:
                socket_file.unlink()
            except Exception:
                pass
        # Remove TAP interface (best-effort; may not have permissions or `ip` binary)
        tap_name = f"tap-{sandbox_id[:12]}"
        try:
            subprocess.run(
                ["ip", "link", "delete", tap_name],
                capture_output=True,
                timeout=5,
            )
        except (FileNotFoundError, PermissionError, subprocess.TimeoutExpired):
            pass

    # ------------------------------------------------------------------
    # Info
    # ------------------------------------------------------------------
    @property
    def active_sandbox_count(self) -> int:
        return len(self._instances)

    def get_instance(self, sandbox_id: str) -> MicroVMInstance | None:
        return self._instances.get(sandbox_id)

    def is_mock_mode(self) -> bool:
        return self._use_mock

    async def stop_all(self) -> None:
        """Stop all running microVMs."""
        for sandbox_id in list(self._instances.keys()):
            await self.stop_sandbox(sandbox_id)
