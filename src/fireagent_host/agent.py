"""Refactored Host Agent — delegates to Firecracker microVM manager."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("fireagent.agent")


class HostAgent:
    """Manages Firecracker microVMs on this worker host.

    Delegates to MicroVMManager for actual Firecracker process management.
    """

    def __init__(self, config: dict | None = None) -> None:
        self.config = config or {}
        self._vm_manager = None  # Lazy init to avoid import cycle
        self._running = False

        logging_level = self.config.get("agent", {}).get("log_level", "info").upper()
        logging.basicConfig(
            level=getattr(logging, logging_level, logging.INFO),
            format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        )

    @property
    def vm_manager(self):
        if self._vm_manager is None:
            from fireagent_host.microvm import MicroVMManager
            self._vm_manager = MicroVMManager(self.config)
        return self._vm_manager

    async def run(self) -> None:
        """Start the host agent loop."""
        self._running = True
        host_id = self.config.get("agent", {}).get("host_id", "host-01")
        control_plane = self.config.get("agent", {}).get("control_plane_url", "http://127.0.0.1:8000")

        logger.info("Starting host agent %s (control plane: %s)", host_id, control_plane)

        mock_mode = self.vm_manager.is_mock_mode()
        logger.info("Firecracker mode: %s", "MOCK (CI/dev)" if mock_mode else "REAL")

        # Main loop
        while self._running:
            try:
                await asyncio.sleep(self.config.get("agent", {}).get("heartbeat_interval", 10))
            except asyncio.CancelledError:
                break

        logger.info("Host agent stopped")

    async def stop(self) -> None:
        """Graceful shutdown."""
        logger.info("Shutting down host agent...")
        self._running = False
        if self._vm_manager:
            await self.vm_manager.stop_all()

    # ------------------------------------------------------------------
    # Delegated MicroVM management
    # ------------------------------------------------------------------
    async def create_sandbox(
        self, sandbox_id: str, image: str, vcpus: int, memory_mib: int, disk_mib: int
    ) -> dict:
        """Create a new microVM sandbox."""
        instance = await self.vm_manager.create_sandbox(
            sandbox_id=sandbox_id,
            image=image,
            vcpus=vcpus,
            memory_mib=memory_mib,
            disk_mib=disk_mib,
        )
        return {
            "sandbox_id": sandbox_id,
            "state": "ready",
            "pid": instance.process.pid if instance.process else 0,
            "mock": self.vm_manager.is_mock_mode(),
        }

    async def exec_command(
        self,
        sandbox_id: str,
        command: str,
        working_dir: str | None = None,
        environment: dict | None = None,
        execution_timeout_seconds: int | None = None,
        stdin: str | None = None,
    ) -> dict:
        """Execute a command in a sandbox's guest agent."""
        return await self.vm_manager.exec_command(
            sandbox_id=sandbox_id,
            command=command,
            working_dir=working_dir,
            environment=environment,
            execution_timeout_seconds=execution_timeout_seconds,
            stdin=stdin,
        )

    async def stop_sandbox(self, sandbox_id: str) -> bool:
        """Stop a sandbox."""
        return await self.vm_manager.stop_sandbox(sandbox_id)

    async def delete_sandbox(self, sandbox_id: str) -> bool:
        """Delete a sandbox."""
        return await self.vm_manager.delete_sandbox(sandbox_id)

    async def health_check(self, sandbox_id: str) -> bool:
        """Check if the sandbox's guest agent is responsive."""
        return await self.vm_manager.health_check(sandbox_id)

    @property
    def active_sandbox_count(self) -> int:
        return self.vm_manager.active_sandbox_count if self._vm_manager else 0


# ---------------------------------------------------------------------------
# Legacy wrapper (for backward compatibility with old entrypoint)
# ---------------------------------------------------------------------------

# Preserve the old HostAgent interface for backward compat
class LegacyHostAgent(HostAgent):
    """Backward-compatible wrapper that matches the original API."""

    @staticmethod
    def _get_total_memory() -> int:
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        return int(line.split()[1]) // 1024
        except OSError:
            pass
        return 4096

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
        except OSError:
            return 100


def main() -> None:
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Fireagent Host Agent")
    parser.add_argument("--config", type=str, default="/etc/fireagent/agent.conf",
                        help="Path to agent configuration file")
    parser.add_argument("--mock", action="store_true",
                        help="Use mock Firecracker (no KVM required)")
    args = parser.parse_args()

    from fireagent_agent.agent import DEFAULT_CONFIG
    config = DEFAULT_CONFIG.copy()
    if os.path.exists(args.config):
        import configparser
        cfg = configparser.ConfigParser()
        cfg.read(args.config)
        for section in cfg.sections():
            if section in config:
                config[section].update(dict(cfg.items(section)))

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s %(message)s")

    agent = HostAgent(config)

    try:
        asyncio.run(agent.run())
    except KeyboardInterrupt:
        logger.info("Received SIGINT")
        asyncio.run(agent.stop())


if __name__ == "__main__":
    main()