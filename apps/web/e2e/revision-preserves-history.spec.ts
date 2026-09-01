import { expect, test } from "@playwright/test";
import { apiBase, apiGet, liveAuth, runFullCreationCycle, sessionHeaders, verifyPostCycleIntegrity } from "./helpers";

test("R0 remains unchanged after R1 and genealogy stays intact", async ({ page, request }) => {
  test.setTimeout(180_000);
  const { projectId, token } = await runFullCreationCycle(page);
  const realities = await apiGet(request, `/projects/${projectId}/resources/REALITY`, token);
  const r0 = realities[0];
  expect(r0?.id).toBeTruthy();
  const r0Text = String(r0.data?.text ?? JSON.stringify(r0.data));

  await verifyPostCycleIntegrity(request, projectId, token, { id: r0.id, text: r0Text.includes("Services") ? "Services" : r0Text.slice(0, 12) });

  const snapshots = await apiGet(request, `/projects/${projectId}/resources/REALITY_SNAPSHOT`, token);
  expect(snapshots[0].id).not.toBe(r0.id);
  const preserved = await apiGet(request, `/projects/${projectId}/resources/REALITY/${r0.id}`, token);
  expect(preserved.id).toBe(r0.id);
  expect(JSON.stringify(preserved.data)).toBe(JSON.stringify(r0.data));

  await page.getByRole("button", { name: /Reality/i }).click();
  await expect(page.locator("text=Services").first()).toBeVisible();

  const superseded = await request.post(`${apiBase}/projects/${projectId}/resources/REALITY/${r0.id}/supersede`, {
    headers: sessionHeaders(token),
    data: { data: { text: "R0-next revision." } },
  });
  expect(superseded.status()).toBe(201);
  const after = await apiGet(request, `/projects/${projectId}/resources/REALITY/${r0.id}`, token);
  expect(JSON.stringify(after.data)).toBe(JSON.stringify(r0.data));
  const genealogy = await apiGet(request, `/projects/${projectId}/creation-genealogy`, token);
  expect(genealogy.links.some((link: { relation?: string }) => link.relation === "SUPERSEDES")).toBeTruthy();
  expect(genealogy.links.some((link: { relation?: string }) => link.relation === "DERIVES" || link.relation === "SUPERSEDES")).toBeTruthy();
  await liveAuth(page);
});
