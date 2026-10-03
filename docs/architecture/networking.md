# Networking Model

## Design principles

- **Deny-by-default** – No inbound or outbound traffic unless explicitly allowed.
- **Isolated per sandbox** – No cross-sandbox communication.
- **Egress-only control** – Only outbound traffic can be policy-controlled.
- **Host protection** – No access to host services, metadata endpoints, or private IPs.
- **Minimal attack surface** – TAP interface is the only network attachment.

## Architecture

```mermaid
flowchart TD
    S["Sandbox microVM"]
    S -->|TAP interface| N["Bridge (br0)"]
    N -->|upstream| E["Egress Proxy
(i.e., fireagent-proxy")]
    E -->|upstream| I["Internet
or internal network"]
    N -->|internal| H["Host agent
with iptables/nftables"]
    H -->|monitoring| L["Logs & Metrics"]
    H -->|control| C["Control Plane
(Sandbox API)"]
    C -->|policies| H
    L -->|aggregation| M["Observability
(ELK, Prometheus)"]
```

## TAP interface

Each sandbox gets a dedicated TAP interface with a unique name (e.g., `tap-sb-a1b2c3`).

- Created at sandbox creation
- Assigned to the bridge `br0` (or `fireagent-br`)
- IP address assigned via DHCP or static (optional)
- Automatically deleted on sandbox stop/delete

Example:

```bash
# Create TAP interface
sudo ip tuntap add dev tap-sb-a1b2c3 mode tap user fireagent

# Bring up
sudo ip link set tap-sb-a1b2c3 up

# Attach to bridge
sudo ip link set tap-sb-a1b2c3 master br0

# Set MAC (optional)
sudo ip link set tap-sb-a1b2c3 address 02:00:00:00:00:a1
```

## Bridge and firewall

### Bridge (`br0`)

- Default bridge for all Fireagent sandboxes
- Created at host agent startup
- Has no IP address
- Forwarding enabled

### iptables/nftables rules

Rules are applied per sandbox at creation time. Default rules:

```bash
# Deny all inbound
-A INPUT -i br0 -j DROP

# Deny all outbound
-A OUTPUT -o br0 -j DROP

# Allow DHCP (if needed)
-A OUTPUT -o br0 -p udp --dport 67 -j ACCEPT
-A INPUT -i br0 -p udp --sport 67 -j ACCEPT

# Allow DNS
-A OUTPUT -o br0 -p udp --dport 53 -j ACCEPT
-A OUTPUT -o br0 -p tcp --dport 53 -j ACCEPT

# Allow egress proxy (if configured)
-A OUTPUT -o br0 -d 10.0.0.100 -j ACCEPT
```

Rule application is idempotent: rules are applied only once per sandbox, and new rules overwrite old ones.

## Egress proxy

The egress proxy is an optional layer that:

- Acts as a gateway for outbound traffic
- Enforces policy (allowlist) for destination IPs and ports
- Logs all outbound requests
- Can perform TLS inspection or rate limiting

### Proxy configuration

```yaml
# /etc/fireagent/proxy.yaml
proxy:
  enabled: true
  bind_address: "10.0.0.100"
  port: 8080
  allowlist:
    - host: "github.com"
      port: 443
      protocol: "tcp"
    - host: "pypi.org"
      port: 443
      protocol: "tcp"
    - host: "registry.hub.docker.com"
      port: 443
      protocol: "tcp"
  logging: true
  rate_limit: 1000
```

### Proxy lifecycle

- Starts at host agent boot
- Listens on `10.0.0.100:8080`
- All outbound traffic from sandboxes is routed through it
- Sandboxes are configured to use `10.0.0.100` as their gateway

## Network policies

### Default policy

- `network_policy: deny-all`
- No inbound or outbound traffic
- Only allowed if explicitly overridden

### Explicit allow rules

Clients can specify allow rules in the `create` request:

```json

  "image": "ubuntu:24.04",
  "network_policy": {
    "rules": [
      {
        "action": "allow",
        "protocol": "tcp",
        "destination": "github.com",
        "port": 443
      },
      {
        "action": "allow",
        "protocol": "tcp",
        "destination": "pypi.org",
        "port": 443
      }
    ]
  }
}
```

### Policy application

- Rules are applied via `iptables` or `nftables`
- Multiple sandboxes can have different rules
- Rules are enforced at the bridge level, not at the guest level
- No rule can permit access to host services, `10.0.0.0/8`, `192.168.0.0/16`, or `172.16.0.0/12`

## Security hardening

- **No access to host services** – Sandboxes cannot access `localhost`, `127.0.0.1`, or any host IP
- **No access to metadata endpoints** – `169.254.169.254` is blocked
- **No access to private networks** – All internal IP ranges are blocked
- **No DNS spoofing** – DNS requests are routed through the egress proxy or host resolver
- **Logging** – All policy denials are logged with sandbox ID, timestamp, and rule

## Debugging and diagnostics

### Check TAP interface

```bash
ip link show tap-sb-a1b2c3
```

### Check bridge

```bash
brctl show br0
```

### Check iptables rules

```bash
sudo iptables -L -n -v | grep tap-sb-a1b2c3
```

### Check egress proxy logs

```bash
journalctl -u fireagent-proxy -f
```

## Next steps

- [ ] Add support for UDP and ICMP
- [ ] Implement rate limiting per sandbox
- [ ] Add TLS inspection (optional)
- [ ] Add support for VLANs
- [ ] Add support for custom routing tables
- [ ] Add network performance monitoring (latency, packet loss)
- [ ] Implement network traffic shaping (QoS)