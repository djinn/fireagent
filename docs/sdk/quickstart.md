# Quickstart

## Prerequisites

- Python 3.10 or higher
- `pip` installed
- An API key from the Fireagent control plane

## Installation

```bash
pip install fireagent
```

## Set up API key

```bash
export FIREAGENT_API_KEY="sk-abc123..."
```

Or set it in code:

```python
import fireagent as fa

fa.set_api_key("sk-abc123...")
```

## Create a sandbox

```python
import fireagent as fa

# Create a sandbox with 2 vCPUs, 1 GiB memory, 2 GiB disk
sb = fa.create(
    image="ubuntu:24.04",
    vcpus=2,
    memory_mib=1024,
    disk_mib=2048,
    ttl_seconds=3600,
    labels={"job_id": "job-123"}
)

print(f"Created sandbox: {sb.id}")
```

## Wait for ready state

```python
# Wait for the sandbox to be ready
sb.wait_for("ready")

print(f"Sandbox {sb.id} is ready!")
```

## Execute a command

```python
# Run a command in the sandbox
result = sb.exec("echo 'Hello from $HOSTNAME'")

print(result.stdout)  # Hello from sb-a1b2c3d4
print(result.exit_code)  # 0
```

## Run a test

```python
# Run a Python test
result = sb.exec("python3 -c 'print(f"Hello from {__import__("platform").node()}"'"')

print(result.stdout)  # Hello from sb-a1b2c3d4
```

## Stop and delete

```python
# Stop the sandbox
sb.stop()

# Delete the sandbox
sb.delete()
```

## Full example

```python
import fireagent as fa

# Create sandbox
sb = fa.create(
    image="ubuntu:24.04",
    vcpus=1,
    memory_mib=512,
    disk_mib=1024,
    ttl_seconds=1800,
    labels={"job_id": "job-123"}
)

# Wait for ready
sb.wait_for("ready")

# Run command
result = sb.exec("echo 'Hello from $HOSTNAME'")
print(result.stdout)

# Stop
sb.stop()

# Delete
sb.delete()
```

## Next steps

- [ ] Use `workspace` to clone a git repo
- [ ] Use `network_policy` to allow specific outbound traffic
- [ ] Use `async` methods for concurrent operations
- [ ] Use `wait_for()` with custom conditions
- [ ] Use `stream()` for streaming output
- [ ] Use `on_event()` for event callbacks
- [ ] Use `with` context manager for automatic cleanup