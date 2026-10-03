"""Minimal root filesystem builder for Firecracker microVMs.

Builds a small, bootable Linux root filesystem containing:
- BusyBox (init, sh, coreutils)
- musl libc
- Fireagent guest agent
- CA certificates, DNS resolution

This is a self-contained Python script that does NOT require Buildroot.
It downloads and assembles pre-built binaries into a cpio archive.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("fireagent.imagebuilder")

# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------

BUSYBOX_VERSION = "1.36.1"
BUSYBOX_URL = (
    f"https://busybox.net/downloads/binaries/{BUSYBOX_VERSION}/"
    f"busybox-{BUSYBOX_VERSION}-x86_64.tar.gz"
)

# Tiny init script
INIT_SCRIPT = """#!/bin/sh

# Fireagent minimal init
set -e

echo "=== Fireagent guest boot ==="

# Mount /proc, /sys, /dev
mount -t proc none /proc
mount -t sysfs none /sys
mount -t devtmpfs none /dev

# Set up networking (loopback only)
ifconfig lo 127.0.0.1 up

# Mount workspace (second virtio drive)
if [ -b /dev/vdb ]; then
    mkdir -p /workspace
    mount -t ext4 -o rw,noexec,nosuid /dev/vdb /workspace
    echo "[init] Workspace mounted at /workspace"
fi

# Set up PATH
export PATH="/usr/local/bin:/usr/bin:/bin:/sbin"
export HOME="/root"
export TERM="linux"
export WORKSPACE="/workspace"

# Start guest agent (background)
if [ -x /usr/bin/fireagent-guest-agent.py ]; then
    echo "[init] Starting guest agent..."
    python3 /usr/bin/fireagent-guest-agent.py &
fi

# Signal readiness to host via serial
echo "=== Fireagent guest ready ===" > /dev/ttyS0

# Keep alive
while true; do
    sleep 30
done
"""

GUEST_AGENT_SCRIPT = """#!/usr/bin/env python3
\"\"\"Fireagent guest agent — runs inside the microVM.

Communicates with the host agent over /dev/ttyS0 (serial port).
Reads JSON requests, executes commands, returns JSON responses.
\"\"\"

import json
import os
import shlex
import signal
import subprocess
import sys
import time

SERIAL_PORT = "/dev/ttyS0"
WORKSPACE = "/workspace"
DANGEROUS_COMMANDS = {"sudo", "su", "chroot", "reboot", "shutdown", "halt", "poweroff", "init", "telinit"}


def execute_command(command, timeout=300, stdin=None):
    try:
        result = subprocess.run(
            ["sh", "-c", command],
            capture_output=True, text=True, timeout=timeout,
            cwd=WORKSPACE if os.path.exists(WORKSPACE) else "/",
        )
        return {"stdout": result.stdout, "stderr": result.stderr,
                "exit_code": result.returncode, "timed_out": False, "oom_killed": False}
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": "Command timed out",
                "exit_code": -1, "timed_out": True, "oom_killed": False}
    except Exception as exc:
        return {"stdout": "", "stderr": str(exc),
                "exit_code": -1, "timed_out": False, "oom_killed": False}


def handle_request(request):
    command = request.get("command")
    if not command:
        return {"stdout": "", "stderr": "No command", "exit_code": -1,
                "timed_out": False, "oom_killed": False}
    try:
        cmd_parts = shlex.split(command)
    except ValueError:
        return {"stdout": "", "stderr": "Invalid command", "exit_code": -1,
                "timed_out": False, "oom_killed": False}
    if cmd_parts and cmd_parts[0] in DANGEROUS_COMMANDS:
        return {"stdout": "", "stderr": "Command not allowed: privileged operations disabled",
                "exit_code": -1, "timed_out": False, "oom_killed": False}
    timeout = request.get("execution_timeout_seconds", 300)
    return execute_command(command, timeout, request.get("stdin"))


def main():
    os.environ.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
    os.environ.setdefault("HOME", "/root")
    os.environ.setdefault("WORKSPACE", WORKSPACE)

    sys.stdout.write("Fireagent guest agent starting...\\n")
    sys.stdout.flush()

    buffer = ""
    try:
        with open(SERIAL_PORT, "r+b", buffering=0) as ser:
            while True:
                data = ser.read(1024)
                if not data:
                    continue
                buffer += data.decode("utf-8", errors="replace")
                while "\\n" in buffer:
                    line, buffer = buffer.split("\\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        req = json.loads(line)
                        resp = handle_request(req)
                        ser.write((json.dumps(resp) + "\\n").encode())
                    except json.JSONDecodeError:
                        ser.write(b'{"error": "invalid_json"}\\n')
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
"""


def download_busybox(dest_dir: Path) -> Path:
    """Download BusyBox binary."""
    url = BUSYBOX_URL
    tarball = dest_dir / "busybox.tar.gz"
    logger.info("Downloading BusyBox %s from %s ...", BUSYBOX_VERSION, url)
    urllib.request.urlretrieve(url, tarball)
    logger.info("Downloaded to %s", tarball)

    # Extract
    import tarfile

    with tarfile.open(tarball) as tf:
        tf.extractall(dest_dir)

    return dest_dir / "busybox"


def setup_busybox(rootfs: Path, busybox_bin: Path) -> None:
    """Install BusyBox and create symlinks for all applets."""
    bb = rootfs / "bin" / "busybox"
    rootfs.mkdir(parents=True, exist_ok=True)
    shutil.copy2(busybox_bin, bb)
    bb.chmod(0o755)

    # Create standard applet symlinks
    applets = [
        "sh",
        "bash",
        "ls",
        "cp",
        "mv",
        "rm",
        "mkdir",
        "rmdir",
        "cat",
        "echo",
        "printf",
        "true",
        "false",
        "sleep",
        "test",
        "[",
        "ps",
        "kill",
        "mount",
        "umount",
        "df",
        "du",
        "dmesg",
        "grep",
        "sed",
        "awk",
        "cut",
        "sort",
        "uniq",
        "wc",
        "head",
        "tail",
        "find",
        "xargs",
        "tee",
        "env",
        "chmod",
        "chown",
        "chgrp",
        "ln",
        "readlink",
        "stat",
        "pwd",
        "cd",
        "which",
        "whoami",
        "id",
        "groups",
        "tar",
        "gzip",
        "gunzip",
        "bzip2",
        "unxz",
        "ping",
        "ifconfig",
        "route",
        "netstat",
        "nslookup",
        "vi",
        "less",
        "more",
        "clear",
        "reset",
        "adduser",
        "deluser",
        "passwd",
        "date",
        "cal",
        "time",
        "uptime",
        "hostname",
        "dnsdomainname",
        "pidof",
        "pgrep",
        "pkill",
        "fuser",
        "cpio",
        "dd",
        "sync",
        "truncate",
        "watch",
        "logger",
        "printenv",
    ]
    for applet in applets:
        link = rootfs / "bin" / applet
        os.symlink("busybox", link)

    # Also in /sbin/ and /usr/bin/
    usr_bin = rootfs / "usr" / "bin"
    usr_bin.mkdir(parents=True, exist_ok=True)
    sbin = rootfs / "sbin"
    sbin.mkdir(parents=True, exist_ok=True)
    for applet in applets:
        os.symlink("/bin/busybox", usr_bin / applet)
        os.symlink("/bin/busybox", sbin / applet)


def setup_directories(rootfs: Path) -> None:
    """Create standard Linux filesystem directories."""
    for d in [
        "bin",
        "sbin",
        "usr/bin",
        "usr/sbin",
        "etc",
        "etc/init.d",
        "dev",
        "dev/pts",
        "proc",
        "sys",
        "tmp",
        "root",
        "var",
        "var/log",
        "var/tmp",
        "usr/local/bin",
        "usr/local/lib",
    ]:
        (rootfs / d).mkdir(parents=True, exist_ok=True)
    # Workspace mount point
    (rootfs / "workspace").mkdir(exist_ok=True)


def setup_etc(rootfs: Path) -> None:
    """Set up /etc files."""
    # fstab
    (rootfs / "etc" / "fstab").write_text(
        "proc /proc proc defaults 0 0\n"
        "sysfs /sys sysfs defaults 0 0\n"
        "devtmpfs /dev devtmpfs defaults 0 0\n"
    )

    # hostname
    (rootfs / "etc" / "hostname").write_text("fireagent-guest\n")

    # hosts
    (rootfs / "etc" / "hosts").write_text("127.0.0.1 localhost\n" "127.0.1.1 fireagent-guest\n")

    # inittab
    (rootfs / "etc" / "inittab").write_text("::sysinit:/etc/init.d/rcS\n" "::askfirst:-/bin/sh\n")

    # init.d/rcS
    rc_s = rootfs / "etc" / "init.d" / "rcS"
    rc_s.write_text(INIT_SCRIPT)
    rc_s.chmod(0o755)

    # group, passwd (minimal)
    (rootfs / "etc" / "group").write_text("root:x:0:\n")
    (rootfs / "etc" / "passwd").write_text("root:x:0:0:root:/root:/bin/sh\n")


def setup_guest_agent(rootfs: Path) -> None:
    """Install the guest agent into the rootfs."""
    agent_dir = rootfs / "usr" / "bin"
    agent_dir.mkdir(parents=True, exist_ok=True)
    agent_script = agent_dir / "fireagent-guest-agent.py"
    agent_script.write_text(GUEST_AGENT_SCRIPT)
    agent_script.chmod(0o755)


def create_initramfs(rootfs: Path, output_path: Path) -> Path:
    """Create a compressed cpio initramfs from the rootfs directory."""
    logger.info("Creating initramfs at %s ...", output_path)
    original_dir = os.getcwd()
    os.chdir(str(rootfs))

    try:
        subprocess.run(
            ["find", ".", "-print0"],
            capture_output=True,
        )
        with subprocess.Popen(
            ["cpio", "--null", "--create", "--format=newc"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ) as cpio_proc:
            find_proc = subprocess.Popen(
                ["find", ".", "-print0"],
                stdout=cpio_proc.stdin,
                stderr=subprocess.DEVNULL,
            )
            find_proc.wait()
            cpio_proc.stdin.close()  # type: ignore[union-attr]
            cpio_out, cpio_err = cpio_proc.communicate()

        if cpio_proc.returncode != 0:
            raise RuntimeError(f"cpio failed: {cpio_err.decode()}")

        # Gzip compress
        import gzip

        with open(output_path, "wb") as f:
            compressed = gzip.compress(cpio_out, compresslevel=6)
            f.write(compressed)
    finally:
        os.chdir(original_dir)

    logger.info("Initramfs created: %s (%d bytes)", output_path, output_path.stat().st_size)
    return output_path


def compute_digest(path: Path) -> str:
    """Compute SHA-256 digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build_image(
    output_dir: Path,
    image_name: str = "fireagent-mini",
    version: str = "0.1.0",
    kernel_url: str | None = None,
) -> dict[str, Any]:
    """Build a minimal bootable Firecracker guest image.

    Returns metadata about the built image.
    """
    logger.info("Building Fireagent guest image: %s:%s", image_name, version)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="fireagent-rootfs-") as tmp:
        rootfs = Path(tmp) / "rootfs"

        logger.info("Creating rootfs directory structure...")
        setup_directories(rootfs)
        setup_etc(rootfs)

        logger.info("Downloading and installing BusyBox...")
        busybox_bin = download_busybox(Path(tmp))
        setup_busybox(rootfs, busybox_bin)

        logger.info("Installing guest agent...")
        setup_guest_agent(rootfs)

        logger.info("Creating initramfs...")
        initramfs_path = output_dir / f"{image_name}-{version}.img"
        create_initramfs(rootfs, initramfs_path)

    digest = compute_digest(initramfs_path)
    img_size = initramfs_path.stat().st_size

    metadata = {
        "name": image_name,
        "version": version,
        "path": str(initramfs_path),
        "size_bytes": img_size,
        "sha256": digest,
        "busybox_version": BUSYBOX_VERSION,
        "kernel_url": kernel_url,
        "initramfs": True,
    }

    # Write metadata
    meta_path = output_dir / f"{image_name}-{version}.meta.json"
    import json

    meta_path.write_text(json.dumps(metadata, indent=2))
    logger.info("Image metadata written to %s", meta_path)

    logger.info(
        "Build complete: %s (%s, %d bytes, sha256=%s)", image_name, version, img_size, digest[:16]
    )

    return metadata


def download_kernel(output_dir: Path, version: str = "6.8-microvm") -> Path:
    """Download a pre-built Firecracker-compatible kernel.

    Uses the public Firecracker CI kernel builds.
    """
    kernel_url = (
        f"https://s3.amazonaws.com/spec.ccfc.min/ci-artifacts/" f"kernels/x86_64/{version}/vmlinux"
    )
    kernel_path = output_dir / "vmlinux"

    if kernel_path.exists():
        logger.info("Kernel already exists at %s", kernel_path)
        return kernel_path

    logger.info("Downloading Firecracker kernel %s ...", version)
    urllib.request.urlretrieve(kernel_url, kernel_path)
    kernel_path.chmod(0o644)
    logger.info("Kernel downloaded to %s (%d bytes)", kernel_path, kernel_path.stat().st_size)
    return kernel_path


def ensure_dir(path: str) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a minimal Firecracker guest image for Fireagent",
    )
    parser.add_argument(
        "--output", "-o", default="/artifacts/images", help="Output directory for built images"
    )
    parser.add_argument("--name", default="fireagent-mini", help="Image name")
    parser.add_argument("--version", default="0.1.0", help="Image version")
    parser.add_argument(
        "--kernel-version",
        default="6.8-microvm",
        help="Kernel version to download (or 'skip' to skip)",
    )
    parser.add_argument("--skip-kernel", action="store_true", help="Skip kernel download")
    args = parser.parse_args()

    output_dir = ensure_dir(args.output)

    # Optionally download kernel
    kernel_path = None
    if not args.skip_kernel:
        try:
            kernel_path = download_kernel(output_dir, args.kernel_version)
        except Exception as exc:
            logger.warning("Kernel download failed: %s (continuing without kernel)", exc)

    # Build image
    meta = build_image(
        output_dir=output_dir,
        image_name=args.name,
        version=args.version,
    )

    logger.info("Image ready at %s", meta["path"])
    logger.info(
        "  Size:     %d bytes (%.1f MiB)", meta["size_bytes"], meta["size_bytes"] / 1024 / 1024
    )
    logger.info("  SHA256:   %s", meta["sha256"])
    if kernel_path:
        logger.info("  Kernel:   %s", kernel_path)


if __name__ == "__main__":
    main()
