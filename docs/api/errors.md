# Errors & Status Codes

## Error response format

All error responses have the same structure:

```json

  "error": {
    "code": "suspended_tenant",
    "message": "Tenant is suspended due to policy violation",
    "details": {
      "tenant_id": "ten-abc123",
      "action": "block_sandboxes"
    }
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `error.code` | string | Machine-readable error code |
| `error.message` | string | Human-readable error message |
| `error.details` | object | Additional context (optional) |

## Status codes

| Code | Meaning | When used |
|------|---------|-----------|
| `200 OK` | Success | Most responses |
| `201 Created` | Sandbox created | `POST /v1/sandboxes` |
| `202 Accepted` | Request enqueued | `POST /v1/sandboxes` (when host assignment pending) |
| `204 No Content` | No body | `POST /v1/sandboxes/{id}/stop`, `DELETE /v1/sandboxes/{id}` |
| `400 Bad Request` | Invalid request | Malformed JSON, missing fields |
| `401 Unauthorized` | Invalid or missing API key | No `Authorization` header |
| `403 Forbidden` | Tenant or sandbox access denied | Client doesn't own sandbox |
| `404 Not Found` | Resource not found | Sandbox ID doesn't exist |
| `409 Conflict` | Resource already exists | Duplicate sandbox ID |
| `429 Too Many Requests` | Rate limit exceeded | Too many requests in a window |
| `500 Internal Server Error` | Unexpected error | Server-side failure |
| `503 Service Unavailable` | System overloaded | Control plane too busy |

## Error codes

| Code | Meaning |
|------|---------|
| `invalid_request` | Invalid or missing field in request |
| `sandbox_not_found` | Sandbox ID does not exist |
| `sandbox_not_ready` | Sandbox is not in a state that allows this operation |
| `image_not_found` | Guest image not found or not approved |
| `placement_failure` | No host with sufficient capacity available |
| `boot_timeout` | microVM did not boot within timeout |
| `guest_agent_timeout` | Guest agent did not respond after boot |
| `resource_limit` | Guest exceeded CPU, memory, or disk limits |
| `network_denial` | A network policy was violated |
| `host_failure` | Host agent stopped reporting health |
| `user_cancellation` | Client cancelled the operation |
| `internal_error` | Unexpected platform error |
| `suspended_tenant` | Tenant is suspended due to policy violation |
| `rate_limit_exceeded` | Too many requests in a time window |
| `system_busy` | Control plane too busy to handle request |

## Failure handling

When a sandbox enters `failed`, the `failure_reason` field contains a structured error category:

| Category | Meaning |
|----------|---------|
| `image_error` | Guest image not found, corrupt, or incompatible |
| `placement_failure` | No host with sufficient capacity available |
| `boot_timeout` | microVM did not reach ready state within timeout |
| `guest_agent_timeout` | Guest agent did not connect after boot |
| `resource_limit` | Guest exceeded CPU, memory, or disk limits |
| `network_denial` | A network policy was violated |
| `host_failure` | Host agent stopped reporting health |
| `user_cancellation` | Client cancelled the operation |
| `internal_error` | Unexpected platform error |

## Next steps

- [ ] Add support for `GET /v1/sandboxes/{id}/errors` to list past errors
- [ ] Add support for `GET /v1/sandboxes/{id}/logs` to stream logs
- [ ] Add support for `GET /v1/sandboxes/{id}/metrics` for performance metrics
- [ ] Add support for `GET /v1/sandboxes/{id}/events` for lifecycle events
- [ ] Add support for `GET /v1/sandboxes/{id}/diagnostics` for health checks
- [ ] Add support for `GET /v1/sandboxes/{id}/debug` for troubleshooting