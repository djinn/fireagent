# Fireagent

<div class="hero" markdown>
# **Isolated microVM sandboxes for AI agents.**

**Fireagent** is an open-source platform that creates, manages, and destroys **Firecracker microVM sandboxes** through a clean API and Python SDK. Each sandbox is an isolated Linux environment — with persistent state, resource controls, and network policies — designed for agent harnesses, RL training rollouts, code evaluation, and anything that needs a *trustworthy, disposable computer*.

<div class="badge-row">
<span class="badge">⚡ Firecracker-powered</span>
<span class="badge">🔒 microVM isolation</span>
<span class="badge">📦 stateful sessions</span>
<span class="badge">🐍 Python SDK</span>
<span class="badge">📡 REST API first</span>
<span class="badge">🏗️ MIT licensed</span>
</div>

```bash
pip install fireagent
```
```python
import fireagent as fa

sb = fa.create(image="ubuntu:24.04", vcpus=2, memory_mib=1024)
result = sb.exec("python3 -c 'print(f\"Hello from {__import__(\"platform\").node()}\")'")
print(result.stdout)  # Hello from sb-a1b2c3
sb.stop()
```
</div>

## Why Fireagent?

Agent frameworks, RL training loops, and evaluation harnesses all share a common need: **a safe place to run untrusted code**. Traditional containers share a kernel and depend on a daemon's privilege boundary. Full VMs are heavy and slow to boot. Fireagent lives in the middle — microVMs that boot in milliseconds, provide real kernel isolation, and cost barely more than a process.

|                          | Containers | Full VMs | **Fireagent** |
|--------------------------|:----------:|:--------:|:-------------:|
| Isolation boundary       | Kernel     | Hardware | **Kernel + hardware** |
| Boot to ready            | ~50 ms     | ~5 s     | **~150 ms**   |
| Memory per sandbox       | ~5 MiB     | ~1 GiB   | **~75 MiB**†  |
| Attack surface           | Large      | Small    | **Minimal**   |

† Idle guest with minimal init; workload-dependent.

## What the spec says

> *"A sandbox is a stateful session, not a one-shot command."*
>
> *"Firecracker provides the guest isolation boundary. Host services must still assume guest code is hostile."*
>
> *"Make limits explicit. Every sandbox has defined CPU, memory, disk, network, and lifetime policy."*
>
> *"Separate control from execution."*

These design principles — full transparency — are documented across this site.

## When to use Fireagent

**✅ Agent backends** – give each agent interaction its own ephemeral Linux environment with persistent `$HOME`.

**✅ RL training rollouts** – launch hundreds of sandboxes, run a policy episode, collect rewards, tear down.

**✅ Code evaluation** – run student or model-generated code in isolation, check outputs, enforce timeouts.

**✅ CI/CD workspaces** – spin up per-job environments with guaranteed resource limits.

**✅ Security research** – test payloads, analyze malware, fuzz kernels — all inside disposable microVMs.

**❌ Not for:** GPU workloads (passthrough is out of scope), general-purpose container orchestration, or production databases.

## What's inside

<div class="grid cards" markdown>

-   :material-rocket-launch: **Sandbox lifecycle** – Create, exec, stop, delete. Every state is observable.
-   :material-code-braces: **Python SDK** – First-class SDK with async support, retries, and structured results.
-   :material-api: **RESTful API** – FastAPI-based control plane with OpenAPI docs at `/docs`.
-   :material-lan: **Network policies** – Deny-by-default, with explicit allow rules. No cross-sandbox chatter.
-   :material-cpu: **Resource controls** – CPU/memory via cgroups, disk quotas, lifetime & idle timeouts.
-   :material-console: **Host agent** – Lightweight daemon that manages Firecracker processes with minimal privileges.
-   :material-image: **Reproducible guest images** – Versioned, signed, minimal Linux images built from pinned packages.
-   :material-chart-line: **Observability** – Every lifecycle event logged. Metrics for creation, execution, resource use.

</div>

## Project status

<div class="grid cards" markdown>

-   :material-factory: **Phase 1** – Single-host prototype. One Linux host, one guest image, local state store. **Complete.**
-   :material-server: **Phase 2** – Multi-host service. FastAPI + PostgreSQL, host registration, scheduler. **In progress.**
-   :material-cloud: **Phase 3** – Elastic scale. Queue-backed bursts, autoscaling, snapshot recovery. **Planned.**

</div>

---

**Fireagent** is built by [Supreet Sethi](https://spaceswordai.com) at [Spacesword AI](https://spaceswordai.com). Licensed [MIT](https://github.com/spaceswordai/fireagent/blob/main/LICENSE).

*"The first hard problem is not 'how tiny can the Linux image be?' It is how reliably the platform creates, contains, observes, and cleans up thousands of stateful guests."* – Supreet Sethi