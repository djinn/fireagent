# Reference

## Client

The main entry point for the SDK.

### `create()`

Creates a new sandbox.

```python
sandbox = fa.create(
    image="ubuntu:24.04",
    vcpus=2,
    memory_mib=1024,
    disk_mib=2048,
    ttl_seconds=3600,
    idle_timeout_seconds=600,
    network_policy={"rules": [...]},
    workspace={"type": "git", "url": "..."},
    labels={"job_id": "job-123"}
)
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `image` | str | Yes | Guest image name and version |
| `vcpus` | int | Yes | Number of virtual CPUs |
| `memory_mib` | int | Yes | Guest memory in MiB |
| `disk_mib` | int | Yes | Writable workspace capacity in MiB |
| `ttl_seconds` | int | No | Maximum sandbox lifetime in seconds |
| `idle_timeout_seconds` | int | No | Stop after idle for this many seconds |
| `network_policy` | dict | No | Network rules |
| `workspace` | dict | No | Task workspace configuration |
| `labels` | dict | No | Caller-supplied metadata |
| `idempotency_key` | str | No | Idempotency key for retry safety |

Returns: `Sandbox` object

### `get()`

Gets an existing sandbox.

```python
sandbox = fa.get("sb-a1b2c3d4")
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `id` | str | Yes | Sandbox ID |

Returns: `Sandbox` object

### `list()`

Lists all sandboxes.

```python
sandboxes = fa.list()
```

Returns: List of `Sandbox` objects

### `set_api_key()`

Sets the API key.

```python
fa.set_api_key("sk-abc123...")
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `key` | str | Yes | API key |

### `set_base_url()`

Sets the API base URL.

```python
fa.set_base_url("https://api.fireagent.example.com")
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `url` | str | Yes | Base URL |

### `set_timeout()`

Sets the request timeout.

```python
fa.set_timeout(30)
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `timeout` | int | Yes | Timeout in seconds |

### `set_retries()`

Sets the number of retries.

```python
fa.set_retries(3)
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `retries` | int | Yes | Number of retries |

### `set_retry_delay()`

Sets the retry delay.

```python
fa.set_retry_delay(0.5)
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `delay` | float | Yes | Delay in seconds |

## Sandbox

Represents a sandbox.

### `exec()`

Executes a command in the sandbox.

```python
result = sb.exec("echo 'Hello from $HOSTNAME'")
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `command` | str | Yes | Command to run |
| `working_dir` | str | No | Current working directory |
| `environment` | dict | No | Environment variables |
| `execution_timeout_seconds` | int | No | Command timeout |
| `stdin` | str | No | Standard input |

Returns: `CommandResult` object

### `wait_for()`

Waits for the sandbox to reach a given state.

```python
sb.wait_for("ready")
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `state` | str | Yes | Target state |
| `timeout_seconds` | int | No | Timeout in seconds |

### `status()`

Gets the current status of the sandbox.

```python
status = sb.status()
```

Returns: `SandboxStatus` object

### `stop()`

Stops the sandbox.

```python
sb.stop()
```

### `delete()`

Deletes the sandbox.

```python
sb.delete()
```

### `wait_for()`

Waits for the sandbox to reach a given state.

```python
sb.wait_for("stopped")
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `state` | str | Yes | Target state |
| `timeout_seconds` | int | No | Timeout in seconds |

### `is_ready()`

Checks if the sandbox is ready.

```python
if sb.is_ready():
    print("Sandbox is ready!")
```

Returns: `bool`

### `is_running()`

Checks if the sandbox is running.

```python
if sb.is_running():
    print("Sandbox is running!")
```

Returns: `bool`

## CommandResult

Represents the result of a command execution.

### `stdout`

Standard output.

### `stderr`

Standard error.

### `exit_code`

Command exit code.

### `start_time`

Start time (ISO 8601 string).

### `finish_time`

Finish time (ISO 8601 string).

### `timed_out`

Was the command killed by timeout?

### `oom_killed`

Was the command killed by OOM?

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

## Async methods

### `acreate()`

Asynchronous create.

```python
sb = await fa.acreate(...)
```

### `aexec()`

Asynchronous exec.

```python
result = await sb.aexec(...)
```

### `astop()`

Asynchronous stop.

```python
await sb.astop()
```

### `adelete()`

Asynchronous delete.

```python
await sb.adelete()
```

### `await_for()`

Asynchronous wait_for.

```python
await sb.await_for("ready")
```

## Next steps

- [ ] Add support for `stream()` for streaming output
- [ ] Add support for `on_event()` for event callbacks
- [ ] Add support for `with` context manager
- [ ] Add support for `retry_on_failure` decorator
- [ ] Add support for `get_logs()`
- [ ] Add support for `get_metrics()`