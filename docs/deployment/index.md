# Deployment

## Overview

Fireagent is designed to scale from a single-host prototype to a multi-host production service. The deployment architecture is modular and extensible.

## Phase 1: Single-host prototype

### Components

- One Linux host (e.g., Ubuntu 24.04)
- Firecracker installed
- Host agent running as systemd service
- FastAPI control plane
- PostgreSQL state store
- Local SSD for guest images and workspace volumes

### Setup

```bash
# Install dependencies
sudo apt update
sudo apt install -y python3-pip postgresql postgresql-contrib firecracker firejail

# Create fireagent user
sudo useradd -m -s /bin/false fireagent

# Install Python dependencies
pip3 install -r requirements.txt

# Create PostgreSQL database
sudo -u postgres createdb fireagent
sudo -u postgres createuser -P fireagent

# Start Postgres
sudo systemctl start postgresql

# Run migrations (if any)
python3 -m fireagent.migrate

# Start control plane
python3 -m fireagent.api

# Start host agent
sudo systemctl start fireagent-agent
```

### Test

```python
import fireagent as fa

sb = fa.create(image="ubuntu:24.04", vcpus=1, memory_mib=512)
sb.wait_for("ready")
result = sb.exec("echo 'Hello from sandbox'")
print(result.stdout)
sb.stop()
sb.delete()
```

## Phase 2: Multi-host service

### Components

- FastAPI control plane (multi-replica)
- PostgreSQL with replication (primary + standby)
- Multiple Linux hosts with host agents
- Shared SSD or NFS for image and workspace storage
- Load balancer (e.g., Nginx)
- Prometheus + Grafana for metrics
- ELK stack for logs

### Deployment

```bash
# On control plane nodes
python3 -m fireagent.api --replica-id=1
python3 -m fireagent.api --replica-id=2

# On host nodes
sudo systemctl start fireagent-agent

# On storage node
sudo apt install -y nfs-kernel-server
sudo mkdir /artifacts
sudo chown fireagent:fireagent /artifacts
sudo chmod 755 /artifacts

# In /etc/exports
/artifacts *(rw,sync,no_root_squash)

# On control plane
sudo systemctl start nfs-client
sudo mount storage-host:/artifacts /artifacts
```

### Scaling

- Add hosts: register new hosts with the control plane
- Add replicas: start new control plane instances
- Add storage: expand NFS or use object storage

## Phase 3: Elastic scale

### Components

- Queue-based job processing (e.g., Celery + Redis)
- Auto-scaling host groups (e.g., K8s, EC2 Auto Scaling)
- Shared object storage (e.g., S3)
- Advanced scheduling (e.g., Kubernetes CRD)
- Snapshot recovery (after testing)
- Admission control during overload

### Deployment

```bash
# Start Celery workers
celery -A fireagent.celery_app worker -l info

# Start Redis
redis-server

# Start control plane with queue backend
python3 -m fireagent.api --queue-backend=redis

# Deploy host agents on auto-scaling group
# Configure host agent to register with control plane
```

## Next steps

- [ ] Add Helm charts for Kubernetes deployment
- [ ] Add Terraform for infrastructure as code
- [ ] Add CI/CD pipeline for automated deployment
- [ ] Add health checks and readiness probes
- [ ] Add automatic failover for PostgreSQL
- [ ] Add automated scaling based on resource usage
- [ ] Add snapshot recovery tests