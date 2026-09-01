import { expect, test } from "@playwright/test";
import { apiBase, completeInterview, confirmGate, liveAuth, sessionHeaders, startLiveCycle } from "./helpers";

test("AI cannot close gates or confirm human-owned records", async ({ page, request }) => {
  test.setTimeout(90_000);
  await startLiveCycle(page);
  await expect(page.getByTestId("human-gate")).toBeVisible();
  await expect(page.getByTestId("confirm-gate")).toBeVisible();
  const { projectId, token } = await liveAuth(page);

  const project = await request.get(`${apiBase}/projects/${projectId}`, { headers: sessionHeaders(token) });
  const current = await project.json();
  const gateId = current.active_gate.id;

  const aiGate = await request.post(`${apiBase}/projects/${projectId}/gates/${gateId}/decision`, {
    headers: sessionHeaders(token),
    data: { decision: "CONFIRM", payload: {}, actor_type: "AI", expected_version: current.version },
  });
  expect(aiGate.status()).toBe(403);
  expect((await aiGate.json()).error.code).toBe("HUMAN_AUTHORITY_REQUIRED");

  const stillOpen = await request.get(`${apiBase}/projects/${projectId}`, { headers: sessionHeaders(token) });
  expect((await stillOpen.json()).active_gate.status).toBe("PENDING");

  const value = await request.post(`${apiBase}/projects/${projectId}/resources/VALUE_BOUNDARY`, {
    headers: sessionHeaders(token),
    data: { data: { name: "Human control", "priority": "NON_NEGOTIABLE" }, provenance: "USER" },
  });
  const valueConfirm = await request.post(
    `${apiBase}/projects/${projectId}/resources/VALUE_BOUNDARY/${value.ok() ? (await value.json()).id : "vb_missing"}/confirm`,
    { headers: sessionHeaders(token), data: { actor_type: "AI" } },
  );
  expect([403, 404, 422]).toContain(valueConfirm.status());

  const commitment = await request.post(`${apiBase}/projects/${projectId}/resources/COMMITMENT`, {
    headers: sessionHeaders(token),
    data: { data: { statement: "Pilot" }, provenance: "USER" },
  });
  const commitmentConfirm = await request.post(
    `${apiBase}/projects/${projectId}/resources/COMMITMENT/${commitment.ok() ? (await commitment.json()).id : "cmt_missing"}/confirm`,
    { headers: sessionHeaders(token), data: { actor_type: "AI" } },
  );
  expect([403, 404, 422]).toContain(commitmentConfirm.status());

  const decision = await request.post(`${apiBase}/projects/${projectId}/resources/HUMAN_DECISION`, {
    headers: sessionHeaders(token),
    data: { data: { decision: "GO" }, provenance: "CTF" },
  });
  expect([400, 403, 409, 422]).toContain(decision.status());

  const draft = page.getByTestId("draft-with-ai");
  if (await draft.isEnabled()) {
    await draft.click();
    await expect(page.getByTestId("ai-proposal-badge")).toBeVisible({ timeout: 30_000 });
  }
  await expect(page.getByTestId("confirm-gate")).toBeVisible();
  await expect(page.getByTestId("human-gate")).toContainText("AI cannot do it");
  await completeInterview(page, ["Observed fragmentation.", "Affected users.", "Time.", "Unknown consent."]);
  await confirmGate(page);
});
