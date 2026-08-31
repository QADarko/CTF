from __future__ import annotations

import pytest

from packages.ctf_domain.errors import DomainError
from packages.ctf_domain.grounding import GroundingIndex
from packages.ctf_domain.non_fabrication import NonFabricationGuard

INDEX = GroundingIndex(evidence_ids=frozenset({"ev_1"}), resource_ids=frozenset({"base_1"}), memory_refs=frozenset({"value"}))


def _validate(output):
    NonFabricationGuard().validate(operation="REALIZED_VALUE", output=output, grounding_index=INDEX)


def test_unknown_budget_is_allowed():
    _validate(
        {
            "status": "PROPOSED",
            "items": [{"budget": {"value": None, "knowledge_state": "UNKNOWN", "evidence_refs": []}}],
        }
    )


def test_unsupported_budget_value_rejected():
    with pytest.raises(DomainError) as caught:
        _validate({"status": "PROPOSED", "items": [{"budget": "€2.4 billion"}]})
    assert caught.value.code == "AI_UNGROUNDED_ASSERTION"


def test_unknown_market_size_is_allowed():
    _validate(
        {
            "status": "PROPOSED",
            "items": [{"market_size": {"value": None, "knowledge_state": "NOT_PROVIDED", "evidence_refs": []}}],
        }
    )


def test_unreferenced_baseline_rejected():
    with pytest.raises(DomainError) as caught:
        _validate(
            {
                "status": "PROPOSED",
                "items": [
                    {
                        "baseline": {
                            "value": 12,
                            "knowledge_state": "KNOWN",
                            "evidence_refs": ["missing"],
                        }
                    }
                ],
            }
        )
    assert caught.value.code == "AI_UNGROUNDED_ASSERTION"


def test_unreferenced_trl_rejected():
    with pytest.raises(DomainError) as caught:
        _validate({"status": "PROPOSED", "items": [{"trl": 7}]})
    assert caught.value.code == "AI_UNGROUNDED_ASSERTION"


def test_causal_claim_without_basis_rejected():
    with pytest.raises(DomainError) as caught:
        _validate(
            {
                "status": "PROPOSED",
                "items": [
                    {
                        "causal_attribution": {
                            "value": "the idea caused the lift",
                            "knowledge_state": "KNOWN",
                            "evidence_refs": [],
                        }
                    }
                ],
            }
        )
    assert caught.value.code == "AI_UNGROUNDED_ASSERTION"


def test_estimate_requires_estimate_label():
    with pytest.raises(DomainError) as caught:
        _validate({"status": "PROPOSED", "items": [{"market_size": "€2.4 billion"}]})
    assert caught.value.code == "AI_UNGROUNDED_ASSERTION"
    _validate(
        {
            "status": "PROPOSED",
            "items": [
                {
                    "market_size": {
                        "value": "€2.4 billion",
                        "knowledge_state": "ESTIMATED",
                        "evidence_refs": [],
                    }
                }
            ],
        }
    )


def test_measured_value_requires_evidence():
    with pytest.raises(DomainError) as caught:
        _validate(
            {
                "status": "PROPOSED",
                "items": [
                    {
                        "measured_value": {
                            "value": 18,
                            "knowledge_state": "ASSUMED",
                            "evidence_refs": [],
                        }
                    }
                ],
            }
        )
    assert caught.value.code == "AI_UNGROUNDED_ASSERTION"
    _validate(
        {
            "status": "PROPOSED",
            "items": [
                {
                    "measured_value": {
                        "value": 18,
                        "knowledge_state": "SUPPORTED",
                        "evidence_refs": ["ev_1"],
                    }
                }
            ],
        }
    )
