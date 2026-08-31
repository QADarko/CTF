from __future__ import annotations


def _advance_to_evidence(client, project):
    project_id = project["project"]["id"]
    headers = project["headers"]
    for kind, decision in [
        ("REALITY", "CONFIRM"),
        ("QUESTION", "CONFIRM"),
        ("PERCEPTION", "CONFIRM_SHIFT"),
    ]:
        created = client.post(
            f"/api/v1/projects/{project_id}/resources/{kind}",
            headers=headers,
            json={"data": {"text": kind}},
        )
        assert created.status_code == 201
        state = client.get(f"/api/v1/projects/{project_id}", headers=headers).json()
        decided = client.post(
            f"/api/v1/projects/{project_id}/gates/{state['active_gate']['id']}/decision",
            headers=headers,
            json={"decision": decision},
        )
        assert decided.status_code == 200


def test_attachment_metadata_security_and_no_false_analysis(client, project):
    project_id = project["project"]["id"]
    headers = project["headers"]
    upload = client.post(
        f"/api/v1/projects/{project_id}/attachments?document_type=PROJECT_CONCEPT",
        headers=headers,
        files={"file": ("concept.pdf", b"%PDF-1.4\nsafe test", "application/pdf")},
    )
    assert upload.status_code == 201
    attachment = upload.json()
    assert attachment["data"]["semantically_analyzed"] is False
    assert attachment["data"]["processing_status"] == "READY_FOR_LATER_PROCESSING"
    assert "checksum_sha256" in attachment["data"]

    other = client.post("/api/v1/sessions/anonymous", json={"tenant_id": "other"}).json()
    denied = client.get(
        f"/api/v1/projects/{project_id}/attachments/{attachment['id']}",
        headers={"X-Session-Token": other["token"]},
    )
    assert denied.status_code == 403


def test_evidence_opportunity_genealogy_and_document_job(client, project):
    _advance_to_evidence(client, project)
    project_id = project["project"]["id"]
    headers = project["headers"]

    source = client.post(
        f"/api/v1/projects/{project_id}/resources/EVIDENCE_SOURCE",
        headers=headers,
        json={"data": {"type": "USER_STATEMENT", "title": "Interview"}},
    ).json()
    evidence = client.post(
        f"/api/v1/projects/{project_id}/resources/EVIDENCE",
        headers=headers,
        json={
            "data": {
                "source_id": source["id"],
                "statement": "Three customers cited slow onboarding.",
                "location": {"interview": 1},
            }
        },
    ).json()
    state = client.get(f"/api/v1/projects/{project_id}", headers=headers).json()
    client.post(
        f"/api/v1/projects/{project_id}/gates/{state['active_gate']['id']}/decision",
        headers=headers,
        json={"decision": "CONFIRM"},
    )
    opportunity = client.post(
        f"/api/v1/projects/{project_id}/resources/OPPORTUNITY",
        headers=headers,
        json={
            "data": {
                "title": "Reduce onboarding friction",
                "derived_from": [evidence["id"]],
            }
        },
    )
    assert opportunity.status_code == 201
    trace = client.get(
        f"/api/v1/projects/{project_id}/trace/OPPORTUNITY/{opportunity.json()['id']}",
        headers=headers,
    ).json()
    assert any(link["from_id"] == evidence["id"] for link in trace["links"])
    assert trace["source"] == "PERSISTED_GENEALOGY"

    upload = client.post(
        f"/api/v1/projects/{project_id}/attachments",
        headers=headers,
        files={"file": ("data.pdf", b"%PDF-1.4\ncontent", "application/pdf")},
    ).json()
    job = client.post(
        f"/api/v1/projects/{project_id}/evidence/analyze-document",
        headers=headers,
        json={"data": {"attachment_id": upload["id"]}},
    )
    assert job.status_code == 202
    assert job.json()["status"] == "QUEUED"
