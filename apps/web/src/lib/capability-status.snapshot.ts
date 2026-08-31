import type { CapabilityResponse, ReadinessResponse } from "./api";

// Generated from docs/capability-status.yaml on 2026-08-29.
export const capabilitySnapshot: CapabilityResponse = {
  schema_version: "1.0",
  last_verified: "2026-08-29",
  summary: {
    total: 84,
    matching: 84,
    by_status: {
      IMPLEMENTED: 67,
      PARTIAL: 12,
      NOT_IMPLEMENTED: 1,
      BLOCKED_EXTERNAL: 3,
      DEFERRED_V1: 1,
    },
    by_priority: { P0: 46, P1: 35, P2: 3, P3: 0 },
  },
  capabilities: [
    { id: "CAP-AI-10", name: "Production model quality validation", area: "AI runtime", status: "BLOCKED_EXTERNAL", priority: "P0", gaps: ["No external model-quality evaluation or signed acceptance result exists."], blocked_by: ["Representative production provider, evaluation corpus, and human acceptance exercise."] },
    { id: "CAP-OPS-05", name: "External human pilot validation", area: "Operations", status: "BLOCKED_EXTERNAL", priority: "P0", gaps: ["No completed cohort, signed result, or human go/no-go evidence exists."], blocked_by: ["Pilot participants, facilitator, representative environment, and signed decision."] },
    { id: "CAP-OPS-06", name: "Multi-worker database concurrency", area: "Operations", status: "DEFERRED_V1", priority: "P1", gaps: ["Snapshot repository is explicitly single-process."], blocked_by: ["Normalized repository or cross-process locking design."] },
  ],
};

export const readinessSnapshot: ReadinessResponse = {
  last_verified: "2026-08-29",
  release: { ready: false, blocker_count: 2, blockers: [] },
  ai: {
    provider: "NONE",
    configured: false,
    reachable: false,
    ready: false,
    non_production: false,
    allowed_tiers: [],
    limitations: ["Mock view: no live AI runtime is being queried."],
  },
  runtime: {
    persistence: "mock",
    durable: false,
    object_store: "mock",
    object_store_durable: false,
  },
  document_worker: { capability_id: "CAP-DOC-03", status: "IMPLEMENTED", mode: "queued-worker", limitations: ["Local development may still use an in-process queue with durable=false."] },
  khal: { capability_id: "CAP-ERI-02", status: "BLOCKED_EXTERNAL", mode: "adapter-only", limitations: ["No live KHAL connection is claimed in mock mode."] },
  pilot: { capability_id: "CAP-OPS-05", status: "BLOCKED_EXTERNAL", completed: false, limitations: ["No completed cohort, signed result, or human go/no-go evidence exists."] },
};
