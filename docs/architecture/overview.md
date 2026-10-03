# System Design

This architecture is informed by **DeepSeek Elastic Compute (DSec)**
[[arXiv:2609.22978]](https://arxiv.org/abs/2609.22978), which establishes the
design pattern of separating sandbox lifecycle management from execution,
supporting burst creation patterns, stateful sessions with controlled lifetimes,
and co-design with RL training frameworks.

## High-level architecture

Fireagent separates three concerns that are often conflated in sandbox platforms:

| Layer | Responsibility | Technology |
|-------|---------------|------------|
| **Control Plane** | Client authentication, policy validation, state management, scheduling | FastAPI + PostgreSQL |
| **Host Agent** | Firecracker process management, resource enforcement, health reporting | Standalone daemon (Python/Rust) |
| **Guest** | Untrusted code execution | Minimal Linux inside Firecracker microVM |

This separation means the control plane can be scaled independently from execution hosts, and a host failure does not corrupt the control plane's view of the world — only the sandboxes that were running on that host.

## Control plane design

### Sandbox API

The API is a **FastAPI** service with these route groups:

```
POST   /v1/sandboxes              # Create sandbox
GET    /v1/sandboxes/{id}         # Get sandbox state
POST   /v1/sandboxes/{id}/exec    # Execute command
POST   /v1/sandboxes/{id}/stop    # Stop sandbox
DELETE /v1/sandboxes/{id}         # Delete sandbox
POST   /v1/sandboxes/{id}/snapshot # Future: create snapshot
```

Key design decisions:

- **Idempotency via idempotency keys** – The `POST /v1/sandboxes` endpoint accepts an `Idempotency-Key` header. If a client retries with the same key within the idempotency window, the API returns the existing sandbox rather than creating a duplicate.
- **Command execution is async-aware** – The `/exec` endpoint returns structured results with `stdout`, `stderr`, `exit_code`, and timing metadata. Commands are executed through the guest agent channel — never by forwarding the Firecracker API socket.
- **Validation happens before dispatch** – Resource limits are checked against tenant quotas and host capacity before a sandbox is created or a command is queued.

### Scheduler

The scheduler is deliberately simple for Phase 1:

1. Maintains a database of registered hosts with their total and available CPU/memory/disk.
2. On sandbox creation, selects a host with sufficient capacity (first-fit or round-robin).
3. On host heartbeat failure, marks the host as unhealthy and its sandboxes as `failed`.

The interface is designed to accommodate a more sophisticated scheduler (capacity-aware bin packing, queue-based burst handling, admission control) without changing the API or host agent.

### State store

PostgreSQL schema organized around these core tables:

- `sandboxes` – Primary sandbox metadata and lifecycle state
- `hosts` – Registered hosts with capacity and health info
- `images` – Versioned guest image artifacts with digests and verification status
- `executions` – Command execution records with input/output and timing
- `network_policies` – Per-sandbox and default network allow rules
- `audit_log` – Append-only lifecycle event log

See [State Store](state-store.md) for the full schema.

## Host agent design

The host agent is a lightweight daemon that:

- **Launches Firecracker** – Creates a unique working directory, API socket, and jailer environment per microVM.
- **Configures networking** – Creates TAP interfaces, applies iptables/nftables rules, sets up egress proxy rules.
- **Enforces limits** – Applies cgroup CPU/memory constraints, disk quotas via filesystem quotas, and process limits.
- **Reports health** – Sends heartbeat with capacity metrics to the control plane.
- **Cleans up** – On sandbox deletion or agent restart, removes orphaned Firecracker processes, TAP devices, sockets, and temporary files.

The host agent runs with **minimum host privileges**:

- A dedicated `fireagent` user with no unnecessary capabilities.
- Firecracker's jailer for further privilege reduction.
- seccomp policies applied at the Firecracker process level.

See [Host Agent](host-agent.md) for the full design.

## Design decision records

### Why Firecracker instead of containers?

| Criterion | Containers (Docker/podman) | Firecracker microVMs |
|-----------|---------------------------|----------------------|
| Kernel isolation | Shared kernel; container breakout = host compromise | Separate kernel; guest kernel exploit ≠ host kernel exploit |
| Boot speed | ~50ms (with pre-warm) | ~150ms (cold boot) |
| Resource overhead | ~5 MiB per container | ~75 MiB per microVM (idle) |
| Management surface | Large: dockerd, containerd, runc, kernel features | Small: single binary, KVM only |
| Snapshot support | Limited (Criu) | Native (Firecracker built-in) |
| Attack surface | Hundreds of syscalls reachable | KVM + limited device drivers |

Fireagent chooses microVM isolation for workloads where **security is paramount** — running untrusted agent code, model-generated scripts, and evaluation tasks from unknown sources.

### Why not allow direct Firecracker API access?

The Firecracker API socket is powerful — it can modify machine state, attach/detach drives, and control the VM. Exposing it to clients would:
- Bypass resource limits and policy enforcement.
- Allow clients to alter the guest image or networking at runtime.
- Create an irreconcilable state gap between the control plane's view and actual VM state.

Instead, the host agent mediates all interactions, presenting only the operations the control plane has authorized.

### Why PostgreSQL for Phase 1?

PostgreSQL provides:
- Strong consistency for sandbox state transitions.
- Familiar tooling for operators.
- JSONB for flexible metadata and network policy storage.
- The ability to evolve into a more scalable store later without changing the API.

The state store is abstracted behind a repository interface; replacing it with a higher-throughput store (e.g., FoundationDB, CockroachDB) is possible without changing the API or host agent.