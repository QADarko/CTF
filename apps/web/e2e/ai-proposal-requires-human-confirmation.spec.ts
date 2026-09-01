import { expect, test } from "@playwright/test";
import { confirmGate, liveAuth, startLiveCycle } from "./helpers";

test("AI proposal is mandatory, marked, and cannot auto-confirm", async ({ page, request }) => {
  test.setTimeout(90_000);
  await startLiveCycle(page);
  const draft = page.getByTestId("draft-with-ai");
  await expect(draft).toBeEnabled({ timeout: 30_000 });
  await draft.click();
  await expect(page.getByTestId("ai-proposal-badge")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("human-gate")).toBeVisible();
  await expect(page.getByTestId("human-gate")).toContainText("Human decision");
  await expect(page.getByTestId("confirm-gate")).toBeVisible();

  const { projectId, token } = await liveAuth(page);
  const realities = await request.get(
    `${process.env.NEXT_PUBLIC_CTF_API_URL || "http://127.0.0.1:8080/api/v1"}/projects/${projectId}/resources/REALITY`,
    { headers: { "X-Session-Token": token } },
  );
  expect(realities.ok()).toBeTruthy();
  const records = await realities.json();
  expect(records.some((item: { status?: string; provenance?: string }) => item.status === "PROPOSED" || item.provenance === "CTF")).toBeTruthy();
  expect(records.every((item: { status?: string }) => item.status !== "CONFIRMED" || item.status === "PROPOSED")).toBeTruthy();

  const edited = "Human-edited reality: services remain fragmented.";
  await page.getByTestId("resource-text").fill(edited);
  await page.getByTestId("save-resource").click();
  await expect(page.getByTestId("resource-card").first()).toBeVisible();
  await confirmGate(page);
  await expect(page.getByTestId("human-gate")).not.toContainText("Confirm reality and go to Question");
});
