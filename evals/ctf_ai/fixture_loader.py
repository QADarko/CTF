"""Load evaluation fixtures into real CTF repository state (CTF-005B-03)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from packages.ctf_domain.models import Project
from packages.ctf_domain.repository import InMemoryRepository

ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True, slots=True)
class LoadedFixture:
    project: Project
    version: str
    resources: dict[str, str]
    known_fields: tuple[str, ...]
    unknown_fields: tuple[str, ...]
    unsupported_fields: tuple[str, ...]


class EvaluationFixtureLoader:
    def load(self, *, fixture_path: str | Path, repository: InMemoryRepository) -> LoadedFixture:
        path = Path(fixture_path)
        if not path.is_file():
            path = ROOT / fixture_path
        payload = json.loads(path.read_text(encoding="utf-8"))
        entry = payload.get("entry") or {}
        session = repository.create_session(str(entry.get("tenant_id") or "eval"))
        project = repository.create_project(
            session,
            str(entry.get("family") or "CREATION"),
            str(entry.get("type") or "PROBLEM"),
            str(entry.get("input") or "evaluation fixture"),
            {"channel": "eval"},
        )
        live = repository.projects[project.id]
        created: dict[str, str] = {}
        for index, spec in enumerate(payload.get("resources") or []):
            kind = str(spec["kind"]).upper()
            record = repository.create_resource(
                live,
                kind,
                dict(spec.get("data") or {}),
                status=str(spec.get("status") or "PROPOSED"),
                provenance=str(spec.get("provenance") or "USER"),
            )
            created[f"{kind}:{index}"] = record.id
            created[kind] = record.id
        memory = payload.get("memory")
        if isinstance(memory, dict):
            live.memory.update(memory)
            repository.snapshot_memory(live, [{"op": "UPDATE", "path": "reality", "value": memory}])
        return LoadedFixture(
            project=live,
            version=str(payload.get("version") or "1.0"),
            resources=created,
            known_fields=tuple(str(item) for item in payload.get("known_fields") or ()),
            unknown_fields=tuple(str(item) for item in payload.get("unknown_fields") or ()),
            unsupported_fields=tuple(str(item) for item in payload.get("unsupported_fields") or ()),
        )
