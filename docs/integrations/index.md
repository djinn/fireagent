# AI Coding Agent Integrations

Fireagent integrates seamlessly with AI-powered coding agents to give them **isolated, stateful, disposable Linux environments** for command execution, code evaluation, and multi-step agentic workflows.

<div class="grid cards" markdown>

-   :material-code-braces: **Claude Code** – Run agentic coding sessions inside Firecracker microVMs. Isolate tool execution, protect the host, and give Claude its own Linux environment.
-   :fontawesome-brands-python: **OpenAI Codex** – Deploy Codex agent loops into disposable sandboxes for safe code execution, testing, and evaluation.
-   :material-lan: **Coding Agent Sandbox** – A reusable pattern: start a sandbox, install tools, hand the agent a shell, collect results, tear down.
-   :material-security: **Why isolate?** – Coding agents run LLM-generated shell commands. MicroVM isolation ensures a hallucinated `rm -rf /` or malicious package install never touches your host.

</div>

---

## Available Integrations

| Integration | Description | Quick Start |
|-------------|-------------|-------------|
| [Claude Code](claude-code.md) | Run Claude Code coding sessions in isolated microVMs via the Operator SDK or SSH sandbox pattern | `pip install fireagent && fireagent sandboxes create ...` |
| [OpenAI Codex](openai-codex.md) | Forward Codex agent execution to Fireagent sandboxes for safe code evaluation and RL rollout | See dedicated guide |
| [Generic Agent Pattern](generic-agent.md) | The general pattern for wiring any AI coding agent to fireagent | Tool-calling agent → fireagent SDK → isolated sandbox |

---

## Common Integration Patterns

All coding agent integrations follow one of three patterns:

### Pattern A: Agent-Side SDK (Direct)

The coding agent imports `fireagent` and calls `fa.create()`, `sb.exec()`, etc. directly.
Best for agents that can install Python packages and talk to a local or remote API server.

```python
import fireagent as fa

# Agent creates isolated sandbox
sb = fa.create(image="ubuntu:24.04", vcpus=2, memory_mib=1024, disk_mib=2048)
sb.wait_for("ready")

# Agent runs commands inside sandbox
result = sb.exec("pip install pytest && pytest tests/")
print(result.stdout)

# Clean up
sb.stop()
sb.delete()
```

### Pattern B: Remote Operator (SSH Workers)

Use the Operator SDK to dispatch sandboxes to remote worker machines.
Best for multi-host deployments where the coding agent runs on a lightweight client.

```python
from fireagent_host.operator import Operator

op = Operator()
op.add_host("worker-gpu-01.example.com", deploy_key=True)

sb = op.create_sandbox("worker-gpu-01.example.com", "sb-abc",
                        "ubuntu:24.04", vcpus=8, memory_mib=16384, disk_mib=32768)
result = op.exec_command("worker-gpu-01.example.com", "sb-abc", "python3 eval.py")
```

### Pattern C: CLI Wrapper

The agent uses the `fireagent` CLI as a shell tool, piping commands through sandboxes.
Best for read-only agents that can only run shell commands.

```bash
# Create sandbox, capture its ID
SANDOX_ID=$(fireagent sandboxes create --image ubuntu:24.04 --vcpus 2 --memory 1024 --format json | jq -r '.id')

# Run commands inside sandbox
fireagent sandboxes exec $SANDOX_ID --command "git clone https://github.com/example/repo.git /workspace"
fireagent sandboxes exec $SANDOX_ID --command "cd /workspace && python3 -m pytest"

# Clean up
fireagent sandboxes stop $SANDOX_ID
fireagent sandboxes delete $SANDOX_ID
```

---

## Why Coding Agents Need Fireagent

| Challenge | Without Fireagent | With Fireagent |
|-----------|-------------------|----------------|
| **Safety** | Agent runs shell commands directly on host | Agent runs inside isolated microVM — host is safe |
| **Statefulness** | Files and state accumulate on host | Each session gets a fresh workspace; cleanup is guaranteed |
| **Reproducibility** | Environment varies per host | Bundled guest image guarantees same environment |
| **Resource control** | Agent can consume all RAM/CPU | cgroups enforce per-sandbox CPU, memory, and disk limits |
| **Parallelism** | One agent at a time | Hundreds of agents in parallel on one host |
| **Network isolation** | Agent can reach internal services | Network policies block or allow specific destinations |
| **Evaluation fairness** | Results affected by host state | Every run starts from a clean, pinned image |

---

## Next Steps

- **Claude Code users** → [Claude Code Integration Guide](claude-code.md)
- **OpenAI Codex users** → [OpenAI Codex Integration Guide](openai-codex.md)
- **Generic / custom agents** → [Generic Agent Pattern](generic-agent.md)
- **Architecture overview** → [System Design](../architecture/overview.md)
- **SDK reference** → [Python SDK Reference](../sdk/reference.md)