from __future__ import annotations

import hashlib
import os
import re
import secrets
from dataclasses import asdict
from pathlib import PurePath
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Header, UploadFile
from fastapi.responses import StreamingResponse

from packages.ctf_domain.errors import DomainError, require
from packages.ctf_domain.malware import create_malware_scanner
from packages.ctf_domain.models import AnonymousSession
from packages.ctf_domain.object_store import object_store
from packages.ctf_domain.repository import repository
from packages.ctf_domain.service import CTFService

from .schemas import (
    GateDecision,
    MemoryPatch,
    ProjectCreate,
    ResourceCreate,
    RevisionTransition,
    SessionCreate,
    UserInput,
)

router = APIRouter(prefix="/api/v1")
service = CTFService(repository)


def current_session(
    x_session_token: Annotated[str | None, Header()] = None,
) -> AnonymousSession:
    return repository.session_from_token(x_session_token)


def owned_project(project_id: str, session: AnonymousSession):
    return repository.project_for(project_id, session)


@router.post("/sessions/anonymous", status_code=201)
def create_anonymous_session(body: SessionCreate) -> dict[str, Any]:
    return asdict(repository.create_session(body.tenant_id))


@router.post("/projects", status_code=201)
def create_project(
    body: ProjectCreate,
    session: Annotated[AnonymousSession, Depends(current_session)],
    idempotency_key: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    scope = "create_project"
    cached = repository.idempotent_get(scope, session.id, idempotency_key)
    if cached:
        return cached
    with repository.transaction():
        project = repository.create_project(
            session,
            body.entry_family,
            body.entry_type.upper(),
            body.initial_input,
            body.source,
        )
        result = project.public()
        repository.idempotent_put(scope, session.id, idempotency_key, result)
        return result


@router.get("/projects/{project_id}")
def get_project(
    project_id: str, session: Annotated[AnonymousSession, Depends(current_session)]
) -> dict[str, Any]:
    return owned_project(project_id, session).public()


@router.get("/projects/{project_id}/workspace")
def get_workspace(
    project_id: str, session: Annotated[AnonymousSession, Depends(current_session)]
) -> dict[str, Any]:
    project = owned_project(project_id, session)
    return {
        "project": project.public(),
        "memory": project.memory,
        "active_gate": project.public()["active_gate"],
        "resources": [
            repository.resources[item].public()
            for item in repository.project_resources[project.id]
        ],
    }


@router.post("/projects/{project_id}/input", status_code=201)
def submit_input(
    project_id: str,
    body: UserInput,
    session: Annotated[AnonymousSession, Depends(current_session)],
    idempotency_key: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    project = owned_project(project_id, session)
    scope = f"{project.id}:input"
    cached = repository.idempotent_get(scope, session.id, idempotency_key)
    if cached:
        return cached
    with repository.transaction():
        repository.check_version(project, body.expected_version)
        message = repository.create_resource(
            project,
            "MESSAGE",
            {
                "text": body.text,
                "information_type": body.information_type,
                "source": "USER",
            },
            status="PERSISTED",
            provenance="USER",
            immutable=True,
        )
        result = {
            "message": message.public(),
            "project_version": project.version,
            "stage": project.stage,
            "note": "Input persisted; no external AI call is configured.",
        }
        repository.idempotent_put(scope, session.id, idempotency_key, result)
        return result


@router.post("/projects/{project_id}/memory/operations", status_code=201)
def patch_memory(
    project_id: str,
    body: MemoryPatch,
    session: Annotated[AnonymousSession, Depends(current_session)],
) -> dict[str, Any]:
    project = owned_project(project_id, session)
    with repository.transaction():
        return service.patch_memory(
            project, body.operations, body.expected_version, body.actor_type
        )


@router.get("/projects/{project_id}/memory/versions")
def memory_versions(
    project_id: str, session: Annotated[AnonymousSession, Depends(current_session)]
) -> list[dict[str, Any]]:
    return repository.memory_history(owned_project(project_id, session))


@router.get("/projects/{project_id}/audit")
def audit(
    project_id: str, session: Annotated[AnonymousSession, Depends(current_session)]
) -> list[dict[str, Any]]:
    return repository.project_audit(owned_project(project_id, session))


@router.post("/projects/{project_id}/gates/{gate_id}/decision")
def decide_gate(
    project_id: str,
    gate_id: str,
    body: GateDecision,
    session: Annotated[AnonymousSession, Depends(current_session)],
    idempotency_key: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    project = owned_project(project_id, session)
    scope = f"{project.id}:gate:{gate_id}"
    cached = repository.idempotent_get(scope, session.id, idempotency_key)
    if cached:
        return cached
    with repository.transaction():
        result = service.decide_gate(
            project,
            gate_id,
            body.decision,
            body.payload,
            body.expected_version,
            body.actor_type,
        )
        repository.idempotent_put(scope, session.id, idempotency_key, result)
        return result


@router.post("/projects/{project_id}/transitions/revise")
def revision_transition(
    project_id: str,
    body: RevisionTransition,
    session: Annotated[AnonymousSession, Depends(current_session)],
) -> dict[str, Any]:
    project = owned_project(project_id, session)
    with repository.transaction():
        return service.explicit_transition(project, body.target_stage, body.expected_version)


@router.get("/projects/{project_id}/{kind}/current")
def get_current(
    project_id: str,
    kind: str,
    session: Annotated[AnonymousSession, Depends(current_session)],
) -> dict[str, Any]:
    project = owned_project(project_id, session)
    mapping = {"reality": "REALITY", "question": "QUESTION", "perception": "PERCEPTION"}
    records = repository.list_resources(project, mapping.get(kind.lower(), kind.upper()))
    return records[-1].public() if records else {"status": "NOT_CREATED"}


@router.put("/projects/{project_id}/funding-context")
def put_funding_context(
    project_id: str,
    body: ResourceCreate,
    session: Annotated[AnonymousSession, Depends(current_session)],
) -> dict[str, Any]:
    project = owned_project(project_id, session)
    with repository.transaction():
        repository.check_version(project, body.expected_version)
        project.memory["funding_context"] = body.data
        repository.touch(project)
        version = repository.snapshot_memory(
            project, [{"op": "UPDATE", "path": "funding_context", "value": body.data}]
        )
        return {"funding_context": body.data, "memory_version": version.version}


ALLOWED_ATTACHMENTS = {
    ".pdf": {"application/pdf"},
    ".docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/zip",
    },
    ".xlsx": {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/zip",
    },
    ".txt": {"text/plain"},
    ".csv": {"text/csv", "application/vnd.ms-excel"},
}
SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._ -]+")
WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


def sanitize_filename(filename: str | None) -> str:
    candidate = PurePath((filename or "").replace("\\", "/")).name
    candidate = SAFE_FILENAME.sub("_", candidate).strip(" .")
    if not candidate:
        candidate = "upload"
    stem, dot, suffix = candidate.rpartition(".")
    if not dot:
        stem, suffix = candidate, ""
    if stem.upper() in WINDOWS_RESERVED:
        stem = f"_{stem}"
    extension = f".{suffix}" if suffix else ""
    return f"{stem[: max(1, 180 - len(extension))]}{extension}"


@router.post("/projects/{project_id}/attachments", status_code=201)
async def upload_attachment(
    project_id: str,
    file: Annotated[UploadFile, File()],
    session: Annotated[AnonymousSession, Depends(current_session)],
    document_type: str = "OTHER",
) -> dict[str, Any]:
    project = owned_project(project_id, session)
    safe_filename = sanitize_filename(file.filename)
    suffix = (
        "." + safe_filename.rsplit(".", 1)[-1].lower()
        if "." in safe_filename
        else ""
    )
    max_upload = int(os.getenv("CTF_MAX_UPLOAD_BYTES", str(20 * 1024 * 1024)))
    content = await file.read(max_upload + 1)

    require(suffix in ALLOWED_ATTACHMENTS, "INVALID_INPUT", "Unsupported attachment type.")
    require(
        len(content) <= max_upload,
        "REQUEST_TOO_LARGE",
        "Attachment exceeds the configured upload limit.",
        413,
    )
    require(
        file.content_type in ALLOWED_ATTACHMENTS[suffix],
        "INVALID_INPUT",
        "Attachment MIME type does not match the extension.",
    )
    if suffix == ".pdf":
        require(content.startswith(b"%PDF"), "INVALID_INPUT", "Invalid PDF signature.")
    if suffix in {".docx", ".xlsx"}:
        require(content.startswith(b"PK"), "INVALID_INPUT", "Invalid Office document signature.")
    tenant_scope = hashlib.sha256(project.tenant_id.encode()).hexdigest()[:20]
    object_key = f"{tenant_scope}/{project.id}/{secrets.token_hex(24)}{suffix}"
    scanner = create_malware_scanner()
    rejected: DomainError | None = None
    try:
        with repository.transaction():
            object_store.put(object_key, content, file.content_type or "application/octet-stream")
            record = repository.create_resource(
                project,
                "ATTACHMENT",
                {
                    "document_type": document_type.upper(),
                    "original_filename": safe_filename,
                    "mime_type": file.content_type,
                    "size": len(content),
                    "checksum_sha256": hashlib.sha256(content).hexdigest(),
                    "processing_status": "SCANNING",
                    "semantically_analyzed": False,
                    "object_store": object_store.backend,
                    "object_key": object_key,
                    "malware_scan": {"scanner": scanner.name, "status": "PENDING"},
                },
                status="SCANNING",
                provenance="USER",
            )
            scan = scanner.scan(content)
            record = repository.get_resource(project, record.id, "ATTACHMENT")
            record.data["malware_scan"] = {
                "scanner": scan.scanner,
                "status": "CLEAN" if scan.clean else "REJECTED",
                "signature": scan.signature,
            }
            if scan.clean:
                record.status = "READY_FOR_LATER_PROCESSING"
                record.data["processing_status"] = "READY_FOR_LATER_PROCESSING"
            else:
                record.status = "QUARANTINED"
                record.data["processing_status"] = "QUARANTINED"
                rejected = DomainError(
                    "MALWARE_DETECTED",
                    "Attachment was quarantined because malware was detected.",
                    422,
                )
            project.memory["document_provenance"].append(
                {"attachment_id": record.id, "checksum": record.data["checksum_sha256"]}
            )
            repository.audit(
                project.id,
                "attachment_scanned",
                "SYSTEM",
                {
                    "attachment_id": record.id,
                    "scanner": scan.scanner,
                    "result": record.data["malware_scan"]["status"],
                },
            )
            result = record.public()
        if rejected:
            raise rejected
        return result
    except DomainError as exc:
        if exc is rejected:
            raise
        object_store.delete(object_key)
        raise
    except Exception:
        object_store.delete(object_key)
        raise


@router.get("/projects/{project_id}/attachments")
def list_attachments(
    project_id: str, session: Annotated[AnonymousSession, Depends(current_session)]
) -> list[dict[str, Any]]:
    project = owned_project(project_id, session)
    return [item.public() for item in repository.list_resources(project, "ATTACHMENT")]


@router.get("/projects/{project_id}/attachments/{attachment_id}")
def get_attachment(
    project_id: str,
    attachment_id: str,
    session: Annotated[AnonymousSession, Depends(current_session)],
) -> dict[str, Any]:
    project = owned_project(project_id, session)
    return repository.get_resource(project, attachment_id, "ATTACHMENT").public()


@router.get("/projects/{project_id}/attachments/{attachment_id}/download")
def download_attachment(
    project_id: str,
    attachment_id: str,
    session: Annotated[AnonymousSession, Depends(current_session)],
):
    project = owned_project(project_id, session)
    record = repository.get_resource(project, attachment_id, "ATTACHMENT")
    require(
        record.status in {"READY_FOR_LATER_PROCESSING", "ANALYZED"}
        and record.data.get("malware_scan", {}).get("status") == "CLEAN",
        "ATTACHMENT_NOT_READY",
        "Attachment is not available for download.",
        409,
    )
    ttl = min(900, max(30, int(os.getenv("CTF_PRESIGN_TTL_SECONDS", "300"))))
    url = object_store.presign_get(record.data["object_key"], ttl)
    repository.audit(
        project.id,
        "attachment_download_authorized",
        "HUMAN",
        {"attachment_id": record.id, "delivery": "presigned" if url else "stream"},
    )
    repository.persist()
    if url:
        return {"url": url, "expires_in": ttl, "attachment_id": record.id}
    stream = object_store.open_stream(record.data["object_key"])
    return StreamingResponse(
        stream,
        media_type=record.data["mime_type"],
        headers={
            "Content-Disposition": f'attachment; filename="{record.data["original_filename"]}"',
            "Content-Length": str(record.data["size"]),
        },
    )


@router.delete("/projects/{project_id}/attachments/{attachment_id}")
def delete_attachment(
    project_id: str,
    attachment_id: str,
    session: Annotated[AnonymousSession, Depends(current_session)],
) -> dict[str, Any]:
    project = owned_project(project_id, session)
    with repository.transaction():
        record = repository.get_resource(project, attachment_id, "ATTACHMENT")
        record.status = "DELETED"
        record.data["processing_status"] = "DELETED"
        repository.touch(project)
        repository.audit(project.id, "attachment_deleted", "HUMAN", {"attachment_id": record.id})
    object_store.delete(record.data["object_key"])
    return {"deleted": True, "attachment_id": record.id}
