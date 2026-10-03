# Monitoring & Observability

## Design principles

- **Observable by default** – Every lifecycle event is logged and accessible.
- **Structured logging** – All logs are JSON, not plaintext.
- **Metrics as first-class data** – All operations produce metrics.
- **Events before logs, logs before metrics** – Events are the source of truth.
- **No secrets in logs** – Secrets are redacted before logging.

## Metrics

### Sandbox metrics

| Metric | Type | Description |
|--------|------|-------------|
| `fireagent.sandboxes.created` | counter | Total sandboxes created |
| `fireagent.sandboxes.ready` | counter | Sandboxes that reached ready state |
| `fireagent.sandboxes.failed` | counter | Sandboxes that entered failed state |
| `fireagent.sandboxes.deleted` | counter | Sandboxes deleted |
| `fireagent.sandboxes.active` | gauge | Currently active sandboxes |
| `fireagent.sandboxes.creation_latency_ms` | histogram | Time from create to ready |
| `fireagent.sandboxes.duration_seconds` | histogram | Lifetime of sandbox |

### Command metrics

| Metric | Type | Description |
|--------|------|-------------|
| `fireagent.executions.started` | counter | Commands started |
| `fireagent.executions.completed` | counter | Commands completed |
| `fireagent.executions.timed_out` | counter | Commands killed by timeout |
| `fireagent.executions.oom_killed` | counter | Commands killed by OOM |
| `fireagent.executions.latency_ms` | histogram | Command execution time |

### Host metrics

| Metric | Type | Description |
|--------|------|-------------|
| `fireagent.hosts.registered` | gauge | Registered hosts |
| `fireagent.hosts.unhealthy` | gauge | Unhealthy hosts |
| `fireagent.hosts.cpu_usage_percent` | gauge | Host CPU usage |
| `fireagent.hosts.memory_usage_percent` | gauge | Host memory usage |
| `fireagent.hosts.disk_usage_percent` | gauge | Host disk usage |

### Resource metrics

| Metric | Type | Description |
|--------|------|-------------|
| `fireagent.resources.cpu_limit_millicores` | gauge | Total CPU limit across sandboxes |
| `fireagent.resources.memory_limit_bytes` | gauge | Total memory limit |
| `fireagent.resources.disk_limit_bytes` | gauge | Total disk limit |

## Logs

### Log format

All logs are structured JSON:

```json
{
  "timestamp": "2026-10-03T17:00:00.000Z",
  "level": "INFO",
  "logger": "fireagent.api",
  "message": "Sandbox created",
  "sandbox_id": "sb-a1b2c3d4",
  "tenant_id": "ten-abc123",
  "host_id": "host-01",
  "task_id": "task-789",
  "duration_ms": 45,
  "state": "queued"
}
```

### Log categories

| Category | Events |
|----------|--------|
| `fireagent.api.*` | API request/response |
| `fireagent.scheduler.*` | Host assignment, placement failure |
| `fireagent.host.*` | microVM lifecycle, resource enforcement |
| `fireagent.executions.*` | Command execution |
| `fireagent.audit.*` | State transitions, policy denials |
| `fireagent.storage.*` | Image cache hit/miss, workspace operations |

## Dashboards

### Grafana dashboard

A default dashboard is available in `fireagent/grafana/dashboard.json`. It includes:

1. **Sandbox creation rate** (line chart)
2. **Active sandboxes per host** (stacked area)
3. **Boot-to-ready latency** (histogram)
4. **Command execution latency** (heatmap)
5. **Host resource usage** (CPU, memory, disk)
6. **Error distribution** (pie chart)
7. **Top failing sandboxes** (table)
8. **Network policy denials** (counter)

## Alerting

| Alert | Condition | Severity |
|-------|-----------|----------|
| Host agent unhealthy | No heartbeat for 30 seconds | Critical |
| High sandbox failure rate | >10% failure rate in 5 minutes | Warning |
| Resource exhaustion | >90% CPU or memory usage on host | Critical |
| High command timeout rate | >5% in 1 minute | Warning |
| Policy violation | Any network policy denial | Info |
| Image cache miss | >50% cache miss rate | Warning |

## OpenTelemetry

The control plane exports OpenTelemetry traces:

- **Create sandbox** – Full trace from API to host agent
- **Execute command** – Trace from API to guest agent
- **Host heartbeat** – Periodic span for health check

Configure via environment variables:

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT="http://otel-collector:4318"
export OTEL_SERVICE_NAME="fireagent-api"
```

## Next steps

- [ ] Add support for distributed tracing (OpenTelemetry)
- [ ] Add support for log aggregation (ELK)
- [ ] Add support for metrics aggregation (Prometheus)
- [ ] Add support for alerting (Prometheus Alert)
- [ ] Add support for dashboards (Grafana)
- [ ] Add support for anomaly detection (ML-based)
- [ ] Add support for automated incident response