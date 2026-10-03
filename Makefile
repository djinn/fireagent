# Fireagent Makefile
# ===========================================================================
.POSIX:

PROJECT   := fireagent
VENV      := .venv
PYTHON    := python3
PIP       := $(PYTHON) -m pip
MKCMD     := $(PYTHON) -m mkdocs

# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------
.DEFAULT_GOAL := help

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
venv: ## Create Python virtual environment
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install --upgrade pip setuptools wheel

install: ## Install package in development mode
	$(PIP) install -e ".[dev,agent,test]"

install-docs: ## Install documentation dependencies
	$(PIP) install mkdocs mkdocs-material mkdocs-mermaid2-plugin \
		mkdocs-glightbox pymdown-extensions

# ---------------------------------------------------------------------------
# Lint & format
# ---------------------------------------------------------------------------
format: ## Auto-format code (black + isort)
	black src/ tests/ examples/
	isort --profile black src/ tests/ examples/

lint: ## Lint code (ruff + mypy)
	ruff check src/ tests/ examples/
	mypy src/ --ignore-missing-imports || true

check: ## Check formatting without changes
	black --check --diff src/ tests/ examples/
	isort --check --diff --profile black src/ tests/ examples/
	ruff check src/ tests/ examples/

# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------
test: ## Run all tests
	pytest tests/ -v --tb=short --cov=fireagent --cov=fireagent_api \
		--cov=fireagent_agent --cov=fireagent_guest --cov-report=term-missing

test-unit: ## Run unit tests only
	pytest tests/unit/ -v --tb=short --numprocesses auto

test-integration: ## Run integration tests
	pytest tests/integration/ -v --tb=short

test-e2e: ## Run end-to-end tests
	pytest tests/e2e/ -v --tb=short

test-property: ## Run property-based tests (hypothesis)
	pytest tests/unit/test_property.py -v --tb=short --hypothesis-show-statistics

test-all: test-unit test-integration test-e2e test-property ## Run all test suites

# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------
security: ## Run security scans
	bandit -r src/ -x tests,examples -ll

# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------
build-sdist: ## Build source distribution
	python -m build --sdist

build-wheels: ## Build platform wheels (requires cibuildwheel)
	cibuildwheel --output-dir wheelhouse

build-all: build-sdist build-wheels ## Build everything

# ---------------------------------------------------------------------------
# Documentation
# ---------------------------------------------------------------------------
docs-serve: ## Serve docs locally
	$(MKCMD) serve

docs-build: ## Build static docs
	$(MKCMD) build --strict

docs-deploy: ## Deploy docs to GitHub Pages
	$(MKCMD) gh-deploy --force

# ---------------------------------------------------------------------------
# Distribution
# ---------------------------------------------------------------------------
clean: ## Clean build artifacts
	rm -rf build/ dist/ *.egg-info/ __pycache__/ .pytest_cache/ .mypy_cache/ .ruff_cache/
	rm -rf site/ wheelhouse/
	rm -rf .coverage coverage.xml bandit-report.json
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

distclean: clean ## Deep clean (remove venv)
	rm -rf $(VENV)

# ---------------------------------------------------------------------------
# Release
# ---------------------------------------------------------------------------
release: test-all build-all ## Prepare a release (tag in git)
	@echo "Ready for release. Run: git tag v0.1.0 && git push --tags"

# ---------------------------------------------------------------------------
# CI simulation
# ---------------------------------------------------------------------------
ci: check test-all security docs-build ## Simulate CI pipeline locally