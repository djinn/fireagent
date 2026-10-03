# Multi-Host Production

## Architecture

Phase 2 scales from a single host to a pool of Linux workers managed by a centralized control plane.

```mermaid
flowchart TD
    LB["Load Balancer<br/>(Nginx / HAProxy)"] --> CP1["Control Plane 1"]
    LB --> CP2["Control Plane 2"]
    CP1 --> DB["PostgreSQL<br/>(Primary + Replica)"]
    CP2 --> DB
    CP1 --> H1["Host Agent 1<br/>host-01"]
    CP1 --> H2["Host Agent 2<br/>host-02"]
    CP1 --> H3["Host Agent N<br/>host-N"]
    H1 --> S["Shared Storage<br/>(NFS / S3 / Gluster)"]
    H2 --> S
    H3 --> S
    H1 --> M["Monitoring<br/>(Prometheus + Grafana)"]
    H2 --> M
    H3 --> M
    H1 --> L["Logging<br/>(ELK / Loki)"]
```

## Components

| Component | Technology | Notes |
|-----------|------------|-------|
| Load balancer | Nginx / HAProxy | Health checks, SSL termination, rate limiting |
| Control plane | FastAPI (uvicorn) | Stateless, replicable |
| State store | PostgreSQL 16+ | Primary + async replica |
| Host agent | fireagent-agent | Per-host daemon |
| Shared storage | NFS / S3 | Image and workspace volumes |
| Monitoring | Prometheus + Grafana | Metrics, dashboards, alerts |
| Logging | ELK / Loki | Structured log aggregation |
| Alerting | Prometheus Alert / PagerDuty | Host failure, resource exhaustion |

## Deployment

### Control plane (multi-replica)

```bash
# On each control plane node
python3 -m fireagent.api --replica-id=1 --port=8000
python3 -m fireagent.api --replica-id=2 --port=8001
```

Configuration:

```yaml
# /etc/fireagent/api.yaml
server:
  host: "0.0.0.0"
  port: 8000
  workers: 4

database:
  url: "postgresql+asyncpg://fireagent:password@db-primary:5432/fireagent"
  pool_size: 20
  max_overflow: 10

auth:
  jwt_secret: "${JWT_SECRET}"
  jwt_algorithm: "HS256"
  api_key_header: "Authorization"
  api_key_prefix: "Bearer "

rate_limiting:
  enabled: true
  max_requests: 1000
  window_seconds: 60

logging:
  level: "info"
  format: "json"
  output: "stdout"
```

### Host registration

Each host agent registers on startup:

```python
POST /v1/hosts

{
  "host_id": "host-01",
  "cpu_cores": 16,
  "total_memory_mib": 65536,
  "total_disk_gb": 512,
  "free_disk_gb": 384,
  "version": "2.0.0"
}
```

### Health heartbeat

```python
PUT /v1/hosts/host-01/heartbeat

{
  "cpu_usage_percent": 45.2,
  "memory_usage_percent": 62.8,
  "active_sandbox_count": 5,
  "failed_sandbox_count": 0,
  "uptime_seconds": 123456,
  "error_count": 0
}
```

## Networking

- All control plane traffic is over HTTPS
- Host agents connect to control plane via mTLS
- Shared storage is mounted over NFS with encryption
- API is accessible via load balancer only
- Host agents are in a private network (no public IP)

## Scaling strategy

| Scale | Hosts | Control plane replicas | Storage |
|-------|-------|----------------------|---------|
| Small (< 10 hosts) | 1-10 | 2 | Local SSD |
| Medium (10-100 hosts) | 10-100 | 4 | NFS |
| Large (100-1000 hosts) | 100-1000 | 8 | S3 / Gluster |

## Disaster recovery

- **Host failure**: Sandboxes on failed host are marked `failed`. If workspace is on shared storage, it can be re-attached to a new host.
- **Control plane failure**: Load balancer redirects traffic to healthy replica.
- **Database failure**: Automatic failover to replica.
- **Storage failure**: Backups restored to new volume.
- **Total loss**: Service state restored from backups. Sandboxes cannot be recovered without Firecracker snapshots (Phase 3).

## Next steps

- [ ] Add mTLS between control plane and host agents
- [ ] Add database migration tooling
- [ ] Add automated backup tests
- [ ] Add chaos engineering tests
- [ ] Add capacity planning documentation
- [ ] Add Kubernetes deployment manifests