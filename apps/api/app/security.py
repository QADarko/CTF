from __future__ import annotations

import asyncio
import hashlib
import os
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

from fastapi import Request, Response
from fastapi.responses import JSONResponse

from packages.ctf_domain.repository import InMemoryRepository

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
IDEMPOTENCY_EXEMPT = {
    "/api/v1/sessions/anonymous",
    "/api/v1/ai/routes/resolve",
}
KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")
_IDEMPOTENCY_LOCKS: dict[tuple[str, str, str], asyncio.Lock] = {}


def _integer(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def _error(
    request: Request,
    code: str,
    message: str,
    status_code: int,
    *,
    retry_after: int | None = None,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None) or request.headers.get(
        "X-Request-ID", f"req_{uuid4().hex}"
    )
    headers = {
        "X-Request-ID": request_id,
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "Cache-Control": "no-store",
    }
    if retry_after is not None:
        headers["Retry-After"] = str(retry_after)
    return JSONResponse(
        status_code=status_code,
        headers=headers,
        content={"error": {"code": code, "message": message, "request_id": request_id}},
    )


def idempotency_policy() -> str:
    configured = os.getenv("CTF_IDEMPOTENCY_POLICY")
    if configured:
        return configured.strip().lower()
    return "optional" if os.getenv("PYTEST_CURRENT_TEST") else "required"


def _request_fingerprint(body: bytes, content_type: str, query: str) -> str:
    canonical = body
    if content_type.startswith("multipart/") and "boundary=" in content_type:
        boundary = content_type.split("boundary=", 1)[1].split(";", 1)[0].strip().strip('"')
        if boundary:
            canonical = body.replace(boundary.encode(), b"<multipart-boundary>")
    digest = hashlib.sha256()
    digest.update(query.encode())
    digest.update(b"\0")
    digest.update(canonical)
    return digest.hexdigest()


def _identity(request: Request, repo: InMemoryRepository) -> tuple[str, str] | None:
    token = request.headers.get("X-Session-Token")
    session_id = repo.session_tokens.get(token or "")
    if not session_id:
        return None
    session = repo.sessions[session_id]
    return session.id, session.tenant_id


async def security_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
    repo: InMemoryRepository,
) -> Response:
    max_json = _integer("CTF_MAX_REQUEST_BODY_BYTES", 1_048_576)
    max_upload = _integer("CTF_MAX_UPLOAD_BYTES", 20 * 1024 * 1024)
    content_length = request.headers.get("content-length")
    content_type = request.headers.get("content-type", "")
    allowed_length = max_upload + 65_536 if content_type.startswith("multipart/") else max_json
    if content_length:
        try:
            if int(content_length) > allowed_length:
                return _error(
                    request, "REQUEST_TOO_LARGE", "Request body exceeds the configured limit.", 413
                )
        except ValueError:
            return _error(request, "INVALID_INPUT", "Content-Length is invalid.", 400)
    request_body = b""
    if request.method in MUTATING:
        chunks: list[bytes] = []
        received = 0
        async for chunk in request.stream():
            received += len(chunk)
            if received > allowed_length:
                return _error(
                    request,
                    "REQUEST_TOO_LARGE",
                    "Request body exceeds the configured limit.",
                    413,
                )
            chunks.append(chunk)
        request_body = b"".join(chunks)
        request._body = request_body

    identity = _identity(request, repo)
    if identity and request.url.path.startswith("/api/"):
        limit = _integer("CTF_RATE_LIMIT_REQUESTS", 600)
        tenant_limit = _integer("CTF_TENANT_RATE_LIMIT_REQUESTS", 3000)
        window = _integer("CTF_RATE_LIMIT_WINDOW_SECONDS", 60)
        now = time.time()
        retry = repo.consume_rate_limit(f"session:{identity[0]}", now, limit, window)
        tenant_retry = repo.consume_rate_limit(
            f"tenant:{identity[1]}", now, tenant_limit, window
        )
        retry = max(retry, tenant_retry)
        if retry:
            return _error(
                request,
                "RATE_LIMIT_EXCEEDED",
                "Request rate limit exceeded.",
                429,
                retry_after=retry,
            )

    consequential = (
        request.method in MUTATING
        and request.url.path.startswith("/api/")
        and request.url.path not in IDEMPOTENCY_EXEMPT
    )
    scope = ""
    actor = identity[0] if identity else "unauthenticated"
    key = request.headers.get("Idempotency-Key")
    fingerprint = ""
    idempotency_lock: asyncio.Lock | None = None
    if consequential:
        policy = idempotency_policy()
        if policy not in {"required", "optional", "deterministic"}:
            return _error(
                request, "SECURITY_POLICY_INVALID", "Idempotency policy is invalid.", 500
            )
        body = request_body
        fingerprint = _request_fingerprint(body, content_type, request.url.query)
        if not key and policy == "required":
            return _error(
                request,
                "IDEMPOTENCY_KEY_REQUIRED",
                "Idempotency-Key is required for this mutating request.",
                400,
            )
        if not key and policy == "deterministic":
            key = f"legacy:{fingerprint}"
        if key and not KEY_PATTERN.fullmatch(key):
            return _error(
                request,
                "INVALID_IDEMPOTENCY_KEY",
                "Idempotency-Key must be 1-200 safe ASCII characters.",
                400,
            )
        if key:
            scope = f"{request.method}:{request.url.path}"
            cached = repo.idempotent_get(scope, actor, key)
            if cached:
                if cached.get("fingerprint") != fingerprint:
                    return _error(
                        request,
                        "IDEMPOTENCY_CONFLICT",
                        "Idempotency-Key was already used with a different request body.",
                        409,
                    )
                headers = dict(cached.get("headers", {}))
                headers["Idempotency-Replayed"] = "true"
                return Response(
                    content=cached["body"],
                    status_code=cached["status_code"],
                    media_type=cached.get("media_type"),
                    headers=headers,
                )
            lock_id = (scope, actor, key)
            idempotency_lock = _IDEMPOTENCY_LOCKS.setdefault(lock_id, asyncio.Lock())
            await idempotency_lock.acquire()
            cached = repo.idempotent_get(scope, actor, key)
            if cached:
                idempotency_lock.release()
                if cached.get("fingerprint") != fingerprint:
                    return _error(
                        request,
                        "IDEMPOTENCY_CONFLICT",
                        "Idempotency-Key was already used with a different request body.",
                        409,
                    )
                headers = dict(cached.get("headers", {}))
                headers["Idempotency-Replayed"] = "true"
                return Response(
                    content=cached["body"],
                    status_code=cached["status_code"],
                    media_type=cached.get("media_type"),
                    headers=headers,
                )

    try:
        response = await call_next(request)
        if consequential and key and response.status_code < 500 and response.status_code != 429:
            response_body = b"".join([chunk async for chunk in response.body_iterator])
            safe_headers = {
                name: value
                for name, value in response.headers.items()
                if name.lower() in {"content-type", "location"}
            }
            envelope: dict[str, Any] = {
                "fingerprint": fingerprint,
                "status_code": response.status_code,
                "media_type": response.media_type,
                "headers": safe_headers,
                "body": response_body.decode("utf-8"),
            }
            repo.idempotent_put(scope, actor, key, envelope)
            response = Response(
                content=response_body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
                background=response.background,
            )

        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"
        )
        response.headers.setdefault("Cache-Control", "no-store")
        return response
    finally:
        if idempotency_lock and idempotency_lock.locked():
            idempotency_lock.release()


def quota_retry_after() -> int:
    """Seconds until the next UTC day, used by the shared 429 contract."""
    return max(1, 86_400 - int(time.time()) % 86_400)
