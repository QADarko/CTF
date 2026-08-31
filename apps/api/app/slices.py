from __future__ import annotations

import json
from collections import deque
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Query

from packages.ctf_domain.ai_runtime import AIExecutionService
from packages.ctf_domain.document_intelligence import DocumentIntelligenceService
from packages.ctf_domain.errors import require
from packages.ctf_domain.models import AnonymousSession, Gate, new_id
from packages.ctf_domain.object_store import object_store
from packages.ctf_domain.repository import repository
from packages.ctf_domain.service import CTFService
from packages.ctf_domain.state_machine import GATE_SPECS

from .common import current_session, owned_project
from .schemas import ActionStatus, ResourceConfirm, ResourceCreate, ResourcePatch

router = APIRouter(prefix="/api/v1/projects")
service = CTFService(repository)
document_intelligence = DocumentIntelligenceService(repository, object_store)
ai_execution = AIExecutionService.from_env(repository)


RESOURCE_PATHS = {
    "claims": "CLAIM",
    "evidence": "EVIDENCE",
    "evidence/gaps": "EVIDENCE_GAP",
    "evidence-sources": "EVIDENCE_SOURCE",
    "opportunities": "OPPORTUNITY",
    "sparks": "SPARK",
    "ideas": "IDEA",
    "assumptions": "ASSUMPTION",
    "failure-modes": "FAILURE_MODE",
    "premortem": "PREMORTEM",
    "counterarguments": "COUNTERARGUMENT",
    "value-boundaries": "VALUE_BOUNDARY",
    "consequences": "CONSEQUENCE",
    "decision-briefs": "DECISION_BRIEF",
    "decision-recommendation": "RECOMMENDATION",
    "validation-plans": "VALIDATION_PLAN",
    "commitment-readiness": "COMMITMENT_READINESS",
    "decisions": "HUMAN_DECISION",
    "commitments": "COMMITMENT",
    "resources": "RESOURCE_COMMITMENT",
    "outcomes": "OUTCOME",
    "milestones": "MILESTONE",
    "actions": "ACTION",
    "execution-evidence": "EXECUTION_EVIDENCE",
    "blockers": "BLOCKER",
    "roadmaps": "ROADMAP",
    "commitment-reviews": "COMMITMENT_REVIEW",
    "creation-records": "CREATION_RECORD",
    "value-stakeholders": "STAKEHOLDER",
    "value-hypotheses": "VALUE_HYPOTHESIS",
    "value-metrics": "VALUE_METRIC",
    "baselines": "BASELINE",
    "observations": "OBSERVATION",
    "value-evidence": "VALUE_EVIDENCE",
    "realized-values": "REALIZED_VALUE",
    "negative-effects": "NEGATIVE_EFFECT",
    "attributions": "ATTRIBUTION",
    "counterfactuals": "COUNTERFACTUAL",
    "adoptions": "ADOPTION",
    "impacts": "IMPACT",
    "transformation-assessments": "TRANSFORMATION",
    "reality-snapshots": "REALITY_SNAPSHOT",
    "creation-cycles": "CREATION_CYCLE",
}


@router.post("/{project_id}/resources/{kind}", status_code=201)
def create_resource(
    project_id: str,
    kind: str,
    body: ResourceCreate,
    session: Annotated[AnonymousSession, Depends(current_session)],
    idempotency_key: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    project = owned_project(project_id, session)
    kind = kind.upper()
    scope = f"{project.id}:resource:{kind}"
    cached = repository.idempotent_get(scope, session.id, idempotency_key)
    if cached:
        return cached
    with repository.transaction():
        record = service.create_resource(
            project, kind, dict(body.data), body.expected_version, body.provenance
        )
        result = record.public()
        repository.idempotent_put(scope, session.id, idempotency_key, result)
        return result


@router.get("/{project_id}/resources/{kind}")
def list_resources(
    project_id: str,
    kind: str,
    session: Annotated[AnonymousSession, Depends(current_session)],
) -> list[dict[str, Any]]:
    project = owned_project(project_id, session)
    return [item.public() for item in repository.list_resources(project, kind.upper())]


@router.get("/{project_id}/resources/{kind}/{resource_id}")
def get_resource(
    project_id: str,
    kind: str,
    resource_id: str,
    session: Annotated[AnonymousSession, Depends(current_session)],
) -> dict[str, Any]:
    project = owned_project(project_id, session)
    return repository.get_resource(project, resource_id, kind.upper()).public()


@router.patch("/{project_id}/resources/{kind}/{resource_id}")
def patch_resource(
    project_id: str,
    kind: str,
    resource_id: str,
    body: ResourcePatch,
    session: Annotated[AnonymousSession, Depends(current_session)],
) -> dict[str, Any]:
    project = owned_project(project_id, session)
    with repository.transaction():
        record = repository.get_resource(project, resource_id, kind.upper())
        return repository.update_resource(
            project, record.id, body.data, body.expected_version
        ).public()


@router.post("/{project_id}/resources/{kind}/{resource_id}/confirm")
def confirm_resource(
    project_id: str,
    kind: str,
    resource_id: str,
    session: Annotated[AnonymousSession, Depends(current_session)],
    body: ResourceConfirm | None = None,
) -> dict[str, Any]:
    project = owned_project(project_id, session)
    payload = body or ResourceConfirm()
    with repository.transaction():
        return service.confirm_resource(
            project, kind, resource_id, payload.expected_version, payload.actor_type
        ).public()


@router.post(
    "/{project_id}/resources/{kind}/{resource_id}/supersede", status_code=201
)
def supersede_resource(
    project_id: str,
    kind: str,
    resource_id: str,
    body: ResourceCreate,
    session: Annotated[AnonymousSession, Depends(current_session)],
) -> dict[str, Any]:
    project = owned_project(project_id, session)
    with repository.transaction():
        return service.supersede_resource(
            project,
            kind,
            resource_id,
            dict(body.data),
            body.expected_version,
            body.provenance,
        ).public()


def _make_list(kind: str) -> Callable[..., list[dict[str, Any]]]:
    def endpoint(
        project_id: str,
        session: Annotated[AnonymousSession, Depends(current_session)],
    ) -> list[dict[str, Any]]:
        project = owned_project(project_id, session)
        return [item.public() for item in repository.list_resources(project, kind)]

    endpoint.__name__ = f"list_{kind.lower()}"
    return endpoint


def _make_create(kind: str, ai_operation: str | None = None) -> Callable[..., dict[str, Any]]:
    def endpoint(
        project_id: str,
        body: ResourceCreate,
        session: Annotated[AnonymousSession, Depends(current_session)],
    ) -> dict[str, Any]:
        project = owned_project(project_id, session)
        if body.execute_ai:
            require(
                bool(ai_operation),
                "AI_OPERATION_NOT_ALLOWED",
                "This endpoint has no registered AI operation.",
                400,
            )
            require(
                body.ai_operation is None or body.ai_operation.upper() == ai_operation,
                "AI_OPERATION_NOT_ALLOWED",
                "The requested AI operation does not match this generator.",
                400,
            )
            result = ai_execution.execute(
                project,
                operation=ai_operation or "",
                user_input=str(body.data.get("prompt") or json.dumps(body.data)),
                consequentiality=body.consequentiality,
                prompt_version=body.prompt_version,
                extra_context=body.data,
            )
            persisted = []
            for item in result["output"]["items"]:
                data = dict(item)
                data["status"] = "PROPOSED"
                with repository.transaction():
                    persisted.append(
                        service.create_resource(project, kind, data, None, "CTF").public()
                    )
            return {"run": result["run"], "items": persisted}
        with repository.transaction():
            return service.create_resource(
                project, kind, dict(body.data), body.expected_version, body.provenance
            ).public()

    endpoint.__name__ = f"create_{kind.lower()}"
    return endpoint


for path, resource_kind in RESOURCE_PATHS.items():
    router.add_api_route(
        f"/{{project_id}}/{path}",
        _make_list(resource_kind),
        methods=["GET"],
        tags=[resource_kind],
    )
    if resource_kind != "HUMAN_DECISION":
        router.add_api_route(
            f"/{{project_id}}/{path}",
            _make_create(resource_kind),
            methods=["POST"],
            status_code=201,
            tags=[resource_kind],
        )


GENERATOR_PATHS = {
    "evidence/input": "EVIDENCE",
    "opportunities/generate": "OPPORTUNITY",
    "opportunities/custom": "OPPORTUNITY",
    "sparks/generate": "SPARK",
    "sparks/custom": "SPARK",
    "sparks/combine": "SPARK",
    "ideas/generate": "IDEA",
    "ideas/combine": "IDEA",
    "assumptions/generate": "ASSUMPTION",
    "assumptions/custom": "ASSUMPTION",
    "adversarial-tests": "FAILURE_MODE",
    "value-boundaries/test": "VALUE_BOUNDARY_TEST",
    "consequences/analyze": "CONSEQUENCE",
    "commitment-readiness/assess": "COMMITMENT_READINESS",
    "outcomes/generate": "OUTCOME",
    "milestones/generate": "MILESTONE",
    "actions/generate": "ACTION",
    "roadmaps/generate": "ROADMAP",
    "value-hypotheses/generate": "VALUE_HYPOTHESIS",
}

AI_GENERATOR_OPERATIONS = {
    "reality/generate": ("REALITY", "REALITY_UPDATE"),
    "questions/generate": ("QUESTION", "QUESTION_REFRAME"),
    "perceptions/generate": ("PERCEPTION", "PERCEPTION_SYNTHESIS"),
    "opportunities/generate": ("OPPORTUNITY", "OPPORTUNITY_GENERATION"),
    "sparks/generate": ("SPARK", "SPARK_GENERATION"),
    "ideas/generate": ("IDEA", "IDEA_BLUEPRINT"),
    "adversarial-tests": ("FAILURE_MODE", "RED_TEAM"),
    "roadmaps/generate": ("ROADMAP", "ROADMAP_REPLAN"),
    "next-best-action/generate": ("ACTION", "NEXT_BEST_ACTION"),
    "value-assessments/generate": ("REALIZED_VALUE", "REALIZED_VALUE"),
    "transformation-assessments/generate": ("TRANSFORMATION", "TRANSFORMATION"),
    "r1/generate": ("REALITY_SNAPSHOT", "R1_GENERATION"),
}

for path, resource_kind in GENERATOR_PATHS.items():
    operation = AI_GENERATOR_OPERATIONS.get(path, (resource_kind, None))[1]
    router.add_api_route(
        f"/{{project_id}}/{path}",
        _make_create(resource_kind, operation),
        methods=["POST"],
        status_code=201,
        tags=[resource_kind],
    )

for path, (resource_kind, operation) in AI_GENERATOR_OPERATIONS.items():
    if path in GENERATOR_PATHS:
        continue
    router.add_api_route(
        f"/{{project_id}}/{path}",
        _make_create(resource_kind, operation),
        methods=["POST"],
        status_code=201,
        tags=[resource_kind],
    )


@router.post("/{project_id}/evidence/analyze-document", status_code=202)
def analyze_document(
    project_id: str,
    body: ResourceCreate,
    background_tasks: BackgroundTasks,
    session: Annotated[AnonymousSession, Depends(current_session)],
) -> dict[str, Any]:
    project = owned_project(project_id, session)
    attachment = repository.get_resource(project, body.data.get("attachment_id"), "ATTACHMENT")
    require(
        attachment.status in {"READY_FOR_LATER_PROCESSING", "ANALYZED"}
        and attachment.data.get("malware_scan", {}).get("status") == "CLEAN",
        "ATTACHMENT_NOT_READY",
        "Attachment has not passed malware scanning.",
        409,
    )
    with repository.transaction():
        for existing in repository.list_resources(project, "DOCUMENT_JOB"):
            if (
                existing.data.get("attachment_id") == attachment.id
                and existing.data.get("attachment_checksum_sha256")
                == attachment.data["checksum_sha256"]
            ):
                if existing.status in {"QUEUED", "PROCESSING"}:
                    background_tasks.add_task(
                        document_intelligence.process, project.id, existing.id
                    )
                return existing.public()
        job = repository.create_resource(
            project,
            "DOCUMENT_JOB",
            {
                "attachment_id": attachment.id,
                "attachment_checksum_sha256": attachment.data["checksum_sha256"],
                "operation": "CONTEXTUAL_EVIDENCE_EXTRACTION",
                "status": "QUEUED",
                "progress": 0,
                "counts": {
                    "units": 0,
                    "chunks": 0,
                    "candidate_claims": 0,
                    "candidate_evidence": 0,
                },
                "error": None,
                "result_contract": {
                    "claims": "list",
                    "evidence_items": "list",
                    "source_locations_required": True,
                },
            },
            status="QUEUED",
            provenance="SYSTEM",
        )
    background_tasks.add_task(document_intelligence.process, project.id, job.id)
    return job.public()


@router.get("/{project_id}/document-jobs/{job_id}")
def document_job(
    project_id: str,
    job_id: str,
    session: Annotated[AnonymousSession, Depends(current_session)],
) -> dict[str, Any]:
    project = owned_project(project_id, session)
    return repository.get_resource(project, job_id, "DOCUMENT_JOB").public()


@router.get("/{project_id}/attachments/{attachment_id}/parsed")
def parsed_document(
    project_id: str,
    attachment_id: str,
    session: Annotated[AnonymousSession, Depends(current_session)],
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
) -> dict[str, Any]:
    project = owned_project(project_id, session)
    attachment = repository.get_resource(project, attachment_id, "ATTACHMENT")
    parses = [
        item
        for item in repository.list_resources(project, "PARSED_DOCUMENT")
        if item.data.get("attachment_id") == attachment.id
    ]
    require(bool(parses), "RESOURCE_NOT_FOUND", "Parsed document was not found.", 404)
    chunks = [
        item.public()
        for item in repository.list_resources(project, "DOCUMENT_CHUNK")
        if item.data.get("attachment_id") == attachment.id
    ]
    chunks.sort(key=lambda item: item["data"]["ordinal"])
    return {
        "document": parses[-1].public(),
        "chunks": chunks[offset : offset + limit],
        "pagination": {
            "offset": offset,
            "limit": limit,
            "total": len(chunks),
        },
    }


@router.post("/{project_id}/actions/{action_id}/status")
def action_status(
    project_id: str,
    action_id: str,
    body: ActionStatus,
    session: Annotated[AnonymousSession, Depends(current_session)],
) -> dict[str, Any]:
    project = owned_project(project_id, session)
    with repository.transaction():
        return service.action_status(
            project, action_id, body.status, body.expected_version
        ).public()


@router.post("/{project_id}/actions/{action_id}/evidence", status_code=201)
def add_action_evidence(
    project_id: str,
    action_id: str,
    body: ResourceCreate,
    session: Annotated[AnonymousSession, Depends(current_session)],
) -> dict[str, Any]:
    project = owned_project(project_id, session)
    data = dict(body.data)
    data["action_id"] = action_id
    with repository.transaction():
        return service.create_resource(
            project, "EXECUTION_EVIDENCE", data, body.expected_version, body.provenance
        ).public()


@router.post("/{project_id}/execution-events", status_code=201)
def create_execution_event(
    project_id: str,
    body: ResourceCreate,
    session: Annotated[AnonymousSession, Depends(current_session)],
) -> dict[str, Any]:
    project = owned_project(project_id, session)
    data = dict(body.data)
    data["materiality"] = service.classify_materiality(data)
    data["status"] = "OPEN"
    with repository.transaction():
        record = service.create_resource(
            project, "EXECUTION_EVENT", data, body.expected_version, body.provenance
        )
        if data["materiality"] == "DECISION_RELEVANT" and project.stage == "ACTION":
            project.active_gate = Gate(new_id("gate"), 14, GATE_SPECS[14].name)
            repository.touch(project)
        return record.public()


@router.get("/{project_id}/execution-events")
def list_execution_events(
    project_id: str, session: Annotated[AnonymousSession, Depends(current_session)]
) -> list[dict[str, Any]]:
    project = owned_project(project_id, session)
    return [item.public() for item in repository.list_resources(project, "EXECUTION_EVENT")]


@router.get("/{project_id}/next-best-action")
def next_best_action(
    project_id: str, session: Annotated[AnonymousSession, Depends(current_session)]
) -> dict[str, Any]:
    return service.next_best_action(owned_project(project_id, session))


@router.get("/{project_id}/redecision-triggers/open")
def redecision_triggers(
    project_id: str, session: Annotated[AnonymousSession, Depends(current_session)]
) -> list[dict[str, Any]]:
    project = owned_project(project_id, session)
    return [
        item.public()
        for item in repository.list_resources(project, "EXECUTION_EVENT")
        if item.status == "OPEN" and item.data.get("materiality") == "DECISION_RELEVANT"
    ]


@router.get("/{project_id}/creation-graph")
@router.get("/{project_id}/creation-genealogy")
def creation_graph(
    project_id: str, session: Annotated[AnonymousSession, Depends(current_session)]
) -> dict[str, Any]:
    project = owned_project(project_id, session)
    nodes = [
        item.public() for item in repository.resources.values() if item.project_id == project.id
    ]
    links = [link for link in repository.creation_links if link["project_id"] == project.id]
    return {"nodes": nodes, "links": links}


@router.get("/{project_id}/trace/{object_type}/{object_id}")
def trace(
    project_id: str,
    object_type: str,
    object_id: str,
    session: Annotated[AnonymousSession, Depends(current_session)],
) -> dict[str, Any]:
    project = owned_project(project_id, session)
    target = repository.get_resource(project, object_id)
    queue = deque([target.id])
    seen = {target.id}
    links: list[dict[str, Any]] = []
    while queue:
        current = queue.popleft()
        for link in repository.creation_links:
            if link["project_id"] == project.id and link["to_id"] == current:
                links.append(link)
                if link["from_id"] not in seen:
                    seen.add(link["from_id"])
                    queue.append(link["from_id"])
    nodes = [repository.resources[item].public() for item in seen]
    return {
        "target_type": object_type.upper(),
        "target_id": object_id,
        "nodes": nodes,
        "links": links,
        "source": "PERSISTED_GENEALOGY",
    }


@router.get("/{project_id}/reality-snapshots/{from_id}/compare/{to_id}")
def compare_reality(
    project_id: str,
    from_id: str,
    to_id: str,
    session: Annotated[AnonymousSession, Depends(current_session)],
) -> dict[str, Any]:
    project = owned_project(project_id, session)
    old = repository.get_resource(project, from_id, "REALITY_SNAPSHOT")
    new = repository.get_resource(project, to_id, "REALITY_SNAPSHOT")
    old_dimensions = {x["dimension"]: x for x in old.data.get("dimensions", [])}
    new_dimensions = {x["dimension"]: x for x in new.data.get("dimensions", [])}
    delta = []
    for dimension in sorted(old_dimensions.keys() | new_dimensions.keys()):
        before = old_dimensions.get(dimension)
        after = new_dimensions.get(dimension)
        classification = "NEW_DIMENSION" if before is None else "UNKNOWN"
        if after is None:
            classification = "UNKNOWN"
        elif before and before.get("method") != after.get("method"):
            classification = "NOT_COMPARABLE"
        elif before and before.get("value") == after.get("value"):
            classification = "UNCHANGED"
        delta.append(
            {
                "dimension": dimension,
                "before": before,
                "after": after,
                "classification": classification,
            }
        )
    return {"from": from_id, "to": to_id, "delta": delta}
