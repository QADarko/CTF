from __future__ import annotations

import json
from pathlib import Path

from apps.api.app.horizontal import ai_execution
from packages.ctf_domain.ai_runtime import FakeProvider


def valid_output(**item):
    return json.dumps(
        {
            "status": "PROPOSED",
            "items": [item],
            "summary": "e2e",
            "grounding": {
                "evidence_refs": [],
                "memory_refs": [],
                "assumptions": [],
                "unknowns": [],
                "limitations": [],
                "confidence_class": "INSUFFICIENT_EVIDENCE",
            },
        }
    )


def test_e2e_r0_to_r1_uses_fake_ai_and_preserves_integrity(client, project):
    assert (Path(__file__).parent / "fixtures" / "full_creation_cycle.json").is_file()
    project_id = project["project"]["id"]
    headers = project["headers"]
    previous = ai_execution.provider
    ai_execution.provider = FakeProvider([valid_output(text="proposal")] * 20)

    def create(kind: str, data: dict, provenance: str = "USER") -> dict:
        response = client.post(
            f"/api/v1/projects/{project_id}/resources/{kind}",
            headers=headers,
            json={"data": data, "provenance": provenance},
        )
        assert response.status_code == 201, response.text
        return response.json()

    def decide(decision: str, payload: dict | None = None) -> dict:
        current = client.get(f"/api/v1/projects/{project_id}", headers=headers).json()
        gate = current["active_gate"]
        response = client.post(
            f"/api/v1/projects/{project_id}/gates/{gate['id']}/decision",
            headers=headers,
            json={"decision": decision, "payload": payload or {}, "expected_version": current["version"]},
        )
        assert response.status_code == 200, response.text
        return response.json()

    try:
        r0 = create("REALITY", {"items": [{"text": "Fragmented service"}]})
        ai = client.post(
            f"/api/v1/projects/{project_id}/ai/execute",
            headers=headers,
            json={"operation": "QUESTION_REFRAME", "user_input": "reframe the question"},
        )
        assert ai.status_code == 200
        assert ai.json()["output"]["status"] == "PROPOSED"
        decide("CONFIRM")
        create("QUESTION", {"text": "How might continuity be preserved?"})
        decide("CONFIRM")
        create("PERCEPTION", {"from": "channel", "to": "continuity"})
        decide("CONFIRM_SHIFT")
        decide("ACKNOWLEDGE_UNCERTAINTY")
        opportunity = create("OPPORTUNITY", {"name": "Continuity", "derived_from": [r0["id"]]})
        decide("SELECT", {"selected_ids": [opportunity["id"]]})
        spark = create("SPARK", {"text": "portable case", "derived_from": [opportunity["id"]]})
        decide("SELECT", {"selected_ids": [spark["id"]]})
        idea = create("IDEA", {"name": "Portable case", "what": "continues across channels", "derived_from": [spark["id"]]})
        decide("SELECT", {"selected_ids": [idea["id"]]})
        create("ASSUMPTION", {"statement": "Consent stays explicit."})
        decide("CONFIRM")
        create("FAILURE_MODE", {"title": "Consent unclear"})
        decide("CONFIRM")
        create("VALUE_BOUNDARY", {"name": "Human control", "priority": "NON_NEGOTIABLE", "test_result": "ALIGNED"})
        decide("CONFIRM")
        create("DECISION_BRIEF", {"idea_id": idea["id"], "idea_version": idea["version"]}, "SYSTEM")
        create("RECOMMENDATION", {"recommendation": "CONDITIONAL_GO"}, "CTF")
        gate11 = decide(
            "CONDITIONAL_GO",
            {
                "idea_id": idea["id"],
                "idea_version": idea["version"],
                "rationale": "Proceed with safeguards.",
                "conditions": ["Independent review"],
            },
        )
        create("COMMITMENT", {"decision_id": gate11["decision_record"]["id"], "statement": "Pilot"})
        decide("CONFIRM")
        create("ROADMAP", {"name": "Pilot roadmap", "outcomes": ["Safe continuity"]})
        decide("CONFIRM")
        client.post(
            f"/api/v1/projects/{project_id}/execution-events",
            headers=headers,
            json={"data": {"type": "BLOCKING_LEGAL_CHANGE", "statement": "guidance changed"}},
        )
        decide("CONFIRM_REDECISION")
        gate11b = decide(
            "CONDITIONAL_GO",
            {
                "idea_id": idea["id"],
                "idea_version": idea["version"],
                "rationale": "Revised safeguard.",
                "conditions": ["Use revised control"],
            },
        )
        create("COMMITMENT", {"decision_id": gate11b["decision_record"]["id"], "statement": "Revised pilot"})
        decide("CONFIRM")
        create("ROADMAP", {"name": "Revised roadmap"})
        decide("CONFIRM")
        create("COMMITMENT_REVIEW", {"status": "READY", "finding": "viable"})
        decide("REAFFIRM")
        action = create("ACTION", {"title": "Run", "why": "evidence", "owner_id": "usr_1", "status": "READY"})
        evidence = create("EXECUTION_EVIDENCE", {"action_id": action["id"], "statement": "worked"})
        create("CREATION_RECORD", {"title": "pilot", "type": "PROTOTYPE", "evidence_refs": [evidence["id"]]})
        stakeholder = create("STAKEHOLDER", {"name": "Users", "type": "BENEFICIARY"})
        decide("CONFIRM")
        create("VALUE_HYPOTHESIS", {"stakeholder_id": stakeholder["id"], "statement": "faster"})
        value_evidence = create("EVIDENCE", {"statement": "time fell"})
        create("REALIZED_VALUE", {"stakeholder_id": stakeholder["id"], "evidence_refs": [value_evidence["id"]]})
        decide("CONFIRM")
        snapshot = create("REALITY_SNAPSHOT", {"label": "R1", "dimensions": [{"dimension": "continuity", "value": "improved"}]})
        decide("CONFIRM", {"snapshot_id": snapshot["id"]})
        cycle = create("CREATION_CYCLE", {"label": "R0-to-R1", "status": "READY_TO_CLOSE"})
        result = decide("CLOSE", {"cycle_id": cycle["id"]})
    finally:
        ai_execution.provider = previous

    assert result["project_stage"] == "COMPLETED"
    assert result["next_gate"]["status"] == "DECIDED"
    current = client.get(f"/api/v1/projects/{project_id}", headers=headers).json()
    assert current["stage"] == "COMPLETED"
    realities = client.get(f"/api/v1/projects/{project_id}/resources/REALITY", headers=headers).json()
    snapshots = client.get(f"/api/v1/projects/{project_id}/resources/REALITY_SNAPSHOT", headers=headers).json()
    assert realities
    assert snapshots
    assert realities[0]["id"] != snapshots[0]["id"]
    runs = client.get(f"/api/v1/projects/{project_id}/ai/runs", headers=headers).json()
    assert runs
    assert all(run.get("outcome") in {"SUCCEEDED", "FAILED"} for run in runs)
    assert all(run.get("context_policy_version") for run in runs)
    assert all(run.get("consequentiality") for run in runs)
    costs = client.get(f"/api/v1/projects/{project_id}/ai-cost-ledger", headers=headers).json()
    assert costs["runs"] >= 1
