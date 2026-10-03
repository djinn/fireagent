# Resources

## Firecracker

- **Official site**: https://firecracker-microvm.github.io/
- **GitHub**: https://github.com/firecracker-microvm/firecracker
- **Documentation**: https://github.com/firecracker-microvm/firecracker/blob/main/docs/
- **Security model**: https://github.com/firecracker-microvm/firecracker/blob/main/docs/design.md
- **REST API**: https://github.com/firecracker-microvm/firecracker/blob/main/docs/api.md

## Related projects

| Project | Description | Comparison |
|---------|-------------|------------|
| **Firecracker** | AWS's microVM monitor | The core technology under Fireagent |
| **QEMU** | Full-featured VM emulator | More features, larger attack surface than Firecracker |
| **Docker** | Container runtime | Shared kernel; less isolation than microVMs |
| **gVisor** | Google's microVM orchestrator | Similar concept, Kubernetes-native |
| **Kata Containers** | Container runtime with VM isolation | Container-focused; Fireagent is API-first |
| **Sysbox** | Docker runtime with VM-like isolation | Container-focused; different architecture |
| **Firecracker-containers** | AWS's container-on-Firecracker | Container runtime; Fireagent is sandbox-focused |

## Tools

| Tool | Purpose |
|------|---------|
| **Buildroot** | Embedded Linux build system for guest images |
| **strace** | System call tracing for debugging guest agent |
| **ltrace** | Library call tracing |
| **tcpdump** | Network traffic analysis |
| **netstat** | Network interface monitoring |
| **iptables** | Firewall rule management |
| **nftables** | Firewall rule management (iptables replacement) |
| **systemctl** | Service management for host agent |
| **cgcreate** | cgroup management |
| **setquota** | Filesystem quota management |
| **Firejail** | Firecracker jailer for seccomp and privilege drops |
| **Prometheus** | Metrics collection |
| **Grafana** | Metrics dashboard |
| **ELK (Elastic, Logstash, Kibana)** | Log aggregation |
| **OpenTelemetry** | Distributed tracing |

## Reading

| Resource | Description |
|----------|-------------|
| **Firecracker whitepaper** | AWS's paper on microVM design |
| **Linux kernel documentation** | KVM, cgroups, seccomp, namespaces |
| **Buildroot manual** | Embedded Linux build system documentation |
| **PostgreSQL documentation** | Database administration and tuning |
| **FastAPI documentation** | Python web framework documentation |
| **OWASP Top 10** | Web application security risks |
| **NIST SP 800-190** | Application container security guide |

## Community

- **GitHub Issues**: https://github.com/djinn/fireagent/issues
- **GitHub Discussions**: https://github.com/djinn/fireagent/discussions
- **Spacesword AI**: https://djinn.ai

## License

Fireagent is released under the [MIT License](https://github.com/djinn/fireagent/blob/main/LICENSE).

## Contributors

- Supreet Sethi – Architect and maintainer
- Spacesword AI – Primary sponsor