"""Nox sessions — run tests across multiple Python versions.

Usage:
    nox                          # Run all sessions
    nox -s test-3.10             # Run a specific session
    nox --session lint           # Run only lint sessions
"""

from __future__ import annotations

import nox

nox.options.sessions = ["lint", "test"]
nox.options.reuse_existing_virtualenvs = True

PYTHON_VERSIONS = ["3.10", "3.11", "3.12"]


@nox.session
def lint(session: nox.Session) -> None:
    """Lint and format check."""
    session.install("black", "isort", "ruff", "mypy")
    session.run("black", "--check", "--diff", "src/", "tests/", "examples/")
    session.run("isort", "--check", "--diff", "--profile", "black", "src/", "tests/", "examples/")
    session.run("ruff", "check", "src/", "tests/", "examples/")
    session.run("mypy", "src/", "--ignore-missing-imports", silent=True)


@nox.session
def security(session: nox.Session) -> None:
    """Security scan."""
    session.install("bandit", "safety")
    session.run("bandit", "-r", "src/", "-x", "tests,examples", "-ll")


@nox.session
def docs(session: nox.Session) -> None:
    """Build documentation."""
    session.install(
        "mkdocs", "mkdocs-material", "mkdocs-mermaid2-plugin",
        "mkdocs-glightbox", "pymdown-extensions",
    )
    session.run("mkdocs", "build", "--strict")


def _test_session(session: nox.Session, python: str = "3.10", extras: str = "dev,test") -> None:
    """Shared test session logic."""
    session.run(
        "python", "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel",
        silent=True,
    )
    session.install("-e", f".[{extras}]")
    session.run(
        "pytest", "tests/", "-v", "--tb=short",
        "--cov=fireagent", "--cov=fireagent_api",
        "--cov=fireagent_agent", "--cov=fireagent_guest",
        "--cov-report=term-missing",
    )


@nox.session(python=PYTHON_VERSIONS)
def test(session: nox.Session) -> None:
    """Run tests on Python {python}."""
    _test_session(session, python=session.python)


@nox.session
def coverage(session: nox.Session) -> None:
    """Run tests with coverage report."""
    session.install("-e", ".[dev,test]")
    session.run(
        "pytest", "tests/",
        "--cov=fireagent", "--cov=fireagent_api",
        "--cov=fireagent_agent", "--cov=fireagent_guest",
        "--cov-report=html", "--cov-report=term-missing",
    )
    session.run("python", "-c", "import webbrowser; webbrowser.open('htmlcov/index.html')")