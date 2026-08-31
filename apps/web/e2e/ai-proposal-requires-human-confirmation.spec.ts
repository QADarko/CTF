import { expect, test } from "@playwright/test";
import { startLiveCycle } from "./helpers";

test("AI proposal is marked and cannot replace the human gate", async ({ page }) => {
  await startLiveCycle(page);
  const draft = page.getByTestId("draft-with-ai");
  if (await draft.isEnabled()) {
    await draft.click();
    await expect(page.getByTestId("ai-proposal-badge")).toBeVisible({ timeout: 30_000 });
  }
  await expect(page.getByTestId("human-gate")).toBeVisible();
  await expect(page.getByTestId("human-gate")).toContainText("Human decision");
});
