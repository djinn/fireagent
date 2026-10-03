#!/usr/bin/env bash
# ===========================================================================
# Fireagent — Single-host setup script
# Installs dependencies, creates users, configures directories, and starts
# the control plane and host agent for local development.
# ===========================================================================
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  Fireagent — Single-Host Setup${NC}"
echo -e "${GREEN}============================================${NC}"

# ------------------------------------------------------------------
# 1. Check prerequisites
# ------------------------------------------------------------------
echo -e "\n${YELLOW}[1/8] Checking prerequisites...${NC}"

command -v python3 >/dev/null 2>&1 || { echo -e "${RED}python3 is required${NC}"; exit 1; }
command -v pip3 >/dev/null 2>&1 || { echo -e "${RED}pip3 is required${NC}"; exit 1; }

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "  Python:     $PYTHON_VERSION"

# Check for KVM
if [ -c /dev/kvm ]; then
    echo "  KVM:        available"
else
    echo -e "  ${YELLOW}KVM:         not detected — Firecracker will not run${NC}"
fi

# Check for Firecracker
if command -v firecracker >/dev/null 2>&1; then
    echo "  Firecracker: $(firecracker --version 2>&1 | head -1)"
else
    echo -e "  ${YELLOW}Firecracker: not installed — install with: sudo apt install firecracker${NC}"
fi

# ------------------------------------------------------------------
# 2. Install system dependencies
# ------------------------------------------------------------------
echo -e "\n${YELLOW}[2/8] Installing system dependencies...${NC}"
sudo apt update -qq
sudo apt install -y -qq \
    build-essential \
    curl \
    jq \
    git \
    bridge-utils \
    qemu-utils \
    iptables \
    postgresql postgresql-contrib \
    python3-pip python3-venv \
    2>/dev/null || true

echo "  Done."

# ------------------------------------------------------------------
# 3. Create fireagent user
# ------------------------------------------------------------------
echo -e "\n${YELLOW}[3/8] Creating fireagent user...${NC}"
if id "fireagent" &>/dev/null; then
    echo "  User fireagent already exists."
else
    sudo useradd -m -s /bin/false -G kvm fireagent
    echo "  Created user 'fireagent'."
fi

# ------------------------------------------------------------------
# 4. Set up directories
# ------------------------------------------------------------------
echo -e "\n${YELLOW}[4/8] Setting up directories...${NC}"
sudo mkdir -p /opt/fireagent
sudo mkdir -p /etc/fireagent
sudo mkdir -p /var/fireagent/sandboxes
sudo mkdir -p /artifacts/images

sudo chown -R fireagent:fireagent /opt/fireagent /etc/fireagent /var/fireagent /artifacts

echo "  /opt/fireagent/          — Application"
echo "  /etc/fireagent/          — Configuration"
echo "  /var/fireagent/sandboxes/ — Sandbox working directories"
echo "  /artifacts/images/       — Guest images"

# ------------------------------------------------------------------
# 5. Set up Python virtual environment
# ------------------------------------------------------------------
echo -e "\n${YELLOW}[5/8] Setting up Python virtual environment...${NC}"
python3 -m venv /opt/fireagent/venv
source /opt/fireagent/venv/bin/activate
pip install --quiet --upgrade pip setuptools wheel

# Install fireagent from source
cd "$(dirname "$0")/.."
pip install -e ".[dev,agent]"

echo "  Virtual environment: /opt/fireagent/venv"

# ------------------------------------------------------------------
# 6. Configure Fireagent
# ------------------------------------------------------------------
echo -e "\n${YELLOW}[6/8] Creating default configuration...${NC}"

cat > /etc/fireagent/agent.conf << 'CONF'
[agent]
host_id = "host-01"
control_plane_url = "http://127.0.0.1:8000"
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
CONF

echo "  Configuration: /etc/fireagent/agent.conf"

# ------------------------------------------------------------------
# 7. Install systemd service (fireagent-agent)
# ------------------------------------------------------------------
echo -e "\n${YELLOW}[7/8] Installing systemd service...${NC}"

cat > /tmp/fireagent-agent.service << 'SERVICE'
[Unit]
Description=Fireagent Host Agent
After=network.target

[Service]
Type=simple
User=fireagent
Group=fireagent
ExecStart=/opt/fireagent/venv/bin/python -m fireagent_agent.agent --config /etc/fireagent/agent.conf
Restart=always
RestartSec=5
Environment=FIREAGENT_BASE_URL=http://127.0.0.1:8000

[Install]
WantedBy=multi-user.target
SERVICE

sudo cp /tmp/fireagent-agent.service /etc/systemd/system/fireagent-agent.service
sudo systemctl daemon-reload

echo "  Service: fireagent-agent.service"

# ------------------------------------------------------------------
# 8. Done
# ------------------------------------------------------------------
echo -e "\n${GREEN}============================================${NC}"
echo -e "${GREEN}  Setup complete!${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo "  Start the control plane:"
echo "    source /opt/fireagent/venv/bin/activate"
echo "    fireagent-api"
echo ""
echo "  Start the host agent:"
echo "    sudo systemctl start fireagent-agent"
echo ""
echo "  Run the smoke test:"
echo "    source /opt/fireagent/venv/bin/activate"
echo "    python examples/basic_test.py"
echo ""