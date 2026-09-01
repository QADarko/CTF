import { expect, test } from "@playwright/test";
import { apiBase, completeInterview, confirmGate, liveAuth, sessionHeaders, startLiveCycle } from "./helpers";

test("confirmed resource is immutable and only changes through supersession", async ({ page, request }) => {
  test.setTimeout(90_000);
  await startLiveCycle(page);
  await completeInterview(page, ["Observed fragmentation.", "Affected users.", "Time.", "Unknown consent."]);
  await confirmGate(page);
  const card = page.getByTestId("resource-card").first();
  await expect(card).toBeVisible();
  await expect(card).toHaveAttribute("data-status", /CONFIRMED|SELECTED|ACTIVE/);

  const { projectId, token } = await liveAuth(page);
  const listed = await request.get(`${apiBase}/projects/${projectId}/resources/REALITY`, {
    headers: sessionHeaders(token),
  });
  expect(listed.ok()).toBeTruthy();
  const realities = await listed.json();
  const original = realities.find((item: { status?: string }) => item.status === "CONFIRMED") ?? realities[0];
  expect(original?.id).toBeTruthy();
  const originalText = JSON.stringify(original.data);

  const denied = await request.patch(`${apiBase}/projects/${projectId}/resources/REALITY/${original.id}`, {
    headers: sessionHeaders(token),
    data: { data: { text: "tampered in place" } },
  });
  expect(denied.status()).toBe(409);
  expect((await denied.json()).error.code).toBe("IMMUTABLE_RECORD");

  const replacement = await request.post(`${apiBase}/projects/${projectId}/resources/REALITY/${original.id}/supersede`, {
    headers: sessionHeaders(token),
    data: { data: { text: "Superseding reality record." } },
  });
  expect(replacement.status()).toBe(201);
  const created = await replacement.json();
  expect(created.supersedes_id).toBe(original.id);
  expect(created.id).not.toBe(original.id);

  const preserved = await request.get(`${apiBase}/projects/${projectId}/resources/REALITY/${original.id}`, {
    headers: sessionHeaders(token),
  });
  expect(preserved.ok()).toBeTruthy();
  const body = await preserved.json();
  expect(body.id).toBe(original.id);
  expect(JSON.stringify(body.data)).toBe(originalText);

  const genealogy = await request.get(`${apiBase}/projects/${projectId}/creation-genealogy`, {
    headers: sessionHeaders(token),
  });
  const graph = await genealogy.json();
  expect(
    graph.links.some(
      (link: { from_id?: string; to_id?: string; relation?: string }) =>
        link.from_id === original.id && link.to_id === created.id && link.relation === "SUPERSEDES",
    ),
  ).toBeTruthy();
});
