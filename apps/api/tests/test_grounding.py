from __future__ import annotations

import json

import pytest

from packages.ctf_domain.context_policy import CompiledContext, ContextManifest
from packages.ctf_domain.errors import DomainError
from packages.ctf_domain.grounding import GroundingValidator


def _compiled(evidence=("ev_1",), resources=("res_1",), memory=("reality",), version=3):
    manifest = ContextManifest(
        policy_version="1.0",
        operation="ATTRIBUTION",
        memory_version=version,
        included_memory_roots=memory,
        included_resource_refs=resources,
        included_evidence_refs=evidence,
        excluded_resource_kinds=("REALITY_EVENT",),
        estimated_tokens=100,
    )
    return CompiledContext(payload={"confirmed_memory": {"reality": {}}}, manifest=manifest)


def _output(**grounding):
    return {
        "status": "PROPOSED",
        "items": [],
        "summary": "draft",
        "grounding": {
            "evidence_refs": ["ev_1"],
            "memory_refs": ["reality"],
            "assumptions": [],
            "unknowns": [],
            "limitations": [],
            "confidence_class": "MEDIUM",
            **grounding,
        },
    }


def test_grounding_accepts_context_evidence():
    GroundingValidator().validate(
        output=_output(),
        compiled_context=_compiled(),
        operation="ATTRIBUTION",
    )


def test_grounding_rejects_nonexistent_evidence():
    with pytest.raises(DomainError) as caught:
        GroundingValidator().validate(
            output=_output(evidence_refs=["missing"]),
            compiled_context=_compiled(),
            operation="ATTRIBUTION",
        )
    assert caught.value.code == "AI_GROUNDING_INVALID_REFERENCE"


def test_grounding_rejects_other_project_evidence():
    with pytest.raises(DomainError) as caught:
        GroundingValidator().validate(
            output=_output(evidence_refs=["ev_other_project"]),
            compiled_context=_compiled(),
            operation="RED_TEAM",
        )
    assert caught.value.code == "AI_GROUNDING_INVALID_REFERENCE"


def test_grounding_rejects_resource_not_present_in_context():
    with pytest.raises(DomainError) as caught:
        GroundingValidator().validate(
            output=_output(memory_refs=["ideas"]),
            compiled_context=_compiled(),
            operation="ATTRIBUTION",
        )
    assert caught.value.code == "AI_GROUNDING_CONTEXT_MISMATCH"


def test_critical_output_requires_grounding():
    with pytest.raises(DomainError) as caught:
        GroundingValidator().validate(
            output={"status": "PROPOSED", "items": [], "summary": "none"},
            compiled_context=_compiled(),
            operation="R1_GENERATION",
        )
    assert caught.value.code == "AI_GROUNDING_REQUIRED"


def test_insufficient_evidence_is_valid_grounding_state():
    GroundingValidator().validate(
        output=_output(evidence_refs=[], confidence_class="INSUFFICIENT_EVIDENCE"),
        compiled_context=_compiled(evidence=()),
        operation="TRANSFORMATION",
    )


def test_grounding_preserves_memory_version():
    compiled = _compiled(version=14)
    GroundingValidator().validate(output=_output(), compiled_context=compiled, operation="ATTRIBUTION")
    assert compiled.manifest.memory_version == 14
    assert json.dumps(compiled.payload)


def test_non_critical_output_may_omit_grounding():
    GroundingValidator().validate(
        output={"status": "PROPOSED", "items": [], "summary": "ok"},
        compiled_context=_compiled(),
        operation="QUESTION_REFRAME",
    )
