import { apiConfig } from "./ctf-data";
import { capabilitySnapshot, readinessSnapshot } from "./capability-status.snapshot";

export type CapabilityStatus = "IMPLEMENTED" | "PARTIAL" | "NOT_IMPLEMENTED" | "BLOCKED_EXTERNAL" | "DEFERRED_V1";
export type CapabilityPriority = "P0" | "P1" | "P2" | "P3";
export type Capability = {
  id: string;
  name: string;
  area: string;
  status: CapabilityStatus;
  priority: CapabilityPriority;
  gaps: string[];
  blocked_by: string[];
};
export type CapabilityResponse = {
  schema_version: string;
  last_verified: string;
  summary: {
    total: number;
    matching: number;
    by_status: Record<CapabilityStatus, number>;
    by_priority: Record<CapabilityPriority, number>;
  };
  capabilities: Capability[];
};
type ReadinessComponent = {
  capability_id: string | null;
  status: string;
  limitations: string[];
};
export type ReadinessResponse = {
  last_verified: string;
  release: { ready: boolean; blocker_count: number; blockers: unknown[] };
  ai: {
    provider: string;
    configured: boolean;
    reachable: boolean;
    ready: boolean;
    non_production: boolean;
    allowed_tiers: string[];
    limitations: string[];
  };
  runtime: {
    persistence: string;
    durable: boolean;
    object_store: string;
    object_store_durable: boolean;
  };
  document_worker: ReadinessComponent & { mode: string };
  khal: ReadinessComponent & { mode: string };
  pilot: ReadinessComponent & { completed: boolean };
};

export type EntryFamily = "CREATION" | "FUNDING" | "DOCUMENT";

export type ActiveGate = {
  id: string;
  number: number;
  name: string;
  status: string;
  decision?: string | null;
};

export type CTFProject = {
  id: string;
  entry_family: EntryFamily;
  entry_type: string;
  initial_input: string;
  stage: string;
  version: number;
  active_gate: ActiveGate;
  methodology_version?: string;
  created_at?: string;
  updated_at?: string;
};

export type CTFResource = {
  id: string;
  project_id: string;
  kind: string;
  version: number;
  data: Record<string, unknown>;
  status: string;
  provenance: string;
  immutable: boolean;
  created_at: string;
  updated_at: string;
};

export type WorkspaceResponse = {
  project: CTFProject;
  memory: Record<string, unknown>;
  active_gate: ActiveGate;
  resources: CTFResource[];
};

export type AIReadiness = {
  provider: string;
  configured: boolean;
  reachable: boolean;
  ready: boolean;
  allowed_tiers: string[];
  required_models?: string[];
  models?: Record<string, boolean>;
  limitations: string[];
};

export type AIRun = CTFResource;
export type AICostSummary = Record<string, unknown>;
export type ERIProvider = Record<string, unknown>;

export type DocumentJob = CTFResource & {
  data: {
    attachment_id: string;
    status: string;
    progress: number;
    counts: Record<string, number>;
    error?: { message?: string } | string | null;
  };
};

export type GateDecisionResponse = {
  gate: ActiveGate;
  project_stage: string;
  project_version: number;
  next_gate: ActiveGate;
  decision_record: { id: string; version: number } | null;
};

export type GateDecisionInput = {
  decision: string;
  payload?: Record<string, unknown>;
  expected_version?: number;
  actor_type?: "HUMAN";
};

type GateNumber = 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 | 16 | 17 | 18 | 19;

export const gateDecisionFor = (
  gate: number,
  payload: Record<string, unknown> = {},
): GateDecisionInput => {
  const decisions: Record<GateNumber, string> = {
    1: "CONFIRM",
    2: "CONFIRM",
    3: "CONFIRM_SHIFT",
    4: "ACKNOWLEDGE_UNCERTAINTY",
    5: "SELECT",
    6: "SELECT",
    7: "SELECT",
    8: "CONFIRM",
    9: "CONFIRM",
    10: "CONFIRM",
    11: "CONDITIONAL_GO",
    12: "CONFIRM",
    13: "CONFIRM",
    14: "CONFIRM_REDECISION",
    15: "REAFFIRM",
    16: "CONFIRM",
    17: "CONFIRM",
    18: "CONFIRM",
    19: "CLOSE",
  };
  if (!(gate in decisions)) throw new Error(`Unknown CTF gate ${gate}`);
  const decision = decisions[gate as GateNumber];
  return { decision, payload, actor_type: "HUMAN" };
};

export interface CTFClient {
  createProject(input: {
    entryFamily: EntryFamily;
    entryType: string;
    initialInput: string;
  }): Promise<CTFProject>;
  getProject(id: string): Promise<CTFProject>;
  getWorkspace(id: string): Promise<WorkspaceResponse>;
  createResource(id: string, kind: string, data: Record<string, unknown>, provenance?: string): Promise<CTFResource>;
  confirmResource(id: string, kind: string, resourceId: string): Promise<CTFResource>;
  uploadAttachment(id: string, file: File): Promise<CTFResource>;
  analyzeDocument(id: string, attachmentId: string): Promise<DocumentJob>;
  getDocumentJob(id: string, jobId: string): Promise<DocumentJob>;
  getParsedDocument(id: string, attachmentId: string): Promise<Record<string, unknown>>;
  getAIReadiness(): Promise<AIReadiness>;
  getAIOperations(): Promise<string[]>;
  executeAI(id: string, input: Record<string, unknown>): Promise<Record<string, unknown>>;
  getAIRuns(id: string): Promise<AIRun[]>;
  getAICost(id: string): Promise<AICostSummary>;
  getERIProviders(): Promise<ERIProvider[]>;
  getERIEvents(id: string): Promise<CTFResource[]>;
  decideGate(id: string, gate: number, decision: GateDecisionInput): Promise<GateDecisionResponse>;
  getCapabilities(): Promise<CapabilityResponse>;
  getReadiness(): Promise<ReadinessResponse>;
  ensureSession?(): Promise<string | null>;
}

const wait = (ms = 180) => new Promise((resolve) => setTimeout(resolve, ms));

class MockCTFClient implements CTFClient {
  private project: CTFProject | null = null;

  async createProject(input: {
    entryFamily: EntryFamily;
    entryType: string;
    initialInput: string;
  }): Promise<CTFProject> {
    await wait();
    this.project = {
      id: "mock-project",
      entry_family: input.entryFamily,
      entry_type: input.entryType,
      initial_input: input.initialInput,
      stage: "REALITY",
      version: 1,
      active_gate: { id: "mock-gate-1", number: 1, name: "REALITY_CONFIRMATION", status: "PENDING" },
    };
    return this.project;
  }

  async getProject(): Promise<CTFProject> {
    await wait();
    if (!this.project) throw new Error("Mock project has not been created");
    return this.project;
  }

  async getWorkspace(): Promise<WorkspaceResponse> {
    const project = await this.getProject();
    return { project, memory: {}, active_gate: project.active_gate, resources: [] };
  }

  async createResource(id: string, kind: string, data: Record<string, unknown>): Promise<CTFResource> {
    await wait();
    return { id: `demo-${kind}`, project_id: id, kind, version: 1, data, status: "PROPOSED", provenance: "USER", immutable: false, created_at: new Date().toISOString(), updated_at: new Date().toISOString() };
  }

  async confirmResource(_id: string, kind: string, resourceId: string): Promise<CTFResource> {
    await wait();
    return { id: resourceId, project_id: _id, kind, version: 2, data: { confirmation: "CONFIRMED" }, status: "CONFIRMED", provenance: "DOCUMENT", immutable: true, created_at: new Date().toISOString(), updated_at: new Date().toISOString() };
  }

  async uploadAttachment(id: string, file: File) {
    return this.createResource(id, "ATTACHMENT", { original_filename: file.name });
  }

  async analyzeDocument(id: string, attachmentId: string) {
    return {
      ...await this.createResource(id, "DOCUMENT_JOB", { attachment_id: attachmentId }),
      data: { attachment_id: attachmentId, status: "COMPLETED", progress: 100, counts: {} },
    } as DocumentJob;
  }

  async getDocumentJob(id: string, jobId: string) {
    return {
      ...await this.createResource(id, "DOCUMENT_JOB", {}),
      id: jobId,
      data: { attachment_id: "", status: "COMPLETED", progress: 100, counts: {} },
    } as DocumentJob;
  }

  async getParsedDocument() { return {}; }
  async getAIReadiness(): Promise<AIReadiness> { return { provider: "FAKE", configured: true, reachable: true, ready: true, allowed_tiers: ["T1", "T2"], limitations: ["Fixture-backed demo runtime."] }; }
  async getAIOperations() { return ["REALITY_UPDATE"]; }
  async executeAI() { return { output: { status: "PROPOSED", items: [] } }; }
  async getAIRuns() { return []; }
  async getAICost() { return {}; }
  async getERIProviders() { return []; }
  async getERIEvents() { return []; }

  async decideGate(_id: string, gate: number, input: GateDecisionInput) {
    await wait();
    if (!this.project) throw new Error("Mock project has not been created");
    const number = gate;
    const nextNumber = number === 19 ? 1 : number + 1;
    const result: GateDecisionResponse = {
      gate: { ...this.project.active_gate, status: "DECIDED", decision: input.decision },
      project_stage: number === 19 ? "REALITY" : this.project.stage,
      project_version: this.project.version + 1,
      next_gate: {
        id: `mock-gate-${nextNumber}`,
        number: nextNumber,
        name: `GATE_${nextNumber}`,
        status: "PENDING",
      },
      decision_record: null,
    };
    this.project = {
      ...this.project,
      stage: result.project_stage,
      version: result.project_version,
      active_gate: result.next_gate,
    };
    localStorage.setItem(`ctf-gate-${number}`, JSON.stringify(input));
    return result;
  }

  async getCapabilities() {
    await wait();
    return capabilitySnapshot;
  }

  async getReadiness() {
    await wait();
    return readinessSnapshot;
  }

  async ensureSession() {
    return "mock-session";
  }
}

export const LIVE_PROJECT_KEY = "ctf-live-project-id";
export const LIVE_SESSION_KEY = "ctf-session-token";

export function clearLiveClientState() {
  if (typeof window === "undefined") return;
  localStorage.removeItem(LIVE_PROJECT_KEY);
  localStorage.removeItem(LIVE_SESSION_KEY);
}

export async function ensureLiveSession() {
  if (apiConfig.useMocks || typeof window === "undefined") return null;
  return ctfClient.ensureSession?.() ?? null;
}

class HttpCTFClient implements CTFClient {
  private static readonly tokenKey = LIVE_SESSION_KEY;

  private cachedToken: string | null = null;

  private readToken(): string | null {
    if (typeof window === "undefined") return this.cachedToken;
    const stored = localStorage.getItem(HttpCTFClient.tokenKey);
    const token = stored?.trim() || this.cachedToken?.trim() || null;
    this.cachedToken = token;
    return token;
  }

  private writeToken(token: string) {
    const normalized = token.trim();
    this.cachedToken = normalized;
    if (typeof window !== "undefined") {
      localStorage.setItem(HttpCTFClient.tokenKey, normalized);
    }
  }

  async ensureSession(): Promise<string> {
    const existing = this.readToken();
    if (existing) return existing;
    const session = await this.request<{ token: string }>(
      "/sessions/anonymous",
      { method: "POST", body: JSON.stringify({ tenant_id: "public" }) },
      false,
    );
    this.writeToken(session.token);
    return session.token;
  }

  private async request<T>(
    path: string,
    init?: RequestInit,
    authenticated = true,
    retried = false,
  ): Promise<T> {
    const method = (init?.method ?? "GET").toUpperCase();
    const token = authenticated ? await this.ensureSession() : null;
    const headers: Record<string, string> = {
      ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...(init?.headers as Record<string, string> | undefined),
      ...(authenticated && token ? { "X-Session-Token": token } : {}),
    };
    if (["POST", "PUT", "PATCH", "DELETE"].includes(method) && !headers["Idempotency-Key"]) {
      headers["Idempotency-Key"] = crypto.randomUUID();
    }
    const response = await fetch(`${apiConfig.baseUrl}${path}`, {
      ...init,
      headers,
    });
    if (!response.ok) {
      const body = await response.json().catch(() => null) as {
        error?: { code?: string; message?: string };
      } | null;
      const code = body?.error?.code ?? "";
      const message = body?.error?.message ?? `CTF API error ${response.status}`;
      if (
        authenticated
        && !retried
        && response.status === 403
        && code === "ACCESS_DENIED"
        && /session token is invalid|session has expired/i.test(message)
      ) {
        this.cachedToken = null;
        if (typeof window !== "undefined") localStorage.removeItem(HttpCTFClient.tokenKey);
        return this.request<T>(path, init, authenticated, true);
      }
      throw new Error(message);
    }
    return response.json() as Promise<T>;
  }

  async createProject(input: {
    entryFamily: EntryFamily;
    entryType: string;
    initialInput: string;
  }) {
    const session = await this.request<{ token: string }>(
      "/sessions/anonymous",
      { method: "POST", body: JSON.stringify({ tenant_id: "public" }) },
      false,
    );
    this.writeToken(session.token);
    return this.request<CTFProject>("/projects", {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({
        entry_family: input.entryFamily,
        entry_type: input.entryType,
        initial_input: input.initialInput,
        source: { channel: "web" },
      }),
    });
  }

  getProject(id: string) {
    return this.request<CTFProject>(`/projects/${id}`);
  }

  getWorkspace(id: string) {
    return this.request<WorkspaceResponse>(`/projects/${id}/workspace`);
  }

  createResource(
    projectId: string,
    kind: string,
    data: Record<string, unknown>,
    provenance = "USER",
  ) {
    return this.request<CTFResource>(`/projects/${projectId}/resources/${kind}`, {
      method: "POST",
      body: JSON.stringify({ data, provenance }),
    });
  }

  confirmResource(projectId: string, kind: string, resourceId: string) {
    return this.request<CTFResource>(
      `/projects/${projectId}/resources/${kind}/${resourceId}/confirm`,
      { method: "POST" },
    );
  }

  uploadAttachment(projectId: string, file: File) {
    const body = new FormData();
    body.append("file", file);
    return this.request<CTFResource>(`/projects/${projectId}/attachments`, { method: "POST", body });
  }

  analyzeDocument(projectId: string, attachmentId: string) {
    return this.request<DocumentJob>(`/projects/${projectId}/evidence/analyze-document`, {
      method: "POST",
      body: JSON.stringify({ data: { attachment_id: attachmentId } }),
    });
  }

  getDocumentJob(projectId: string, jobId: string) {
    return this.request<DocumentJob>(`/projects/${projectId}/document-jobs/${jobId}`);
  }

  getParsedDocument(projectId: string, attachmentId: string) {
    return this.request<Record<string, unknown>>(`/projects/${projectId}/attachments/${attachmentId}/parsed`);
  }

  getAIReadiness() { return this.request<AIReadiness>("/ai/readiness"); }
  getAIOperations() { return this.request<string[]>("/ai/operations"); }
  executeAI(projectId: string, input: Record<string, unknown>) {
    return this.request<Record<string, unknown>>(`/projects/${projectId}/ai/execute`, { method: "POST", body: JSON.stringify(input) });
  }
  getAIRuns(projectId: string) { return this.request<AIRun[]>(`/projects/${projectId}/ai/runs`); }
  getAICost(projectId: string) { return this.request<AICostSummary>(`/projects/${projectId}/ai-cost-ledger`); }
  getERIProviders() { return this.request<ERIProvider[]>("/eri/providers"); }
  getERIEvents(projectId: string) { return this.request<CTFResource[]>(`/eri/reality-events?project_id=${encodeURIComponent(projectId)}`); }

  async decideGate(id: string, gate: number, decision: GateDecisionInput) {
    const current = await this.getProject(id);
    if (current.active_gate.number !== gate || current.active_gate.status !== "PENDING") {
      throw new Error(`The backend is waiting at Gate ${current.active_gate.number}, not Gate ${gate}.`);
    }
    const result = await this.request<GateDecisionResponse>(
      `/projects/${id}/gates/${current.active_gate.id}/decision`,
      {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify({ ...decision, expected_version: current.version }),
      },
    );
    return result;
  }

  getCapabilities() {
    return this.request<CapabilityResponse>("/system/capabilities", undefined, false);
  }

  getReadiness() {
    return this.request<ReadinessResponse>("/system/readiness", undefined, false);
  }
}

export const ctfClient: CTFClient = apiConfig.useMocks ? new MockCTFClient() : new HttpCTFClient();
export const isDemoMode = apiConfig.useMocks;
