# Contributing

## Welcome

Fireagent is an open-source project built by Supreet Sethi and Spacesword AI. We welcome contributions from the community, whether it's fixing bugs, adding features, improving documentation, or building guest images.

## Code of conduct

We follow the [Contributor Covenant](https://www.contributor-covenant.org/) code of conduct. Be respectful, be inclusive, be constructive.

## How to contribute

### 1. Find something to work on

- **Issues labeled `good first issue`** – For newcomers
- **Issues labeled `help wanted`** – For experienced contributors
- **Documentation** – Always a need for better docs
- **Guest images** – Build and test new guest image configurations
- **Bug fixes** – Report and fix issues

### 2. Fork and branch

```bash
git clone https://github.com/djinn/fireagent.git
git checkout -b fix/description-of-fix
```

### 3. Make changes

- Follow the [code style](#code-style)
- Write tests
- Update documentation

### 4. Submit a pull request

```bash
git push origin fix/description-of-fix
```

Open a PR against `main` with:
- A clear title and description
- Reference to the issue (e.g., "Fixes #123")
- A changelog entry in `CHANGELOG.md`

### 5. Code review

- Maintainers will review your PR
- Expect questions and suggestions
- Iterate until approval

## Code style

### Python

- **Format**: `black` with default settings
- **Import sorting**: `isort` with `black` profile
- **Type checking**: `mypy` strict mode
- **Linting**: `ruff` with default settings
- **Docstrings**: Google style

### Shell

- **Shell**: `bash` with `set -euo pipefail`
- **Format**: `shfmt`
- **Lint**: `shellcheck`

### Commit messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
type(scope): description

[optional body]

[optional footer]
```

Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `ci`, `security`

Examples:

```
feat(api): add support for workspace upload

fix(agent): prevent orphan TAP interfaces on crash

docs(security): add threat model for metadata endpoints

security(isolation): block additional private IP ranges
```

## Pull request guidelines

- **One change per PR** – Keep focused
- **Small PRs** – Easier to review (< 400 lines preferred)
- **Tests included** – New code needs tests
- **Documentation updated** – If it's user-facing, document it
- **Changelog entry** – Add to `CHANGELOG.md`
- **No unrelated changes** – Don't fix formatting in a feature branch

## Testing requirements

- **Unit tests** – All new code needs unit tests
- **Integration tests** – Code that touches Firecracker or networking needs integration tests
- **E2E tests** – Full lifecycle tests for new features
- **Security tests** – Code that changes isolation boundaries needs security tests

## Documentation

- **Docstrings** – Google-style on all public functions and classes
- **API docs** – Update `docs/api/` when changing API endpoints
- **Architecture docs** – Update `docs/architecture/` when changing design
- **Security docs** – Update `docs/security/` when changing isolation boundaries
- **Examples** – Add example scripts for new features

## Getting help

- **Issues**: Open a GitHub issue for bugs, feature requests, and questions
- **Discussions**: Use GitHub Discussions for design discussions and RFCs
- **Security**: Email security@djinn.ai for security vulnerabilities

Thank you for contributing!