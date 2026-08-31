import {
  Aperture, Atom, BrainCircuit, Compass, Crosshair, Eye, FileSearch,
  Flag, Gauge, GitBranch, HeartHandshake, Lightbulb, Map, Milestone,
  Orbit, Rocket, Scale, ShieldCheck, Sparkles, Target, Telescope, type LucideIcon,
} from "lucide-react";

export type SliceId = "frame" | "create" | "decide" | "activate" | "transform";
export type Confidence = "High" | "Medium" | "Low";

export type Stage = {
  id: string;
  slice: SliceId;
  short: string;
  title: string;
  prompt: string;
  gate: number;
  icon: LucideIcon;
};

export type Slice = {
  id: SliceId;
  number: string;
  name: string;
  description: string;
  accent: string;
};

export const slices: Slice[] = [
  { id: "frame", number: "01", name: "Frame", description: "Reality to perception", accent: "#4e8d78" },
  { id: "create", number: "02", name: "Create", description: "Evidence to idea", accent: "#9c7134" },
  { id: "decide", number: "03", name: "Decide", description: "Test to decision", accent: "#a14c4c" },
  { id: "activate", number: "04", name: "Activate", description: "Commitment to action", accent: "#4c6f9d" },
  { id: "transform", number: "05", name: "Transform", description: "Value to new reality", accent: "#765e9d" },
];

export const stages: Stage[] = [
  { id: "reality", slice: "frame", short: "R₀", title: "Reality", prompt: "What is true right now?", gate: 1, icon: Aperture },
  { id: "question", slice: "frame", short: "Q", title: "Question", prompt: "What are we really trying to change?", gate: 2, icon: Compass },
  { id: "perception", slice: "frame", short: "P", title: "Perception", prompt: "What might we be missing?", gate: 3, icon: Eye },
  { id: "evidence", slice: "create", short: "E", title: "Evidence", prompt: "What do we really know?", gate: 4, icon: FileSearch },
  { id: "opportunity", slice: "create", short: "O", title: "Opportunity", prompt: "What becomes possible?", gate: 5, icon: Telescope },
  { id: "spark", slice: "create", short: "S", title: "Spark", prompt: "What if…?", gate: 6, icon: Sparkles },
  { id: "idea", slice: "create", short: "I", title: "Idea", prompt: "How does the spark take form?", gate: 7, icon: Lightbulb },
  { id: "assumptions", slice: "decide", short: "A", title: "Assumptions", prompt: "What must be true?", gate: 8, icon: BrainCircuit },
  { id: "adversarial", slice: "decide", short: "X", title: "Red team", prompt: "Where could this fail?", gate: 9, icon: ShieldCheck },
  { id: "boundaries", slice: "decide", short: "V", title: "Value boundaries", prompt: "What will we not sacrifice?", gate: 10, icon: Scale },
  { id: "decision", slice: "decide", short: "D", title: "Decision", prompt: "What do you choose?", gate: 11, icon: Crosshair },
  { id: "commitment", slice: "activate", short: "C", title: "Commitment", prompt: "What will we truly commit to?", gate: 12, icon: Flag },
  { id: "roadmap", slice: "activate", short: "M", title: "Roadmap", prompt: "What must become true?", gate: 13, icon: Map },
  { id: "actions", slice: "activate", short: "N", title: "Actions & NBA", prompt: "What is the most valuable next move?", gate: 14, icon: Milestone },
  { id: "reaffirm", slice: "activate", short: "↻", title: "Reaffirm", prompt: "Does the commitment still hold?", gate: 15, icon: GitBranch },
  { id: "value", slice: "transform", short: "V", title: "Value", prompt: "For whom did value emerge?", gate: 16, icon: HeartHandshake },
  { id: "impact", slice: "transform", short: "Δ", title: "Impact", prompt: "What changed, and why?", gate: 17, icon: Orbit },
  { id: "transformation", slice: "transform", short: "T", title: "Transformation", prompt: "Did the system itself change?", gate: 18, icon: Rocket },
  { id: "r1", slice: "transform", short: "R₁", title: "New reality", prompt: "Where are we now?", gate: 19, icon: Target },
];

export const project = {
  name: "Fair access to public services",
  code: "CTF–024",
  cycle: "Creation cycle 01",
  updated: "Updated 8 min ago",
};

export const realityItems = [
  { type: "Observed fact", text: "Average application processing takes 15 days.", source: "Service logs · 2025", confidence: "High" as Confidence },
  { type: "Constraint", text: "20% of applicants require assisted access.", source: "User interview set", confidence: "Medium" as Confidence },
  { type: "Resource", text: "A verified digital identity layer already exists.", source: "Project document", confidence: "High" as Confidence },
  { type: "Assumption", text: "People abandon the service primarily because it is slow.", source: "Team inference", confidence: "Low" as Confidence },
];

export const claims = [
  { id: "CLM-01", text: "Long processing time drives service abandonment.", status: "Partially supported", tone: "amber", source: "3 linked items", confidence: "Medium" },
  { id: "CLM-02", text: "Digital identity can remove duplicate verification.", status: "Supported", tone: "green", source: "Architecture review · p.17", confidence: "High" },
  { id: "CLM-03", text: "A digital-only path would improve access for everyone.", status: "Contradicted", tone: "red", source: "Access study · §3.2", confidence: "High" },
];

export const opportunities = [
  { id: "OPP-01", title: "Assisted digital continuity", text: "Keep one continuous application across self-service and human-assisted channels.", evidence: "Strong", value: "High", selected: true },
  { id: "OPP-02", title: "Verify once, reuse with consent", text: "Reduce repeated proof without removing human control over data use.", evidence: "Medium", value: "High", selected: true },
  { id: "OPP-03", title: "Proactive exception handling", text: "Detect stalled cases and route help before applicants abandon.", evidence: "Medium", value: "Medium", selected: false },
];

export const sparks = [
  { origin: "CTF", text: "What if the service moved with the person—not the channel?" },
  { origin: "Co-created", text: "What if asking for help never meant starting over?" },
  { origin: "Yours", text: "One case, one history, many ways to continue." },
];

export const assumptions = [
  { level: "KILL", title: "Cross-channel identity matching is legally permitted", state: "Unvalidated", test: "Independent regulatory review" },
  { level: "HIGH", title: "Applicants will consent to reuse verified data", state: "Partial evidence", test: "Prototype consent flow" },
  { level: "MEDIUM", title: "Staff can support the new exception queue", state: "Unknown", test: "Capacity simulation" },
];

export const failureModes = [
  { category: "Access", title: "Assistance becomes a second-class lane", impact: "High", likelihood: "Medium", basis: "Evidence-informed" },
  { category: "Trust", title: "Data reuse feels invisible or coercive", impact: "High", likelihood: "Medium", basis: "Hypothetical" },
  { category: "Operations", title: "Exception queue moves the bottleneck", impact: "Medium", likelihood: "High", basis: "Evidence-informed" },
];

export const blueprint = [
  ["What", "A continuous case layer that preserves progress across digital and assisted service."],
  ["Who", "Applicants, service agents, and partner agencies."],
  ["Why", "People should not lose progress because they need a different channel."],
  ["Value", "Faster resolution with equitable access and explicit consent."],
  ["How", "Reusable verified data, shared case state, and proactive exceptions."],
  ["Enablers", "Digital identity · case API · assisted-service network"],
  ["Assumptions", "Consent acceptance · legal reuse · staff capacity"],
  ["Evidence", "EVD-14 · EVD-21 · Architecture review"],
  ["Unknowns", "Cross-agency operating owner · exception volume"],
  ["Constraints", "No digital-only exclusion · consent can be withdrawn"],
];

export const roadmap = [
  { month: "Now · Sep", outcome: "Legal feasibility confirmed", action: "Prepare independent review package", status: "Ready", evidence: "Written legal opinion", critical: true },
  { month: "Next · Oct", outcome: "Continuity concept validated", action: "Test assisted-to-digital handoff", status: "Planned", evidence: "Observed completion data", critical: false },
  { month: "Later · Dec", outcome: "Pilot operating safely", action: "Run a 200-case service pilot", status: "Planned", evidence: "Pilot evidence pack", critical: false },
];

export const stakeholders = [
  { name: "Applicants", role: "Primary beneficiary", value: "11.2 days saved", status: "Partially realized" },
  { name: "Assisted-service users", role: "At-risk cohort", value: "Completion +18%", status: "Realized" },
  { name: "Service agents", role: "Delivery stakeholder", value: "Exception load +9%", status: "Negative effect" },
];

export const gates = stages.map((stage) => ({
  number: stage.gate,
  label: stage.title,
  slice: stage.slice,
  state: stage.gate < 4 ? "confirmed" : stage.gate === 4 ? "current" : "pending",
}));

export const traceNodes = [
  "R₀ item 04", "Q-01", "Perception shift", "EVD-14", "OPP-01",
  "Spark 02", "Idea v2", "Decision 01", "Commitment 01", "Action 14", "R₁",
];

export const apiConfig = {
  baseUrl: process.env.NEXT_PUBLIC_CTF_API_URL ?? "/api/v1",
  useMocks: process.env.NEXT_PUBLIC_USE_MOCKS !== "false",
};

export const uiIcons = { Gauge, Atom };
