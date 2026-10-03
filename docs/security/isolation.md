# Isolation Guarantees

## How isolation works

Fireagent uses **five layers of isolation** to ensure that one sandbox cannot affect another, or the host:

1. **Firecracker microVM** – Kernel-level isolation (hardware virtualization)
2. **cgroups** – Resource-level isolation (CPU, memory, disk)
3. **seccomp** – System-call-level isolation
4. **Filesystem isolation** – Unique working directories, no shared mounts
5. **Network isolation** – Dedicated TAP interfaces, deny-by-default iptables

## Layer 1: Firecracker microVM

Firecracker is the primary isolation boundary. Each sandbox runs as a **separate Linux kernel** inside a Firecracker process. Firecracker uses **KVM (Kernel-based Virtual Machine)** to create isolated execution environments.

**What this means:**
- Each sandbox has its own kernel, init system, and libraries
- A crash in the guest kernel does not affect the host kernel
- No shared memory, filesystem, or process space between VMs
- The only interface between guest and host is the Firecracker API socket (which is not exposed to clients)

**Hardware requirements:**
- Intel VT-x or AMD-V (hardware virtualization)
- KVM enabled in the Linux kernel
- Sufficient host RAM for allocatted guest memory

## Layer 2: cgroups

cgroups (control groups) enforce CPU, memory, and disk limits at the OS level.

### CPU

Each sandbox's Firecracker process is assigned a cgroup with a CPU share:

```bash
# Create cgroup
cgcreate -g cpu:fireagent/sandbox-sb-a1b2c3

# Set CPU limit (1024 = 100%, 512 = 50%)
cgset -r cpu.shares=1024 fireagent/sandbox-sb-a1b2c3

# Move Firecracker process
cgclassify -g cpu:fireagent/sandbox-sb-a1b2c3 <firecracker-pid>
```

### Memory

Memory is enforced at both the cgroup and Firecracker level:

```bash
# Create cgroup
cgcreate -g memory:fireagent/sandbox-sb-a1b2c3

# Set 1 GiB limit
cgset -r memory.limit_in_bytes=1073741824 fireagent/sandbox-sb-a1b2c3

# Move Firecracker process
cgclassify -g memory:fireagent/sandbox-sb-a1b2c3 <firecracker-pid>
```

If memory is exceeded, the OOM killer kills the Firecracker process.

### Disk

Disk quotas are enforced via filesystem quotas on the workspace directory:

```bash
# Set 10 GiB quota
setquota -u fireagent 0 10485760 0 0 /var/fireagent/sandboxes/sb-a1b2c3
```

## Layer 3: seccomp

Firecracker's jailer applies seccomp filters to the Firecracker process. The filters restrict the system calls that the process can make.

**Blocked syscalls:**
- `mount`, `umount`, `chroot`, `pivot_root`
- `ptrace`, `process_vm_writev`, `process_vm_readv`
- `syslog`, `sysctl`, `reboot`
- `mkfifo`, `mknod`, `mknoda`
- `setuid`, `setgid`, `setreuid`, `setregid`

**Allowed syscalls (required for Firecracker operation):**
- `read`, `write`, `open`, `close`, `fstat`, `lseek`, `ftruncate`
- `mmap`, `munmap`, `mprotect`, `madvise`, `mlockall`
- `clone`, `execve`, `waitpid`, `kill`, `exit`
- `socket`, `bind`, `listen`, `accept`, `connect`
- `select`, `poll`, `epoll` (for I/O multiplexing)
- `ioctl`, `fcntl`, `stat`, `lstat`, `readlink`

## Layer 4: Filesystem isolation

### Container within a VM

Each sandbox is a Firecracker VM with a **read-only root filesystem** (the guest image) and a **writable workspace volume**.

- The root filesystem (`rootfs.ext4`) is read-only — no changes persist across sandbox restarts
- The workspace volume (`workspace.img`) is read-write and is the only persistent storage
- The workspace volume is mounted under `/workspace` inside the guest
- No host filesystem paths are mounted inside the guest

### Working directory

Each sandbox has a unique working directory on the host:

```
/var/fireagent/sandboxes/
├── sb-a1b2c3/
│   ├── firecracker.sock    # Firecracker API socket (not exposed to clients)
│   ├── workspace.img       # Workspace volume
│   └── system.log          # Firecracker process logs
└── sb-d4e5f6/
    ├── firecracker.sock
    ├── workspace.img
    └── system.log
```

- Directories are owned by the `fireagent` user
- No other user (including `root`) has access to another sandbox's directory
- Directories and files are deleted on sandbox delete

## Layer 5: Network isolation

Each sandbox has a dedicated TAP interface:

```
Host:                         Guest:
tap-sb-a1b2c3                 eth0
   │                           │
   │  (no routing between      │
   │   sandbox TAPs)           │
   │                           │
   v                           v
  bridge (br0)                  |
   │                           │
   ├── egress proxy (optional) │
   │                           │
   └── iptables rules          │
        (deny-all by default)  │
```

- No IP routing between TAP interfaces
- iptables rules block all inbound/outbound traffic by default
- Explicit allow rules can be set per sandbox
- No access to host `localhost`, `127.0.0.1`, private IPs, or metadata endpoints

## Testing isolation

### Can Guest A reach Guest B?

```bash
# From Guest A
ping 10.0.0.2   # Guest B's IP
# Result: No route to host
telnet 10.0.0.2 22
# Result: Connection refused
```

### Can Guest reach host?

```bash
# From Guest
ping 127.0.0.1
# Result: Sent to itself (guest localhost)
curl http://169.254.169.254/latest/meta-data/
# Result: Connection timed out
curl http://10.0.0.1:5432
# Result: Connection refused
```

### Can Guest read host files?

```bash
# From Guest
cat /proc/1/environ
# Result: Shows guest init process, not host
ls /proc/1/root/
# Result: Guest's root filesystem, not host's
```

## Isolation guarantees summary

| Property | Guarantee | Violation |
|----------|-----------|-----------|
| No cross-sandbox process access | Firecracker + seccomp | Extremely unlikely with current implementation |
| No cross-sandbox network access | TAP isolation + iptables | Not possible |
| No cross-sandbox filesystem access | Unique working directories + per-user quotas | Not possible |
| Guest cannot read host files | Firecracker + no host mount | Not possible |
| Guest cannot write to host | Firecracker + no writable host mount + seccomp | Not possible |
| Guest cannot communicate with other guests | TAP + iptables + bridge isolation | Not possible |
| Guest cannot DDoS host | cgroups + process limit | Low residual risk |
| Guest cannot reach internet without explicit policy | iptables + egress proxy | Not possible by default |