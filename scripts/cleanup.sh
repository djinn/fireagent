#!/usr/bin/env bash
# ===========================================================================
# Fireagent — Cleanup script
# Removes orphaned Firecracker processes, TAP interfaces, sockets, and
# sandbox working directories.
# ===========================================================================
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

echo -e "${YELLOW}Fireagent Cleanup${NC}"
echo ""

# ------------------------------------------------------------------
# 1. Kill orphaned Firecracker processes
# ------------------------------------------------------------------
echo "[1/5] Killing orphaned Firecracker processes..."
if pgrep -x firecracker > /dev/null 2>&1; then
    sudo pkill -9 firecracker 2>/dev/null || true
    echo "  Killed $(pgrep -x firecracker | wc -l) processes."
else
    echo "  No orphaned Firecracker processes found."
fi

# ------------------------------------------------------------------
# 2. Remove orphaned TAP interfaces
# ------------------------------------------------------------------
echo "[2/5] Removing orphaned TAP interfaces..."
for tap in $(ip link show | grep -oP 'tap-\w+'); do
    sudo ip link delete "$tap" 2>/dev/null && echo "  Deleted $tap" || true
done

# ------------------------------------------------------------------
# 3. Clean up sandbox working directories
# ------------------------------------------------------------------
echo "[3/5] Cleaning sandbox directories..."
SANDBOX_DIR="/var/fireagent/sandboxes"
if [ -d "$SANDBOX_DIR" ]; then
    count=$(ls -1 "$SANDBOX_DIR" 2>/dev/null | wc -l)
    if [ "$count" -gt 0 ]; then
        sudo rm -rf "$SANDBOX_DIR"/*
        echo "  Removed $count sandbox directories."
    else
        echo "  No sandbox directories found."
    fi
else
    echo "  $SANDBOX_DIR does not exist."
fi

# ------------------------------------------------------------------
# 4. Remove Firecracker sockets
# ------------------------------------------------------------------
echo "[4/5] Removing Firecracker sockets..."
find /var/fireagent/sandboxes -name 'firecracker.sock' -delete 2>/dev/null || true
echo "  Done."

# ------------------------------------------------------------------
# 5. Verify no remaining resources
# ------------------------------------------------------------------
echo "[5/5] Verifying cleanup..."
if pgrep -x firecracker > /dev/null 2>&1; then
    echo -e "${RED}Warning: Firecracker processes still running!${NC}"
fi
if ip link show | grep -q 'tap-'; then
    echo -e "${RED}Warning: TAP interfaces still present!${NC}"
fi

echo ""
echo -e "${GREEN}Cleanup complete.${NC}"