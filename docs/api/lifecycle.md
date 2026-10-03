# Lifecycle Management

## Stop sandbox

Gracefully stops the sandbox.

### Endpoint

`POST /v1/sandboxes/{id}/stop`

### Request

```json

  "grace_period_seconds": 5
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `grace_period_seconds` | integer | No | How long to wait for graceful shutdown (default: 5) |

### Response

Returns `202 Accepted` immediately. The sandbox will transition to `stopping`, then `stopped`.

## Delete sandbox

Deletes the sandbox and its writable state.

### Endpoint

`DELETE /v1/sandboxes/{id}`

### Request

```json

  "retain_workspace": false
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `retain_workspace` | boolean | No | If `true`, keep the workspace volume; if `false`, delete it (default: `false`) |

### Response

Returns `204 No Content`.

## Snapshot sandbox (future)

Optional feature: saves a resumable state of the sandbox.

### Endpoint

`POST /v1/sandboxes/{id}/snapshot`

### Response

```json

  "snapshot_id": "snap-1a2b3c",
  "created_at": "2026-10-03T17:00:00.000Z",
  "size_bytes": 2147483648,
  "status": "pending"
}
```

### Statuses

- `pending` – Snapshot in progress
- `completed` – Snapshot complete
- `failed` – Snapshot failed

## Restore from snapshot (future)

Creates a new sandbox from a previously saved snapshot.

### Endpoint

`POST /v1/sandboxes`

### Request

```json

  "snapshot": "snap-1a2b3c",
  "vcpus": 2,
  "memory_mib": 1024,
  "disk_mib": 2048
}
```

### Response

Returns `201 Created` with the new sandbox details.

## Next steps

- [ ] Add support for `GET /v1/sandboxes/{id}/snapshot` to list snapshots
- [ ] Add support for `DELETE /v1/sandboxes/{id}/snapshot` to delete a snapshot
- [ ] Add support for `GET /v1/sandboxes/{id}/snapshot/{snapshot_id}/status` to check progress
- [ ] Add support for `GET /v1/sandboxes/{id}/snapshot/{snapshot_id}/download` to download the snapshot
- [ ] Add support for `GET /v1/sandboxes/{id}/snapshot/{snapshot_id}/restore` to restore the snapshot