import { test, expect } from "@playwright/test";

test("live creation-cycle workspace reaches the API", async ({ page, request }) => {
  const api = process.env.NEXT_PUBLIC_CTF_API_URL || "http://localhost:8080/api/v1";
  const health = await request.get(api.replace(/\/api\/v1$/, "/health"));
  expect(health.ok()).toBeTruthy();
  await page.goto("/");
  await expect(page.locator("body")).toBeVisible();
});
