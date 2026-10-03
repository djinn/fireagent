"""Guest agent — minimal init script for Fireagent microVMs.

This script runs inside the Firecracker microVM as the init process.
It opens a serial port or vsock channel, listens for execution requests,
spawns commands, and returns results.
"""

import json
import os
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path

try:
    import serial  # pyserial  # noqa: F401
except ImportError:
    serial = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
GUEST_AGENT_PORT = "/dev/ttyS0"  # Serial port for control channel
BAUD_RATE = 115200
HEARTBEAT_INTERVAL = 2  # seconds
WORKSPACE_MOUNT = "/workspace"


def setup_workspace() -> None:
    """Mount the second drive as workspace."""
    workspace_device = "/dev/vdb"  # Second virtio block device
    if os.path.exists(workspace_device):
        os.makedirs(WORKSPACE_MOUNT, exist_ok=True)
        subprocess.run(
            ["mount", "-o", "rw,noexec,nosuid", workspace_device, WORKSPACE_MOUNT],
            capture_output=True,
        )
        if os.path.exists(WORKSPACE_MOUNT):
            os.chdir(WORKSPACE_MOUNT)


def setup_environment() -> None:
    """Set up default environment variables."""
    os.environ["PATH"] = "/usr/local/bin:/usr/bin:/bin"
    os.environ["HOME"] = "/root"
    os.environ["TERM"] = "linux"
    os.environ["WORKSPACE"] = WORKSPACE_MOUNT


def execute_command(command: str, timeout: int = 300) -> dict:
    """Run a command and return structured output."""
    try:
        result = subprocess.run(
            ["sh", "-c", command],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=WORKSPACE_MOUNT if os.path.exists(WORKSPACE_MOUNT) else "/",
        )
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.returncode,
            "timed_out": False,
            "oom_killed": False,
        }
    except subprocess.TimeoutExpired:
        return {
            "stdout": "",
            "stderr": "Command timed out",
            "exit_code": -1,
            "timed_out": True,
            "oom_killed": False,
        }
    except Exception as exc:
        return {
            "stdout": "",
            "stderr": str(exc),
            "exit_code": -1,
            "timed_out": False,
            "oom_killed": False,
        }


def handle_request(request: dict) -> dict:
    """Process an execution request from the host agent."""
    command = request.get("command", "")
    timeout = request.get("execution_timeout_seconds", 300)

    # Validate
    if command is None:
        return {
            "stdout": "",
            "stderr": "No command provided",
            "exit_code": -1,
            "timed_out": False,
            "oom_killed": False,
        }

    # Basic sanitization: prevent dangerous commands
    dangerous = [
        "sudo",
        "su",
        "chroot",
        "reboot",
        "shutdown",
        "halt",
        "poweroff",
        "init",
        "telinit",
    ]
    try:
        cmd_parts = shlex.split(command)
    except ValueError:
        return {
            "stdout": "",
            "stderr": "Invalid command",
            "exit_code": -1,
            "timed_out": False,
            "oom_killed": False,
        }
    if cmd_parts and cmd_parts[0] in dangerous:
        return {
            "stdout": "",
            "stderr": "Command not allowed: privileged operations are disabled",
            "exit_code": -1,
            "timed_out": False,
            "oom_killed": False,
        }

    return execute_command(command, timeout)


def main() -> None:
    """Guest agent main loop."""
    setup_environment()
    setup_workspace()

    sys.stdout.write("Fireagent guest agent starting...\n")
    sys.stdout.flush()

    # Open serial connection to host agent
    try:
        ser = serial.Serial(GUEST_AGENT_PORT, BAUD_RATE, timeout=1)
    except serial.SerialException:
        # Fallback: read from stdin (for debugging)
        sys.stdout.write("No serial port available, using stdin/stdout\n")
        sys.stdout.flush()

        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
                response = handle_request(request)
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()
            except json.JSONDecodeError:
                pass
        return

    # Main loop over serial
    buffer = ""
    sys.stdout.write("Guest agent ready\n")
    sys.stdout.flush()

    while True:
        try:
            data = ser.read(1024).decode("utf-8", errors="replace")
            if not data:
                continue
            buffer += data

            # Process complete lines
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    request = json.loads(line)
                    response = handle_request(request)
                    ser.write((json.dumps(response) + "\n").encode())
                except json.JSONDecodeError:
                    ser.write(b'{"error": "invalid_json"}\n')
        except serial.SerialException:
            break
        except KeyboardInterrupt:
            break


if __name__ == "__main__":
    main()
