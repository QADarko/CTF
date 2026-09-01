import { expect, test } from "@playwright/test";
import { runFullCreationCycle, verifyPostCycleIntegrity } from "./helpers";

test("live browser R0 to R1 creation cycle preserves integrity", async ({ page, request }) => {
  test.setTimeout(180_000);
  const { projectId, token } = await runFullCreationCycle(page);
  await verifyPostCycleIntegrity(request, projectId, token);
  expect(projectId).toBeTruthy();
});
