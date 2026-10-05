# Claude Code Integration

Run **Claude Code** coding sessions inside isolated Fireagent microVMs. This protects your host from LLM-generated shell commands while giving Claude a full, stateful Linux environment with persistent `$HOME`, installed packages, and resource controls.

---

## How It Works

Claude Code is an agentic coding tool built by Anthropic that uses the Claude model to understand codebases, generate patches, run tests, and execute shell commands. By integrating with Fireagent, every Claude Code session runs inside a disposable Firecracker microVM:

```
┌──────────────────────────────────────────┐
│  Your Host (macOS/Linux/Windows)          │
│                                           │
│  ┌─────────────────────────────────────┐  │
│  │  Claude Code (Fireagent extension)  │  │
│  │  - Each command → sandbox.exec()    │  │
│  │  - File writes → sandbox workspace  │  │
│  │  - All IO sandboxed                 │  │
│  └──────┬──────────────────────────────┘  │
│         │  REST / SDK                     │
│         ▼                                 │
│  ┌─────────────────────────────────────┐  │
│  │  Fireagent Control Plane            │  │
│  │  (local API or remote worker)       │  │
│  └──────┬──────────────────────────────┘  │
│         │  Firecracker microVM             │
│         ▼                                 │
│  ┌─────────────────────────────────────┐  │
│  │  Sandbox Session                    │  │
│  │  - Isolated Linux environment       │  │
│  │  - cgroup resource limits           │  │
│  │  - Network policies enforced        │  │
│  │  - Stateful across commands         │  │
│  └─────────────────────────────────────┘  │
└──────────────────────────────────────────┘
```

---

## Prerequisites

- **Fireagent installed**: `pip install fireagent`
- **Fireagent API running**: `fireagent-api &` (or remote host)
- **Claude Code**: Installed and configured

---

## Integration Methods

### Method 1: Fireagent Extension for Claude Code (Recommended)

The Fireagent extension wraps Claude Code's command execution so every shell call, file write, and test run happens inside a sandbox.

**File: `fireagent_claude.py`** — Claude Code extension entry point:

```python
#!/usr/bin/env python3
"""Fireagent extension for Claude Code.

Installed as a Claude Code tool provider. Each Claude Code session
gets an isolated Fireagent sandbox with controlled resource limits.
"""

import os
import sys
import json
import fireagent as fa
from pathlib import Path


class FireagentClaudeExtension:
    """Bridge between Claude Code and Fireagent sandboxes."""

    def __init__(
        self,
        image: str = "ubuntu:24.04",
        vcpus: int = 2,
        memory_mib: int = 1024,
        disk_mib: int = 2048,
        ttl_seconds: int = 3600,
        idle_timeout: int = 300,
    ):
        self.image = image
        self.vcpus = vcpus
        self.memory_mib = memory_mib
        self.disk_mib = disk_mib
        self.ttl_seconds = ttl_seconds
        self.idle_timeout = idle_timeout
        self._sandbox = None

    def start_session(self) -> str:
        """Create a new sandbox for a Claude Code session."""
        self._sandbox = fa.create(
            image=self.image,
            vcpus=self.vcpus,
            memory_mib=self.memory_mib,
            disk_mib=self.disk_mib,
            ttl_seconds=self.ttl_seconds,
            idle_timeout_seconds=self.idle_timeout,
            labels={"agent": "claude-code"},
        )
        self._sandbox.wait_for("ready", timeout_seconds=60)

        # Pre-install common Claude Code tools
        self._sandbox.exec(
            "apt-get update -qq && apt-get install -y -qq "
            "git curl jq python3-pip ripgrep fd-find tree 2>/dev/null"
        )
        return self._sandbox.id

    def exec_command(
        self,
        command: str,
        working_dir: str | None = None,
        timeout: int = 60,
    ) -> dict:
        """Execute a shell command inside the sandbox.

        This is the primary method Claude Code calls for tool execution.
        """
        if self._sandbox is None:
            raise RuntimeError("No active sandbox session. Call start_session() first.")

        try:
            result = self._sandbox.exec(
                command,
                working_dir=working_dir,
                execution_timeout_seconds=timeout,
            )
            return {
                "exit_code": result.exit_code,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "timed_out": result.timed_out,
            }
        except fa.CommandTimeoutError:
            return {
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Command timed out after {timeout}s",
                "timed_out": True,
            }

    def read_file(self, path: str) -> str:
        """Read a file from inside the sandbox."""
        if self._sandbox is None:
            raise RuntimeError("No active sandbox session.")
        result = self._sandbox.exec(f"cat {path}")
        if result.exit_code != 0:
            raise FileNotFoundError(f"Cannot read {path}: {result.stderr}")
        return result.stdout

    def write_file(self, path: str, content: str) -> None:
        """Write a file inside the sandbox."""
        if self._sandbox is None:
            raise RuntimeError("No active sandbox session.")
        # Safe: content is piped via stdin, not concatenated into shell
        result = self._sandbox.exec(
            f"mkdir -p $(dirname {path}) && cat > {path}",
            stdin=content,
        )
        if result.exit_code != 0:
            raise RuntimeError(f"Cannot write {path}: {result.stderr}")

    def list_files(self, path: str = ".") -> list:
        """List directory contents inside the sandbox."""
        if self._sandbox is None:
            raise RuntimeError("No active sandbox session.")
        result = self._sandbox.exec(f"find {path} -maxdepth 2 -ls 2>/dev/null || ls -laR {path}")
        return result.stdout.splitlines()

    def install_packages(self, packages: list[str]) -> dict:
        """Install system packages inside the sandbox."""
        if not packages:
            return {"installed": 0, "output": ""}
        result = self._sandbox.exec(
            f"apt-get update -qq && apt-get install -y -qq {' '.join(packages)} 2>&1",
            execution_timeout_seconds=120,
        )
        return {
            "installed": len(packages),
            "output": result.stdout + result.stderr,
            "exit_code": result.exit_code,
        }

    def end_session(self) -> None:
        """Stop and delete the sandbox."""
        if self._sandbox is None:
            return
        try:
            self._sandbox.stop()
            self._sandbox.delete()
        except Exception:
            pass
        self._sandbox = None


# ── CLI entry point for Claude Code tool subprocess ──────────────────────

def main():
    """Entry point; reads JSON commands from stdin, writes JSON results to stdout.

    Claude Code calls this subprocess for each tool invocation.
    """
    extension = FireagentClaudeExtension(
        image=os.environ.get("FIREAGENT_IMAGE", "ubuntu:24.04"),
        vcpus=int(os.environ.get("FIREAGENT_VCPUS", "2")),
        memory_mib=int(os.environ.get("FIREAGENT_MEMORY_MIB", "1024")),
        disk_mib=int(os.environ.get("FIREAGENT_DISK_MIB", "2048")),
    )

    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue

        action = request.get("action", "")

        if action == "start_session":
            sandbox_id = extension.start_session()
            print(json.dumps({"sandbox_id": sandbox_id}))

        elif action == "exec":
            result = extension.exec_command(
                command=request["command"],
                working_dir=request.get("working_dir"),
                timeout=request.get("timeout", 60),
            )
            print(json.dumps(result))

        elif action == "read_file":
            try:
                content = extension.read_file(request["path"])
                print(json.dumps({"content": content}))
            except FileNotFoundError as e:
                print(json.dumps({"error": str(e)}))

        elif action == "write_file":
            try:
                extension.write_file(request["path"], request["content"])
                print(json.dumps({"status": "ok"}))
            except RuntimeError as e:
                print(json.dumps({"error": str(e)}))

        elif action == "install_packages":
            result = extension.install_packages(request.get("packages", []))
            print(json.dumps(result))

        elif action == "end_session":
            extension.end_session()
            print(json.dumps({"status": "ok"}))
            break

        sys.stdout.flush()


if __name__ == "__main__":
    main()
```

### Method 2: Claude Code via CLI Tool (No Extension Code)

If Claude Code can run shell commands directly, wrap Fireagent CLI calls:

**Claude Code system prompt instruction:**

```
You have access to a Fireagent sandbox. Use these commands:

  fireagent-helper exec "<shell command>"    # Run a command
  fireagent-helper read <path>               # Read a file
  fireagent-helper write <path> <content>    # Write a file
  fireagent-helper status                    # Check sandbox state
  fireagent-helper end                       # Clean up
```

**File: `fireagent-helper.sh`**

```bash
#!/bin/bash
# fireagent-helper — CLI wrapper for Claude Code <> Fireagent shell integration
set -euo pipefail

FIREAGENT_API="${FIREAGENT_API:-http://127.0.0.1:8000}"
SESSION_FILE="${FIREAGENT_SESSION_FILE:-/tmp/.fireagent_session}"

ensure_session() {
    if [[ ! -f "$SESSION_FILE" ]]; then
        echo "No active session. Creating sandbox..." >&2
        local response
        response=$(fireagent sandboxes create \
            --image "${FIREAGENT_IMAGE:-ubuntu:24.04}" \
            --vcpus "${FIREAGENT_VCPUS:-2}" \
            --memory "${FIREAGENT_MEMORY_MIB:-1024}" \
            --disk "${FIREAGENT_DISK_MIB:-2048}" \
            --format json)
        local sid
        sid=$(echo "$response" | jq -r '.id // empty')
        if [[ -z "$sid" ]]; then
            echo "Failed to create sandbox: $response" >&2
            exit 1
        fi
        echo "$sid" > "$SESSION_FILE"
        echo "Sandbox $sid created. Waiting for ready..." >&2
        fireagent sandboxes wait "$sid" ready --timeout 60 >/dev/null 2>&1 || {
            echo "Sandbox $sid failed to become ready" >&2
            rm -f "$SESSION_FILE"
            exit 1
        }
    fi
    SANDOX_ID=$(cat "$SESSION_FILE")
}

case "${1:-help}" in
    exec)
        ensure_session
        shift
        local cmd="$*"
        fireagent sandboxes exec "$SANDOX_ID" --command "$cmd" 2>&1 || true
        ;;
    read)
        ensure_session
        fireagent sandboxes exec "$SANDOX_ID" --command "cat '$2'" 2>&1
        ;;
    write)
        ensure_session
        fireagent sandboxes exec "$SANDOX_ID" --command "mkdir -p \"\$(dirname '$2')\" && cat > '$2'" --stdin "$3" 2>&1
        ;;
    status)
        ensure_session
        fireagent sandboxes get "$SANDOX_ID" --format json | jq '.state'
        ;;
    end)
        if [[ -f "$SESSION_FILE" ]]; then
            local sid
            sid=$(cat "$SESSION_FILE")
            fireagent sandboxes stop "$sid" 2>/dev/null || true
            fireagent sandboxes delete "$sid" 2>/dev/null || true
            rm -f "$SESSION_FILE"
            echo "Sandbox $sid cleaned up."
        fi
        ;;
    *)
        echo "Usage: fireagent-helper exec|read|write|status|end"
        exit 1
        ;;
esac
```

### Method 3: Direct SDK Integration (For Custom Claude Code Tool Providers)

For custom Claude Code implementations that support Python tool providers:

```python
# claude_tools/fireagent_tools.py
from fireagent import FireagentClient, CommandOomKilledError, CommandTimeoutError

client = FireagentClient()

# Registered as Claude Code tools:
tools = [
    {
        "name": "sandbox_exec",
        "description": "Execute a shell command inside an isolated Fireagent sandbox microVM",
        "input_schema": {
            "type": "object",
            "properties": {
                "sandbox_id": {"type": "string", "description": "Sandbox ID from sandbox_create"},
                "command": {"type": "string", "description": "Shell command to run"},
                "working_dir": {"type": "string", "description": "Working directory (optional)"},
                "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 60},
            },
            "required": ["sandbox_id", "command"],
        },
    },
    {
        "name": "sandbox_create",
        "description": "Create a new isolated Fireagent sandbox microVM",
        "input_schema": {
            "type": "object",
            "properties": {
                "image": {"type": "string", "description": "Guest image", "default": "ubuntu:24.04"},
                "vcpus": {"type": "integer", "description": "Virtual CPUs", "default": 2},
                "memory_mib": {"type": "integer", "description": "Memory in MiB", "default": 1024},
                "disk_mib": {"type": "integer", "description": "Disk in MiB", "default": 2048},
            },
        },
    },
    {
        "name": "sandbox_stop",
        "description": "Stop and delete a sandbox microVM",
        "input_schema": {
            "type": "object",
            "properties": {
                "sandbox_id": {"type": "string"},
            },
            "required": ["sandbox_id"],
        },
    },
]

def sandbox_create(image="ubuntu:24.04", vcpus=2, memory_mib=1024, disk_mib=2048):
    sb = client.create(image=image, vcpus=vcpus, memory_mib=memory_mib, disk_mib=disk_mib)
    sb.wait_for("ready")
    return {"sandbox_id": sb.id}

def sandbox_exec(sandbox_id, command, working_dir=None, timeout=60):
    sb = client.get(sandbox_id)
    try:
        result = sb.exec(command, working_dir=working_dir, execution_timeout_seconds=timeout)
        return {
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    except CommandTimeoutError:
        return {"exit_code": -1, "stdout": "", "stderr": "timed out"}
    except CommandOomKilledError:
        return {"exit_code": -2, "stdout": "", "stderr": "out of memory"}

def sandbox_stop(sandbox_id):
    sb = client.get(sandbox_id)
    sb.stop()
    sb.delete()
    return {"status": "deleted"}
```

---

## Lifecycle in Agentic Workflows

A typical Claude Code session with Fireagent follows this pattern:

```
┌──────────────────────────────────────────────────────┐
│ Claude Code Session Flow                              │
│                                                       │
│ 1. Session Start                                      │
│    ├── Create sandbox (2 vCPU, 1 GB RAM, 2 GB disk)  │
│    ├── Wait for "ready" state                         │
│    └── Pre-install common tools (git, jq, rg, etc.)  │
│                                                       │
│ 2. Claude Works                                       │
│    ├── Read files from repo   → sandbox.exec("cat")   │
│    ├── Edit source files      → sandbox.exec("cat >") │
│    ├── Install deps           → sandbox.exec("pip")   │
│    ├── Run tests              → sandbox.exec("pytest")│
│    └── Git operations         → sandbox.exec("git")   │
│                                                       │
│ 3. Session End                                        │
│    ├── Export diff / results                          │
│    ├── Stop sandbox                                   │
│    └── Delete sandbox (workspace destroyed)           │
└──────────────────────────────────────────────────────┘
```

---

## Configuration Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `FIREAGENT_IMAGE` | `ubuntu:24.04` | Guest image name/version |
| `FIREAGENT_VCPUS` | `2` | Virtual CPUs per sandbox |
| `FIREAGENT_MEMORY_MIB` | `1024` | Memory per sandbox (MiB) |
| `FIREAGENT_DISK_MIB` | `2048` | Disk per sandbox (MiB) |
| `FIREAGENT_TTL` | `3600` | Max sandbox lifetime (seconds) |
| `FIREAGENT_IDLE_TIMEOUT` | `300` | Auto-stop after idle (seconds) |
| `FIREAGENT_API` | `http://127.0.0.1:8000` | API base URL |
| `FIREAGENT_SESSION_FILE` | `/tmp/.fireagent_session` | Session tracking file |

---

## Security Considerations

| Concern | Mitigation |
|---------|------------|
| **Claude generates `rm -rf /`** | Runs inside microVM — host filesystem untouched |
| **Claude tries to access network** | Network policies block/allow specific destinations |
| **Claude runs for too long** | TTL and idle timeout auto-terminate |
| **Claude consumes all RAM** | cgroups enforce per-sandbox memory limit |
| **Claude creates malware** | Sandbox deleted after session; no persistence |
| **Multiple concurrent sessions** | Each sandbox is fully isolated from others |

---

## Example: Automated PR Review with Claude Code + Fireagent

```python
#!/usr/bin/env python3
"""Automated PR review: one sandbox per PR, Claude Code reviews, result returned."""

import fireagent as fa
import json, sys, os

def review_pr(repo_url: str, pr_number: int, pr_branch: str) -> dict:
    """Review a pull request inside an isolated sandbox."""

    sb = fa.create(
        image="ubuntu:24.04",
        vcpus=4, memory_mib=2048, disk_mib=4096,
        ttl_seconds=1800,
        workspace={"type": "git", "url": repo_url, "ref": pr_branch},
        labels={"task": "pr-review", "pr": str(pr_number)},
    )
    sb.wait_for("ready")

    # Install review tools
    sb.exec("apt-get update -qq && apt-get install -y -qq git jq shellcheck")
    sb.exec("pip install -q pylint mypy black bandit")

    # Run static analysis
    results = {}
    for tool, cmd in [
        ("pylint", "pylint --output-format=json src/ 2>/dev/null || true"),
        ("mypy", "mypy src/ --ignore-missing-imports 2>/dev/null || true"),
        ("bandit", "bandit -r src/ -f json 2>/dev/null || true"),
        ("shellcheck", "shellcheck scripts/*.sh 2>/dev/null || true"),
    ]:
        r = sb.exec(cmd, execution_timeout_seconds=120)
        results[tool] = {"exit_code": r.exit_code, "output": r.stdout + r.stderr}

    # Get diff
    diff = sb.exec("git diff origin/main...HEAD 2>/dev/null || git diff")
    results["diff"] = diff.stdout

    # Clean up
    sb.stop()
    sb.delete()

    return results


if __name__ == "__main__":
    repo = sys.argv[1]
    pr = int(sys.argv[2])
    branch = sys.argv[3]
    report = review_pr(repo, pr, branch)
    print(json.dumps(report, indent=2))
```

---

## See Also

- [OpenAI Codex Integration](openai-codex.md) — Same isolation for Codex-powered agents
- [Generic Agent Pattern](generic-agent.md) — General pattern for any coding agent
- [SDK Quickstart](../sdk/quickstart.md) — Fireagent Python SDK basics
- [Architecture: Host Agent](../architecture/host-agent.md) — How sandboxes are managed
- [Security: Isolation Guarantees](../security/isolation.md) — What Fireagent protects