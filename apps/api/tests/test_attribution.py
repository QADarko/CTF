from __future__ import annotations

import pytest

from packages.ctf_domain.attribution import (
    AttributionPolicy,
    AttributionStrength,
    reduce_for_unknown_counterfactual,
)
from packages.ctf_domain.errors import DomainError
from packages.ctf_domain.repository import InMemoryRepository


def _project():
    repo = InMemoryRepository()
    session = repo.create_session()
    project = repo.create_project(session, "CREATION", "PROBLEM", "x", {})
    project.stage = "TRANSFORMATION"
    return repo, project


def test_no_baseline_cannot_support_strong_attribution():
    repo, project = _project()
    with pytest.raises(DomainError):
        AttributionPolicy().validate(
            project=project,
            repo=repo,
            attribution={"strength": "SUPPORTED_ATTRIBUTION", "observation_refs": ["o"], "evidence_refs": ["e"], "intervention_refs": ["i"], "counterfactual_refs": ["c"], "alternative_explanations": ["other"]},
        )


def test_correlation_does_not_equal_causation():
    repo, project = _project()
    with pytest.raises(DomainError):
        AttributionPolicy().validate(
            project=project,
            repo=repo,
            attribution={
                "strength": "SUPPORTED_ATTRIBUTION",
                "correlation_only": True,
                "baseline_refs": ["b"],
                "observation_refs": ["o"],
                "evidence_refs": ["e"],
                "intervention_refs": ["i"],
                "counterfactual_refs": ["c"],
                "alternative_explanations": ["other"],
            },
        )


def test_supported_attribution_requires_counterfactual():
    repo, project = _project()
    with pytest.raises(DomainError):
        AttributionPolicy().validate(
            project=project,
            repo=repo,
            attribution={
                "strength": "SUPPORTED_ATTRIBUTION",
                "baseline_refs": ["b"],
                "observation_refs": ["o"],
                "evidence_refs": ["e"],
                "intervention_refs": ["i"],
                "alternative_explanations": ["other"],
            },
        )


def test_supported_attribution_requires_evidence():
    repo, project = _project()
    with pytest.raises(DomainError):
        AttributionPolicy().validate(
            project=project,
            repo=repo,
            attribution={
                "strength": "SUPPORTED_ATTRIBUTION",
                "baseline_refs": ["b"],
                "observation_refs": ["o"],
                "intervention_refs": ["i"],
                "counterfactual_refs": ["c"],
                "alternative_explanations": ["other"],
            },
        )


def test_unknown_counterfactual_reduces_strength():
    assert reduce_for_unknown_counterfactual("SUPPORTED_ATTRIBUTION") == "PLAUSIBLE_CONTRIBUTION"


def test_valid_attribution_can_be_supported():
    repo, project = _project()
    refs = {}
    for kind in ("BASELINE", "OBSERVATION", "EVIDENCE", "ACTION", "COUNTERFACTUAL"):
        refs[kind] = repo.create_resource(project, kind, {"statement": kind}, status="CONFIRMED").id
    AttributionPolicy().validate(
        project=project,
        repo=repo,
        attribution={
            "strength": AttributionStrength.SUPPORTED_ATTRIBUTION,
            "baseline_refs": [refs["BASELINE"]],
            "observation_refs": [refs["OBSERVATION"]],
            "evidence_refs": [refs["EVIDENCE"]],
            "intervention_refs": [refs["ACTION"]],
            "counterfactual_refs": [refs["COUNTERFACTUAL"]],
            "alternative_explanations": ["seasonality"],
            "limitations": ["small n"],
        },
    )
