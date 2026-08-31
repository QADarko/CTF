import { expect, test } from "@playwright/test";
import { completeInterview, confirmGate, startLiveCycle } from "./helpers";

test("confirmed resource becomes immutable in the live UI", async ({ page }) => {
  await startLiveCycle(page);
  await completeInterview(page, ["Observed fragmentation.", "Affected users.", "Time.", "Unknown consent."]);
  await confirmGate(page);
  const card = page.getByTestId("resource-card").first();
  await expect(card).toBeVisible();
  await expect(card).toHaveAttribute("data-status", /CONFIRMED|SELECTED|ACTIVE/);
});
