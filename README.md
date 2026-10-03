# Fireagent

**Elastic agent sandbox platform powered by Firecracker microVMs.**

[![CI](https://github.com/djinn/fireagent/actions/workflows/ci.yml/badge.svg)](https://github.com/djinn/fireagent/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/fireagent.svg)](https://pypi.org/project/fireagent/)
[![License: MIT](https://img.shields.io/badge/License-MIT-purple.svg)](https://opensource.org/licenses/MIT)
[![arXiv:2609.22978](https://img.shields.io/badge/arXiv-2609.22978-brightgreen)](https://arxiv.org/abs/2609.22978)

---

Fireagent creates, manages, and destroys isolated Linux microVMs for AI agents,
coding assistants, RL rollout workers, and evaluation jobs. Each sandbox is a
**stateful session** — files, processes, and environment persist across commands.

Architecturally inspired by **DeepSeek Elastic Compute (DSec)** [[arXiv:2609.22978]](https://arxiv.org/abs/2609.22978),
the production sandbox infrastructure serving ~3 million sandboxes daily across 160 nodes
at DeepSeek. Fireagent distills DSec's core principles — burst-aware orchestration,
multi-backend isolation, stateful session semantics, and RL co-design — into an
open-source platform focused on microVM-based isolation via Firecracker.

```python
import fireagent as fa

sb = fa.create(image="ubuntu:24.04", vcpus=2, memory_mib=1024, disk_mib=2048)
sb.exec("git clone https://github.com/example/repo.git /workspace/repo")
result = sb.exec("python3 -c 'import numpy; print(numpy.__version__)'")
print(result.stdout)  # → 2.1.0
sb.stop()
sb.delete()
```

**Manage remote workers via SSH:**

```bash
fireagent hosts add worker-01.example.com --label gpu-pool --deploy-key
fireagent hosts health-all
fireagent sandboxes create --image ubuntu:24.04 --vcpus 8 --memory 16384
```

---

## Design Principles (from DSec)

Fireagent's architecture is directly informed by the DSec paper.
Here is what we carry forward:

### 1. Elastic Execution Platform, Not a Single Sandbox Runtime

DSec argues that agentic training workloads need an *elastic platform* rather than a
monolithic runtime. Fireagent provides a **layered architecture** — SDK, API, Scheduler,
Host Agent — so you can mix local development with a multi-host cluster without changing
client code.

### 2. Stateful Sessions with Controlled Lifetimes

> *"... retain state across long interactions, and draw from large image corpora with
> limited reuse."*

Each sandbox is a **session** with a writable workspace, resource limits, TTL, and idle
timeout. The guest agent inside the microVM preserves files and processes between commands.

### 3. Burst-Aware Lifecycle Management

> *"These workloads create sandboxes in large bursts..."*

The scheduler is designed for burst patterns — hundreds of sandboxes created simultaneously,
each running a few commands, then torn down. SSH connections are pooled, images cached,
and workspace creation is staged to absorb bursts.

### 4. Multi-Backend Architecture

DSec exposes FnCall, container, microVM, and full-VM backends. Fireagent starts with
**Firecracker microVMs** (the strongest isolation boundary) and provides a plugin
architecture for additional backends. The `GuestAgentChannel` abstraction (serial, vsock,
in-process) mirrors DSec's layered backend model.

### 5. RL Co-Design — Decoupling Rollout from GPU Training

> *"DSec is co-designed with the RL framework, decouples stateful rollout execution
> from preemptible GPU training..."*

The Operator SDK allows RL training loops to push sandboxes to worker hosts while GPU
nodes focus on gradient computation. Rollout state survives training pauses.
See `examples/rl_rollout.py` for a working demo.

### 6. Memory Efficiency Under High Density

DSec combines *memory sharing, reclamation, and CPU scheduling for high-density execution.*
Fireagent enforces per-sandbox cgroups limits, shares read-only base images across microVMs,
and uses copy-on-write workspace volumes via qcow2.

### 7. Image Distribution

> *"loads image data on demand from Fire-Flyer File System (3FS)"*

Guest images are distributed to workers via SSH SCP with local caching and content-addressed
storage (SHA-256). The `build_image.py` script produces versioned, digest-verified images.

---

## Comparison

| Feature | Docker | QEMU | Firecracker | **Fireagent** |
|---------|--------|------|-------------|---------------|
| **Isolation** | Shared kernel | Full VM | Minimal VM | MicroVM + SSH orchestration |
| **Boot time** | ~10ms | ~5s | ~150ms | ~150ms + remote dispatch |
| **Image size** | ~100 MiB+ | ~500 MiB+ | ~5 MiB | ~5 MiB (customizable) |
| **Overhead/unit** | ~0 MiB | ~200 MiB | ~10 MiB | ~10 MiB + SSH channel |
| **Attack surface** | Kernel CVEs | Full device stack | 3 virtio devices | Same + SSH audit trail |
| **Snapshot** | ❌ | ⚠️ Via libvirt | ✅ Native | ✅ Via Firecracker API |
| **Density/host** | ~1000 | ~50 | ~500 | ~500 + remote pooling |
| **Remote orchestration** | ❌ | ❌ | ❌ | ✅ SSH + key push |
| **RL co-design** | ❌ | ❌ | ❌ | ✅ Rollout decoupling |

---

## Quick Start by Platform

### macOS (SDK + CLI + Remote Only)

Fireagent runs on macOS for development. MicroVMs require a Linux host with KVM,
but the SDK, CLI, and SSH-based remote orchestration work natively.

```bash
# Install
pip install fireagent

# Start the API server (in-process mock mode, no KVM needed)
fireagent-api &

# Use the SDK
python3 -c "
import fireagent as fa
sb = fa.create(image='ubuntu:24.04', vcpus=1, memory_mib=256, disk_mib=512)
result = sb.exec('echo \"hello from fireagent sandbox\"')
print(result.stdout)
sb.stop()
sb.delete()
"

# Or the CLI
fireagent sandboxes create --image ubuntu:24.04 --vcpus 1 --memory 256 --disk 512
fireagent sandboxes ls
fireagent sandboxes exec <id> --command "python3 --version"
```

On macOS, the API runs in **mock mode** — sandbox state is tracked in memory, commands
execute locally. To deploy real microVMs, connect remote Linux workers via SSH:

```bash
fireagent hosts add linux-worker.example.com --deploy-key
fireagent hosts status linux-worker.example.com
# → connected, 16 cores, 64G RAM, KVM=yes, FC=1.2.0
```

### Linux (with KVM — Full Stack)

```bash
# 1. Install Firecracker
sudo apt install -y firecracker  # or download from GitHub releases

# 2. Set up Fireagent
pip install 'fireagent[agent]'
sudo mkdir -p /artifacts/images /var/fireagent/sandboxes

# 3. Build a minimal guest image (~5 MiB initramfs)
python3 -m fireagent_host.build_image --output /artifacts/images

# 4. Start the control plane
fireagent-api &

# 5. Start the host agent (auto-detects Firecracker)
fireagent-agent &

# 6. Run the smoke test
python3 examples/basic_test.py
```

### Linux (without KVM — Mock Mode)

```bash
pip install fireagent
fireagent-api &
fireagent sandboxes create --image ubuntu:24.04 --vcpus 2 --memory 1024
# Falls back to mock Firecracker automatically
```

### Windows (via WSL)

```bash
# Install in WSL2 Ubuntu
sudo apt update && sudo apt install -y python3 python3-pip
pip install fireagent

# Windows doesn't have KVM, but SDK and remote SSH work
fireagent hosts add linux-worker.example.com
fireagent sandboxes create --image ubuntu:24.04  # mock mode
```

---

## Production Deployment Recipe

Based on DSec's production architecture (160 nodes, ~3M sandboxes/day,
380K concurrent, 5K creations/sec).

### Architecture

```
┌──────────────────────────────────────────────────────┐
│   Control Plane (1 node)                              │
│   FastAPI :8000 + PostgreSQL (state) + Host Registry  │
└──────┬───────────────────────────────────────────────┘
       │ SSH (key-based auth, no passwords)
       ▼
┌──────────────────────────────────────────────────────┐
│   Worker Pool (N nodes)                               │
│   ┌──────────┐ ┌──────────┐ ┌──────────┐           │
│   │ host-01  │ │ host-02  │ │ host-N   │           │
│   │ FC VMs   │ │ FC VMs   │ │ FC VMs   │           │
│   └──────────┘ └──────────┘ └──────────┘           │
│   /var/fireagent/sandboxes  (per-host workspaces)    │
│   /artifacts/images          (cached per host)       │
└──────────────────────────────────────────────────────┘
```

### Step 1: Configure Workers

```bash
# On each worker node:
sudo apt install -y firecracker qemu-utils
sudo useradd -m -s /bin/bash fireagent
sudo usermod -aG kvm fireagent
sudo mkdir -p /artifacts/images /var/fireagent/sandboxes
sudo chown -R fireagent:fireagent /artifacts /var/fireagent

# Deploy your SSH public key
echo "ssh-ed25519 AAAAC3N..." | sudo tee -a ~fireagent/.ssh/authorized_keys
```

### Step 2: Build + Distribute Images

```bash
python3 -m fireagent_host.build_image --output /artifacts/images
ls -lh /artifacts/images/
# → fireagent-mini-0.1.0.img      5.2 MiB
# → fireagent-mini-0.1.0.meta.json

for host in worker-{01..10}; do
  rsync -av /artifacts/images/* fireagent@$host:/artifacts/images/
done
```

### Step 3: Start Control Plane

```bash
python3 -m fireagent_api.app --host 0.0.0.0 --port 8000
```

Or with systemd:

```ini
[Unit]
Description=Fireagent API
After=network.target
[Service]
User=fireagent
ExecStart=/opt/fireagent/venv/bin/python -m fireagent_api.app --host 0.0.0.0 --port 8000
Restart=always
[Install]
WantedBy=multi-user.target
```

### Step 4: Register Workers (Operator SDK)

```python
from fireagent_host.operator import Operator

operator = Operator()

for i in range(1, 11):
    operator.add_host(
        f"worker-{i:02d}.example.com",
        label=f"rack-{i // 4}",
        deploy_key=True,
    )

results = operator.health_all()
for r in results:
    print(f"{r['hostname']}: {r['status']} "
          f"({r['cpu_cores']}c/{r['total_memory_mib']}MiB "
          f"KVM={'✓' if r['has_kvm'] else '✗'})")
```

### Step 5: RL Rollout (DSec Co-Design)

```python
import asyncio
from fireagent_host.operator import Operator

operator = Operator()
hosts = [h.id for h in operator.list_hosts(status="connected")]

async def rollout():
    tasks = []
    for i in range(1000):
        host = hosts[i % len(hosts)]
        operator.create_sandbox(host, f"ep-{i:06d}", "ubuntu:24.04", 2, 4096, 8192)
        result = operator.exec_command(host, f"ep-{i:06d}", "python3 /workspace/policy.py")
        operator.stop_sandbox(host, f"ep-{i:06d}")
        tasks.append(result)
    return await asyncio.gather(*tasks)

results = asyncio.run(rollout())
```

### Scaling Parameters (from DSec paper)

| Parameter | Single Host | Small Cluster (10) | Production (160) |
|-----------|-------------|--------------------|------------------|
| Concurrent sandboxes | 500 | 5,000 | **380,000** |
| Creates/sec | 5 | 50 | **5,000** |
| RAM (16 GiB/host) | 8 GiB | 8 GiB | 20 GiB (overcommit) |
| Image cache | 5 GiB | 5 GiB | 5 GiB (shared 3FS) |

---

## CLI Reference

```bash
# Sandbox operations
fireagent sandboxes create  --image ubuntu:24.04 --vcpus 2 --memory 1024 --disk 2048
fireagent sandboxes ls      [--state ready] [--limit 50]
fireagent sandboxes get     <sandbox_id>
fireagent sandboxes exec    <sandbox_id> --command "echo hello" --env KEY=VAL
fireagent sandboxes stop    <sandbox_id> [--no-wait]
fireagent sandboxes delete  <sandbox_id> [--yes]
fireagent sandboxes wait    <sandbox_id> [state] --timeout 120

# Host management
fireagent hosts add         <hostname> [--port] [--user] [--label] [--deploy-key]
fireagent hosts remove      <host_id> [--yes]
fireagent hosts ls          [--status connected]
fireagent hosts status      <host_id>
fireagent hosts health-all
fireagent hosts push-keys   <host_id> [--key-path]
fireagent hosts generate-key
fireagent hosts discover    [--cidr 10.0.0.0/24] [--timeout 3]

# Remote sandbox operations
fireagent hosts sandboxes       <host_id>
fireagent hosts resource-usage  <host_id>

# Configuration
fireagent config show
fireagent config init
fireagent config set api.base_url http://other:9000

# Format options (for any command)
--format json     # JSON output
--format yaml     # YAML output
--format table    # ASCII table (default)
```

---

## Corner Cases

### macOS: "KVM not available"

```bash
# Use mock mode (automatic fallback)
export FIREAGENT_MOCK=1
fireagent sandboxes create --image ubuntu:24.04  # runs locally, no KVM

# Or connect to remote workers
fireagent hosts add linux-worker.example.com --deploy-key
```

### Linux: "No /dev/kvm"

```bash
# Check KVM
ls -la /dev/kvm
# Install KVM if missing:
sudo apt install -y qemu-system-x86
sudo modprobe kvm
```

### "Permission denied (publickey)" on SSH

```bash
# Generate + deploy keys
fireagent hosts generate-key ~/.ssh/fireagent_ed25519
fireagent hosts push-keys fireagent@worker-01:22 --key-path ~/.ssh/fireagent_ed25519

# Verify
fireagent hosts status worker-01
```

### Sandbox stuck in "creating"

```bash
# Inspect
fireagent hosts status worker-01
fireagent hosts resource-usage worker-01

# Force cleanup via operator SDK
python3 -c "
from fireagent_host.operator import Operator
Operator().delete_sandbox('fireagent@worker-01:22', 'sb-stuck-id')
"
```

### Memory pressure on workers

```bash
fireagent hosts resource-usage fireagent@worker-01:22
# → cpu_cores: 16, total_memory_mib: 65536, active_sandbox_count: 423
# → free_disk_gb: 234, firecracker_version: 1.2.0

# Adjust per-sandbox memory limit in /etc/fireagent/agent.conf
# [cgroups]
# memory_limit_gb = 1
```

### High creation latency

```bash
# Pre-distribute images to all workers
for h in worker-{01..10}; do
  rsync -av /artifacts/images/* fireagent@$h:/artifacts/images/
done

# Check cache hit rate on the control plane
```

---

## Architecture

```
     Agent SDK (fireagent/)
          │
     FastAPI Control Plane (fireagent_api/)
          │
     ┌────┴────┐
     │         │
  Local    Remote (SSH)
  │         │
Host Agent  RemoteMicroVMManager
  │         │
MicroVMManager
  │
FirecrackerAPI / MockFirecracker
  │
GuestAgentChannel (serial / vsock / in-process)
  │
Guest Agent inside microVM
```

### Components

| Component | Location | Purpose |
|-----------|----------|---------|
| `fireagent/` | `src/fireagent/` | Python SDK + CLI (click-based) |
| `fireagent_api/` | `src/fireagent_api/` | FastAPI control plane |
| `fireagent_host/` | `src/fireagent_host/` | Firecracker REST API, SSH transport, Operator SDK |
| `fireagent_agent/` | `src/fireagent_agent/` | Legacy host agent daemon |
| `fireagent_guest/` | `src/fireagent_guest/` | Guest agent (runs inside microVM) |

### States

```
queued → creating → ready → running → stopping → stopped
  ↓         ↓          ↓        ↓          ↓         ↓
failed    failed    expired    expired    failed    deleted
```

---

## Tests

```bash
# Unit + integration + property-based
pytest tests/          # 233 tests

# By area
pytest tests/unit/     # Unit tests (service, client, CLI, host, guest, security, property, Firecracker host, remote)
pytest tests/integration/  # API route tests (FastAPI)
pytest tests/e2e/          # End-to-end lifecycle

# With coverage
pytest --cov=fireagent --cov=fireagent_host --cov-report=html
```

## License

MIT — Copyright (c) 2026 Supreet Sethi, Spacesword AI.

Full documentation at **[djinn.github.io/fireagent](https://djinn.github.io/fireagent)**