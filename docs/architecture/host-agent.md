# Host Agent

## Role and responsibilities

The **host agent** is the trusted daemon that runs on every Linux worker host. It is the *only* component that directly interacts with Firecracker and the host OS. Its job is to:

- Launch and manage Firecracker processes
- Create and configure TAP interfaces for networking
- Attach and detach drives (guest image, workspace volume)
- Apply and enforce resource limits via cgroups
- Report health and capacity to the control plane
- Clean up orphaned processes, sockets, and files
- Log all events, both successful and failed

The host agent runs in a minimal environment with the fewest privileges possible.

## Architecture

```mermaid
flowchart TD
    H["Host Agent
(i.e., fireagent-agent")]
    H -->|"Firecracker process"| F["Firecracker
microVM"]
    H -->|"TAP interface"| N["Network
(bridge, firewall)"]
    H -->|"cgroups"| R["Resource limits
(CPU, memory, disk)"]
    H -->|"API socket"| A["Control Plane
(Sandbox API)"]
    H -->|"logs"| L["Logging
(syslog, JSON)"]
    H -->|"health"| C["Heartbeat
(periodic, 10s)"]
    F -->|"workspace"| W["Workspace
volume (RW)"]
    F -->|"image"| I["Guest
image (RO)"]
    A -->|"commands"| H
    C -->|"status"| A
```

## Launch and lifecycle

### Starting

The host agent is launched as a systemd service:

```ini
# /etc/systemd/system/fireagent-agent.service
[Unit]
Description=Fireagent Host Agent
After=network.target

[Service]
Type=simple
User=fireagent
Group=fireagent
ExecStart=/usr/bin/fireagent-agent --config /etc/fireagent/agent.conf
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

It starts with a minimal `fireagent` user (no shell, no login, no sudo).

### Boot sequence

When the host agent starts:

1. Reads configuration from `/etc/fireagent/agent.conf`
2. Initializes cgroups for CPU and memory limits
3. Registers itself with the control plane (`POST /v1/hosts`) with:
   - Host ID (UUID)
   - CPU cores
   - Total memory (MiB)
   - Total disk (GiB)
   - Free disk (GiB)
   - Host OS, kernel version
   - Agent version
4. Starts heartbeat loop (every 10 seconds)

### Heartbeat

Every 10 seconds, the agent sends a `PUT /v1/hosts/{id}/heartbeat` request with:

- Current capacity (free CPU, memory, disk)
- Uptime
- Error count
- Active sandbox count

If the control plane doesn't receive a heartbeat for 30 seconds, the host is marked as `unhealthy`, and its sandboxes are transitioned to `failed`.

## MicroVM management

### Create a sandbox

On `POST /v1/sandboxes` from the control plane:

1. The agent generates a unique `sandbox_id` (UUID)
2. Creates a working directory: `/var/fireagent/sandboxes/{sandbox_id}/`
3. Sets up the Firecracker API socket at `firecracker.sock`
4. Attaches drives:
   - Guest image: read-only, `--rootfs` argument
   - Workspace volume: read-write, `--drives` argument
5. Creates a TAP interface (e.g., `tap0`) and assigns it to the sandbox
6. Applies network policies from the control plane (iptables/nftables rules)
7. Launches Firecracker with the jailer:
   ```bash
   firejail --seccomp --cgroups --net=none --pid=0 -- /usr/bin/firecracker \
     --api-sock /var/fireagent/sandboxes/sb-a1b2c3/firecracker.sock \
     --kernel /artifacts/images/ubuntu:24.04/kernel \
     --rootfs /artifacts/images/ubuntu:24.04/rootfs.ext4 \
     --drives /var/fireagent/sandboxes/sb-a1b2c3/workspace.img
   ```
8. Waits for the guest agent to report healthy (at `/health` endpoint)
9. Reports `ready` to the control plane

### Execute command

On `POST /v1/sandboxes/{id}/exec`:

1. The agent forwards the command to the guest agent via the serial port or vsock
2. The guest agent spawns the command in a shell (e.g., `sh -c "command"`)
3. Captures stdout/stderr and monitors timeout
4. Returns structured results with timing and exit code

### Stop

On `POST /v1/sandboxes/{id}/stop`:

1. Sends SIGTERM to the Firecracker process
2. Waits 5 seconds for graceful shutdown
3. If not stopped, sends SIGKILL
4. Detaches drives and deletes TAP interface
5. Removes working directory
6. Reports `stopped` to control plane

### Delete

On `DELETE /v1/sandboxes/{id}`:

1. Stops the sandbox (if not stopped)
2. Deletes the workspace volume
3. Cleans up temporary files
4. Reports to control plane

## Resource controls

### CPU limits

- Firecracker uses `vcpu_count` from the `create` request
- Host agent sets cgroup v1 `cpu.shares`:
  ```bash
  echo 1024 > /sys/fs/cgroup/cpu/sandbox/sb-a1b2c3/cpu.shares
  ```

### Memory limits

- Host agent sets cgroup v1 `memory.limit_in_bytes`:
  ```bash
  echo 2147483648 > /sys/fs/cgroup/memory/sandbox/sb-a1b2c3/memory.limit_in_bytes
  ```

### Disk limits

- Host agent creates a `qemu-img` file for the workspace volume with a size limit:
  ```bash
  qemu-img create -f qcow2 -o size=10GiB workspace.img
  ```
- Applies filesystem quotas:
  ```bash
  setquota -u sandbox_user 10485760 10485760 0 0 /var/fireagent/sandboxes/sb-a1b2c3
  ```

### Process and file limits

- Limits are enforced at the Firecracker process level via `seccomp` and `cgroups`
- Max processes: 1000
- Max file descriptors: 1024
- Max command runtime: 300 seconds

## Security model

- **Principle of least privilege**: The host agent runs as `fireagent` user with no shell.
- **No root access**: Even if compromised, an attacker cannot escalate to root.
- **Firecracker jailer**: Prevents access to host filesystem, devices, and network.
- **seccomp filters**: Restricted system calls — no `mount`, `chroot`, `socket`, etc.
- **cgroups**: Enforce CPU, memory, and disk limits.
- **Network isolation**: No access to host services, private IPs, or other sandboxes.

## Error handling and recovery

- **Orphan detection**: On agent startup, scans `/var/fireagent/sandboxes/` for old working directories and Firecracker processes
- **Cleanup**: Stops and removes any orphaned microVMs
- **Health monitoring**: If more than 10% of sandboxes fail in 1 minute, logs alert
- **Fallback**: If the control plane is unreachable, the agent continues to manage local sandboxes but does not report health

## Configuration

```ini
# /etc/fireagent/agent.conf
[agent]
host_id = "host-01"
control_plane_url = "https://api.fireagent.example.com"
heartbeat_interval = 10
log_level = "info"

[storage]
workspace_dir = "/var/fireagent/sandboxes"
image_dir = "/artifacts/images"

[firecracker]
bin_path = "/usr/bin/firecracker"
jailer_path = "/usr/bin/firejail"

[cgroups]
cpu_shares = 1024
memory_limit = 2GB

[security]
seccomp_profile = "fireagent"
run_as_user = "fireagent"
```

## Next steps

- [ ] Add support for Firecracker v0.36.0
- [ ] Implement journalctl integration for logs
- [ ] Add Prometheus metrics endpoint (`/metrics`)
- [ ] Implement live migration (Phase 3)
- [ ] Add logging to external system (e.g., ELK)
- [ ] Add audit trail for every operation