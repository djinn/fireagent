"""Host Registry — persists known hosts to disk and tracks their state.

Storage: JSON file at ~/.fireagent/hosts.json
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from .secure_host import SecureHost

logger = logging.getLogger("fireagent.remote.registry")

DEFAULT_REGISTRY_PATH = Path.home() / ".fireagent" / "hosts.json"


class HostRegistry:
    """Persists and tracks known remote hosts.

    Usage::

        registry = HostRegistry()
        registry.add(host)
        registry.remove("user@host:22")
        host = registry.get("user@host:22")
        for host in registry.list(): ...
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path else DEFAULT_REGISTRY_PATH
        self._hosts: dict[str, SecureHost] = {}
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def _load(self) -> None:
        """Load hosts from disk."""
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text())
                for item in data:
                    host = SecureHost.from_dict(item)
                    self._hosts[host.id] = host
                logger.info("Loaded %d hosts from %s", len(self._hosts), self._path)
            except (json.JSONDecodeError, KeyError) as exc:
                logger.warning("Failed to load hosts: %s (starting fresh)", exc)
                self._hosts = {}

    def _save(self) -> None:
        """Save hosts to disk."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = [h.to_dict() for h in self._hosts.values()]
        self._path.write_text(json.dumps(data, indent=2, default=str))
        logger.debug("Saved %d hosts to %s", len(self._hosts), self._path)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    def add(self, host: SecureHost) -> SecureHost:
        """Add or update a host in the registry."""
        self._hosts[host.id] = host
        self._save()
        logger.info("Added host %s (%s)", host.id, host.display_name)
        return host

    def remove(self, host_id: str) -> bool:
        """Remove a host from the registry by ID."""
        if host_id in self._hosts:
            del self._hosts[host_id]
            self._save()
            logger.info("Removed host %s", host_id)
            return True
        return False

    def get(self, host_id: str) -> SecureHost | None:
        """Get a host by ID."""
        return self._hosts.get(host_id)

    def list(self, status: str | None = None) -> list[SecureHost]:
        """List all hosts, optionally filtered by status."""
        hosts = list(self._hosts.values())
        if status:
            hosts = [h for h in hosts if h.status == status]
        return sorted(hosts, key=lambda h: h.hostname)

    def clear(self) -> None:
        """Remove all hosts."""
        self._hosts.clear()
        self._save()
        logger.info("Cleared all hosts from registry")

    @property
    def count(self) -> int:
        return len(self._hosts)

    def __contains__(self, host_id: str) -> bool:
        return host_id in self._hosts

    def __len__(self) -> int:
        return len(self._hosts)

    def __iter__(self):
        return iter(self._hosts.values())
