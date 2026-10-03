"""Fireagent HTTP client — wraps the REST API for sandbox lifecycle management."""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from datetime import datetime
from typing import Any

import httpx

from .exceptions import (
    CommandOomKilledError,
    CommandTimeoutError,
    FireagentError,
    NetworkDenialError,
    SandboxFailedError,
    SandboxTimeoutError,
    map_http_status,
)
from .models import CommandResult, SandboxStatus

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT = 30
DEFAULT_RETRIES = 3
DEFAULT_RETRY_DELAY = 0.5
API_KEY_ENV_VAR = "FIREAGENT_API_KEY"


# ---------------------------------------------------------------------------
# Sandbox handle
# ---------------------------------------------------------------------------
class Sandbox:
    """Represents a Fireagent sandbox and exposes lifecycle operations."""

    def __init__(self, client: "FireagentClient", sandbox_id: str) -> None:
        self._client = client
        self.id = sandbox_id

    # ---- sync operations ---------------------------------------------------

    def exec(
        self,
        command: str,
        *,
        working_dir: str | None = None,
        environment: dict[str, str] | None = None,
        execution_timeout_seconds: int | None = None,
        stdin: str | None = None,
    ) -> CommandResult:
        """Execute a command inside this sandbox."""
        return self._client._exec(
            self.id,
            command=command,
            working_dir=working_dir,
            environment=environment,
            execution_timeout_seconds=execution_timeout_seconds,
            stdin=stdin,
        )

    def status(self) -> SandboxStatus:
        """Fetch the current sandbox state from the API."""
        return self._client._get_sandbox(self.id)

    def wait_for(self, state: str, *, timeout_seconds: int = 120) -> SandboxStatus:
        """Poll until the sandbox reaches *state* or *timeout_seconds* elapses."""
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            status = self.status()
            if status.state == state:
                return status
            if status.state in ("failed", "expired"):
                raise SandboxFailedError(
                    f"Sandbox {self.id} entered {status.state!r} "
                    f"(reason: {status.failure_reason})"
                )
            time.sleep(0.5)
        raise SandboxTimeoutError(
            f"Sandbox {self.id} did not reach {state!r} within {timeout_seconds}s"
        )

    def stop(self) -> None:
        """Gracefully stop the sandbox."""
        self._client._stop(self.id)

    def delete(self) -> None:
        """Delete the sandbox and its writable state."""
        self._client._delete(self.id)

    def is_ready(self) -> bool:
        return self.status().state == "ready"

    def is_running(self) -> bool:
        return self.status().state == "running"

    # ---- async operations --------------------------------------------------

    async def aexec(
        self,
        command: str,
        **kwargs,
    ) -> CommandResult:
        return await self._client._aexec(self.id, command=command, **kwargs)

    async def astop(self) -> None:
        await self._client._astop(self.id)

    async def adelete(self) -> None:
        await self._client._adelete(self.id)

    async def await_for(self, state: str, *, timeout_seconds: int = 120) -> SandboxStatus:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            status = self.status()
            if status.state == state:
                return status
            if status.state in ("failed", "expired"):
                raise SandboxFailedError(
                    f"Sandbox {self.id} entered {status.state!r} "
                    f"(reason: {status.failure_reason})"
                )
            await asyncio.sleep(0.5)
        raise SandboxTimeoutError(
            f"Sandbox {self.id} did not reach {state!r} within {timeout_seconds}s"
        )

    def __repr__(self) -> str:
        return f"<Sandbox {self.id}>"


# ---------------------------------------------------------------------------
# HTTP Client
# ---------------------------------------------------------------------------
class FireagentClient:
    """Low-level HTTP client that talks to the Fireagent control plane."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        retry_delay: float = DEFAULT_RETRY_DELAY,
    ) -> None:
        self._base_url = (base_url or os.environ.get("FIREAGENT_BASE_URL")) or DEFAULT_BASE_URL
        self._api_key = api_key or os.environ.get(API_KEY_ENV_VAR) or ""
        self._timeout = timeout
        self._retries = retries
        self._retry_delay = retry_delay
        self._http = httpx.Client(base_url=self._base_url, timeout=timeout)
        self._async_http = httpx.AsyncClient(base_url=self._base_url, timeout=timeout)

    # ---- configuration ----------------------------------------------------

    def set_api_key(self, key: str) -> None:
        self._api_key = key

    def set_base_url(self, url: str) -> None:
        self._base_url = url
        self._http = httpx.Client(base_url=url, timeout=self._timeout)
        self._async_http = httpx.AsyncClient(base_url=url, timeout=self._timeout)

    def set_timeout(self, timeout: int) -> None:
        self._timeout = timeout

    def set_retries(self, retries: int) -> None:
        self._retries = retries

    def set_retry_delay(self, delay: float) -> None:
        self._retry_delay = delay

    # ---- request helpers --------------------------------------------------

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(self._retries + 1):
            try:
                resp = self._http.request(
                    method,
                    path,
                    headers=self._headers(),
                    **kwargs,
                )
                if resp.is_success or resp.status_code >= 400 and resp.status_code < 500:
                    # Non-retryable: success or client error
                    pass
                else:
                    last_exc = FireagentError(f"HTTP {resp.status_code} on {method} {path}")
                    if attempt < self._retries:
                        time.sleep(self._retry_delay * (2**attempt))
                        continue
            except httpx.TimeoutException as exc:
                last_exc = exc
                if attempt < self._retries:
                    time.sleep(self._retry_delay * (2**attempt))
                    continue
                raise FireagentError(f"Request timed out: {method} {path}") from exc
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt < self._retries:
                    time.sleep(self._retry_delay * (2**attempt))
                    continue
                raise FireagentError(f"HTTP error: {exc}") from exc
            else:
                if not resp.is_success:
                    exc_cls = map_http_status(resp.status_code)
                    try:
                        body = resp.json()
                        msg = body.get("error", {}).get("message", resp.text)
                    except (json.JSONDecodeError, AttributeError):
                        msg = resp.text
                    raise exc_cls(msg)
                return resp
        raise FireagentError(f"Request failed after {self._retries} retries") from last_exc

    async def _arequest(self, method: str, path: str, **kwargs) -> httpx.Response:
        for attempt in range(self._retries + 1):
            try:
                resp = await self._async_http.request(
                    method,
                    path,
                    headers=self._headers(),
                    **kwargs,
                )
                if resp.is_success or (400 <= resp.status_code < 500):
                    pass
                else:
                    if attempt < self._retries:
                        await asyncio.sleep(self._retry_delay * (2**attempt))
                        continue
            except httpx.TimeoutException as exc:
                if attempt < self._retries:
                    await asyncio.sleep(self._retry_delay * (2**attempt))
                    continue
                raise FireagentError(f"Async request timed out: {method} {path}") from exc
            except httpx.HTTPError as exc:
                if attempt < self._retries:
                    await asyncio.sleep(self._retry_delay * (2**attempt))
                    continue
                raise FireagentError(f"Async HTTP error: {exc}") from exc
            else:
                if not resp.is_success:
                    exc_cls = map_http_status(resp.status_code)
                    try:
                        body = resp.json()
                        msg = body.get("error", {}).get("message", resp.text)
                    except (json.JSONDecodeError, AttributeError):
                        msg = resp.text
                    raise exc_cls(msg)
                return resp
        raise FireagentError(f"Async request failed after {self._retries} retries")

    # ---- sandbox operations -----------------------------------------------

    def create(
        self,
        image: str,
        vcpus: int,
        memory_mib: int,
        disk_mib: int,
        *,
        workspace: dict | None = None,
        ttl_seconds: int | None = None,
        idle_timeout_seconds: int | None = None,
        network_policy: dict | None = None,
        labels: dict | None = None,
        idempotency_key: str | None = None,
    ) -> Sandbox:
        body: dict[str, Any] = {
            "image": image,
            "vcpus": vcpus,
            "memory_mib": memory_mib,
            "disk_mib": disk_mib,
        }
        if workspace is not None:
            body["workspace"] = workspace
        if ttl_seconds is not None:
            body["ttl_seconds"] = ttl_seconds
        if idle_timeout_seconds is not None:
            body["idle_timeout_seconds"] = idle_timeout_seconds
        if network_policy is not None:
            body["network_policy"] = network_policy
        if labels is not None:
            body["labels"] = labels

        headers = self._headers()
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        resp = self._request("POST", "/v1/sandboxes", json=body, headers=headers)
        data = resp.json()
        sandbox_id = data.get("id", "")
        return Sandbox(self, sandbox_id)

    def get(self, sandbox_id: str) -> Sandbox:
        return Sandbox(self, sandbox_id)

    def list(self) -> list[Sandbox]:
        resp = self._request("GET", "/v1/sandboxes")
        data = resp.json()
        return [Sandbox(self, item["id"]) for item in data.get("sandboxes", [])]

    def _get_sandbox(self, sandbox_id: str) -> SandboxStatus:
        resp = self._request("GET", f"/v1/sandboxes/{sandbox_id}")
        return SandboxStatus.from_dict(resp.json())

    def _exec(
        self,
        sandbox_id: str,
        command: str,
        *,
        working_dir: str | None = None,
        environment: dict[str, str] | None = None,
        execution_timeout_seconds: int | None = None,
        stdin: str | None = None,
    ) -> CommandResult:
        body: dict[str, Any] = {"command": command}
        if working_dir is not None:
            body["working_dir"] = working_dir
        if environment is not None:
            body["environment"] = environment
        if execution_timeout_seconds is not None:
            body["execution_timeout_seconds"] = execution_timeout_seconds
        if stdin is not None:
            body["stdin"] = stdin

        resp = self._request("POST", f"/v1/sandboxes/{sandbox_id}/exec", json=body)
        data = resp.json()
        result = CommandResult.from_dict(data)

        if result.timed_out:
            raise CommandTimeoutError(
                f"Command {command!r} timed out after {execution_timeout_seconds or 'default'}s"
            )
        if result.oom_killed:
            raise CommandOomKilledError(f"Command {command!r} was killed by OOM")
        if "network_denial" in data:
            raise NetworkDenialError(data.get("network_denial", "Network policy violated"))

        return result

    def _stop(self, sandbox_id: str) -> None:
        self._request("POST", f"/v1/sandboxes/{sandbox_id}/stop")

    def _delete(self, sandbox_id: str) -> None:
        self._request("DELETE", f"/v1/sandboxes/{sandbox_id}")

    # ---- async operations -------------------------------------------------

    async def acreate(
        self, image: str, vcpus: int, memory_mib: int, disk_mib: int, **kwargs
    ) -> Sandbox:
        body: dict[str, Any] = {
            "image": image,
            "vcpus": vcpus,
            "memory_mib": memory_mib,
            "disk_mib": disk_mib,
        }
        body.update(kwargs)
        resp = await self._arequest("POST", "/v1/sandboxes", json=body)
        data = resp.json()
        return Sandbox(self, data.get("id", ""))

    async def _aexec(self, sandbox_id: str, command: str, **kwargs) -> CommandResult:
        body: dict[str, Any] = {"command": command}
        body.update(kwargs)
        resp = await self._arequest("POST", f"/v1/sandboxes/{sandbox_id}/exec", json=body)
        return CommandResult.from_dict(resp.json())

    async def _astop(self, sandbox_id: str) -> None:
        await self._arequest("POST", f"/v1/sandboxes/{sandbox_id}/stop")

    async def _adelete(self, sandbox_id: str) -> None:
        await self._arequest("DELETE", f"/v1/sandboxes/{sandbox_id}")
