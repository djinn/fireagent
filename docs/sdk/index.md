# Python SDK

## Overview

The **Fireagent Python SDK** provides a clean, Pythonic interface to the Fireagent API. It handles authentication, retries, polling, and structured results.

```python
import fireagent as fa

# Create a sandbox
sb = fa.create(
    image="ubuntu:24.04",
    vcpus=2,
    memory_mib=1024,
    disk_mib=2048,
    ttl_seconds=3600,
    labels={"job_id": "job-123"}
)

# Execute a command
result = sb.exec("echo 'Hello from $HOSTNAME'")
print(result.stdout)  # Hello from sb-a1b2c3d4

# Stop the sandbox
sb.stop()

# Delete the sandbox
sb.delete()
```

## Installation

```bash
pip install fireagent
```

## Authentication

The SDK uses API keys. Set the key via environment variable:

```bash
export FIREAGENT_API_KEY="sk-abc123..."
```

Or pass it directly:

```python
import fireagent as fa

fa.set_api_key("sk-abc123...")
```

## Core classes

### `Sandbox`

Represents a sandbox. It has methods for:

- `create()` – Create a new sandbox
- `exec()` – Execute a command
- `status()` – Get current state
- `stop()` – Stop the sandbox
- `delete()` – Delete the sandbox

### `Client`

The main entry point. It provides:

- `create()` – Create a new sandbox
- `get()` – Get an existing sandbox
- `list()` – List all sandboxes
- `set_api_key()` – Set the API key
- `set_base_url()` – Set the API base URL

## Usage examples

### Quickstart

```python
import fireagent as fa

# Create a sandbox
sb = fa.create(
    image="ubuntu:24.04",
    vcpus=2,
    memory_mib=1024,
    disk_mib=2048,
    ttl_seconds=3600,
    labels={"job_id": "job-123"}
)

# Wait for it to be ready
sb.wait_for("ready")

# Execute a command
result = sb.exec("python3 -c 'print(\"Hello from {__import__(\"platform\").node()}\")'")
print(result.stdout)  # Hello from sb-a1b2c3d4

# Stop and delete
sb.stop()
sb.delete()
```

### With workspace

```python
import fireagent as fa

# Create from git repo
sb = fa.create(
    image="ubuntu:24.04",
    workspace={
        "type": "git",
        "url": "https://github.com/myorg/myrepo.git",
        "ref": "main"
    },
    vcpus=1,
    memory_mib=512,
    disk_mib=1024,
    ttl_seconds=1800
)

# Wait for ready
sb.wait_for("ready")

# Run tests
result = sb.exec("cd /workspace && python -m pytest")
print(result.stdout)

# Stop
sb.stop()
```

### Async support

```python
import fireagent as fa
import asyncio

async def main():
    sb = await fa.acreate(
        image="ubuntu:24.04",
        vcpus=2,
        memory_mib=1024,
        disk_mib=2048
    )
    
    result = await sb.aexec("echo 'Hello from async'")
    print(result.stdout)
    
    await sb.astop()
    await sb.adelete()

asyncio.run(main())
```

## Configuration

Set global options:

```python
import fireagent as fa

fa.set_base_url("https://api.fireagent.example.com")
fa.set_timeout(30)
fa.set_retries(3)
fa.set_retry_delay(0.5)
```

## Exception hierarchy

| Exception | When thrown |
|-----------|-------------|
| `FireagentError` | Base exception |
| `InvalidRequestError` | Invalid request (400) |
| `UnauthorizedError` | Invalid API key (401) |
| `ForbiddenError` | Access denied (403) |
| `NotFoundError` | Sandbox not found (404) |
| `ConflictError` | Duplicate sandbox (409) |
| `RateLimitError` | Too many requests (429) |
| `InternalServerError` | Server error (500) |
| `ServiceUnavailableError` | System overloaded (503) |
| `SandboxFailedError` | Sandbox is in `failed` state |
| `SandboxTimeoutError` | Sandbox timed out during wait |
| `CommandTimeoutError` | Command exceeded timeout |
| `CommandOomKilledError` | Command was killed by OOM |
| `NetworkDenialError` | Network policy violation |

## Next steps

- [ ] Add support for `wait_for()` with custom conditions
- [ ] Add support for `stream()` for streaming stdout/stderr
- [ ] Add support for `on_event()` for event callbacks
- [ ] Add support for `with` context manager
- [ ] Add support for `retry_on_failure` decorator
- [ ] Add support for `get_logs()`
- [ ] Add support for `get_metrics()`