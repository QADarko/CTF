from __future__ import annotations


def test_cors_allows_local_web_origin_only(client):
    allowed = client.options(
        "/api/v1/projects",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-session-token",
        },
    )
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:3000"

    denied = client.options(
        "/api/v1/projects",
        headers={
            "Origin": "https://example.invalid",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert "access-control-allow-origin" not in denied.headers


def test_complete_r0_to_r1_lifecycle_exercises_all_human_gates(client, project):
    project_id = project["project"]["id"]
    headers = project["headers"]
    decided: list[int] = []

    def create(kind: str, data: dict, provenance: str = "USER") -> dict:
        response = client.post(
            f"/api/v1/projects/{project_id}/resources/{kind}",
            headers=headers,
            json={"data": data, "provenance": provenance},
        )
        assert response.status_code == 201, response.text
        return response.json()

    def decide(decision: str, payload: dict | None = None) -> dict:
        current = client.get(
            f"/api/v1/projects/{project_id}", headers=headers
        ).json()
        gate = current["active_gate"]
        response = client.post(
            f"/api/v1/projects/{project_id}/gates/{gate['id']}/decision",
            headers=headers,
            json={
                "decision": decision,
                "payload": payload or {},
                "expected_version": current["version"],
            },
        )
        assert response.status_code == 200, response.text
        result = response.json()
        decided.append(result["gate"]["number"])
        assert result["project_version"] > current["version"]
        return result

    reality = create("REALITY", {"items": [{"text": "The current service is fragmented."}]})
    decide("CONFIRM")
    create("QUESTION", {"text": "How might the service preserve continuity?"})
    decide("CONFIRM")
    create("PERCEPTION", {"from": "Channel problem", "to": "Continuity problem"})
    decide("CONFIRM_SHIFT")
    decide("ACKNOWLEDGE_UNCERTAINTY")

    opportunity = create("OPPORTUNITY", {"name": "Continuity", "derived_from": [reality["id"]]})
    decide("SELECT", {"selected_ids": [opportunity["id"]]})
    spark = create("SPARK", {"text": "What if the case travelled?", "derived_from": [opportunity["id"]]})
    decide("SELECT", {"selected_ids": [spark["id"]]})
    idea = create(
        "IDEA",
        {"name": "Portable case", "what": "A case that continues across channels", "derived_from": [spark["id"]]},
    )
    decide("SELECT", {"selected_ids": [idea["id"]]})
    create("ASSUMPTION", {"statement": "Consent can remain explicit."})
    decide("CONFIRM")
    create("FAILURE_MODE", {"title": "Consent is unclear."})
    decide("CONFIRM")
    create(
        "VALUE_BOUNDARY",
        {"name": "Human control", "priority": "NON_NEGOTIABLE", "test_result": "ALIGNED"},
    )
    decide("CONFIRM")

    create(
        "DECISION_BRIEF",
        {"idea_id": idea["id"], "idea_version": idea["version"]},
        "SYSTEM",
    )
    create("RECOMMENDATION", {"recommendation": "CONDITIONAL_GO"}, "CTF")
    gate11 = decide(
        "CONDITIONAL_GO",
        {
            "idea_id": idea["id"],
            "idea_version": idea["version"],
            "rationale": "Proceed with explicit consent safeguards.",
            "conditions": ["Independent consent review"],
        },
    )
    decision_id = gate11["decision_record"]["id"]
    create("COMMITMENT", {"decision_id": decision_id, "statement": "Run a safe pilot."})
    decide("CONFIRM")
    create("ROADMAP", {"name": "Pilot roadmap", "outcomes": ["Safe continuity"]})
    decide("CONFIRM")

    trigger = client.post(
        f"/api/v1/projects/{project_id}/execution-events",
        headers=headers,
        json={
            "data": {
                "type": "BLOCKING_LEGAL_CHANGE",
                "materiality": "LOCAL",
                "statement": "Consent guidance changed.",
            }
        },
    )
    assert trigger.status_code == 201, trigger.text
    decide("CONFIRM_REDECISION")

    gate11_repeat = decide(
        "CONDITIONAL_GO",
        {
            "idea_id": idea["id"],
            "idea_version": idea["version"],
            "rationale": "The revised safeguard addresses the legal change.",
            "conditions": ["Use the revised consent control"],
        },
    )
    create(
        "COMMITMENT",
        {"decision_id": gate11_repeat["decision_record"]["id"], "statement": "Run revised pilot."},
    )
    decide("CONFIRM")
    create("ROADMAP", {"name": "Revised pilot roadmap"})
    decide("CONFIRM")

    create("COMMITMENT_REVIEW", {"status": "READY", "finding": "Commitment remains viable."})
    decide("REAFFIRM")

    action = create(
        "ACTION",
        {
            "title": "Run the pilot",
            "why": "Produces evidence of service continuity.",
            "owner_id": "usr_1",
            "status": "READY",
        },
    )
    evidence = create(
        "EXECUTION_EVIDENCE",
        {"action_id": action["id"], "statement": "The pilot operated successfully."},
    )
    create(
        "CREATION_RECORD",
        {"title": "Portable case pilot", "type": "PROTOTYPE", "evidence_refs": [evidence["id"]]},
    )

    stakeholder = create("STAKEHOLDER", {"name": "Service users", "type": "BENEFICIARY"})
    decide("CONFIRM")
    create(
        "VALUE_HYPOTHESIS",
        {"stakeholder_id": stakeholder["id"], "statement": "Users complete service faster."},
    )
    value_evidence = create("EVIDENCE", {"statement": "Completion time fell in the pilot."})
    create(
        "REALIZED_VALUE",
        {"stakeholder_id": stakeholder["id"], "evidence_refs": [value_evidence["id"]]},
    )
    decide("CONFIRM")

    snapshot = create(
        "REALITY_SNAPSHOT",
        {"label": "R1", "dimensions": [{"dimension": "continuity", "value": "improved"}]},
    )
    decide("CONFIRM", {"snapshot_id": snapshot["id"]})
    cycle = create("CREATION_CYCLE", {"label": "R0-to-R1", "status": "READY_TO_CLOSE"})
    result = decide("CLOSE", {"cycle_id": cycle["id"]})

    assert set(decided) == set(range(1, 20))
    assert result["project_stage"] == "COMPLETED"
    assert result["next_gate"]["status"] == "DECIDED"
