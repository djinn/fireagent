"""Mock Firecracker — simulates the Firecracker REST API for CI/testing.

When no KVM or actual Firecracker binary is available, MockFirecracker
provides a realistic simulation that can be used for integration tests,
CI pipelines, and development on non-Linux platforms.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("fireagent.host.mock_firecracker")


class MockFirecrackerServer:
    """Simulates the Firecracker REST API.

    Uses Unix sockets where available (Linux), falls back to TCP
    localhost on platforms without AF_UNIX (macOS, Windows).
    """

    def __init__(self, sock_path: str | Path) -> None:
        self._sock_path = str(sock_path)
        self._use_unix = hasattr(socket, "AF_UNIX") and os.name != "nt"
        self._server: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self.port: int = 0
        self.state: dict[str, Any] = {
            "machine_config": {},
            "boot_source": {},
            "drives": {},
            "vm_state": "not_started",
            "vsock": {},
            "network": {},
        }

    def start(self) -> None:
        """Start the mock server in a background thread."""
        if self._use_unix:
            # Unix socket (Linux)
            if os.path.exists(self._sock_path):
                os.unlink(self._sock_path)
            parent = Path(self._sock_path).parent
            parent.mkdir(parents=True, exist_ok=True)
            self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._server.bind(self._sock_path)
        else:
            # TCP fallback (macOS, Windows)
            self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._server.bind(("127.0.0.1", 0))
            self.port = self._server.getsockname()[1]

        self._server.listen(5)
        self._server.settimeout(1.0)
        self._running = True

        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        loc = self._sock_path if self._use_unix else f"127.0.0.1:{self.port}"
        logger.info("Mock Firecracker listening at %s", loc)

    def stop(self) -> None:
        """Stop the mock server and clean up."""
        self._running = False
        if self._server:
            try:
                self._server.close()
            except Exception:
                pass
        if self._use_unix and os.path.exists(self._sock_path):
            try:
                os.unlink(self._sock_path)
            except Exception:
                pass

    def _serve(self) -> None:
        """Accept and handle connections."""
        while self._running:
            try:
                conn, _ = self._server.accept()  # type: ignore[union-attr]
                threading.Thread(target=self._handle, args=(conn,), daemon=True).start()
            except socket.timeout:
                continue
            except OSError:
                break

    def _handle(self, conn: socket.socket) -> None:
        """Handle a single HTTP-like request."""
        try:
            conn.settimeout(5.0)
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = conn.recv(4096)
                if not chunk:
                    conn.close()
                    return
                data += chunk

            # Parse request
            request_line, _, remaining = data.partition(b"\r\n")
            method, path, _ = request_line.decode("utf-8").split(" ", 2)

            # Parse body
            body = {}
            if b"Content-Length:" in remaining:
                for line in remaining.split(b"\r\n"):
                    if line.lower().startswith(b"content-length:"):
                        cl = int(line.split(b":")[1].strip())
                        break
                _, _, body_bytes = remaining.partition(b"\r\n\r\n")
                if len(body_bytes) < cl:
                    more = conn.recv(cl - len(body_bytes))
                    body_bytes += more
                if body_bytes.strip():
                    body = json.loads(body_bytes.decode("utf-8"))

            # Route to handler
            response = self._route(method, path, body)
            conn.sendall(response)
        except Exception as exc:
            logger.error("Mock Firecracker handler error: %s", exc)
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _route(self, method: str, path: str, body: dict) -> bytes:
        """Route a request to the appropriate handler."""
        try:
            if method == "GET" and path == "/machine-config":
                return self._json_response(self.state["machine_config"])
            elif method == "PUT" and path == "/machine-config":
                self.state["machine_config"] = body
                return self._json_response({"status": 204})
            elif method == "PUT" and path == "/boot-source":
                self.state["boot_source"] = body
                return self._json_response({"status": 204})
            elif method == "PUT" and path.startswith("/drives/"):
                drive_id = path.split("/")[-1]
                self.state["drives"][drive_id] = body
                return self._json_response({"status": 204})
            elif method == "PUT" and path == "/vsock":
                self.state["vsock"] = body
                return self._json_response({"status": 204})
            elif method == "PUT" and path.startswith("/network/"):
                iface_id = path.split("/")[-1]
                self.state["network"][iface_id] = body
                return self._json_response({"status": 204})
            elif method == "POST" and path == "/actions":
                action = body.get("action_type", "")
                if action == "InstanceStart":
                    self.state["vm_state"] = "running"
                elif action == "SendCtrlAltDel":
                    self.state["vm_state"] = "stopping"
                return self._json_response({"status": 204})
            elif method == "GET" and path == "/vm":
                return self._json_response({"state": self.state["vm_state"]})
            elif method == "PUT" and path.startswith("/vm/snapshot"):
                return self._json_response({"status": 204})
            else:
                return self._json_response({"error": "not_found"}, status=404)
        except Exception as exc:
            return self._json_response({"error": str(exc)}, status=500)

    @staticmethod
    def _json_response(data: dict, status: int = 200) -> bytes:
        body = json.dumps(data)
        return (
            f"HTTP/1.1 {status} OK\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"\r\n"
            f"{body}"
        ).encode("utf-8")


class MockFirecrackerProcess:
    """Simulates a Firecracker subprocess for use in lieu of a real binary.

    Usage::

        mock = MockFirecrackerProcess(Path("/tmp/sandbox/sb-1/"))
        mock.start()    # launches mock server
        mock.stop()     # stops mock server
    """

    def __init__(self, working_dir: str | Path) -> None:
        self.working_dir = Path(working_dir)
        self.api_sock = self.working_dir / "firecracker.sock"
        self._server: MockFirecrackerServer | None = None
        self.pid: int = 0

    def start(self) -> None:
        """Start the mock Firecracker server."""
        self.working_dir.mkdir(parents=True, exist_ok=True)
        self._server = MockFirecrackerServer(self.api_sock)
        self._server.start()
        self.pid = os.getpid()  # Simulated PID
        logger.info("Mock Firecracker started (PID=%s)", self.pid)

    def stop(self) -> None:
        """Stop the mock Firecracker server."""
        if self._server:
            self._server.stop()
            self._server = None
        # Clean up socket
        if self.api_sock.exists():
            self.api_sock.unlink()

    @property
    def state(self) -> dict:
        if self._server:
            return self._server.state
        return {}

    @property
    def is_running(self) -> bool:
        return self._server is not None and self._server._running
