# OpenAI Codex Integration

Run **OpenAI Codex** agent loops inside isolated Fireagent microVMs. This gives Codex a safe, stateful Linux environment for multi-step tasks — code generation, testing, evaluation, and RL rollouts — without exposing your host to generated code.

---

## How It Works

OpenAI Codex is an agent framework that transforms natural language into code, executes it, observes results, and iterates. Fireagent provides the **execution substrate** — a disposable microVM per session:

```
+------------------------------+
|  Your Host                    |
|                                |
|  +---------------------------+|
|  | Codex Agent Loop          ||
|  | 1. User prompt            ||
|  | 2. Codex generates code   ||
|  | 3. Codex -> Code Exec     ||
|  |    (Fireagent sandbox)    ||
|  | 4. Result -> Codex        ||
|  | 5. Iterate or finish      ||
|  +----------+----------------+|
|             |  REST API / SDK |
|             v                 |
|  +---------------------------+|
|  | Fireagent Control Plane   ||
|  +------+--------------------+|
|         | Firecracker microVM |
|         v                     |
|  +---------------------------+|
|  | Isolated Sandbox          ||
|  | - Code executes here      ||
|  | - Files, env persist      ||
|  | - Network policy enforced ||
|  +---------------------------+|
+------------------------------+
```

---

## Prerequisites

- **Fireagent installed**: `pip install fireagent`
- **Fireagent API running**: `fireagent-api &`
- **OpenAI Python SDK**: `pip install openai`
- **OpenAI API key**: `export OPENAI_API_KEY=sk-...`

---

## Integration Methods

### Method 1: Custom Code Interpreter (Sandbox-Exec)

Replace OpenAI's built-in Code Interpreter with a Fireagent sandbox for more control,
lower cost, and persistent state:

```python
import os
import json
from openai import OpenAI
import fireagent as fa


class FireagentCodeInterpreter:
    """Drop-in replacement for OpenAI Code Interpreter backed by Fireagent."""

    def __init__(
        self,
        image: str = "ubuntu:24.04",
        vcpus: int = 2,
        memory_mib: int = 1024,
        disk_mib: int = 2048,
        session_ttl: int = 3600,
    ):
        self.image = image
        self.vcpus = vcpus
        self.memory_mib = memory_mib
        self.disk_mib = disk_mib
        self.session_ttl = session_ttl
        self._sandbox = None

    def start_session(self):
        """Create a new sandbox for a Codex agent session."""
        self._sandbox = fa.create(
            image=self.image,
            vcpus=self.vcpus,
            memory_mib=self.memory_mib,
            disk_mib=self.disk_mib,
            ttl_seconds=self.session_ttl,
            idle_timeout_seconds=120,
            labels={"agent": "openai-codex"},
        )
        self._sandbox.wait_for("ready", timeout_seconds=60)
        self._sandbox.exec(
            "apt-get update -qq && apt-get install -y -qq "
            "python3 python3-pip nodejs git curl jq 2>/dev/null"
        )
        return self._sandbox.id

    def exec(self, code: str, language: str = "python") -> dict:
        """Execute code inside the sandbox."""
        if self._sandbox is None:
            raise RuntimeError("No session. Call start_session() first.")

        runners = {
            "python": "python3",
            "python3": "python3",
            "bash": "bash",
            "shell": "bash",
            "node": "node",
            "javascript": "node",
        }
        runner = runners.get(language, "python3")

        result = self._sandbox.exec(
            f"{runner} -c 'import sys; exec(sys.stdin.read())'",
            stdin=code,
            execution_timeout_seconds=30,
        )
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.exit_code,
        }

    def install_packages(
        self, packages: list[str], language: str = "python"
    ) -> dict:
        """Install packages into the sandbox."""
        if language in ("python", "python3"):
            cmd = f"pip install {' '.join(packages)} 2>&1"
        elif language in ("node", "javascript"):
            cmd = f"npm install {' '.join(packages)} 2>&1"
        else:
            cmd = f"apt-get install -y -qq {' '.join(packages)} 2>&1"
        result = self._sandbox.exec(cmd, execution_timeout_seconds=120)
        return {
            "exit_code": result.exit_code,
            "output": result.stdout + result.stderr,
        }

    def upload_file(self, local_path: str, remote_path: str) -> str:
        """Upload a file into the sandbox."""
        with open(local_path) as f:
            content = f.read()
        result = self._sandbox.exec(
            f"mkdir -p $(dirname {remote_path}) && cat > {remote_path}",
            stdin=content,
        )
        if result.exit_code != 0:
            raise RuntimeError(f"Upload failed: {result.stderr}")
        return remote_path

    def download_file(self, remote_path: str) -> str:
        """Read a file from the sandbox."""
        result = self._sandbox.exec(f"cat {remote_path}")
        if result.exit_code != 0:
            raise FileNotFoundError(
                f"Cannot read {remote_path}: {result.stderr}"
            )
        return result.stdout

    def end_session(self):
        """Stop and clean up the sandbox."""
        if self._sandbox is None:
            return
        try:
            self._sandbox.stop()
            self._sandbox.delete()
        except Exception:
            pass
        self._sandbox = None
```

### Method 2: Codex Agent Loop with Fireagent Interpreter

```python
def codex_agent_example():
    """Run a Codex agent loop with Fireagent-backed execution."""
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    interpreter = FireagentCodeInterpreter(
        image="ubuntu:24.04",
        vcpus=2,
        memory_mib=1024,
        disk_mib=2048,
        session_ttl=1800,
    )

    session_id = interpreter.start_session()
    print(f"Session started: {session_id}")

    interpreter.install_packages(["numpy", "matplotlib", "pandas"])

    conversation = [
        {"role": "system", "content": (
            "You are a data analysis assistant. When you need to run Python, "
            "output ```python ... ``` blocks."
        )},
        {"role": "user", "content": "Analyze this CSV data and compute stats."},
    ]

    for turn in range(5):
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=conversation,
        )
        assistant_msg = response.choices[0].message.content
        print(f"\n--- Turn {turn + 1} ---")
        print(assistant_msg)

        if "```python" in assistant_msg:
            code_block = (
                assistant_msg.split("```python")[1].split("```")[0].strip()
            )
            result = interpreter.exec(code_block, language="python")
            feedback = (
                f"Exit {result['exit_code']}:\n"
                f"stdout: {result['stdout']}\n"
                f"stderr: {result['stderr']}"
            )
            conversation.append(
                {"role": "assistant", "content": assistant_msg}
            )
            conversation.append(
                {"role": "user", "content": f"Result:\n{feedback}"}
            )
        else:
            print("\nAgent finished.")
            break

    interpreter.end_session()
```

### Method 3: Sandbox Per Task (RL Rollout Pattern)

For RL training loops where Codex generates policy code for many rollouts:

```python
"""RL Rollout: one Codex-generated policy, many sandbox evaluations."""

import fireagent as fa
from fireagent_host.operator import Operator


class CodexRLRollout:
    """Co-design Codex-generated policies with Fireagent rollouts."""

    def __init__(self, worker_hosts: list[str] | None = None):
        self.operator = Operator()
        self.worker_hosts = worker_hosts or []

    def register_workers(self, hosts: list[str]):
        for h in hosts:
            self.operator.add_host(h, deploy_key=True)
            self.operator.host_health(h)
            print(f"OK {h} connected")
        self.worker_hosts = hosts

    def evaluate_policy(
        self, policy_code: str, n_episodes: int = 10
    ) -> dict:
        """Evaluate a policy across N sandbox episodes."""
        results = []
        for ep in range(n_episodes):
            host = (
                self.worker_hosts[ep % len(self.worker_hosts)]
                if self.worker_hosts
                else None
            )

            if host:
                sb_id = f"rollout-{ep}"
                self.operator.create_sandbox(
                    host, sb_id, "ubuntu:24.04", 2, 1024, 2048
                )
                self.operator.exec_command(
                    host,
                    sb_id,
                    "cat > /workspace/policy.py && python3 /workspace/policy.py",
                    stdin=policy_code,
                )
                self.operator.stop_sandbox(host, sb_id)
            else:
                sb = fa.create(
                    image="ubuntu:24.04",
                    vcpus=2,
                    memory_mib=1024,
                    disk_mib=2048,
                    ttl_seconds=300,
                    labels={"episode": str(ep)},
                )
                sb.wait_for("ready")
                result = sb.exec(
                    "python3 -c 'import sys; exec(sys.stdin.read())'",
                    stdin=policy_code,
                    execution_timeout_seconds=60,
                )
                results.append({
                    "episode": ep,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "exit_code": result.exit_code,
                })
                sb.stop()
                sb.delete()

        return {"n_episodes": n_episodes, "results": results}
```

### Method 4: Codex Function Calling + Fireagent Tools

Wire Codex function calling to Fireagent sandbox operations:

```python
"""Codex function calling with Fireagent tool implementations."""

import json
import fireagent as fa
from openai import OpenAI


FIREAGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "sandbox_create",
            "description": "Create an isolated Linux sandbox",
            "parameters": {
                "type": "object",
                "properties": {
                    "vcpus": {"type": "integer", "default": 2},
                    "memory_mib": {"type": "integer", "default": 1024},
                    "disk_mib": {"type": "integer", "default": 2048},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sandbox_exec",
            "description": "Execute a command in a sandbox",
            "parameters": {
                "type": "object",
                "properties": {
                    "sandbox_id": {"type": "string"},
                    "command": {"type": "string"},
                    "timeout": {"type": "integer", "default": 30},
                },
                "required": ["sandbox_id", "command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sandbox_stop",
            "description": "Stop and delete a sandbox",
            "parameters": {
                "type": "object",
                "properties": {
                    "sandbox_id": {"type": "string"},
                },
                "required": ["sandbox_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sandbox_install",
            "description": "Install Python packages in a sandbox",
            "parameters": {
                "type": "object",
                "properties": {
                    "sandbox_id": {"type": "string"},
                    "packages": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["sandbox_id", "packages"],
            },
        },
    },
]


_sandboxes: dict[str, fa.Sandbox] = {}


def handle_tool_call(tool_name: str, args: dict) -> str:
    """Dispatch a Codex function call to Fireagent."""
    if tool_name == "sandbox_create":
        sb = fa.create(
            image="ubuntu:24.04",
            vcpus=args.get("vcpus", 2),
            memory_mib=args.get("memory_mib", 1024),
            disk_mib=args.get("disk_mib", 2048),
            ttl_seconds=1800,
            labels={"agent": "codex"},
        )
        sb.wait_for("ready")
        _sandboxes[sb.id] = sb
        return json.dumps({"sandbox_id": sb.id, "status": "ready"})

    elif tool_name == "sandbox_exec":
        sb = _sandboxes.get(args["sandbox_id"])
        if not sb:
            return json.dumps({"error": "Sandbox not found"})
        try:
            result = sb.exec(
                args["command"],
                execution_timeout_seconds=args.get("timeout", 30),
            )
            return json.dumps({
                "exit_code": result.exit_code,
                "stdout": result.stdout,
                "stderr": result.stderr,
            })
        except fa.CommandTimeoutError:
            return json.dumps({"error": "Command timed out"})

    elif tool_name == "sandbox_stop":
        sb = _sandboxes.pop(args["sandbox_id"], None)
        if sb:
            sb.stop()
            sb.delete()
        return json.dumps({"status": "deleted"})

    elif tool_name == "sandbox_install":
        sb = _sandboxes.get(args["sandbox_id"])
        if not sb:
            return json.dumps({"error": "Sandbox not found"})
        result = sb.exec(
            f"pip install {' '.join(args['packages'])} 2>&1",
            execution_timeout_seconds=120,
        )
        return json.dumps({
            "exit_code": result.exit_code,
            "output": result.stdout + result.stderr,
        })

    return json.dumps({"error": f"Unknown tool: {tool_name}"})
```

---

## Comparison: OpenAI Code Interpreter vs. Fireagent

| Feature | OpenAI Code Interpreter | Fireagent Sandbox |
|---------|------------------------|-------------------|
| **Isolation** | Container (shared kernel) | MicroVM (separate kernel) |
| **Session persistence** | Session expires ~1h idle | Configurable TTL + idle timeout |
| **Resource limits** | Opaque | Explicit (CPU, RAM, disk) |
| **Network access** | Default deny (limited) | Configurable policies |
| **Image choice** | Python-only sandbox | Any Linux image |
| **Hosting** | OpenAI cloud | Self-hosted (your infrastructure) |
| **Cost** | Per-token execution cost | Fixed per-sandbox (your hardware) |
| **Parallelism** | 1 session at a time | Hundreds per host |
| **Data privacy** | Code goes to OpenAI | Code stays on your hardware |
| **RL co-design** | Not available | Built-in via Operator SDK |

---

## Lifecycle in Codex Workflows

```
+----------------------------------------------------+
| Codex + Fireagent Session Flow                     |
|                                                     |
| 1. Agent Start                                      |
|    - Create sandbox (vcpus=2, mem=1024, disk=2048) |
|    - Wait for "ready" state                         |
|    - Pre-install runtimes (python3, pip, node)      |
|                                                     |
| 2. Agent Loop (N turns)                             |
|    - Codex generates code/plan                      |
|    - Code -> sandbox.exec()                          |
|    - Observe stdout/stderr/exit_code                |
|    - Feed results back to Codex                     |
|                                                     |
| 3. Agent End                                        |
|    - Retrieve workspace files / logs                |
|    - Stop sandbox                                   |
|    - Delete sandbox (complete cleanup)              |
+----------------------------------------------------+
```

---

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `FIREAGENT_IMAGE` | `ubuntu:24.04` | Guest image for code execution |
| `FIREAGENT_VCPUS` | `2` | Virtual CPUs per sandbox |
| `FIREAGENT_MEMORY_MIB` | `1024` | Memory per sandbox |
| `FIREAGENT_DISK_MIB` | `2048` | Disk per sandbox |
| `FIREAGENT_SESSION_TTL` | `3600` | Max session duration (seconds) |
| `OPENAI_API_KEY` | - | OpenAI API key |

---

## RL Co-Design with Codex

Fireagent's Operator SDK is designed for exactly the pattern described in
**DeepSeek Elastic Compute (DSec)**
[[arXiv:2609.22978]](https://arxiv.org/abs/2609.22978):
**decoupling rollout execution from GPU training**.

In an RL training loop with Codex-generated policies:

```
GPU Node (Training)                       Worker Nodes (Rollout)
  |                                              |
  | 1. Codex generates policy pi_theta           |
  | 2. Operator pushes policy to workers         |
  | 3. Worker creates N sandboxes                |
  |    | Rollout 0: sandbox 0                    |
  |    |   exec(policy_code)                     |
  |    | Rollout 1: sandbox 1                    |
  |    |   exec(policy_code)                     |
  |    | ... N rollouts in parallel              |
  | 4. Worker aggregates rewards                 |
  | 5. Rewards -> GPU node for pi update         |
  | 6. Sandboxes cleaned up                      |
  +----------------------------------------------+
```

---

## Example: Safe Code Evaluator

```python
"""Evaluate code submissions in isolated sandboxes."""

import fireagent as fa


class SafeCodeEvaluator:
    """Evaluates code submissions, each in its own sandbox."""

    def __init__(self, timeout: int = 30, memory_mib: int = 512, disk_mib: int = 1024):
        self.timeout = timeout
        self.memory_mib = memory_mib
        self.disk_mib = disk_mib

    def evaluate(
        self,
        code: str,
        language: str = "python",
        test_cases: list[dict] | None = None,
    ) -> dict:
        """Evaluate a code submission inside a disposable sandbox.

        Args:
            code: Source code to evaluate.
            language: 'python' or 'bash'.
            test_cases: Optional list of {"input": ..., "expected": ...}.

        Returns:
            dict with pass/fail, stdout, stderr, and test results.
        """
        sb = fa.create(
            image="ubuntu:24.04",
            vcpus=1,
            memory_mib=self.memory_mib,
            disk_mib=self.disk_mib,
            ttl_seconds=120,
            labels={"task": "code-eval"},
        )
        sb.wait_for("ready")

        try:
            # Write code to sandbox
            sb.exec("mkdir -p /workspace && cat > /workspace/submission.py", stdin=code)

            if test_cases:
                results = []
                for tc in test_cases:
                    result = sb.exec(
                        f"cd /workspace && echo '{tc['input']}' | python3 submission.py",
                        execution_timeout_seconds=self.timeout,
                    )
                    passed = tc.get("expected", "") in result.stdout
                    results.append({
                        "input": tc["input"],
                        "expected": tc.get("expected"),
                        "actual": result.stdout.strip(),
                        "passed": passed,
                        "stderr": result.stderr,
                    })
            else:
                result = sb.exec(
                    f"python3 /workspace/submission.py",
                    execution_timeout_seconds=self.timeout,
                )
                results = [{"stdout": result.stdout, "stderr": result.stderr}]

            all_passed = all(r.get("passed", True) for r in results)
            return {"passed": all_passed, "results": results}

        finally:
            sb.stop()
            sb.delete()


# Usage
evaluator = SafeCodeEvaluator(timeout=10)
output = evaluator.evaluate(
    code="print('hello world')",
    test_cases=[{"input": "", "expected": "hello world"}],
)
print(output)
```

---

## See Also

- [Claude Code Integration](claude-code.md) — Same isolation for Claude Code
- [Generic Agent Pattern](generic-agent.md) — General pattern for any coding agent
- [SDK Quickstart](../sdk/quickstart.md) — Fireagent Python SDK basics
- [RL Rollout Example](../../examples/rl_rollout.py) — Production RL co-design example
- [Architecture Overview](../architecture/overview.md) — System design
- [Security: Isolation Guarantees](../security/isolation.md) — What Fireagent protects
