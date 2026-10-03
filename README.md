# Fireagent

**Elastic agent sandbox platform powered by Firecracker microVMs.**

Fireagent creates, manages, and destroys isolated Linux microVMs for AI agents,
coding tasks, and evaluation workloads. Each sandbox is a stateful session with
persistent file changes, resource limits, and network policies.

```python
import fireagent as fa

sb = fa.create(image="ubuntu:24.04", vcpus=2, memory_mib=1024)
result = sb.exec("python3 -c 'print(f\"Hello from {__import__(\"platform\").node()}\")'")
print(result.stdout)  # Hello from sb-a1b2c3
sb.stop()
```

## Documentation

Full documentation at **[spaceswordai.github.io/fireagent](https://spaceswordai.github.io/fireagent)**.

## Quick start

```bash
pip install fireagent
export FIREAGENT_API_KEY="sk-abc123..."
python3 -m fireagent_api.app
```

## License

MIT — Copyright (c) 2026 Supreet Sethi