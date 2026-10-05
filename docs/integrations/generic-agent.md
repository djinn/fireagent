# Generic Agent Integration Pattern

The general pattern for wiring **any AI coding agent** to Fireagent for safe, stateful, isolated execution.

---

## Overview

Whether you're using Claude Code, OpenAI Codex, a custom agent framework, or an open-source coding assistant, the integration follows the same architectural pattern:

```
+---------------------------------------------------+
| AI Coding Agent (any framework)                    |
|                                                     |
|  Tools available to the agent:                      |
|    - sandbox_create -> returns sandbox_id           |
|    - sandbox_exec(sandbox_id, command) -> result    |
|    - sandbox_read(sandbox_id, path) -> content      |
|    - sandbox_write(sandbox_id, path, content) -> ok |
|    - sandbox_stop(sandbox_id) -> cleaned up         |
|                                                     |
+--------------------+-------------------------------+
                     |
          SDK / REST API
                     |
                     v
+---------------------------------------------------+
| Fireagent Control Plane + Firecracker microVMs     |
| - One sandbox per agent session                    |
| - Resource limits, network policies, TTL enforced  |
| - Stateful: files persist across commands          |
| - Disposable: stop+delete = complete cleanup       |
+---------------------------------------------------+
```

---

## The Three Integration Patterns

### Pattern A: SDK Import (Python Agent)

If your agent runs Python code, import `fireagent` directly:

```python
import fireagent as fa

# Create once per session
sb = fa.create(
    image="ubuntu:24.04",
    vcpus=2,
    memory_mib=1024,
    disk_mib=2048,
    ttl_seconds=3600,
    idle_timeout_seconds=300,
    labels={"agent": "my-agent", "session": "session-123"},
)
sb.wait_for("ready")

# Agent tool implementations
def exec_command(command, timeout=30):
    return sb.exec(command, execution_timeout_seconds=timeout)

def read_file(path):
    result = sb.exec(f"cat {path}")
    return result.stdout

def write_file(path, content):
    return sb.exec(
        f"mkdir -p $(dirname {path}) && cat > {path}",
        stdin=content,
    )

def list_directory(path="."):
    result = sb.exec(f"ls -la {path}")
    return result.stdout

# ... agent uses these tools ...

# Cleanup
sb.stop()
sb.delete()
```

### Pattern B: CLI Wrapper (Shell-Only Agent)

If your agent can only run shell commands, wrap Fireagent CLI:

```bash
#!/bin/bash
# fa-agent-tool.sh — shell-based fireagent integration for any agent

FA_CLI="fireagent"
SESSION_FILE="/tmp/.fa_session_$$"

sandbox_create() {
    local image="${1:-ubuntu:24.04}" vcpus="${2:-2}" mem="${3:-1024}" disk="${4:-2048}"
    local response
    response=$($FA_CLI sandboxes create \
        --image "$image" --vcpus "$vcpus" --memory "$mem" --disk "$disk" \
        --format json 2>&1)
    local sid
    sid=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])" 2>/dev/null)
    if [ -z "$sid" ]; then
        echo "ERROR: $response" >&2
        return 1
    fi
    echo "$sid" > "$SESSION_FILE"
    $FA_CLI sandboxes wait "$sid" ready --timeout 60 >/dev/null 2>&1
    echo "$sid"
}

sandbox_exec() {
    local sid="$1" cmd="$2" timeout="${3:-30}"
    $FA_CLI sandboxes exec "$sid" --command "$cmd" 2>&1 || true
}

sandbox_read() {
    local sid="$1" path="$2"
    $FA_CLI sandboxes exec "$sid" --command "cat '$path' 2>/dev/null || echo 'FILE_NOT_FOUND'" 2>&1
}

sandbox_write() {
    local sid="$1" path="$2" content="$3"
    # Escape content for safe shell passing
    local encoded
    encoded=$(echo "$content" | base64 -w0)
    $FA_CLI sandboxes exec "$sid" \
        --command "mkdir -p \"\$(dirname '$path')\" && echo '$encoded' | base64 -d > '$path'" 2>&1
}

sandbox_stop() {
    local sid="$1"
    $FA_CLI sandboxes stop "$sid" 2>/dev/null || true
    $FA_CLI sandboxes delete "$sid" 2>/dev/null || true
    rm -f "$SESSION_FILE"
    echo "Cleaned up"
}

# Dispatch
case "${1:-help}" in
    create)  sandbox_create "$2" "$3" "$4" "$5" ;;
    exec)    sandbox_exec "$2" "$3" "$4" ;;
    read)    sandbox_read "$2" "$3" ;;
    write)   sandbox_write "$2" "$3" "$4" ;;
    stop)    sandbox_stop "$2" ;;
    *)       echo "Usage: $0 {create|exec|read|write|stop} [args...]" ;;
esac
```

### Pattern C: REST API (Any Language / HTTP Agent)

If your agent speaks HTTP, hit the Fireagent API directly:

```bash
# Create sandbox
curl -s -X POST http://127.0.0.1:8000/v1/sandboxes \
  -H "Content-Type: application/json" \
  -d '{"image": "ubuntu:24.04", "vcpus": 2, "memory_mib": 1024, "disk_mib": 2048}' \
  | jq '.id'

# Execute command
curl -s -X POST http://127.0.0.1:8000/v1/sandboxes/$SANDOX_ID/exec \
  -H "Content-Type: application/json" \
  -d '{"command": "python3 --version"}' \
  | jq '{stdout, stderr, exit_code}'

# Stop sandbox
curl -s -X POST http://127.0.0.1:8000/v1/sandboxes/$SANDOX_ID/stop

# Delete sandbox
curl -s -X DELETE http://127.0.0.1:8000/v1/sandboxes/$SANDOX_ID

# Get status
curl -s http://127.0.0.1:8000/v1/sandboxes/$SANDOX_ID | jq '.state'
```

---

## Agent Tool Definitions

When defining tools for your agent, here are the standard Fireagent tool descriptors:

```json
[
  {
    "name": "sandbox_create",
    "description": "Create an isolated Linux sandbox microVM for safe command execution",
    "parameters": {
      "type": "object",
      "properties": {
        "image": {"type": "string", "description": "Guest image name", "default": "ubuntu:24.04"},
        "vcpus": {"type": "integer", "description": "Number of virtual CPUs", "default": 2},
        "memory_mib": {"type": "integer", "description": "Memory in MiB", "default": 1024},
        "disk_mib": {"type": "integer", "description": "Disk space in MiB", "default": 2048}
      }
    }
  },
  {
    "name": "sandbox_exec",
    "description": "Execute a shell command inside an existing sandbox and return output",
    "parameters": {
      "type": "object",
      "properties": {
        "sandbox_id": {"type": "string", "description": "ID of sandbox to execute in"},
        "command": {"type": "string", "description": "Shell command to run"},
        "timeout": {"type": "integer", "description": "Execution timeout in seconds", "default": 30}
      },
      "required": ["sandbox_id", "command"]
    }
  },
  {
    "name": "sandbox_read_file",
    "description": "Read a file from inside the sandbox",
    "parameters": {
      "type": "object",
      "properties": {
        "sandbox_id": {"type": "string"},
        "path": {"type": "string", "description": "Absolute path to file"}
      },
      "required": ["sandbox_id", "path"]
    }
  },
  {
    "name": "sandbox_write_file",
    "description": "Write content to a file inside the sandbox",
    "parameters": {
      "type": "object",
      "properties": {
        "sandbox_id": {"type": "string"},
        "path": {"type": "string", "description": "Absolute path to file"},
        "content": {"type": "string", "description": "File content"}
      },
      "required": ["sandbox_id", "path", "content"]
    }
  },
  {
    "name": "sandbox_install",
    "description": "Install system or Python packages inside the sandbox",
    "parameters": {
      "type": "object",
      "properties": {
        "sandbox_id": {"type": "string"},
        "packages": {"type": "array", "items": {"type": "string"}, "description": "Package names"},
        "type": {"type": "string", "enum": ["apt", "pip", "npm"], "default": "pip"}
      },
      "required": ["sandbox_id", "packages"]
    }
  },
  {
    "name": "sandbox_stop",
    "description": "Stop and permanently delete a sandbox (all data lost)",
    "parameters": {
      "type": "object",
      "properties": {
        "sandbox_id": {"type": "string"}
      },
      "required": ["sandbox_id"]
    }
  }
]
```

---

## Session Lifecycle Guidance

For agent frameworks, we recommend:

| Phase | Action | Why |
|-------|--------|-----|
| **Session start** | `sandbox_create()` | Agent begins work |
| **First command** | Wait for "ready" state | Blocks until microVM boots (~150ms) |
| **Tool calls** | `sandbox_exec()` with timeouts | Prevents runaway commands |
| **File I/O** | `sandbox_read/write_file` via stdin | Avoids shell escaping bugs |
| **Idle detection** | Set `idle_timeout_seconds` | Sandbox auto-stops if agent stalls |
| **Session end** | `sandbox_stop()` + `sandbox_delete()` | Guarantees cleanup |
| **Error** | `sandbox_stop()` in finally block | No orphaned sandboxes |

---

## Security Notes for All Agents

| Rule | Rationale |
|------|-----------|
| **Never expose sandbox_id to untrusted users** | Sandbox ID + open API = shell access |
| **Always set TTL and idle timeout** | Prevents sandbox accumulation |
| **Always stop + delete in `finally`** | Prevents resource leaks |
| **Use network policies** | Block outbound by default; allow only needed hosts |
| **Never share sandboxes between agents** | Each agent gets its own microVM |
| **Treat guest as hostile** | The hostagent should validate all guest outputs |

---

## Compatibility Matrix

| Agent / Framework | SDK Import | CLI Wrapper | REST API | Notes |
|-------------------|:----------:|:-----------:|:--------:|-------|
| Claude Code | ✓ | ✓ | ✓ | See [dedicated guide](claude-code.md) |
| OpenAI Codex | ✓ | ✓ | ✓ | See [dedicated guide](openai-codex.md) |
| LangChain | ✓ | ✓ | ✓ | Use `sandbox_exec` as a custom Tool |
| AutoGPT | ✓ | ✓ | ✓ | CLI wrapper works well |
| CrewAI | ✓ | ✓ | ✓ | SDK import for custom tools |
| smolagents (Hugging Face) | ✓ | ✓ | ✓ | Wrap as `Tool` object |
| Custom Python agent | ✓ | ✓ | ✓ | SDK import is simplest |
| Shell-only agent | ✗ | ✓ | ✓ | CLI wrapper required |
| HTTP-only agent | ✗ | ✗ | ✓ | REST API calls |

---

## See Also

- [Claude Code Integration](claude-code.md) — Full guide for Claude Code
- [OpenAI Codex Integration](openai-codex.md) — Full guide for OpenAI Codex
- [SDK Quickstart](../sdk/quickstart.md) — Fireagent Python SDK
- [API Reference](../api/index.md) — REST API documentation
- [Architecture: Sandbox Lifecycle](../architecture/lifecycle.md) — State machine details
- [Security: Isolation Guarantees](../security/isolation.md) — What sandboxes protect