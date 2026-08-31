"""Operation-specific context compilation (CTF-001)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .context_safety import (
    ALLOWED_REQUEST_CONTEXT_KEYS,
    DEFAULT_EXCLUDED_RESOURCE_KINDS,
    FORBIDDEN_RESOURCE_KINDS,
    assert_no_forbidden_kind,
    sanitize_request_context,
    sanitize_value,
)
from .errors import DomainError, require
from .models import Project, ResourceRecord
from .repository import InMemoryRepository

ROOT = Path(__file__).resolve().parents[2]
MANDATORY_STATUSES = frozenset({"CONFIRMED", "SELECTED", "ACTIVE", "COMPLETED"})


@dataclass(frozen=True, slots=True)
class ContextPolicy:
    operation: str
    version: str
    memory_roots: tuple[str, ...]
    resource_kinds: tuple[str, ...]
    allowed_statuses: tuple[str, ...]
    evidence_limit: int
    include_user_input: bool
    include_request_context: bool
    allowed_request_context_keys: tuple[str, ...]
    excluded_resource_kinds: tuple[str, ...]
    max_resource_items: int
    include_superseded_history: bool
    allow_document_chunks: bool
    max_document_chunks: int
    max_chunk_characters: int
    require_explicit_chunk_refs: bool


@dataclass(frozen=True, slots=True)
class ContextManifest:
    policy_version: str
    operation: str
    memory_version: int
    included_memory_roots: tuple[str, ...]
    included_resource_refs: tuple[str, ...]
    included_evidence_refs: tuple[str, ...]
    excluded_resource_kinds: tuple[str, ...]
    estimated_tokens: int


@dataclass(frozen=True, slots=True)
class CompiledContext:
    payload: dict[str, Any]
    manifest: ContextManifest


class ContextPolicyRegistry:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path or ROOT / "prompts" / "context-policies.yaml").resolve()
        self.version = "1.0"
        self._policies: dict[str, ContextPolicy] = {}
        self._load()

    def _load(self) -> None:
        try:
            raw = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise DomainError("AI_CONTEXT_POLICY_INVALID", f"Cannot load context policies: {exc}.", 500) from exc
        require(isinstance(raw, dict), "AI_CONTEXT_POLICY_INVALID", "Context policy file must be an object.", 500)
        self.version = str(raw.get("version", "1.0"))
        defaults = dict(raw.get("defaults", {}))
        policies = raw.get("policies", {})
        require(isinstance(policies, dict) and policies, "AI_CONTEXT_POLICY_INVALID", "Context policies are required.", 500)
        for operation, spec in policies.items():
            merged = {**defaults, **dict(spec or {})}
            memory_roots = tuple(str(item) for item in merged.get("memory_roots", []))
            resource_kinds = tuple(str(item).upper() for item in merged.get("resource_kinds", []))
            require(bool(memory_roots), "AI_CONTEXT_POLICY_INVALID", f"{operation} must declare memory_roots.", 500)
            require(bool(resource_kinds), "AI_CONTEXT_POLICY_INVALID", f"{operation} must declare resource_kinds.", 500)
            require(
                "allow_all_memory" not in merged or merged.get("allow_all_memory") is not True,
                "AI_CONTEXT_POLICY_INVALID",
                "allow_all_memory is not permitted.",
                500,
            )
            excluded = tuple(
                str(item).upper()
                for item in merged.get(
                    "excluded_resource_kinds",
                    list(DEFAULT_EXCLUDED_RESOURCE_KINDS),
                )
            )
            excluded = tuple(dict.fromkeys((*excluded, *FORBIDDEN_RESOURCE_KINDS)))
            allow_chunks = bool(merged.get("allow_document_chunks", False))
            if allow_chunks:
                excluded = tuple(item for item in excluded if item != "DOCUMENT_CHUNK")
            self._policies[str(operation).upper()] = ContextPolicy(
                operation=str(operation).upper(),
                version=str(merged.get("version", self.version)),
                memory_roots=memory_roots,
                resource_kinds=resource_kinds,
                allowed_statuses=tuple(str(item).upper() for item in merged.get("allowed_statuses", [])),
                evidence_limit=int(merged.get("evidence_limit", 8)),
                include_user_input=bool(merged.get("include_user_input", False)),
                include_request_context=bool(merged.get("include_request_context", True)),
                allowed_request_context_keys=tuple(
                    str(item) for item in merged.get("allowed_request_context_keys", ALLOWED_REQUEST_CONTEXT_KEYS)
                ),
                excluded_resource_kinds=excluded,
                max_resource_items=int(merged.get("max_resource_items", 20)),
                include_superseded_history=bool(merged.get("include_superseded_history", False)),
                allow_document_chunks=allow_chunks,
                max_document_chunks=int(merged.get("max_document_chunks", 5)),
                max_chunk_characters=int(merged.get("max_chunk_characters", 4000)),
                require_explicit_chunk_refs=bool(merged.get("require_explicit_chunk_refs", True)),
            )

    def get(self, operation: str) -> ContextPolicy:
        policy = self._policies.get(operation.upper())
        if policy is None:
            raise DomainError(
                "AI_CONTEXT_POLICY_NOT_FOUND",
                f"No context policy is registered for {operation.upper()}.",
                500,
            )
        return policy

    def operations(self) -> list[str]:
        return sorted(self._policies)

    def require_coverage(self, operations: list[str]) -> None:
        missing = [item for item in operations if item.upper() not in self._policies]
        if missing:
            raise DomainError(
                "AI_CONTEXT_POLICY_NOT_FOUND",
                f"Missing context policies: {', '.join(sorted(missing))}.",
                500,
            )


def estimate_tokens(value: Any) -> int:
    return max(1, (len(json.dumps(value, separators=(",", ":"), ensure_ascii=False)) + 3) // 4)


class ContextCompiler:
    def __init__(
        self,
        repository: InMemoryRepository,
        registry: ContextPolicyRegistry | None = None,
    ) -> None:
        self.repository = repository
        self.registry = registry or ContextPolicyRegistry()

    def compile(
        self,
        *,
        project: Project,
        operation: str,
        constitution: str,
        policy: str,
        authority_rules: str,
        user_input: str,
        request_context: dict[str, Any],
        output_schema: dict[str, Any],
        max_input_tokens: int,
    ) -> CompiledContext:
        context_policy = self.registry.get(operation)
        safe_request = sanitize_request_context(
            request_context,
            context_policy.allowed_request_context_keys,
        )
        memory_slice = self._normalize_memory_slice(
            {
                root: sanitize_value(project.memory[root])
                for root in context_policy.memory_roots
                if root in project.memory
            }
        )
        selected_ids = {
            str(item)
            for item in (
                *(safe_request.get("selected_ids") or []),
                *(safe_request.get("resource_refs") or []),
            )
            if item
        }
        resources, evidence = self._select_records(project, context_policy, selected_ids)
        payload = self._payload(
            constitution=constitution,
            policy=policy,
            authority_rules=authority_rules,
            memory_slice=memory_slice,
            resources=resources,
            evidence=evidence,
            user_input=user_input if context_policy.include_user_input else "",
            include_user_input=context_policy.include_user_input,
            request_context=safe_request if context_policy.include_request_context else {},
            output_schema=output_schema,
            max_chunk_characters=context_policy.max_chunk_characters,
        )
        resources, evidence, payload = self._enforce_budget(
            payload=payload,
            resources=resources,
            evidence=evidence,
            selected_ids=selected_ids,
            max_input_tokens=max_input_tokens,
            constitution=constitution,
            policy=policy,
            authority_rules=authority_rules,
            memory_slice=memory_slice,
            user_input=user_input if context_policy.include_user_input else "",
            include_user_input=context_policy.include_user_input,
            request_context=safe_request if context_policy.include_request_context else {},
            output_schema=output_schema,
            max_chunk_characters=context_policy.max_chunk_characters,
        )
        versions = self.repository.memory_versions.get(project.id, [])
        memory_version = versions[-1].version if versions else project.version
        tokens = estimate_tokens(payload)
        manifest = ContextManifest(
            policy_version=context_policy.version,
            operation=context_policy.operation,
            memory_version=memory_version,
            included_memory_roots=tuple(memory_slice),
            included_resource_refs=tuple(item.id for item in resources),
            included_evidence_refs=tuple(item.id for item in evidence),
            excluded_resource_kinds=context_policy.excluded_resource_kinds,
            estimated_tokens=tokens,
        )
        return CompiledContext(payload=payload, manifest=manifest)

    def _project_records(self, project: Project) -> list[ResourceRecord]:
        ids = self.repository.project_resources.get(project.id, [])
        return [self.repository.resources[item_id] for item_id in ids if item_id in self.repository.resources]

    def _current_record(self, record_id: str) -> ResourceRecord | None:
        record = self.repository.resources.get(record_id)
        if record is None:
            return None
        seen: set[str] = set()
        while record.superseded_by and record.superseded_by not in seen:
            seen.add(record.id)
            nxt = self.repository.resources.get(record.superseded_by)
            if nxt is None:
                break
            record = nxt
        return record

    def _normalize_memory_slice(self, memory_slice: dict[str, Any]) -> dict[str, Any]:
        def resolve(value: Any) -> Any:
            if isinstance(value, dict):
                record_id = value.get("id")
                if isinstance(record_id, str):
                    current = self._current_record(record_id)
                    if current is not None:
                        value = {
                            **value,
                            "id": current.id,
                            "version": current.version,
                            "status": current.status,
                        }
                return {key: resolve(child) for key, child in value.items()}
            if isinstance(value, list):
                return [resolve(item) for item in value]
            return value

        return {key: resolve(item) for key, item in memory_slice.items()}

    def _select_records(
        self,
        project: Project,
        context_policy: ContextPolicy,
        selected_ids: set[str],
    ) -> tuple[list[ResourceRecord], list[ResourceRecord]]:
        allowed_kinds = set(context_policy.resource_kinds)
        excluded = set(context_policy.excluded_resource_kinds) | set(FORBIDDEN_RESOURCE_KINDS)
        if context_policy.allow_document_chunks:
            excluded.discard("DOCUMENT_CHUNK")
            allowed_kinds.add("DOCUMENT_CHUNK")
        allowed_statuses = set(context_policy.allowed_statuses)
        resources: list[ResourceRecord] = []
        evidence: list[ResourceRecord] = []
        chunks: list[ResourceRecord] = []
        for record in self._project_records(project):
            if record.kind in excluded:
                continue
            if record.kind == "DOCUMENT_CHUNK":
                if not context_policy.allow_document_chunks:
                    continue
                if context_policy.require_explicit_chunk_refs and record.id not in selected_ids:
                    continue
                chunks.append(record)
                continue
            if record.kind not in allowed_kinds:
                continue
            if record.superseded_by and not context_policy.include_superseded_history:
                continue
            if record.status not in allowed_statuses and record.id not in selected_ids:
                continue
            if record.kind == "EVIDENCE":
                evidence.append(record)
            else:
                resources.append(record)
        resources.sort(key=lambda item: (item.created_at, item.id))
        evidence.sort(key=lambda item: (item.created_at, item.id))
        chunks.sort(key=lambda item: (item.created_at, item.id))
        if len(chunks) > context_policy.max_document_chunks:
            selected_chunks = [item for item in chunks if item.id in selected_ids]
            extra = [item for item in chunks if item.id not in selected_ids]
            keep = max(0, context_policy.max_document_chunks - len(selected_chunks))
            chunks = [*selected_chunks, *extra[:keep]]
            chunks.sort(key=lambda item: (item.created_at, item.id))
        resources.extend(chunks)
        if len(resources) > context_policy.max_resource_items:
            mandatory = [item for item in resources if self._mandatory(item, selected_ids)]
            optional = [item for item in resources if not self._mandatory(item, selected_ids)]
            keep = max(0, context_policy.max_resource_items - len(mandatory))
            resources = [*mandatory, *optional[-keep:]]
            resources.sort(key=lambda item: (item.created_at, item.id))
        evidence = evidence[-context_policy.evidence_limit :]
        return resources, evidence

    @staticmethod
    def _mandatory(record: ResourceRecord, selected_ids: set[str]) -> bool:
        return record.id in selected_ids or record.status in MANDATORY_STATUSES

    def _payload(
        self,
        *,
        constitution: str,
        policy: str,
        authority_rules: str,
        memory_slice: dict[str, Any],
        resources: list[ResourceRecord],
        evidence: list[ResourceRecord],
        user_input: str,
        include_user_input: bool,
        request_context: dict[str, Any],
        output_schema: dict[str, Any],
        max_chunk_characters: int,
    ) -> dict[str, Any]:
        payload = {
            "constitution": constitution,
            "operation_policy": policy,
            "authority_rules": authority_rules,
            "confirmed_memory": memory_slice,
            "relevant_resources": [
                sanitize_value(self._public_resource(item, max_chunk_characters)) for item in resources
            ],
            "relevant_evidence": [sanitize_value(item.public()) for item in evidence],
            "request_context": request_context,
            "output_schema": output_schema,
        }
        if include_user_input:
            payload["current_user_input"] = user_input
        return payload

    @staticmethod
    def _public_resource(record: ResourceRecord, max_chunk_characters: int) -> dict[str, Any]:
        payload = record.public()
        if record.kind != "DOCUMENT_CHUNK":
            return payload
        data = payload.get("data")
        if not isinstance(data, dict):
            return payload
        text = data.get("text") or data.get("content") or data.get("chunk")
        if isinstance(text, str) and len(text) > max_chunk_characters:
            payload = {**payload, "data": {**data, "text": text[:max_chunk_characters]}}
        return payload

    def _enforce_budget(
        self,
        *,
        payload: dict[str, Any],
        resources: list[ResourceRecord],
        evidence: list[ResourceRecord],
        selected_ids: set[str],
        max_input_tokens: int,
        **parts: Any,
    ) -> tuple[list[ResourceRecord], list[ResourceRecord], dict[str, Any]]:
        tokens = estimate_tokens(payload)
        if tokens <= max_input_tokens:
            return resources, evidence, payload
        while evidence and estimate_tokens(payload) > max_input_tokens:
            evidence = evidence[1:]
            payload = self._payload(resources=resources, evidence=evidence, **parts)
        optional = [item for item in resources if not self._mandatory(item, selected_ids)]
        while optional and estimate_tokens(payload) > max_input_tokens:
            optional = optional[1:]
            mandatory = [item for item in resources if self._mandatory(item, selected_ids)]
            resources = [*mandatory, *optional]
            resources.sort(key=lambda item: (item.created_at, item.id))
            payload = self._payload(resources=resources, evidence=evidence, **parts)
        if estimate_tokens(payload) > max_input_tokens:
            raise DomainError(
                "AI_INPUT_BUDGET_EXCEEDED",
                "Compiled AI context exceeds the routed input budget after dropping optional items.",
                413,
            )
        return resources, evidence, payload


def assert_kind_allowed(kind: str) -> None:
    assert_no_forbidden_kind(kind)
