"""Integration tests for the Fireagent API."""

import pytest
from httpx import ASGITransport, AsyncClient

from fireagent_api.app import app


@pytest.fixture
async def client() -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestHealth:
    async def test_health(self, client: AsyncClient) -> None:
        resp = await client.get("/v1/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestCreateSandbox:
    async def test_create_sandbox(self, client: AsyncClient) -> None:
        payload = {
            "image": "ubuntu:24.04",
            "vcpus": 1,
            "memory_mib": 512,
            "disk_mib": 1024,
            "ttl_seconds": 3600,
            "labels": {"env": "test"},
        }
        resp = await client.post("/v1/sandboxes", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["id"].startswith("sb-")
        assert data["state"] == "ready"
        assert data["vcpus"] == 1

    async def test_create_sandbox_invalid(self, client: AsyncClient) -> None:
        payload = {"image": "ubuntu", "vcpus": 0, "memory_mib": 0, "disk_mib": 0}
        resp = await client.post("/v1/sandboxes", json=payload)
        assert resp.status_code == 422  # Validation error


class TestExecCommand:
    async def setup_sandbox(self, client: AsyncClient) -> str:
        payload = {
            "image": "ubuntu:24.04",
            "vcpus": 1,
            "memory_mib": 512,
            "disk_mib": 1024,
        }
        resp = await client.post("/v1/sandboxes", json=payload)
        return resp.json()["id"]

    async def test_exec_command(self, client: AsyncClient) -> None:
        sandbox_id = await self.setup_sandbox(client)
        resp = await client.post(
            f"/v1/sandboxes/{sandbox_id}/exec",
            json={"command": "echo 'hello world'"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["exit_code"] == 0
        assert "hello world" in data["stdout"]

    async def test_exec_on_nonexistent(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/v1/sandboxes/sb-nonexistent/exec",
            json={"command": "echo test"},
        )
        assert resp.status_code == 404


class TestLifecycle:
    async def setup_sandbox(self, client: AsyncClient) -> str:
        payload = {
            "image": "ubuntu:24.04",
            "vcpus": 1,
            "memory_mib": 512,
            "disk_mib": 1024,
        }
        resp = await client.post("/v1/sandboxes", json=payload)
        return resp.json()["id"]

    async def test_get_sandbox(self, client: AsyncClient) -> None:
        sandbox_id = await self.setup_sandbox(client)
        resp = await client.get(f"/v1/sandboxes/{sandbox_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == sandbox_id

    async def test_get_nonexistent(self, client: AsyncClient) -> None:
        resp = await client.get("/v1/sandboxes/sb-nonexistent")
        assert resp.status_code == 404

    async def test_list_sandboxes(self, client: AsyncClient) -> None:
        await self.setup_sandbox(client)
        await self.setup_sandbox(client)
        resp = await client.get("/v1/sandboxes")
        assert resp.status_code == 200
        assert len(resp.json()["sandboxes"]) >= 2

    async def test_stop_sandbox(self, client: AsyncClient) -> None:
        sandbox_id = await self.setup_sandbox(client)
        resp = await client.post(f"/v1/sandboxes/{sandbox_id}/stop")
        assert resp.status_code == 202

        # Verify state after stop
        resp = await client.get(f"/v1/sandboxes/{sandbox_id}")
        assert resp.json()["state"] == "stopped"

    async def test_delete_sandbox(self, client: AsyncClient) -> None:
        sandbox_id = await self.setup_sandbox(client)
        resp = await client.delete(f"/v1/sandboxes/{sandbox_id}")
        assert resp.status_code == 204

        # Verify it's gone
        resp = await client.get(f"/v1/sandboxes/{sandbox_id}")
        assert resp.status_code == 404


class TestFullLifecycle:
    async def test_full_lifecycle(self, client: AsyncClient) -> None:
        # Create
        payload = {
            "image": "ubuntu:24.04",
            "vcpus": 1,
            "memory_mib": 256,
            "disk_mib": 512,
            "ttl_seconds": 300,
        }
        resp = await client.post("/v1/sandboxes", json=payload)
        assert resp.status_code == 201
        sandbox_id = resp.json()["id"]

        # Exec
        resp = await client.post(
            f"/v1/sandboxes/{sandbox_id}/exec",
            json={"command": "echo 'lifecycle test'"},
        )
        assert resp.status_code == 200
        assert resp.json()["stdout"].strip() == "lifecycle test"

        # Get status
        resp = await client.get(f"/v1/sandboxes/{sandbox_id}")
        assert resp.status_code == 200
        assert resp.json()["state"] == "ready"

        # Stop
        resp = await client.post(f"/v1/sandboxes/{sandbox_id}/stop")
        assert resp.status_code == 202

        # Verify stopped
        resp = await client.get(f"/v1/sandboxes/{sandbox_id}")
        assert resp.status_code == 200
        assert resp.json()["state"] == "stopped"

        # Delete
        resp = await client.delete(f"/v1/sandboxes/{sandbox_id}")
        assert resp.status_code == 204
