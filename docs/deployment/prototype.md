# Single-Host Prototype

## Overview

Phase 1 of Fireagent runs on a single Linux host. This is the fastest way to get the platform running, validate the lifecycle and isolation, and start developing workloads.

## Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| CPU | 4 cores (Intel/AMD with KVM) | 8+ cores |
| RAM | 8 GiB | 16+ GiB |
| Disk | 50 GiB SSD | 200+ GiB NVMe |
| OS | Ubuntu 24.04 LTS | Ubuntu 24.04 LTS |
| KVM | Hardware virtualization enabled | - |

## Step-by-step setup

### 1. Install system dependencies

```bash
sudo apt update
sudo apt install -y \
  python3.10 python3.10-venv \
  postgresql postgresql-contrib \
  firecracker firejail \
  qemu-utils \
  bridge-utils \
  iptables \
  jq curl \
  git build-essential
```

### 2. Create service user

```bash
sudo useradd -m -s /bin/false fireagent
sudo usermod -aG kvm fireagent
```

### 3. Set up PostgreSQL

```bash
sudo -u postgres createdb fireagent
sudo -u postgres createuser --no-superuser --no-createrole --createdb fireagent
sudo -u postgres psql -c "ALTER USER fireagent WITH PASSWORD 'fireagent';"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE fireagent TO fireagent;"
```

Set `listen_addresses = 'localhost'` in `/etc/postgresql/16/main/postgresql.conf`.

### 4. Create Python environment & install

```bash
python3 -m venv /opt/fireagent
source /opt/fireagent/bin/activate
pip install --upgrade pip setuptools wheel
pip install fireagent
```

### 5. Configure host agent

```bash
sudo mkdir -p /etc/fireagent /var/fireagent/sandboxes /artifacts/images
sudo chown -R fireagent:fireagent /etc/fireagent /var/fireagent /artifacts
```

Create `/etc/fireagent/agent.conf`:

```ini
[agent]
host_id = "host-01"
control_plane_url = "http://localhost:8000"
heartbeat_interval = 10
log_level = "info"

[storage]
workspace_dir = "/var/fireagent/sandboxes"
image_dir = "/artifacts/images"

[firecracker]
bin_path = "/usr/bin/firecracker"

[cgroups]
cpu_shares = 1024
memory_limit_gb = 2

[security]
run_as_user = "fireagent"
```

### 6. Start services

```bash
# Start database
sudo systemctl start postgresql

# Start control plane
nohup /opt/fireagent/bin/uvicorn fireagent.api:app \
  --host 0.0.0.0 --port 8000 \
  --log-level info > /var/log/fireagent-api.log 2>&1 &

# Start host agent
sudo systemctl start fireagent-agent
```

### 7. Verify

```bash
# Check control plane
curl http://localhost:8000/v1/health

# Check host agent
curl http://localhost:8000/v1/hosts/host-01

# List sandboxes
curl http://localhost:8000/v1/sandboxes
```

### 8. Test

```bash
# Run the test script
python3 /opt/fireagent/examples/basic_test.py
```

## Smoke test checklist

- [ ] Control plane starts and responds
- [ ] Host agent registers and heartbeats
- [ ] Sandbox creation succeeds
- [ ] Sandbox reaches `ready` state
- [ ] Command execution returns output
- [ ] File changes persist between commands
- [ ] Sandbox stop works
- [ ] Sandbox delete cleans up
- [ ] Resource limits are enforced (CPU, memory, disk)
- [ ] Network is denied by default
- [ ] Explicit network allow rules work
- [ ] Guest cannot read host files
- [ ] Guest cannot reach other sandboxes

## Troubleshooting

| Problem | Likely cause |
|---------|-------------|
| Sandbox stuck in `queued` | Host agent not running or not registered |
| Sandbox stuck in `creating` | Firecracker binary missing or KVM disabled |
| Sandbox stuck in `ready` | Guest agent not responding |
| Command times out | Execution timeout too short or command hangs |
| Network rule not applied | Egress proxy not started or iptables not configured |
| Disk limit not enforced | Filesystem quota not set |
| cgroup limit not enforced | cgroups v1 not mounted