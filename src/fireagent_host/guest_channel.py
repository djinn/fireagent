"""Guest Agent Channel — protocol for communicating with the microVM's guest agent.

The guest agent runs inside the Firecracker microVM and communicates over
either a serial port (/dev/ttyS0) or a vsock. This module provides the
host-side of the protocol: sending execution requests and receiving responses.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("fireagent.host.guest_channel")

# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

GUEST_AGENT_PROTOCOL_VERSION = "1.0"


def encode_request(request: dict) -> bytes:
    """Encode a request as a JSON line for the guest agent."""
    request["_protocol_version"] = GUEST_AGENT_PROTOCOL_VERSION
    return (json.dumps(request) + "\n").encode("utf-8")


def decode_response(data: bytes) -> dict:
    """Decode a JSON response line from the guest agent."""
    return json.loads(data.decode("utf-8").strip())


# ---------------------------------------------------------------------------
# Host-side channel implementations
# ---------------------------------------------------------------------------


class GuestAgentChannel:
    """Base class for guest agent communication channels."""

    async def connect(self, timeout: float = 10.0) -> None:
        """Connect to the guest agent."""
        raise NotImplementedError

    async def disconnect(self) -> None:
        """Disconnect from the guest agent."""
        raise NotImplementedError

    async def execute(
        self,
        command: str,
        *,
        working_dir: str | None = None,
        environment: dict[str, str] | None = None,
        execution_timeout_seconds: int | None = None,
        stdin: str | None = None,
    ) -> dict[str, Any]:
        """Send a command execution request and wait for the response."""
        raise NotImplementedError

    async def health_check(self) -> bool:
        """Check if the guest agent is responsive."""
        raise NotImplementedError


class SerialChannel(GuestAgentChannel):
    """Communicate with the guest agent over a serial port (host side).

    The host opens the pty/tty that Firecracker connects to the guest's
    serial port. Commands and responses are JSON lines.
    """

    def __init__(
        self,
        serial_device: str = "/dev/ttyS0",
        baud_rate: int = 115200,
        response_timeout: float = 30.0,
    ) -> None:
        self._device = serial_device
        self._baud_rate = baud_rate
        self._timeout = response_timeout
        self._ser = None

    async def connect(self, timeout: float = 10.0) -> None:
        """Open the serial connection."""
        try:
            import serial
        except ImportError:
            raise RuntimeError("pyserial is required for SerialChannel: pip install pyserial")

        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                self._ser = serial.Serial(
                    self._device,
                    self._baud_rate,
                    timeout=self._timeout,
                )
                logger.info("Connected to guest agent on %s", self._device)
                return
            except serial.SerialException as exc:
                if time.time() >= deadline:
                    raise RuntimeError(f"Cannot connect to serial {self._device}: {exc}")
                time.sleep(0.1)

    async def disconnect(self) -> None:
        if self._ser:
            try:
                self._ser.close()
            except Exception:
                pass
            self._ser = None

    async def _write(self, data: bytes) -> None:
        if self._ser is None:
            raise RuntimeError("Not connected to serial device")
        self._ser.write(data)
        self._ser.flush()

    async def _read_line(self) -> bytes:
        if self._ser is None:
            raise RuntimeError("Not connected to serial device")
        return self._ser.readline()

    async def execute(
        self,
        command: str,
        *,
        working_dir: str | None = None,
        environment: dict[str, str] | None = None,
        execution_timeout_seconds: int | None = None,
        stdin: str | None = None,
    ) -> dict[str, Any]:
        request = {
            "command": command,
            "working_dir": working_dir,
            "environment": environment or {},
            "execution_timeout_seconds": execution_timeout_seconds or 300,
            "stdin": stdin or "",
        }
        await self._write(encode_request(request))
        raw = await self._read_line()
        return decode_response(raw)

    async def health_check(self) -> bool:
        try:
            result = await self.execute("echo 'health-ok'")
            return result.get("stdout", "").strip() == "health-ok"
        except Exception:
            return False


class VsockChannel(GuestAgentChannel):
    """Communicate with the guest agent over vsock (host side).

    Firecracker supports vsock for host-guest communication. The host
    connects to a local TCP port that proxies to the guest's vsock port.
    """

    def __init__(
        self,
        host_port: int = 8001,
        response_timeout: float = 30.0,
    ) -> None:
        self._host_port = host_port
        self._timeout = response_timeout
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    async def connect(self, timeout: float = 10.0) -> None:
        """Connect to the vsock proxy on the host."""
        deadline = time.time() + timeout
        last_exc = None
        while time.time() < deadline:
            try:
                self._reader, self._writer = await asyncio.wait_for(
                    asyncio.open_connection("127.0.0.1", self._host_port),
                    timeout=1.0,
                )
                logger.info("Connected to guest agent via vsock on port %d", self._host_port)
                return
            except (ConnectionRefusedError, OSError, asyncio.TimeoutError) as exc:
                last_exc = exc
                await asyncio.sleep(0.1)
        raise RuntimeError(
            f"Cannot connect to vsock proxy on port {self._host_port}: {last_exc}"
        )

    async def disconnect(self) -> None:
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
            self._reader = None
            self._writer = None

    async def execute(
        self,
        command: str,
        *,
        working_dir: str | None = None,
        environment: dict[str, str] | None = None,
        execution_timeout_seconds: int | None = None,
        stdin: str | None = None,
    ) -> dict[str, Any]:
        if self._writer is None:
            raise RuntimeError("Not connected to vsock")

        request = {
            "command": command,
            "working_dir": working_dir,
            "environment": environment or {},
            "execution_timeout_seconds": execution_timeout_seconds or 300,
            "stdin": stdin or "",
        }
        self._writer.write(encode_request(request))
        await self._writer.drain()

        raw = await asyncio.wait_for(self._reader.readline(), timeout=self._timeout)  # type: ignore[union-attr]
        return decode_response(raw)

    async def health_check(self) -> bool:
        try:
            result = await self.execute("echo 'health-ok'")
            return result.get("stdout", "").strip() == "health-ok"
        except Exception:
            return False


class InProcessChannel(GuestAgentChannel):
    """Run commands directly on the host (for testing/dev without microVMs).

    This is the channel used by the in-memory SandboxService. It's not for
    production — it runs commands directly on the host instead of in a microVM.
    """

    def __init__(self) -> None:
        self.connected = False

    async def connect(self, timeout: float = 10.0) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    async def execute(
        self,
        command: str,
        *,
        working_dir: str | None = None,
        environment: dict[str, str] | None = None,
        execution_timeout_seconds: int | None = None,
        stdin: str | None = None,
    ) -> dict[str, Any]:
        import subprocess  # nosec

        timeout = execution_timeout_seconds or 300
        env = environment or {}
        env.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")

        try:
            result = subprocess.run(
                ["sh", "-c", command],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=working_dir or "/",
                env={**os.environ, **env},
                input=stdin,
            )
            return {
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": result.returncode,
                "timed_out": False,
                "oom_killed": False,
                "start_time": time.time(),
                "finish_time": time.time(),
            }
        except subprocess.TimeoutExpired:
            return {
                "stdout": "",
                "stderr": "Command timed out",
                "exit_code": -1,
                "timed_out": True,
                "oom_killed": False,
                "start_time": time.time(),
                "finish_time": time.time(),
            }
        except Exception as exc:
            return {
                "stdout": "",
                "stderr": str(exc),
                "exit_code": -1,
                "timed_out": False,
                "oom_killed": False,
                "start_time": time.time(),
                "finish_time": time.time(),
            }

    async def health_check(self) -> bool:
        result = await self.execute("echo 'health-ok'")
        return result.get("stdout", "").strip() == "health-ok"