# Changelog

All notable changes to Fireagent will be documented here.

## [0.1.0] – 2026-10-03

### Added

- **Python SDK** – First-class client for creating, managing, and deleting sandboxes.
- **FastAPI control plane** – RESTful API with `/v1/sandboxes`, `/v1/sandboxes/{id}/exec`, lifecycle endpoints.
- **Host agent** – Daemon for managing Firecracker microVMs, TAP interfaces, and cgroups.
- **Guest agent** – Lightweight process for command execution and health reporting.
- **Guest image build system** – Buildroot-based minimal Linux images.
- **Documentation** – Full MkDocs site with architecture, API reference, SDK guide, deployment, and security docs.
- **CI/CD pipeline** – GitHub Actions for linting, testing, security scanning, and docs building.
- **Security threat model** – Comprehensive analysis of attack vectors and mitigations.
- **Isolation guarantees** – Five-layer isolation model (Firecracker + cgroups + seccomp + filesystem + network).
- **Network security** – Deny-by-default, TAP-based isolation, egress proxy, firewall rules.
- **Resource controls** – CPU/memory/disk limits via cgroups and filesystem quotas.
- **Idempotency** – Idempotency key support for create operations.
- **Async support** – Async methods for concurrent operations.

### Architecture

- **Phase 1**: Single-host prototype with in-memory state store.
- **Phase 2**: Multi-host service with PostgreSQL (planned).
- **Phase 3**: Elastic scale with queue-based burst handling (planned).

### Security

- No default credentials in guest images.
- No SSH server or remote login services.
- Deny-by-default network policy.
- seccomp filters on Firecracker processes.
- Guest images are signed, versioned, and scanned before use.