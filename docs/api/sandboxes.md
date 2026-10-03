# Sandbox Operations

## Create sandbox

Creates a new sandbox with the given configuration.

### Endpoint

`POST /v1/sandboxes`

### Request

```json

  "image": "ubuntu:24.04",
  "workspace": {
    "type": "git",
    "url": "https://github.com/myorg/myrepo.git",
    "ref": "main"
  },
  "vcpus": 2,
  "memory_mib": 1024,
  "disk_mib": 2048,
  "ttl_seconds": 3600,
  "idle_timeout_seconds": 600,
  "network_policy": {
    "rules": [
      {
        "action": "allow",
        "protocol": "tcp",
        "destination": "github.com",
        "port": 443
      },
      {
        "action": "allow",
        "protocol": "tcp",
        "destination": "pypi.org",
        "port": 443
      }
    ]
  },
  "labels": {
    "job_id": "job-123",
    "rollout_id": "rollout-456",
    "task_id": "task-789"
  }
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `image` | string | Yes | Guest image name and version (e.g., `ubuntu:24.04`) |
| `workspace` | object | No | Task workspace configuration |
| `vcpus` | integer | Yes | Number of virtual CPUs |
| `memory_mib` | integer | Yes | Guest memory in MiB |
| `disk_mib` | integer | Yes | Writable workspace capacity in MiB |
| `ttl_seconds` | integer | No | Maximum sandbox lifetime in seconds |
| `idle_timeout_seconds` | integer | No | Stop after idle for this many seconds |
| `network_policy` | object | No | Network rules |
| `labels` | object | No | Caller-supplied metadata |

### Response

On success, returns `201 Created` with the sandbox details:

```json

  "id": "sb-a1b2c3d4",
  "state": "creating",
  "image": "ubuntu:24.04",
  "vcpus": 2,
  "memory_mib": 1024,
  "disk_mib": 2048,
  "ttl_seconds": 3600,
  "idle_timeout_seconds": 600,
  "network_policy": {
    "rules": [
      {
        "action": "allow",
        "protocol": "tcp",
        "destination": "github.com",
        "port": 443
      }
    ]
  },
  "labels": {
    "job_id": "job-123",
    "rollout_id": "rollout-456",
    "task_id": "task-789"
  },
  "created_at": "2026-10-03T17:00:00.000Z",
  "host": "host-03",
  "effective_limits": {
    "cpu": 2,
    "memory_mib": 1024,
    "disk_mib": 2048
  }
}
```

The `state` will be `queued`, `creating`, or `ready` depending on host assignment.

### Idempotency

The API supports idempotency via the `Idempotency-Key` header. A client can retry a `create` request with the same key within 5 minutes, and the API will return the existing sandbox instead of creating a duplicate.

## Get sandbox

Returns the current state and metadata of a sandbox.

### Endpoint

`GET /v1/sandboxes/{id}`

### Response

```json

  "id": "sb-a1b2c3d4",
  "state": "running",
  "image": "ubuntu:24.04",
  "vcpus": 2,
  "memory_mib": 1024,
  "disk_mib": 2048,
  "ttl_seconds": 3600,
  "idle_timeout_seconds": 600,
  "network_policy": {
    "rules": [
      {
        "action": "allow",
        "protocol": "tcp",
        "destination": "github.com",
        "port": 443
      }
    ]
  },
  "labels": {
    "job_id": "job-123",
    "rollout_id": "rollout-456",
    "task_id": "task-789"
  },
  "created_at": "2026-10-03T17:00:00.000Z",
  "started_at": "2026-10-03T17:00:02.000Z",
  "stopped_at": null,
  "last_activity_at": "2026-10-03T17:00:05.000Z",
  "host": "host-03",
  "failure_reason": null,
  "effective_limits": {
    "cpu": 2,
    "memory_mib": 1024,
    "disk_mib": 2048
  }
}
```

## Stop sandbox

Gracefully stops the sandbox.

### Endpoint

`POST /v1/sandboxes/{id}/stop`

### Response

Returns `202 Accepted` immediately. The sandbox will transition to `stopping`, then `stopped`.

## Delete sandbox

Deletes the sandbox and its writable state.

### Endpoint

`DELETE /v1/sandboxes/{id}`

### Response

Returns `204 No Content`.