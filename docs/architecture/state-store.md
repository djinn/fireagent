# State Store

## Why PostgreSQL

Fireagent uses **PostgreSQL** for the state store because it provides:

- **Strong consistency** – Critical for sandbox state transitions
- **ACID compliance** – No lost updates or race conditions
- **JSONB support** – Flexible for metadata, network policies, and labels
- **Mature tooling** – Backup, replication, monitoring, and migration
- **Scalability** – Can be scaled horizontally with logical replication
- **Familiarity** – Operators know PostgreSQL

The state store is abstracted behind a repository interface, so it can be replaced later with a higher-throughput store (e.g., FoundationDB, CockroachDB).

## Schema design

### Core tables

#### `sandboxes`

```sql
CREATE TABLE sandboxes (
    id UUID PRIMARY KEY,
    state TEXT NOT NULL DEFAULT 'queued',
    image_digest TEXT NOT NULL,
    workspace_size_mb INTEGER NOT NULL DEFAULT 1024,
    vcpus INTEGER NOT NULL DEFAULT 1,
    memory_mib INTEGER NOT NULL DEFAULT 1024,
    ttl_seconds INTEGER,
    idle_timeout_seconds INTEGER,
    network_policy JSONB,
    labels JSONB,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    started_at TIMESTAMP WITH TIME ZONE,
    stopped_at TIMESTAMP WITH TIME ZONE,
    last_activity_at TIMESTAMP WITH TIME ZONE,
    failure_reason TEXT,
    host_id UUID REFERENCES hosts(id),
    retention_policy TEXT DEFAULT 'retain',
    -- Indexes
    INDEX idx_state (state),
    INDEX idx_created_at (created_at),
    INDEX idx_host_id (host_id)
);
```

#### `hosts`

```sql
CREATE TABLE hosts (
    id UUID PRIMARY KEY,
    name TEXT NOT NULL,
    ip_address INET,
    cpu_cores INTEGER NOT NULL,
    total_memory_mib INTEGER NOT NULL,
    total_disk_gb INTEGER NOT NULL,
    free_disk_gb INTEGER NOT NULL,
    last_heartbeat_at TIMESTAMP WITH TIME ZONE NOT NULL,
    status TEXT NOT NULL DEFAULT 'online',
    version TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    -- Indexes
    INDEX idx_status (status)
);
```

#### `images`

```sql
CREATE TABLE images (
    id UUID PRIMARY KEY,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    digest TEXT NOT NULL,
    kernel_version TEXT NOT NULL,
    build_date TIMESTAMP WITH TIME ZONE NOT NULL,
    sbom_url TEXT,
    scan_report_url TEXT,
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    -- Indexes
    INDEX idx_name_version (name, version),
    INDEX idx_digest (digest),
    INDEX idx_status (status)
);
```

#### `executions`

```sql
CREATE TABLE executions (
    id UUID PRIMARY KEY,
    sandbox_id UUID REFERENCES sandboxes(id) ON DELETE CASCADE,
    command TEXT NOT NULL,
    working_dir TEXT,
    environment JSONB,
    timeout_seconds INTEGER,
    stdin TEXT,
    stdout TEXT,
    stderr TEXT,
    exit_code INTEGER,
    started_at TIMESTAMP WITH TIME ZONE NOT NULL,
    finished_at TIMESTAMP WITH TIME ZONE NOT NULL,
    timed_out BOOLEAN NOT NULL DEFAULT FALSE,
    oom_killed BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    -- Indexes
    INDEX idx_sandbox_id (sandbox_id),
    INDEX idx_started_at (started_at)
);
```

#### `audit_log`

```sql
CREATE TABLE audit_log (
    id UUID PRIMARY KEY,
    sandbox_id UUID REFERENCES sandboxes(id),
    event TEXT NOT NULL,
    from_state TEXT,
    to_state TEXT,
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    actor TEXT NOT NULL,
    metadata JSONB,
    -- Indexes
    INDEX idx_sandbox_id (sandbox_id),
    INDEX idx_timestamp (timestamp)
);
```

### Foreign key constraints

- `sandboxes.host_id` → `hosts.id`
- `executions.sandbox_id` → `sandboxes.id`
- `images` is a lookup table; no foreign keys

### Indexes

- `idx_state`, `idx_created_at`, `idx_host_id` on `sandboxes`
- `idx_status` on `hosts`
- `idx_name_version`, `idx_digest`, `idx_status` on `images`
- `idx_sandbox_id`, `idx_started_at` on `executions`
- `idx_sandbox_id`, `idx_timestamp` on `audit_log`

## Data flow

### Sandbox creation

1. Client sends `POST /v1/sandboxes`
2. API validates request and checks tenant quotas
3. API inserts a new record into `sandboxes` with `state = 'queued'`
4. Scheduler selects a host and updates `sandboxes.host_id`
5. Host agent receives the request and creates the microVM
6. Host agent reports `ready` to API
7. API updates `sandboxes` with `state = 'ready'` and `started_at`

### Command execution

1. Client sends `POST /v1/sandboxes/{id}/exec`
2. API validates sandbox state (`ready` or `running`)
3. API inserts a new record into `executions` with `started_at`
4. Host agent runs the command
5. Host agent updates `executions` with `stdout`, `stderr`, `exit_code`, `finished_at`, `timed_out`, `oom_killed`
6. API returns results to client

### Lifecycle transitions

All state transitions are logged in `audit_log`:

```sql
INSERT INTO audit_log (id, sandbox_id, event, from_state, to_state, actor, metadata)
VALUES (gen_random_uuid(), 'sb-a1b2c3', 'state_change', 'queued', 'creating', 'scheduler', '{}');
```

## Reliability and recovery

### Reconciliation

After a control plane restart, the scheduler reconciles recorded state with host reality:

- Scans `sandboxes` table
- For each sandbox with `host_id`, calls `GET /v1/hosts/{id}`
- If host is `unhealthy`, marks sandbox as `failed`
- If host is `online`, checks if the microVM process exists
- If not, marks sandbox as `failed`
- If yes, updates `last_activity_at` and `state`

### Heartbeat and failure detection

- Host agent sends `PUT /v1/hosts/{id}/heartbeat` every 10 seconds
- If no heartbeat in 30 seconds, host is marked `unhealthy`
- Sandboxes on that host are transitioned to `failed`

### Cleanup

- On `stop` or `delete`, the API removes the sandbox record (soft delete) or moves it to a historical table
- On `delete`, the host agent removes the working directory, Firecracker socket, TAP interface, and temporary files
- On `stop`, the host agent removes the working directory but retains the workspace volume

## Next steps

- [ ] Add support for logical replication (Phase 3)
- [ ] Add backup and restore procedures
- [ ] Add schema migration tooling (e.g., `flyway` or `liquibase`)
- [ ] Implement row-level security (RLS) for multi-tenant support
- [ ] Add support for distributed transactions
- [ ] Add monitoring and alerting for schema changes
- [ ] Add automated data retention policies