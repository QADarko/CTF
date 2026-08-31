import type { CapabilityResponse, ReadinessResponse } from "./api";

// Generated from docs/capability-status.yaml on 2026-08-29.
export const capabilitySnapshot: CapabilityResponse = {
  schema_version: "1.0",
  last_verified: "2026-08-29",
  summary: {
    total: 80,
    matching: 80,
    by_status: {
      IMPLEMENTED: 52,
      PARTIAL: 21,
      NOT_IMPLEMENTED: 3,
      BLOCKED_EXTERNAL: 3,
      DEFERRED_V1: 1,
    },
    by_priority: { P0: 42, P1: 35, P2: 3, P3: 0 },
  },
  capabilities: [
    { id: "CAP-CORE-04", name: "Consequential write idempotency", area: "Core workflow", status: "PARTIAL", priority: "P0", gaps: ["Direct idempotency coverage is not present for every consequential route."], blocked_by: [] },
    { id: "CAP-CORE-06", name: "Immutable confirmed records and supersession", area: "Core workflow", status: "PARTIAL", priority: "P0", gaps: ["Immutability is directly tested for R0, not every confirmed resource kind."], blocked_by: [] },
    { id: "CAP-VS03-02", name: "Kill assumption calibration", area: "VS03 Decide", status: "PARTIAL", priority: "P0", gaps: ["Material calibration breadth is not fully verified."], blocked_by: [] },
    { id: "CAP-VS05-03", name: "Baseline and attribution non-fabrication", area: "VS05 Transform", status: "PARTIAL", priority: "P0", gaps: ["Unknown-baseline and correlation scenario coverage is incomplete."], blocked_by: [] },
    { id: "CAP-DOC-03", name: "Durable external document worker", area: "Document intelligence", status: "PARTIAL", priority: "P0", gaps: ["Jobs use in-process BackgroundTasks; no external durable queue or worker is deployed."], blocked_by: [] },
    { id: "CAP-DOC-06", name: "Malware scanning and content disarm", area: "Document intelligence", status: "NOT_IMPLEMENTED", priority: "P0", gaps: ["No malware scanner or content-disarm service is integrated."], blocked_by: [] },
    { id: "CAP-AI-10", name: "Production model quality validation", area: "AI runtime", status: "BLOCKED_EXTERNAL", priority: "P0", gaps: ["No external model-quality evaluation or signed acceptance result exists."], blocked_by: ["Representative production provider, evaluation corpus, and human acceptance exercise."] },
    { id: "CAP-OPS-02", name: "SQLite and PostgreSQL snapshot persistence", area: "Operations", status: "PARTIAL", priority: "P0", gaps: ["SQLite restart is verified; PostgreSQL integration and multi-worker safety are not."], blocked_by: [] },
    { id: "CAP-OPS-03", name: "Private local and S3-compatible object stores", area: "Operations", status: "PARTIAL", priority: "P0", gaps: ["Local storage is directly tested; live S3 or MinIO integration is not."], blocked_by: [] },
    { id: "CAP-OPS-05", name: "External human pilot validation", area: "Operations", status: "BLOCKED_EXTERNAL", priority: "P0", gaps: ["No completed cohort, signed result, or human go/no-go evidence exists."], blocked_by: ["Pilot participants, facilitator, representative environment, and signed decision."] },
    { id: "CAP-ERI-06", name: "Raw telemetry excluded from AI context", area: "External reality", status: "PARTIAL", priority: "P0", gaps: ["No direct captured-context test proves exclusion for every ERI payload."], blocked_by: [] },
    { id: "CAP-OPS-06", name: "Multi-worker database concurrency", area: "Operations", status: "DEFERRED_V1", priority: "P1", gaps: ["Snapshot repository is explicitly single-process."], blocked_by: ["Normalized repository or cross-process locking design."] },
    { id: "CAP-OPS-08", name: "Coordinated backup and restore", area: "Operations", status: "NOT_IMPLEMENTED", priority: "P0", gaps: ["No automated coordinated database/object-store backup and restore test exists."], blocked_by: [] },
  ],
};

export const readinessSnapshot: ReadinessResponse = {
  last_verified: "2026-08-29",
  release: { ready: false, blocker_count: 12, blockers: [] },
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
  document_worker: { capability_id: "CAP-DOC-03", status: "PARTIAL", mode: "in-process-background-task", limitations: ["Jobs use in-process BackgroundTasks; no external durable queue or worker is deployed."] },
  khal: { capability_id: "CAP-ERI-02", status: "BLOCKED_EXTERNAL", mode: "adapter-only", limitations: ["No live KHAL connection is claimed in mock mode."] },
  pilot: { capability_id: "CAP-OPS-05", status: "BLOCKED_EXTERNAL", completed: false, limitations: ["No completed cohort, signed result, or human go/no-go evidence exists."] },
};
