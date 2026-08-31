import { expect, test } from "@playwright/test";
import { apiBase, completeInterview, confirmGate, saveRecord, startLiveCycle } from "./helpers";

test("live browser R0 to R1 creation cycle", async ({ page, request }) => {
  test.setTimeout(180_000);
  await startLiveCycle(page);
  await completeInterview(page, ["Services are fragmented.", "People who need help.", "Time and trust.", "Whether continuity is possible."]);
  await expect(page.getByTestId("human-gate")).toBeVisible();
  await confirmGate(page);

  await completeInterview(page, ["People can continue a case.", "They restart at every channel.", "A national rebuild.", "How might continuity be preserved?"]);
  await confirmGate(page);

  await completeInterview(page, ["We saw a website problem.", "We may be missing trust.", "User interviews."]);
  await confirmGate(page);

  await completeInterview(page, ["Users drop between channels.", "Service logs.", "We lack consent evidence."]);
  await confirmGate(page);

  await completeInterview(page, ["A portable case.", "People seeking help.", "Evidence of drop-off."]);
  await page.locator('input[name="gate-resource"]').first().check();
  await confirmGate(page);

  await completeInterview(page, ["What if the case travelled with the person?", "Ownership of the record."]);
  await page.locator('input[name="gate-resource"]').first().check();
  await confirmGate(page);

  await completeInterview(page, ["Portable case", "A continuing service record.", "Consent remains explicit."]);
  await page.locator('input[name="gate-resource"]').first().check();
  await confirmGate(page);

  await saveRecord(page, "Consent stays explicit.");
  await confirmGate(page);
  await saveRecord(page, "Consent becomes unclear.");
  await confirmGate(page);
  await saveRecord(page, "Human control remains non-negotiable.");
  await confirmGate(page);

  await saveRecord(page, "Proceed with an independent review.");
  await page.getByTestId("gate-rationale").fill("Independent review required.");
  await confirmGate(page);

  await saveRecord(page, "Pilot the portable case.");
  await confirmGate(page);
  await saveRecord(page, "Safe continuity is demonstrated.");
  await confirmGate(page);

  await page.getByTestId("action-title").fill("Run a safe pilot");
  await page.getByTestId("action-why").fill("Prove the portable case works.");
  await page.getByTestId("save-action").click();
  await page.getByTestId("review-finding").fill("Commitment still holds.");
  await page.getByTestId("request-review").click();
  await expect(page.getByTestId("confirm-gate")).toBeVisible({ timeout: 15_000 });
  await confirmGate(page);

  await page.getByTestId("execution-evidence").fill("Pilot completed.");
  await page.getByTestId("save-execution-evidence").click();
  await page.getByTestId("creation-record").fill("Portable case pilot.");
  await page.getByTestId("save-creation-record").click();

  await saveRecord(page, "People seeking help.");
  await confirmGate(page);
  await saveRecord(page, "Faster continuity for users.");
  await confirmGate(page);
  await saveRecord(page, "R1: continuity improved.");
  await confirmGate(page);
  await saveRecord(page, "R0-to-R1");
  await confirmGate(page);

  await expect(page.locator("text=COMPLETED").first()).toBeVisible({ timeout: 20_000 });
  const projectId = (await page.locator("text=Cycle ·").textContent())?.replace("Cycle · ", "").trim();
  expect(projectId).toBeTruthy();

  const session = await request.post(`${apiBase}/sessions/anonymous`, { data: { tenant_id: "public" } });
  expect(session.ok()).toBeTruthy();
});
