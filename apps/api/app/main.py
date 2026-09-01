from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse

from packages.ctf_domain.errors import DomainError
from packages.ctf_domain.object_store import object_store
from packages.ctf_domain.repository import SQLAlchemySnapshotRepository, repository
from packages.ctf_domain.runtime_safety import (
    assert_production_runtime_safety,
    production_runtime_flags,
)

from .capabilities import load_manifest
from .capabilities import router as capabilities_router
from .common import router as common_router
from .horizontal import router as horizontal_router
from .security import quota_retry_after, security_middleware
from .slices import router as slices_router


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    assert_production_runtime_safety()
    application.state.capability_manifest = load_manifest()
    yield


app = FastAPI(
    title="CTF Full V1 API",
    version="0.1.0",
    description=(
        "Runnable modular monolith for CTF VS01-VS05, "
        "Creation Memory, model routing/cost telemetry and ERI/KHAL."
    ),
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Session-Token", "X-Request-ID", "Idempotency-Key"],
    expose_headers=["X-Request-ID", "Idempotency-Replayed", "Retry-After"],
)
app.include_router(common_router)
app.include_router(slices_router)
app.include_router(horizontal_router)
app.include_router(capabilities_router)


def security_openapi() -> dict:
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    exemptions = {"/api/v1/sessions/anonymous", "/api/v1/ai/routes/resolve"}
    for path, path_item in schema.get("paths", {}).items():
        if path in exemptions:
            continue
        for method in ("post", "put", "patch", "delete"):
            operation = path_item.get(method)
            if not operation:
                continue
            parameters = operation.setdefault("parameters", [])
            existing = next(
                (
                    parameter
                    for parameter in parameters
                    if parameter.get("in") == "header"
                    and parameter.get("name", "").lower() == "idempotency-key"
                ),
                None,
            )
            if existing:
                existing["required"] = True
                existing["schema"] = {"type": "string", "minLength": 1, "maxLength": 200}
            else:
                parameters.append(
                    {
                        "name": "Idempotency-Key",
                        "in": "header",
                        "required": True,
                        "schema": {"type": "string", "minLength": 1, "maxLength": 200},
                        "description": "Scoped to session, HTTP method and concrete path.",
                    }
                )
            operation.setdefault("responses", {}).setdefault(
                "429",
                {
                    "description": "Rate or AI quota exhausted; Retry-After is supplied.",
                },
            )
            operation["responses"].setdefault(
                "413", {"description": "Configured request or upload bound exceeded."}
            )
    app.openapi_schema = schema
    return schema


app.openapi = security_openapi


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", f"req_{uuid4().hex}")
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@app.middleware("http")
async def backend_security_middleware(request: Request, call_next):
    return await security_middleware(request, call_next, repository)


@app.exception_handler(DomainError)
async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    headers = (
        {"Retry-After": str(quota_retry_after())}
        if exc.status_code == 429
        else None
    )
    return JSONResponse(
        status_code=exc.status_code,
        headers=headers,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "request_id": request.state.request_id,
            }
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    first = exc.errors()[0] if exc.errors() else {}
    location = ".".join(str(part) for part in first.get("loc", []) if part != "body")
    detail = str(first.get("msg", "Request validation failed."))
    message = f"{location}: {detail}" if location else detail
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "INVALID_INPUT",
                "message": message,
                "details": exc.errors(),
                "request_id": request.state.request_id,
            }
        },
    )


@app.get("/health")
def health() -> dict[str, str]:
    persistence = (
        "sqlalchemy-snapshot"
        if isinstance(repository, SQLAlchemySnapshotRepository)
        else "in-memory"
    )
    return {
        "status": "ok",
        "persistence": persistence,
        "object_store": object_store.backend,
        "methodology": "CTF_FULL_V1",
    }


@app.get("/ready")
def ready() -> dict[str, object]:
    persistence = (
        "sqlalchemy-snapshot"
        if isinstance(repository, SQLAlchemySnapshotRepository)
        else "in-memory"
    )
    persistence_ok = True
    try:
        if isinstance(repository, SQLAlchemySnapshotRepository):
            repository.persist()
    except Exception:  # noqa: BLE001 - readiness must stay a safe operator probe
        persistence_ok = False
    object_ok = True
    try:
        _ = object_store.backend
    except Exception:  # noqa: BLE001
        object_ok = False
    flags = production_runtime_flags()
    registry_ok = True
    registry_error = None
    if flags["is_production"] or flags["enforce_model_registry"]:
        from packages.ctf_domain.model_registry import ModelRegistry

        registry = ModelRegistry()
        registry_ok = registry.is_available()
        if not registry_ok:
            registry_error = registry.load_error or "missing"
    ready_now = persistence_ok and object_ok and registry_ok
    return {
        "ready": ready_now,
        "status": "ready" if ready_now else "degraded",
        "checks": {
            "persistence": {"ok": persistence_ok, "mode": persistence},
            "object_store": {"ok": object_ok, "backend": object_store.backend},
            "model_registry": {"ok": registry_ok, "required": bool(flags["enforce_model_registry"]), "error": registry_error},
        },
        "degradable": {
            "ai": "AI unavailability does not block core workflow.",
            "khal": "KHAL unavailability does not block core workflow.",
        },
    }
