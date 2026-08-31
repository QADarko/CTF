import { expect, test } from "@playwright/test";
import { completeInterview, confirmGate, startLiveCycle } from "./helpers";

test("R0 remains visible after later stages", async ({ page }) => {
  await startLiveCycle(page);
  await completeInterview(page, ["Observed fragmentation.", "Affected users.", "Time.", "Unknown consent."]);
  await confirmGate(page);
  await page.getByRole("button", { name: /Reality/i }).click();
  await expect(page.locator("text=Observed").first()).toBeVisible();
});
