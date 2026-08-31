from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from packages.ctf_domain.ai_runtime import AIExecutionService
from packages.ctf_domain.eri import ERIService
from packages.ctf_domain.errors import require
from packages.ctf_domain.model_router import (
    AICostLedger,
    ContextCompiler,
    ModelRouter,
    route_public,
)
from packages.ctf_domain.models import AnonymousSession
from packages.ctf_domain.repository import repository
from packages.ctf_domain.service import CTFService

from .common import current_session, owned_project
from .schemas import (
    AIExecuteRequest,
    ERIEventCreate,
    MetricBindingCreate,
    RouteRequest,
    UsageCreate,
)

router = APIRouter(prefix="/api/v1")
model_router = ModelRouter()
context_compiler = ContextCompiler()
cost_ledger = AICostLedger(repository)
eri = ERIService.from_env(repository)
ai_execution = AIExecutionService.from_env(repository)
ctf_service = CTFService(repository)


@router.post("/ai/routes/resolve")
def resolve_route(
    body: RouteRequest,
    _: Annotated[AnonymousSession, Depends(current_session)],
) -> dict[str, Any]:
    return route_public(model_router.route(body.operation, body.consequentiality))


@router.get("/ai/routes")
def list_routes(
    _: Annotated[AnonymousSession, Depends(current_session)],
) -> list[dict[str, Any]]:
    from packages.ctf_domain.model_router import ROUTES

    return [route_public(route) for route in ROUTES.values()]


@router.get("/ai/operations")
def list_ai_operations(
    _: Annotated[AnonymousSession, Depends(current_session)],
) -> list[str]:
    return ai_execution.registry.operations()


@router.get("/ai/readiness")
def ai_readiness(
    _: Annotated[AnonymousSession, Depends(current_session)],
) -> dict[str, Any]:
    """Report safe provider/model capability state without returning credentials."""
    return ai_execution.readiness()


@router.post("/projects/{project_id}/ai/execute")
def execute_ai(
    project_id: str,
    body: AIExecuteRequest,
    session: Annotated[AnonymousSession, Depends(current_session)],
) -> dict[str, Any]:
    project = owned_project(project_id, session)
    repository.check_version(project, body.expected_version)
    result = ai_execution.execute(
        project,
        operation=body.operation,
        user_input=body.user_input,
        consequentiality=body.consequentiality,
        prompt_version=body.prompt_version,
        extra_context=body.context,
    )
    if body.persist_as:
        kind = body.persist_as.upper()
        require(
            kind not in {"HUMAN_DECISION", "VALUE_BOUNDARY"},
            "HUMAN_AUTHORITY_REQUIRED",
            "AI cannot persist Human-owned decisions or values.",
            403,
        )
        persisted = []
        for item in result["output"]["items"]:
            data = dict(item)
            data["status"] = "PROPOSED"
            with repository.transaction():
                persisted.append(
                    ctf_service.create_resource(project, kind, data, None, "CTF").public()
                )
        result["persisted"] = persisted
    return result


@router.get("/projects/{project_id}/ai/runs")
def list_ai_runs(
    project_id: str,
    session: Annotated[AnonymousSession, Depends(current_session)],
) -> list[dict[str, Any]]:
    return ai_execution.runs(owned_project(project_id, session))


@router.post("/ai/usage", status_code=201)
def record_usage(
    body: UsageCreate,
    session: Annotated[AnonymousSession, Depends(current_session)],
) -> dict[str, Any]:
    owned_project(body.project_id, session)
    with repository.transaction():
        return cost_ledger.record(
            project_id=body.project_id,
            operation=body.operation,
            provider=body.provider,
            model=body.model,
            capability=body.capability,
            reasoning_effort=body.reasoning_effort,
            input_tokens=body.input_tokens,
            cached_input_tokens=body.cached_input_tokens,
            output_tokens=body.output_tokens,
            input_per_mtok=Decimal(body.input_per_mtok),
            cached_input_per_mtok=Decimal(body.cached_input_per_mtok),
            output_per_mtok=Decimal(body.output_per_mtok),
            price_snapshot_id=body.price_snapshot_id,
            latency_ms=body.latency_ms,
        )


@router.get("/projects/{project_id}/ai-cost-ledger")
def ai_cost_summary(
    project_id: str, session: Annotated[AnonymousSession, Depends(current_session)]
) -> dict[str, Any]:
    owned_project(project_id, session)
    return cost_ledger.summary(project_id)


@router.get("/eri/providers")
def providers(
    _: Annotated[AnonymousSession, Depends(current_session)],
) -> list[dict[str, Any]]:
    return eri.providers()


@router.post("/eri/providers/khal/connect", status_code=201)
def connect_khal(
    body: dict[str, Any],
    session: Annotated[AnonymousSession, Depends(current_session)],
) -> dict[str, Any]:
    allowed = {"base_url", "credential_reference"}
    require(
        set(body) <= allowed,
        "INVALID_INPUT",
        "Raw or unsupported KHAL configuration fields are not accepted.",
    )
    return eri.connect_khal(session.tenant_id, body)


@router.get("/eri/khal/health")
def khal_health(
    session: Annotated[AnonymousSession, Depends(current_session)],
) -> dict[str, Any]:
    return eri.khal_readiness(session.tenant_id)


@router.get("/eri/khal/assets")
def khal_assets(
    session: Annotated[AnonymousSession, Depends(current_session)],
) -> dict[str, Any]:
    return eri.khal_assets(session.tenant_id)


@router.get("/eri/khal/metrics")
def khal_metrics(
    session: Annotated[AnonymousSession, Depends(current_session)],
) -> dict[str, Any]:
    return eri.khal_metrics(session.tenant_id)


@router.get("/eri/khal/measurements")
def khal_measurements(
    session: Annotated[AnonymousSession, Depends(current_session)],
    external_metric: str = Query(...),
    observed_from: str | None = None,
    observed_to: str | None = None,
) -> dict[str, Any]:
    return eri.khal_measurements(
        session.tenant_id,
        {
            "external_metric": external_metric,
            "observed_from": observed_from,
            "observed_to": observed_to,
        },
    )


@router.post("/projects/{project_id}/eri/khal/measurements/ingest", status_code=201)
def ingest_khal_measurements(
    project_id: str,
    session: Annotated[AnonymousSession, Depends(current_session)],
    external_metric: str = Query(...),
    observed_from: str | None = None,
    observed_to: str | None = None,
) -> dict[str, Any]:
    project = owned_project(project_id, session)
    return eri.ingest_khal_measurements(
        project,
        {
            "external_metric": external_metric,
            "observed_from": observed_from,
            "observed_to": observed_to,
        },
    )


@router.post("/eri/reality-events", status_code=201)
def ingest_reality_event(
    body: ERIEventCreate,
    session: Annotated[AnonymousSession, Depends(current_session)],
) -> dict[str, Any]:
    project = owned_project(body.project_id, session)
    event, duplicate = eri.ingest_event(project, body.model_dump(exclude={"project_id"}))
    return {"event": event, "duplicate": duplicate}


@router.get("/eri/reality-events")
def list_reality_events(
    project_id: str,
    session: Annotated[AnonymousSession, Depends(current_session)],
) -> list[dict[str, Any]]:
    project = owned_project(project_id, session)
    return [item.public() for item in repository.list_resources(project, "REALITY_EVENT")]


@router.get("/eri/reality-events/{event_id}")
def get_reality_event(
    event_id: str,
    project_id: str,
    session: Annotated[AnonymousSession, Depends(current_session)],
) -> dict[str, Any]:
    project = owned_project(project_id, session)
    return repository.get_resource(project, event_id, "REALITY_EVENT").public()


@router.post("/eri/reality-events/{event_id}/create-evidence", status_code=201)
def event_to_evidence(
    event_id: str,
    project_id: str,
    session: Annotated[AnonymousSession, Depends(current_session)],
) -> dict[str, Any]:
    project = owned_project(project_id, session)
    return eri.create_evidence(project, event_id)


@router.post("/eri/metric-bindings", status_code=201)
def create_metric_binding(
    body: MetricBindingCreate,
    session: Annotated[AnonymousSession, Depends(current_session)],
) -> dict[str, Any]:
    project = owned_project(body.project_id, session)
    return eri.bind_metric(project, body.model_dump(exclude={"project_id"}))
