# Command Execution

## Execute command

Executes a command in the sandbox.

### Endpoint

`POST /v1/sandboxes/{id}/exec`

### Request

```json

  "command": "python3 -c 'print(f"Hello from {__import__("platform").node()}"'"",
  "working_dir": "/workspace",
  "environment": {
    "PATH": "/usr/local/bin:/usr/bin:/bin",
    "PYTHONPATH": "/workspace"
  },
  "execution_timeout_seconds": 300,
  "stdin": ""
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `command` | string | Yes | Command to run |
| `working_dir` | string | No | Current working directory |
| `environment` | object | No | Environment variables (from allowlist) |
| `execution_timeout_seconds` | integer | No | Command timeout in seconds |
| `stdin` | string | No | Standard input |

### Response

Returns `200 OK` with the command result:

```json

  "stdout": "Hello from sb-a1b2c3d4\n",
  "stderr": "",
  "exit_code": 0,
  "start_time": "2026-10-03T17:00:05.000Z",
  "finish_time": "2026-10-03T17:00:05.100Z",
  "timed_out": false,
  "oom_killed": false
}
```

| Field | Type | Description |
|-------|------|-------------|
| `stdout` | string | Standard output |
| `stderr` | string | Standard error |
| `exit_code` | integer | Command exit code |
| `start_time` | string | ISO 8601 timestamp |
| `finish_time` | string | ISO 8601 timestamp |
| `timed_out` | boolean | Was the command killed by timeout? |
| `oom_killed` | boolean | Was the command killed by OOM? |

### Security

- Only `sh` and `bash` are allowed to run commands
- Environment variables are filtered to an allowlist (e.g., `PATH`, `HOME`, `PYTHONPATH`)
- No shell expansion (`$VAR`, `$(cmd)`) is allowed
- No `sudo`, `su`, `chroot`, or other privileged commands
- No access to host filesystem or network

### Idempotency

Commands are **not idempotent**. Each execution is independent. If a client retries a command, it will be executed again.

## Get command result

Returns the result of a previous command.

### Endpoint

`GET /v1/sandboxes/{id}/exec/{exec_id}`

### Response

```json

  "id": "exec-1a2b3c",
  "command": "python3 -c 'print(f"Hello from {__import__("platform").node()}"'"",
  "working_dir": "/workspace",
  "environment": {
    "PATH": "/usr/local/bin:/usr/bin:/bin"
  },
  "timeout_seconds": 300,
  "stdout": "Hello from sb-a1b2c3d4\n",
  "stderr": "",
  "exit_code": 0,
  "start_time": "2026-10-03T17:00:05.000Z",
  "finish_time": "2026-10-03T17:00:05.100Z",
  "timed_out": false,
  "oom_killed": false
}
```

## Next steps

- [ ] Add support for streaming stdout/stderr
- [ ] Add support for `GET /v1/sandboxes/{id}/exec` to list recent executions
- [ ] Add support for `GET /v1/sandboxes/{id}/exec/{exec_id}/logs` for streaming logs
- [ ] Add support for `PATCH /v1/sandboxes/{id}/exec/{exec_id}` to update timeout
- [ ] Add support for `DELETE /v1/sandboxes/{id}/exec/{exec_id}` to cancel execution
- [ ] Add support for `GET /v1/sandboxes/{id}/exec/{exec_id}/metrics` for performance metrics