"""Fireagent Host Agent — manages Firecracker microVMs on a worker host."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger("fireagent.agent")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DEFAULT_CONFIG: dict[str, Any] = {
    "agent": {
        "host_id": "host-01",
        "control_plane_url": "http://127.0.0.1:8000",
        "heartbeat_interval": 10,
        "log_level": "info",
    },
    "storage": {
        "workspace_dir": "/var/fireagent/sandboxes",
        "image_dir": "/artifacts/images",
    },
    "firecracker": {
        "bin_path": "/usr/bin/firecracker",
        "jailer_path": "/usr/bin/firejail",
    },
    "cgroups": {
        "cpu_shares": 1024,
        "memory_limit_gb": 2,
    },
    "security": {
        "run_as_user": "fireagent",
    },
}


# ---------------------------------------------------------------------------
# MicroVM Manager
# ---------------------------------------------------------------------------
class MicroVMManager:
    """Manages Firecracker microVM processes on this host."""

    def __init__(self, config: dict) -> None:
        self.config = config
        self.workspace_dir = Path(config["storage"]["workspace_dir"])
        self.image_dir = Path(config["storage"]["image_dir"])
        self._processes: dict[str, subprocess.Popen] = {}

    def create_sandbox(
        self,
        sandbox_id: str,
        image: str,
        vcpus: int,
        memory_mib: int,
        disk_mib: int,
    ) -> bool:
        """Launch a Firecracker microVM for the given sandbox."""
        logger.info(
            "Creating sandbox %s (image=%s, vcpus=%d, memory=%dMiB, disk=%dMiB)",
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

        # Create a workspace volume
        size_bytes = disk_mib * 1024 * 1024
        try:
            if shutil.which("qemu-img"):
                subprocess.run(
                    [
                        "qemu-img",
                        "create",
                        "-f",
                        "qcow2",
                        "-o",
                        f"size={disk_mib}MiB",
                        str(workspace_img),
                    ],
                    check=True,
                    capture_output=True,
                )
            else:
                # Fallback: sparse raw file (works on CI, macOS, minimal hosts)
                with open(workspace_img, "wb") as f:
                    f.truncate(size_bytes)
        except (subprocess.CalledProcessError, OSError) as exc:
            logger.error("Failed to create workspace image for %s: %s", sandbox_id, exc)
            return False

        # Locate guest image
        image_path = self.image_dir / image
        kernel_path = image_path / "kernel"
        rootfs_path = image_path / "rootfs.ext4"

        if not kernel_path.exists():
            logger.error("Kernel not found for image %s at %s", image, kernel_path)
            return False
        if not rootfs_path.exists():
            logger.error("Root filesystem not found for image %s at %s", image, rootfs_path)
            return False

        # Launch Firecracker
        cmd = [
            self.config["firecracker"]["bin_path"],
            "--api-sock",
            str(api_socket),
            "--kernel",
            str(kernel_path),
            "--rootfs",
            str(rootfs_path),
            "--vcpus",
            str(vcpus),
            "--mem",
            str(memory_mib),
            "--drives",
            f"{str(workspace_img)}:rw",
        ]

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                cwd=str(sandbox_dir),
            )
            self._processes[sandbox_id] = proc
            logger.info("Firecracker process started for sandbox %s (PID=%d)", sandbox_id, proc.pid)
            return True
        except FileNotFoundError:
            logger.error(
                "Firecracker binary not found at %s", self.config["firecracker"]["bin_path"]
            )
            return False
        except Exception as exc:
            logger.error("Failed to launch Firecracker for %s: %s", sandbox_id, exc)
            return False

    def stop_sandbox(self, sandbox_id: str, grace_period: int = 5) -> bool:
        """Gracefully stop a microVM."""
        proc = self._processes.get(sandbox_id)
        if proc is None:
            logger.warning("No process found for sandbox %s", sandbox_id)
            return False

        logger.info("Stopping sandbox %s (PID=%d)", sandbox_id, proc.pid)

        # Try SIGTERM first
        proc.terminate()
        try:
            proc.wait(timeout=grace_period)
        except subprocess.TimeoutExpired:
            logger.warning("Graceful stop timed out for %s, sending SIGKILL", sandbox_id)
            proc.kill()
            proc.wait()

        self._processes.pop(sandbox_id, None)
        self._cleanup_sandbox(sandbox_id)
        return True

    def delete_sandbox(self, sandbox_id: str) -> bool:
        """Delete a sandbox and its workspace."""
        self.stop_sandbox(sandbox_id)
        sandbox_dir = self.workspace_dir / sandbox_id
        if sandbox_dir.exists():
            import shutil

            shutil.rmtree(sandbox_dir)
            logger.info("Deleted sandbox directory %s", sandbox_dir)
        return True

    def _cleanup_sandbox(self, sandbox_id: str) -> None:
        """Remove Firecracker socket and temporary files."""
        sandbox_dir = self.workspace_dir / sandbox_id
        socket_file = sandbox_dir / "firecracker.sock"
        if socket_file.exists():
            socket_file.unlink()
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

    def get_process(self, sandbox_id: str) -> subprocess.Popen | None:
        return self._processes.get(sandbox_id)

    @property
    def active_sandbox_count(self) -> int:
        return len(self._processes)

    def cleanup_orphans(self) -> None:
        """On startup, clean up any orphaned Firecracker processes."""
        logger.info("Checking for orphaned Firecracker processes...")
        try:
            result = subprocess.run(
                ["pgrep", "-x", "firecracker"],
                capture_output=True,
                text=True,
            )
            if result.stdout.strip():
                pids = result.stdout.strip().split()
                logger.warning("Found %d orphaned Firecracker processes: %s", len(pids), pids)
                for pid in pids:
                    os.kill(int(pid), signal.SIGKILL)
        except (subprocess.CalledProcessError, ProcessLookupError):
            pass


# ---------------------------------------------------------------------------
# Host Agent
# ---------------------------------------------------------------------------
class HostAgent:
    """Main host agent daemon that manages microVMs and reports to control plane."""

    def __init__(self, config: dict | None = None) -> None:
        self.config = config or DEFAULT_CONFIG
        self.vm_manager = MicroVMManager(self.config)
        self._running = False

        logging_level = self.config["agent"].get("log_level", "info").upper()
        logging.basicConfig(
            level=getattr(logging, logging_level, logging.INFO),
            format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        )

    async def run(self) -> None:
        """Start the host agent loop."""
        self._running = True
        host_id = self.config["agent"]["host_id"]
        control_plane = self.config["agent"]["control_plane_url"]

        logger.info("Starting host agent %s (control plane: %s)", host_id, control_plane)

        # Register with control plane
        await self._register()

        # Main loop: heartbeat and health checks
        while self._running:
            try:
                await self._heartbeat()
            except Exception as exc:
                logger.error("Heartbeat failed: %s", exc)

            await asyncio.sleep(self.config["agent"]["heartbeat_interval"])

    async def stop(self) -> None:
        """Graceful shutdown."""
        logger.info("Shutting down host agent...")
        self._running = False

        # Stop all sandboxes
        for sandbox_id in list(self.vm_manager._processes.keys()):
            self.vm_manager.stop_sandbox(sandbox_id)

    async def _register(self) -> None:
        """POST /v1/hosts to register with control plane."""
        import httpx

        host_id = self.config["agent"]["host_id"]
        payload = {
            "host_id": host_id,
            "cpu_cores": os.cpu_count() or 1,
            "total_memory_mib": self._get_total_memory(),
            "total_disk_gb": self._get_disk_space(),
            "free_disk_gb": self._get_free_disk(),
            "version": "0.1.0",
        }

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{self.config['agent']['control_plane_url']}/v1/hosts",
                    json=payload,
                    timeout=5,
                )
                if resp.is_success:
                    logger.info("Registered with control plane as %s", host_id)
                else:
                    logger.warning("Registration failed: HTTP %d", resp.status_code)
        except Exception as exc:
            logger.error("Registration error: %s", exc)

    async def _heartbeat(self) -> None:
        """PUT /v1/hosts/{host_id}/heartbeat."""
        import httpx

        host_id = self.config["agent"]["host_id"]
        payload = {
            "cpu_usage_percent": self._get_cpu_usage(),
            "memory_usage_percent": self._get_memory_usage(),
            "active_sandbox_count": self.vm_manager.active_sandbox_count,
            "failed_sandbox_count": 0,
            "uptime_seconds": int(time.time()),
            "error_count": 0,
        }

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.put(
                    f"{self.config['agent']['control_plane_url']}/v1/hosts/{host_id}/heartbeat",
                    json=payload,
                    timeout=5,
                )
                if not resp.is_success:
                    logger.warning("Heartbeat returned HTTP %d", resp.status_code)
        except Exception as exc:
            logger.error("Heartbeat request failed: %s", exc)

    @staticmethod
    def _get_total_memory() -> int:
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        return int(line.split()[1]) // 1024  # KiB → MiB
        except OSError:
            pass
        return 4096

    @staticmethod
    def _get_memory_usage() -> float:
        try:
            with open("/proc/meminfo") as f:
                total = 0
                available = 0
                for line in f:
                    if line.startswith("MemTotal:"):
                        total = int(line.split()[1])
                    elif line.startswith("MemAvailable:"):
                        available = int(line.split()[1])
                if total:
                    return 100.0 * (1.0 - available / total)
        except OSError:
            pass
        return 0.0

    @staticmethod
    def _get_cpu_usage() -> float:
        try:
            import psutil

            return psutil.cpu_percent(interval=0.5)
        except ImportError:
            return 0.0

    @staticmethod
    def _get_disk_space() -> int:
        try:
            stat = os.statvfs("/")
            return stat.f_blocks * stat.f_frsize // (1024**3)
        except (OSError, AttributeError):
            try:
                import shutil

                return shutil.disk_usage("/").total // (1024**3)
            except Exception:
                return 100

    @staticmethod
    def _get_free_disk() -> int:
        try:
            stat = os.statvfs("/")
            return stat.f_bfree * stat.f_frsize // (1024**3)
        except (OSError, AttributeError):
            try:
                import shutil

                return shutil.disk_usage("/").free // (1024**3)
            except Exception:
                return 50


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------
def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Fireagent Host Agent")
    parser.add_argument(
        "--config",
        type=str,
        default="/etc/fireagent/agent.conf",
        help="Path to agent configuration file",
    )
    args = parser.parse_args()

    config = DEFAULT_CONFIG.copy()
    if os.path.exists(args.config):
        import configparser

        cfg = configparser.ConfigParser()
        cfg.read(args.config)
        # Merge config file values into defaults
        for section in cfg.sections():
            if section in config:
                config[section].update(dict(cfg.items(section)))

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s %(message)s"
    )

    agent = HostAgent(config)

    try:
        asyncio.run(agent.run())
    except KeyboardInterrupt:
        logger.info("Received SIGINT")
        asyncio.run(agent.stop())


if __name__ == "__main__":
    main()
