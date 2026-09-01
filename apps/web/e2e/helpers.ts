import { expect, type APIRequestContext, type Page } from "@playwright/test";

export const apiBase = process.env.NEXT_PUBLIC_CTF_API_URL || "http://127.0.0.1:8080/api/v1";
export const LIVE_PROJECT_KEY = "ctf-live-project-id";
export const LIVE_SESSION_KEY = "ctf-session-token";
export const REQUIRED_GATES = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19];

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

export function sessionHeaders(token: string, extra?: Record<string, string>) {
  return {
    "X-Session-Token": token,
    "Content-Type": "application/json",
    "Idempotency-Key": `e2e-${Date.now()}-${Math.random()}`,
    ...extra,
  };
}

export async function liveAuth(page: Page) {
  const projectId = await page.evaluate((key) => localStorage.getItem(key), LIVE_PROJECT_KEY);
  const token = await page.evaluate((key) => localStorage.getItem(key), LIVE_SESSION_KEY);
  expect(projectId).toBeTruthy();
  expect(token).toBeTruthy();
  return { projectId: projectId as string, token: token as string };
}

export async function apiGet(request: APIRequestContext, path: string, token: string) {
  const response = await request.get(`${apiBase}${path}`, { headers: sessionHeaders(token) });
  expect(response.ok(), `${path} ${response.status()}`).toBeTruthy();
  return response.json();
}

export async function runFullCreationCycle(page: Page) {
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
  return liveAuth(page);
}

export async function verifyPostCycleIntegrity(
  request: APIRequestContext,
  projectId: string,
  token: string,
  r0?: { id: string; text: string },
) {
  const project = await apiGet(request, `/projects/${projectId}`, token);
  expect(project.stage).toBe("COMPLETED");
  expect(project.active_gate.status).toBe("DECIDED");

  const audit = await apiGet(request, `/projects/${projectId}/audit`, token);
  for (const number of REQUIRED_GATES) {
    expect(
      audit.some((event: { event_type?: string }) => event.event_type === `gate_${number}_decided`),
      `missing Gate ${number} decision in audit`,
    ).toBeTruthy();
  }

  const realities = await apiGet(request, `/projects/${projectId}/resources/REALITY`, token);
  const snapshots = await apiGet(request, `/projects/${projectId}/resources/REALITY_SNAPSHOT`, token);
  const cycles = await apiGet(request, `/projects/${projectId}/resources/CREATION_CYCLE`, token);
  expect(realities.length).toBeGreaterThan(0);
  expect(snapshots.length).toBeGreaterThan(0);
  expect(cycles.length).toBeGreaterThan(0);
  expect(realities[0].id).not.toBe(snapshots[0].id);
  if (r0) {
    const original = realities.find((item: { id: string }) => item.id === r0.id) ?? realities[0];
    expect(JSON.stringify(original.data)).toContain(r0.text);
    expect(original.id).toBe(r0.id);
  }

  const memory = await apiGet(request, `/projects/${projectId}/memory/versions`, token);
  expect(memory.length).toBeGreaterThan(0);

  const genealogy = await apiGet(request, `/projects/${projectId}/creation-genealogy`, token);
  expect(genealogy.links.length).toBeGreaterThan(0);

  const decisions = await apiGet(request, `/projects/${projectId}/resources/HUMAN_DECISION`, token);
  expect(decisions.length).toBeGreaterThan(0);
  expect(decisions.every((item: { provenance?: string }) => item.provenance !== "AI")).toBeTruthy();

  const runs = await apiGet(request, `/projects/${projectId}/ai/runs`, token);
  expect(Array.isArray(runs)).toBeTruthy();

  const costs = await apiGet(request, `/projects/${projectId}/ai-cost-ledger`, token);
  expect(costs).toBeTruthy();

  expect(cycles.some((item: { status?: string; data?: { status?: string } }) => item.status === "COMPLETED" || item.data?.status === "COMPLETED")).toBeTruthy();
}
