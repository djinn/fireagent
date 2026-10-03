"""Firecracker API client — talks to the Firecracker REST API over a Unix socket.

Firecracker (v1.x) exposes a REST API over a Unix socket. Machine configuration
(kernel, rootfs, vcpus, memory, drives) is done through PUT endpoints BEFORE
the instance is started via POST /actions.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import subprocess
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("fireagent.host.firecracker")

# ---------------------------------------------------------------------------
# Firecracker REST API client
# ---------------------------------------------------------------------------

FIRECRACKER_API_VERSION = "v1"


class FirecrackerAPIError(Exception):
    """Raised when the Firecracker API returns an error."""


class FirecrackerNotReadyError(FirecrackerAPIError):
    """Raised when Firecracker is not yet ready for API calls."""


class FirecrackerAPI:
    """Low-level HTTP-like client for the Firecracker REST API.

    Firecracker listens on a Unix socket (not TCP). The API uses HTTP-like
    request/response semantics::

        PUT /machine-config
        PUT /boot-source
        PUT /drives/root
        POST /actions  {"action_type": "InstanceStart"}

    Reference: https://github.com/firecracker-microvm/firecracker/blob/main/docs/api.md

    On platforms without AF_UNIX (macOS, Windows), use from_tcp() for mock testing.
    """

    def __init__(self, api_sock_path: str | Path, timeout: float = 10.0) -> None:
        self._sock_path = str(api_sock_path)
        self._timeout = timeout
        self._use_unix = hasattr(socket, "AF_UNIX") and os.name != "nt"
        self._host = "127.0.0.1"
        self._port = 0

    @classmethod
    def from_tcp(cls, host: str = "127.0.0.1", port: int = 0, timeout: float = 10.0) -> "FirecrackerAPI":
        """Create a client connected over TCP (for platforms without AF_UNIX)."""
        api = cls.__new__(cls)
        api._sock_path = f"tcp://{host}:{port}"
        api._timeout = timeout
        api._use_unix = False
        api._host = host
        api._port = port
        return api

    # ------------------------------------------------------------------
    # Raw HTTP-like request over Unix socket
    # ------------------------------------------------------------------
    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send an HTTP-like request to the Firecracker API socket."""
        if body is not None:
            payload = json.dumps(body)
            content_length = len(payload)
        else:
            payload = ""
            content_length = 0

        request = (
            f"{method} {path} HTTP/1.1\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {content_length}\r\n"
            f"\r\n"
            f"{payload}"
        ).encode("utf-8")

        try:
            if self._use_unix:
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.settimeout(self._timeout)
                sock.connect(self._sock_path)
            else:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(self._timeout)
                sock.connect((self._host, self._port))
            sock.sendall(request)

            # Read response
            response = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response += chunk
                if b"\r\n\r\n" in response and b"Content-Length:" in response:
                    # We have the headers — try to read full body
                    headers, _, body_start = response.partition(b"\r\n\r\n")
                    # Extract content length
                    for line in headers.split(b"\r\n"):
                        if line.lower().startswith(b"content-length:"):
                            cl = int(line.split(b":")[1].strip())
                            if len(response) >= len(headers) + 4 + cl:
                                break
                    else:
                        continue  # Keep reading
                    break
                if len(response) > 65536:
                    raise FirecrackerAPIError("Response too large (>64KB)")

            # Parse response
            headers, _, body_bytes = response.partition(b"\r\n\r\n")
            status_line = headers.split(b"\r\n")[0].decode("utf-8", errors="replace")
            _, status_code, *_ = status_line.split(" ", 2)
            status_code = int(status_code)

            if status_code >= 400:
                raise FirecrackerAPIError(
                    f"Firecracker API {method} {path} returned HTTP {status_code}: "
                    f"{body_bytes.decode('utf-8', errors='replace')}"
                )

            if body_bytes.strip():
                return json.loads(body_bytes.decode("utf-8"))
            return {"status": status_code}

        except socket.timeout:
            raise FirecrackerNotReadyError(
                f"Firecracker socket at {self._sock_path} timed out after {self._timeout}s"
            )
        except FileNotFoundError:
            raise FirecrackerNotReadyError(
                f"Firecracker socket not found at {self._sock_path} (not yet started)"
            )
        finally:
            try:
                sock.close()
            except Exception:
                pass

    async def _arequest(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Async version of _request using asyncio."""
        return await asyncio.to_thread(self._request, method, path, body)

    # ------------------------------------------------------------------
    # Firecracker API endpoints
    # ------------------------------------------------------------------
    @property
    def is_ready(self) -> bool:
        """Check if the Firecracker API socket is available."""
        if self._use_unix:
            return os.path.exists(self._sock_path)
        return True if self._port > 0 else os.path.exists(self._sock_path)

    def wait_ready(self, timeout: float = 5.0) -> bool:
        """Wait until the API socket appears."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.is_ready:
                return True
            time.sleep(0.05)
        return False

    def get_machine_config(self) -> dict[str, Any]:
        """GET /machine-config"""
        return self._request("GET", "/machine-config")

    def set_machine_config(self, vcpus: int, mem_size_mib: int) -> dict[str, Any]:
        """PUT /machine-config

        Configure vCPUs and memory BEFORE starting the instance.
        """
        return self._request(
            "PUT",
            "/machine-config",
            {"vcpus": vcpus, "mem_size_mib": mem_size_mib},
        )

    def set_boot_source(
        self,
        kernel_image_path: str,
        boot_args: str = "console=ttyS0 reboot=k panic=1 pci=off",
    ) -> dict[str, Any]:
        """PUT /boot-source

        Set the kernel image path and boot args.
        """
        return self._request(
            "PUT",
            "/boot-source",
            {
                "kernel_image_path": kernel_image_path,
                "boot_args": boot_args,
            },
        )

    def set_root_drive(
        self,
        path: str,
        is_read_only: bool = True,
    ) -> dict[str, Any]:
        """PUT /drives/root

        Attach the root filesystem drive.
        """
        return self._request(
            "PUT",
            "/drives/root",
            {
                "drive_id": "root",
                "path_on_host": path,
                "is_read_only": is_read_only,
                "is_root_device": True,
            },
        )

    def set_workspace_drive(
        self,
        path: str,
        is_read_only: bool = False,
    ) -> dict[str, Any]:
        """PUT /drives/workspace (custom drive_id)

        Attach the writable workspace volume.
        """
        return self._request(
            "PUT",
            "/drives/workspace",
            {
                "drive_id": "workspace",
                "path_on_host": path,
                "is_read_only": is_read_only,
                "is_root_device": False,
            },
        )

    def add_drive(
        self,
        drive_id: str,
        path: str,
        is_read_only: bool = False,
        is_root_device: bool = False,
    ) -> dict[str, Any]:
        """PUT /drives/{drive_id}

        Generic drive attachment.
        """
        return self._request(
            "PUT",
            f"/drives/{drive_id}",
            {
                "drive_id": drive_id,
                "path_on_host": path,
                "is_read_only": is_read_only,
                "is_root_device": is_root_device,
            },
        )

    def instance_start(self) -> dict[str, Any]:
        """POST /actions with InstanceStart

        Boot the microVM after all configuration is done.
        """
        return self._request("POST", "/actions", {"action_type": "InstanceStart"})

    def instance_stop(self) -> dict[str, Any]:
        """POST /actions with SendCtrlAltDel (graceful shutdown)"""
        return self._request("POST", "/actions", {"action_type": "SendCtrlAltDel"})

    def get_instance_state(self) -> dict[str, Any]:
        """GET /vm — get current VM state."""
        try:
            return self._request("GET", "/vm")
        except FirecrackerNotReadyError:
            return {"state": "not_ready"}

    def create_snapshot(self, snapshot_path: str, mem_path: str) -> dict[str, Any]:
        """PUT /vm/snapshot/create

        Future: create a resumable snapshot.
        """
        return self._request(
            "PUT",
            "/vm/snapshot/create",
            {
                "snapshot_type": "full",
                "snapshot_path": snapshot_path,
                "mem_file_path": mem_path,
            },
        )

    def configure_vsock(self, guest_port: int = 8001) -> dict[str, Any]:
        """PUT /vsock to enable vsock communication."""
        return self._request(
            "PUT",
            "/vsock",
            {"guest_port": guest_port},
        )

    def configure_network(
        self,
        iface_id: str = "eth0",
        host_ip: str = "169.254.1.1",
        guest_ip: str = "169.254.1.2",
    ) -> dict[str, Any]:
        """PUT /network/{iface_id} to configure networking."""
        return self._request(
            "PUT",
            f"/network/{iface_id}",
            {
                "iface_id": iface_id,
                "guest_ip": guest_ip,
                "host_ip": host_ip,
            },
        )

    # ------------------------------------------------------------------
    # Higher-level: full boot sequence
    # ------------------------------------------------------------------
    def configure_and_boot(
        self,
        kernel_path: str,
        rootfs_path: str,
        vcpus: int = 1,
        memory_mib: int = 512,
        workspace_path: str | None = None,
        boot_args: str = "console=ttyS0 reboot=k panic=1 pci=off",
        network: bool = False,
    ) -> dict[str, Any]:
        """Full boot sequence: configure machine → attach drives → start.

        This is the main entry point for launching a microVM.
        """
        if not self.wait_ready(timeout=10.0):
            raise FirecrackerNotReadyError("Firecracker socket did not become ready")

        logger.info(
            "Booting microVM: kernel=%s rootfs=%s vcpus=%d mem=%dMiB workspace=%s",
            kernel_path,
            rootfs_path,
            vcpus,
            memory_mib,
            workspace_path,
        )

        # 1. Machine config
        self.set_machine_config(vcpus=vcpus, mem_size_mib=memory_mib)

        # 2. Boot source
        self.set_boot_source(
            kernel_image_path=kernel_path,
            boot_args=boot_args,
        )

        # 3. Root drive (read-only)
        self.set_root_drive(path=rootfs_path, is_read_only=True)

        # 4. Workspace drive (read-write)
        if workspace_path:
            self.set_workspace_drive(path=workspace_path, is_read_only=False)

        # 5. Optional vsock for guest agent
        self.configure_vsock(guest_port=8001)

        # 6. Optional network
        if network:
            self.configure_network()

        # 7. Boot!
        result = self.instance_start()
        logger.info("MicroVM boot initiated: %s", result)
        return result

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------
    def __enter__(self) -> "FirecrackerAPI":
        return self

    def __exit__(self, *args: Any) -> None:
        pass
