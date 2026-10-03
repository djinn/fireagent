"""Fireagent API — FastAPI control plane for sandbox lifecycle management."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .models import SandboxCreateRequest, SandboxExecRequest, SandboxResponse, ExecResponse
from .services import SandboxService

app = FastAPI(
    title="Fireagent API",
    description="Elastic agent sandbox platform powered by Firecracker microVMs",
    version="0.1.0",
    contact={"name": "Supreet Sethi", "url": "https://spaceswordai.com"},
    license_info={"name": "MIT", "url": "https://opensource.org/licenses/MIT"},
    docs_url="/docs",
    redoc_url="/redoc",
)

_sandbox_service: SandboxService | None = None


def _get_service() -> SandboxService:
    global _sandbox_service
    if _sandbox_service is None:
        _sandbox_service = SandboxService()
    return _sandbox_service


# ---------------------------------------------------------------------------
# Exception handler
# ---------------------------------------------------------------------------
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.detail, "message": exc.detail}},
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "internal_error",
                "message": "An unexpected error occurred",
            }
        },
    )


# ---------------------------------------------------------------------------
# Middleware / helpers
# ---------------------------------------------------------------------------
def _extract_tenant_id(authorization: str | None = Header(None)) -> str:
    # Placeholder: extract tenant from API key
    return "ten-000001"


def _generate_id() -> str:
    return "sb-" + uuid.uuid4().hex[:8]


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.get("/v1/health")
async def health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


# ---------------------------------------------------------------------------
# Sandbox CRUD
# ---------------------------------------------------------------------------
@app.post("/v1/sandboxes", status_code=201)
async def create_sandbox(
    body: SandboxCreateRequest,
    authorization: str | None = Header(None),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    tenant_id = _extract_tenant_id(authorization)
    sandbox_id = _generate_id()
    svc = _get_service()

    result = svc.create(
        sandbox_id=sandbox_id,
        tenant_id=tenant_id,
        image=body.image,
        vcpus=body.vcpus,
        memory_mib=body.memory_mib,
        disk_mib=body.disk_mib,
        workspace=body.workspace,
        ttl_seconds=body.ttl_seconds,
        idle_timeout_seconds=body.idle_timeout_seconds,
        network_policy=body.network_policy,
        labels=body.labels,
    )
    return result


@app.get("/v1/sandboxes/{sandbox_id}")
async def get_sandbox(sandbox_id: str):
    svc = _get_service()
    result = svc.get(sandbox_id)
    if result is None:
        raise HTTPException(status_code=404, detail="sandbox_not_found")
    return result


@app.get("/v1/sandboxes")
async def list_sandboxes():
    svc = _get_service()
    return {"sandboxes": svc.list()}


@app.post("/v1/sandboxes/{sandbox_id}/exec")
async def exec_command(
    sandbox_id: str,
    body: SandboxExecRequest,
):
    svc = _get_service()
    result = svc.exec(
        sandbox_id,
        command=body.command,
        working_dir=body.working_dir,
        environment=body.environment,
        execution_timeout_seconds=body.execution_timeout_seconds,
        stdin=body.stdin,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="sandbox_not_found")
    return result


@app.post("/v1/sandboxes/{sandbox_id}/stop")
async def stop_sandbox(sandbox_id: str):
    svc = _get_service()
    ok = svc.stop(sandbox_id)
    if not ok:
        raise HTTPException(status_code=404, detail="sandbox_not_found")
    return JSONResponse(status_code=202, content={"status": "stopping"})


@app.delete("/v1/sandboxes/{sandbox_id}", status_code=204)
async def delete_sandbox(sandbox_id: str):
    svc = _get_service()
    ok = svc.delete(sandbox_id)
    if not ok:
        raise HTTPException(status_code=404, detail="sandbox_not_found")
    return None


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run("fireagent_api.app:app", host="0.0.0.0", port=8000, reload=True)
