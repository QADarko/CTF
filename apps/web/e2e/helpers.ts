import { expect, type APIRequestContext, type Page } from "@playwright/test";

export const apiBase = process.env.NEXT_PUBLIC_CTF_API_URL || "http://127.0.0.1:8080/api/v1";

export async function completeInterview(page: Page, answers: string[]) {
  for (const answer of answers) {
    await page.getByTestId("interview-answer").fill(answer);
    await page.getByTestId("interview-next").click();
  }
  await page.getByTestId("interview-save").click();
  await expect(page.locator(".live-resource, [data-testid=resource-card]").first()).toBeVisible({ timeout: 15_000 });
}

export async function confirmGate(page: Page) {
  await page.getByTestId("confirm-gate").click();
  await page.waitForTimeout(400);
}

export async function saveRecord(page: Page, text: string) {
  await page.getByTestId("resource-text").fill(text);
  await page.getByTestId("save-resource").click();
  await page.waitForTimeout(400);
}

export async function startLiveCycle(page: Page) {
  await page.goto("/");
  await page.getByTestId("start-input").fill("Public services are moving online, but people who need help are left behind.");
  await page.getByTestId("begin-cycle").click();
  await expect(page.getByTestId("stage-interview")).toBeVisible({ timeout: 20_000 });
}

export async function sessionHeaders(request: APIRequestContext, token: string) {
  return {
    "X-Session-Token": token,
    "Content-Type": "application/json",
    "Idempotency-Key": `e2e-${Date.now()}-${Math.random()}`,
  };
}
