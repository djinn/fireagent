# Fireagent Guest Init Script
# This is the init script that runs inside the Firecracker microVM.
# It mounts the workspace volume and starts the guest agent.

#!/bin/sh

set -e

echo "=== Fireagent Guest ==="

# Mount workspace (second virtio drive)
if [ -b /dev/vdb ]; then
    mkdir -p /workspace
    mount -o rw,noexec,nosuid /dev/vdb /workspace
    echo "[init] Workspace mounted at /workspace"
fi

# Set environment
export PATH="/usr/local/bin:/usr/bin:/bin"
export HOME="/root"
export TERM="linux"
export WORKSPACE="/workspace"

# Start guest agent
echo "[init] Starting guest agent..."
python3 /usr/bin/fireagent-guest-agent.py &

# Signal readiness
echo "[init] Guest agent ready"
echo "ready" > /dev/console 2>/dev/null || true

# Sleep forever to keep the VM alive
while true; do
    sleep 30
done