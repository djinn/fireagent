# Development

## Getting started

This section is for developers who want to contribute to Fireagent, build their own guest images, or extend the platform.

## Repository structure

```
fireagent/
├── docs/                     # Documentation (this site)
├── src/
│   ├── fireagent/            # Python SDK source
│   │   ├── __init__.py
│   │   ├── client.py
│   │   ├── models.py
│   │   ├── exceptions.py
│   │   └── utils/
│   ├── fireagent_api/        # FastAPI control plane
│   │   ├── app.py
│   │   ├── routes/
│   │   ├── models/
│   │   ├── services/
│   │   └── config/
│   ├── fireagent_agent/      # Host agent daemon
│   │   ├── agent.py
│   │   ├── firecracker.py
│   │   ├── network.py
│   │   ├── cgroups.py
│   │   └── health.py
│   └── fireagent_guest/      # Guest agent
│       ├── agent.sh
│       └── init.sh
├── images/                   # Guest image build scripts
│   ├── buildroot/
│   │   ├── config/
│   │   ├── patches/
│   │   └── build.sh
│   └── verify/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── e2e/
│   └── security/
├── examples/
│   ├── basic_test.py
│   ├── agent_workflow.py
│   └── rl_rollout.py
├── scripts/
│   ├── setup-host.sh
│   ├── cleanup.sh
│   └── benchmark.sh
├── mkdocs.yml
├── requirements.txt
└── README.md
```

## Development setup

### Prerequisites

- Python 3.10+
- PostgreSQL 16+
- Firecracker (for integration tests)
- KVM-capable machine (or nested virtualization)

### Clone and install

```bash
git clone https://github.com/djinn/fireagent.git
cd fireagent

python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Run tests

```bash
# Unit tests
pytest tests/unit/

# Integration tests (requires Firecracker)
pytest tests/integration/

# End-to-end tests (requires full setup)
pytest tests/e2e/

# Security tests
pytest tests/security/
```

### Build documentation locally

```bash
pip install -r requirements.txt
mkdocs serve
```

Open `http://localhost:8000` in your browser.

## Related topics

- [Contributing](contributing.md) – How to contribute, code style, PR process.
- [Reproducible Builds](reproducible-builds.md) – Building guest images with deterministic outputs.
- [Testing Strategy](testing.md) – Unit, integration, e2e, and security testing.