# Architecture

This section documents the internal design of Fireagent — the components, their responsibilities, and how they interact to create, observe, and destroy stateful microVM sandboxes at scale.

## Guiding principles

- **A sandbox is a stateful session**, not a one-shot command.
- **Firecracker provides the guest isolation boundary.** Host services must still assume guest code is hostile.
- **Use a small immutable base image** and mount task-specific writable state separately.
- **Make limits explicit.** Every sandbox has defined CPU, memory, disk, network, and lifetime policy.
- **Separate control from execution.** The API and scheduler manage sandboxes; isolated host agents run them.
- **Keep lifecycle observable.** Every transition and failure should be queryable.

## Architecture diagram

```mermaid
flowchart TD
    C["Agent harness /<br/>Python SDK"] -->|"REST API calls"| API["Sandbox API<br/><i>FastAPI service</i>"]
    API -->|"lifecycle requests"| S["Scheduler &<br/>State Store<br/><i>PostgreSQL</i>"]
    S -->|"placement decisions"| H["Host Agent<br/><i>per-worker daemon</i>"]
    H -->|"microVM lifecycle"| F["Firecracker<br/>microVM"]
    F -->|"read-only"| I["Guest Image<br/><i>versioned, signed</i>"]
    F -->|"read-write"| W["Workspace Volume<br/><i>task persistence</i>"]
    H --> O["Logs & Metrics<br/><i>observability pipeline</i>"]
    S -.->|"health checks"| H
    style C fill:#1e293b,stroke:#06b6d4,color:#fff
    style API fill:#0f172a,stroke:#06b6d4,color:#fff
    style S fill:#0f172a,stroke:#f97316,color:#fff
    style H fill:#0f172a,stroke:#22d3ee,color:#fff
    style F fill:#1e293b,stroke:#f97316,color:#fff
    style I fill:#1e293b,stroke:#64748b,color:#fff
    style W fill:#1e293b,stroke:#64748b,color:#fff
    style O fill:#1e293b,stroke:#64748b,color:#fff
```

## Components at a glance

<div class="grid cards" markdown>

-   :material-api: **Sandbox API** – FastAPI service that validates requests, enforces policies, records state, and dispatches lifecycle commands. It does *not* execute guest commands directly.
-   :material-sitemap: **Scheduler** – Selects a host with available CPU, memory, and disk. Enforces placement policies and tenant quotas. Simple and database-backed for now.
-   :material-console: **Host Agent** – Runs on each Linux worker host. Manages Firecracker processes, TAP interfaces, drives, and host-level limits. Reports health and capacity.
-   :material-database: **State Store** – PostgreSQL persistence for sandbox metadata, lifecycle state, image references, network policies, and logs.
-   :material-harddisk: **Artifact & Workspace Storage** – Versioned guest images and task workspace volumes. Local SSD for Phase 1; interface is storage-agnostic.
-   :material-chart-line: **Observability Pipeline** – Structured logs, metrics, and events keyed to sandbox/tenant/host IDs.

</div>

## Where to go next

- [**Sandbox Lifecycle**](lifecycle.md) – Follow a sandbox from `queued` to `stopped`, with every state transition explained.
- [**Guest Image Construction**](guest-image.md) – How we build minimal, reproducible, verified Linux guest images.
- [**Host Agent**](host-agent.md) – Deep dive into the daemon that manages Firecracker processes.
- [**Networking Model**](networking.md) – Deny-by-default, TAP interfaces, egress proxy, and firewall rules.
- [**Resource Controls**](resource-controls.md) – cgroups, quotas, timeouts, and how limits are enforced.
- [**State Store**](state-store.md) – Schema, migrations, and query patterns for the PostgreSQL store.