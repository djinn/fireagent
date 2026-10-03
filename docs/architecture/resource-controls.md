# Resource Controls

## Why resource controls matter

Without strict limits, a sandbox can:

- Consume all host CPU, starving other sandboxes
- Use all available memory, causing OOM kills or host instability
- Fill up disk, preventing new sandboxes from starting
- Run indefinitely, consuming precious compute

Fireagent enforces limits at **two levels**:

1. **Host-level** – Via cgroups and filesystem quotas
2. **Guest-level** – Via Firecracker’s built-in CPU and memory limits

## CPU controls

### Host-level (cgroups)

- **cgroup v1** used for compatibility
- CPU shares set via `cpu.shares`:
  - `1024` = 100% CPU
  - `512` = 50% CPU
  - `256` = 25% CPU
  - `1024` = 100% for vcpus=1

- **Example**:
  ```bash
  # Set 50% CPU for sandbox sb-a1b2c3
  echo 512 > /sys/fs/cgroup/cpu/sandbox/sb-a1b2c3/cpu.shares
  ```

### Guest-level (Firecracker)

- Firecracker uses `vcpu_count` from the `create` request
- CPU time is distributed via KVM and the host scheduler
- No priority scheduling — all vCPUs are treated equally

### Enforcement

- Host agent sets cgroup at sandbox creation
- cgroup is updated if `vcpus` changes (via `PATCH /v1/sandboxes/{id}`)
- cgroup is removed on sandbox stop/delete

## Memory controls

### Host-level (cgroups)

- Memory limit set via `memory.limit_in_bytes`:
  ```bash
  echo 2147483648 > /sys/fs/cgroup/memory/sandbox/sb-a1b2c3/memory.limit_in_bytes
  ```

- **OOM killer** is enabled: if memory is exceeded, the Firecracker process is killed

### Guest-level (Firecracker)

- `memory_mib` from `create` request is passed to Firecracker
- Firecracker allocates exactly that much RAM
- No overcommit allowed in Phase 1

### Enforcement

- Host agent sets cgroup at sandbox creation
- cgroup is updated if `memory_mib` changes
- cgroup is removed on stop/delete

## Disk controls

### Host-level (filesystem quotas)

- Workspace volume is a `qcow2` file
- Filesystem quotas applied via `setquota`
- Limits are enforced at the filesystem level

- **Example**:
  ```bash
  # Limit workspace to 10 GiB
  setquota -u sandbox_user 10485760 10485760 0 0 /var/fireagent/sandboxes/sb-a1b2c3
  ```

### Guest-level (Firecracker)

- `disk_mib` from `create` request is used to size the workspace image
- Firecracker does not enforce disk limits — that's handled by the host

### Enforcement

- Host agent creates `qcow2` file with `size` limit
- Applies filesystem quotas at creation
- Quotas are removed on stop/delete

## Lifetime and idle timeouts

### TTL (Time To Live)

- `ttl_seconds` in `create` request
- Sandbox is automatically stopped and deleted after this duration
- **Example**:
  ```json
  "ttl_seconds": 3600
  ```

- If the sandbox is `running`, it continues until the TTL expires
- If the sandbox is `ready`, it will be stopped after the TTL

### Idle timeout

- `idle_timeout_seconds` in `create` request
- Sandbox is stopped if no command is executed for this duration
- **Example**:
  ```json
  "idle_timeout_seconds": 600
  ```

- Reset on every `exec` command
- If `idle_timeout_seconds` is `0`, idle timeout is disabled

### Enforcement

- Host agent starts a timer when sandbox reaches `ready`
- Timer is reset on every `exec` command
- Timer is stopped on `stop` or `delete`
- When timeout expires, sandbox is transitioned to `stopped`

## Command execution limits

### Runtime limit

- `execution_timeout` in `exec` request
- Command is terminated if it runs longer than this
- **Example**:
  ```json
  "execution_timeout_seconds": 300
  ```

- If not specified, defaults to 300 seconds
- If `0`, no timeout

### Process limits

- Max processes: 1000
- Max file descriptors: 1024
- Max command runtime: 300 seconds

### Enforcement

- Host agent applies limits via `seccomp` and `cgroups`
- Limits are applied at the Firecracker process level
- No process can exceed the limits

## Resource reporting

### Host agent metrics

The host agent exposes a `/metrics` endpoint with Prometheus-style metrics:

- `fireagent_sandbox_count` – Number of active sandboxes
- `fireagent_cpu_usage_percent` – Host CPU usage
- `fireagent_memory_usage_percent` – Host memory usage
- `fireagent_disk_usage_percent` – Host disk usage
- `fireagent_sandbox_cpu_limit_millicores` – Total CPU limit
- `fireagent_sandbox_memory_limit_bytes` – Total memory limit
- `fireagent_sandbox_disk_limit_bytes` – Total disk limit

### Control plane metrics

- `sandbox_creation_count_total` – Total sandboxes created
- `sandbox_exec_count_total` – Total commands executed
- `sandbox_duration_seconds` – Duration per sandbox
- `sandbox_cpu_usage_percent` – CPU usage per sandbox
- `sandbox_memory_usage_percent` – Memory usage per sandbox
- `sandbox_disk_usage_percent` – Disk usage per sandbox

## Next steps

- [ ] Add support for memory overcommit (Phase 3)
- [ ] Implement CPU bandwidth limiting
- [ ] Add disk I/O throttling
- [ ] Add network bandwidth limiting
- [ ] Implement quota enforcement via kernel filesystem policies
- [ ] Add alerts for resource exhaustion
- [ ] Add autoscaling based on resource usage