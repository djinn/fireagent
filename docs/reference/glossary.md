# Glossary

## A

**Agent harness** – A system that orchestrates AI agents, often running them in sandboxed environments for safety and resource control.

**API key** – A secret token used to authenticate API requests. Each key is scoped to a tenant.

**Artifact storage** – The system that stores versioned guest images and task artifacts.

## B

**Boot-to-ready time** – The time from starting a microVM to when the guest agent reports healthy. Target: < 150 ms.

## C

**cgroups** – Linux kernel feature for resource isolation (CPU, memory, disk). Used by Fireagent to enforce sandbox limits.

**Control plane** – The Sandbox API and Scheduler that manage sandbox lifecycle and state.

## E

**Egress proxy** – An optional network proxy that provides secure outbound access, with per-tenant allowlists and logging.

## F

**FastAPI** – A modern Python web framework used for the Sandbox API.

**Firecracker** – An open-source virtual machine monitor (VMM) by AWS that creates microVMs with KVM. The core isolation technology in Fireagent.

## G

**Guest agent** – A lightweight process running inside the microVM that receives execution requests from the host agent and returns results.

**Guest image** – The minimal Linux root filesystem used by microVMs. Versioned, signed, and verified.

## H

**Host agent** – The daemon running on each worker host that manages Firecracker processes, networking, and resource limits.

## I

**Idempotency key** – A client-generated token that ensures create requests are idempotent. Reusing the same key within 5 minutes returns the existing sandbox.

## M

**microVM** – A lightweight virtual machine with a minimal kernel and footprint, optimized for fast boot and low resource usage.

## N

**Network policy** – A set of rules that control outbound traffic from a sandbox. Default: deny-all.

## R

**RL rollout** – Reinforcement Learning training loop where an agent interacts with an environment. Fireagent sandboxes can provide isolated environments for each rollout.

## S

**Sandbox** – The primary unit of isolation in Fireagent. A sandbox is a Firecracker microVM with an attached workspace volume.

**Scheduler** – The component that selects a host for each sandbox based on capacity and placement policies.

**SBOM** – Software Bill of Materials. A list of all packages and dependencies in a guest image.

**seccomp** – Linux kernel feature for restricting system calls. Used by Firecracker's jailer.

**State store** – PostgreSQL database that persists sandbox metadata, lifecycle state, and audit logs.

## T

**TAP interface** – A virtual network interface used to connect Firecracker microVMs to the host network.

**Tenant** – A logical grouping of API keys and sandboxes. Each tenant has quotas and resource limits.

**TTL** – Time To Live. The maximum lifetime of a sandbox.

## W

**Workspace volume** – A writable storage volume attached to each sandbox. Persists changes between commands for the sandbox's lifetime.