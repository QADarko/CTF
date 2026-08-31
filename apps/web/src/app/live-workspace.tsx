"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Activity, CloudUpload, Home, Info, LockKeyhole, MessageCircle, Play, Radar, RefreshCw } from "lucide-react";
import {
  ctfClient,
  ensureLiveSession,
  gateDecisionFor,
  type AIReadiness,
  type CTFProject,
  type CTFResource,
  type DocumentJob,
  type EntryFamily,
  type WorkspaceResponse,
} from "@/lib/api";
import { slices, stages, type Stage } from "@/lib/ctf-data";

const resourceKindByGate: Record<number, string | null> = {
  1: "REALITY", 2: "QUESTION", 3: "PERCEPTION", 4: "EVIDENCE",
  5: "OPPORTUNITY", 6: "SPARK", 7: "IDEA", 8: "ASSUMPTION",
  9: "FAILURE_MODE", 10: "VALUE_BOUNDARY", 11: "DECISION_BRIEF",
  12: "COMMITMENT", 13: "ROADMAP", 14: "EXECUTION_EVENT",
  15: "COMMITMENT_REVIEW", 16: "STAKEHOLDER", 17: "REALIZED_VALUE",
  18: "REALITY_SNAPSHOT", 19: "CREATION_CYCLE",
};
const requiredKindsByGate: Record<number, string[]> = {
  1: ["REALITY"], 2: ["QUESTION"], 3: ["PERCEPTION"], 5: ["OPPORTUNITY"],
  6: ["SPARK"], 7: ["IDEA"], 8: ["ASSUMPTION"], 9: ["FAILURE_MODE"],
  10: ["VALUE_BOUNDARY"], 11: ["DECISION_BRIEF", "RECOMMENDATION"],
  12: ["COMMITMENT"], 13: ["ROADMAP"], 15: ["COMMITMENT_REVIEW"], 16: ["STAKEHOLDER"],
  17: ["REALIZED_VALUE"], 18: ["REALITY_SNAPSHOT"], 19: ["CREATION_CYCLE"],
};

const nextStageTitle: Record<number, string> = {
  1: "Gate 2 · Question",
  2: "Gate 3 · Perception",
  3: "Gate 4 · Evidence",
  4: "Gate 5 · Opportunity",
  5: "Gate 6 · Spark",
  6: "Gate 7 · Idea",
  7: "Gate 8 · Assumptions",
  8: "Gate 9 · Red team",
  9: "Gate 10 · Value boundaries",
  10: "Gate 11 · Decision",
  11: "Gate 12 · Commitment",
  12: "Gate 13 · Roadmap",
  13: "Gate 14 · Actions",
  14: "Gate 15 · Reaffirm",
  15: "Gate 16 · Value",
  16: "Gate 17 · Impact",
  17: "Gate 18 · Transformation",
  18: "Gate 19 · New reality",
};

const stageForGate = (gate: number) => stages.find((item) => item.gate === gate) ?? stages[0];

const resolveLiveNavigation = (project: CTFProject, resources: CTFResource[]) => {
  const gateNumber = project.active_gate.number;
  const gateStatus = project.active_gate.status;
  const pendingGate = gateStatus === "PENDING" ? gateNumber : null;

  const hasCreationRecord = resources.some((r) => r.kind === "CREATION_RECORD");
  const hasExecutionEvidence = resources.some((r) => r.kind === "EXECUTION_EVIDENCE");
  const hasCommitmentReview = resources.some((r) => r.kind === "COMMITMENT_REVIEW");

  const inActionPhase = project.stage === "ACTION" && gateNumber === 13 && gateStatus === "DECIDED";
  const inValuePrepPhase = project.stage === "ACTION" && gateNumber === 15 && gateStatus === "DECIDED" && !hasCreationRecord;
  const redecisionPending = gateNumber === 14 && gateStatus === "PENDING";
  const reaffirmPending = gateNumber === 15 && gateStatus === "PENDING";

  if (project.stage === "COMPLETED") {
    return {
      workingGate: 19,
      navigableThrough: 19,
      pendingGate,
      inActionPhase: false,
      inValuePrepPhase: false,
      redecisionPending: false,
      reaffirmPending: false,
      hasCreationRecord,
      hasExecutionEvidence,
    };
  }

  let workingGate = gateNumber;
  let navigableThrough = gateNumber;

  if (pendingGate) {
    workingGate = pendingGate;
    navigableThrough = pendingGate;
  } else if (inValuePrepPhase) {
    workingGate = 15;
    navigableThrough = 15;
  } else if (inActionPhase) {
    workingGate = 14;
    navigableThrough = 14;
    if (hasCommitmentReview) navigableThrough = 15;
  }

  if (reaffirmPending) {
    workingGate = 15;
    navigableThrough = 15;
  }

  return {
    workingGate,
    navigableThrough,
    pendingGate,
    inActionPhase,
    inValuePrepPhase,
    redecisionPending,
    reaffirmPending,
    hasCreationRecord,
    hasExecutionEvidence,
  };
};

const lockedStageMessage = (activeGate: number, navigation: ReturnType<typeof resolveLiveNavigation>) => {
  if (navigation.inValuePrepPhase && activeGate === 15) {
    return "Reaffirm is complete. Record execution evidence and a creation record below to unlock Gate 16 · Value.";
  }
  if (activeGate === 16 && navigation.inValuePrepPhase) {
    return "Record execution evidence and a creation record on Gate 15 to unlock Value (Gate 16).";
  }
  if (activeGate === 15 && navigation.inActionPhase) {
    return "Request a commitment review on Gate 14 to unlock Reaffirm (Gate 15).";
  }
  if (activeGate > navigation.navigableThrough) {
    return `Complete Gate ${navigation.navigableThrough} (${stageForGate(navigation.navigableThrough).title}) first to unlock ${stageForGate(activeGate).title}.`;
  }
  if (navigation.inValuePrepPhase && activeGate === 13) {
    return "Gate 13 is complete. Open Gate 14 · Actions to continue.";
  }
  return "Advance the active server gate before selecting this stage.";
};

const selectionGates = new Set([5, 6, 7, 18, 19]);

const resourceLabel = (resource: CTFResource) => {
  const data = resource.data;
  for (const key of ["name", "text", "statement", "title", "what", "summary"]) {
    const value = data[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return resource.id;
};

const idsOfKinds = (all: CTFResource[] | undefined, kinds: string[]) =>
  (all ?? []).filter((item) => kinds.includes(item.kind)).map((item) => item.id);

const selectedStatuses = new Set(["SELECTED", "CONFIRMED", "ACTIVE"]);

const findSelectedIdea = (all: CTFResource[]) => {
  const selected = all.filter((item) => item.kind === "IDEA" && selectedStatuses.has(item.status));
  if (selected.length) return selected[selected.length - 1];
  const ideas = all.filter((item) => item.kind === "IDEA");
  return ideas.length ? ideas[ideas.length - 1] : null;
};

const findHumanDecision = (all: CTFResource[]) => {
  const decisions = all.filter((item) => item.kind === "HUMAN_DECISION");
  return decisions.length ? decisions[decisions.length - 1] : null;
};

const genealogyParentsFor = (kind: string): string[] => {
  if (kind === "OPPORTUNITY") return ["EVIDENCE", "CLAIM", "REALITY", "PERCEPTION", "QUESTION"];
  if (kind === "SPARK") return ["OPPORTUNITY"];
  if (kind === "IDEA") return ["SPARK", "OPPORTUNITY"];
  return [];
};

const buildResourceData = (
  kind: string,
  text: string,
  allResources: CTFResource[] | undefined,
  preferredParents: string[] = [],
): Record<string, unknown> => {
  const trimmed = text.trim();
  const parents = preferredParents.length
    ? preferredParents
    : idsOfKinds(allResources, genealogyParentsFor(kind));

  if (kind === "OPPORTUNITY") {
    if (!parents.length) {
      throw new Error("Save Evidence or Reality first so the Opportunity can link back to it.");
    }
    return {
      name: trimmed.slice(0, 80),
      statement: trimmed,
      text: trimmed,
      derived_from: parents.slice(0, 3),
    };
  }
  if (kind === "SPARK") {
    if (!parents.length) {
      throw new Error("Save and select an Opportunity first so the Spark can link back to it.");
    }
    return { text: trimmed, derived_from: parents.slice(0, 3) };
  }
  if (kind === "IDEA") {
    if (!parents.length) {
      throw new Error("Save and select a Spark first so the Idea can link back to it.");
    }
    return {
      name: trimmed.slice(0, 80) || "Working idea",
      what: trimmed,
      derived_from: parents.slice(0, 3),
      unknowns: [],
      assumptions: [],
    };
  }
  if (kind === "EVIDENCE") {
    return { statement: trimmed };
  }
  if (kind === "FAILURE_MODE") {
    return { title: trimmed.slice(0, 80), statement: trimmed, text: trimmed };
  }
  if (kind === "ASSUMPTION") {
    return { statement: trimmed, text: trimmed };
  }
  if (kind === "VALUE_BOUNDARY") {
    return { name: trimmed.slice(0, 80), statement: trimmed, priority: "IMPORTANT" };
  }
  if (kind === "PERCEPTION") {
    return { text: trimmed };
  }
  if (kind === "DECISION_BRIEF") {
    const idea = findSelectedIdea(allResources ?? []);
    if (!idea) {
      throw new Error("Save an Idea first so the Decision Brief can link to it.");
    }
    return {
      idea_id: idea.id,
      idea_version: Number(idea.version),
      status: "CONFIRMED",
      summary: trimmed,
      text: trimmed,
    };
  }
  if (kind === "RECOMMENDATION") {
    return { recommendation: trimmed.slice(0, 40) || "CONDITIONAL_GO", status: "CURRENT", text: trimmed };
  }
  if (kind === "COMMITMENT") {
    const humanDecision = findHumanDecision(allResources ?? []);
    if (!humanDecision) {
      throw new Error("Complete Gate 11 first so the Commitment can link to your human decision.");
    }
    return { decision_id: humanDecision.id, statement: trimmed, text: trimmed };
  }
  if (kind === "ROADMAP") {
    return { name: trimmed.slice(0, 80) || "Roadmap", outcomes: [trimmed], text: trimmed };
  }
  if (kind === "STAKEHOLDER") {
    return { name: trimmed.slice(0, 80) || "Stakeholder", type: "BENEFICIARY", role: trimmed, text: trimmed };
  }
  if (kind === "REALITY_SNAPSHOT") {
    const cycleCount = (allResources ?? []).filter((item) => item.kind === "REALITY_SNAPSHOT").length + 1;
    return { label: `R${cycleCount}`, summary: trimmed, text: trimmed };
  }
  if (kind === "CREATION_CYCLE") {
    return { label: trimmed.slice(0, 80) || "R0-to-R1", status: "READY_TO_CLOSE", summary: trimmed, text: trimmed };
  }
  if (kind === "ACTION") {
    return {
      title: trimmed.slice(0, 80) || "Next action",
      why: trimmed,
      owner_id: "usr_owner",
      status: "PLANNED",
      text: trimmed,
    };
  }
  if (kind === "EXECUTION_EVENT") {
    return {
      type: "BLOCKING_LEGAL_CHANGE",
      materiality: "LOCAL",
      statement: trimmed,
      text: trimmed,
    };
  }
  if (kind === "COMMITMENT_REVIEW") {
    return { status: "READY", finding: trimmed, text: trimmed };
  }
  return { text: trimmed };
};

const labelFor = (value: unknown) => {
  if (typeof value === "string" || typeof value === "number") return String(value);
  return JSON.stringify(value);
};

const isLostProject = (message: string) =>
  /session|not found|access denied|project access|invalid|403/i.test(message);

const formatLiveError = (message: string) => {
  if (/x-session-token is required|session token is invalid|session has expired/i.test(message)) {
    return "Your browser session is missing or expired. Go back to the first page and start a new cycle.";
  }
  if (/project access is denied/i.test(message)) {
    return "This project belongs to an earlier session (often after an API restart). Go back to the first page and start a new cycle.";
  }
  return message;
};

type InterviewStep = { id: string; ask: string; hint: string };

const interviewsByGate: Record<number, { title: string; intro: string; steps: InterviewStep[]; compose: (answers: Record<string, string>, seed: string) => string }> = {
  1: {
    title: "CTF asks about Reality",
    intro: "Answer a few short questions. CTF will turn your answers into the Reality record for Gate 1.",
    steps: [
      { id: "observed", ask: "What is happening right now that you can point to?", hint: "Facts, events, or symptoms — not solutions yet." },
      { id: "who", ask: "Who is most affected?", hint: "People, teams, or groups living with this situation." },
      { id: "constraint", ask: "What limits what you can change?", hint: "Rules, budget, time, technology, politics." },
      { id: "unknown", ask: "What do you still not know?", hint: "One material unknown is enough." },
    ],
    compose: (answers) =>
      [
        answers.observed && `Observed: ${answers.observed}`,
        answers.who && `Affected: ${answers.who}`,
        answers.constraint && `Constraint: ${answers.constraint}`,
        answers.unknown && `Unknown: ${answers.unknown}`,
      ].filter(Boolean).join("\n"),
  },
  2: {
    title: "CTF asks about the Question",
    intro: "CTF will ask what you are really trying to change. Your answers become the Question record for Gate 2.",
    steps: [
      { id: "change", ask: "If this cycle succeeds, what would be different for people?", hint: "Describe the change in outcome, not a product idea." },
      { id: "stuck", ask: "What keeps going wrong, or staying stuck, today?", hint: "The pattern you keep seeing." },
      { id: "scope", ask: "What should we deliberately leave out of this cycle?", hint: "Boundaries keep the question honest." },
      { id: "question", ask: "In one sentence: what question is worth creating around?", hint: "Start with How might… / What causes… / How do we… if helpful." },
    ],
    compose: (answers, seed) =>
      answers.question?.trim()
      || [
        answers.change && `Desired change: ${answers.change}`,
        answers.stuck && `What stays stuck: ${answers.stuck}`,
        answers.scope && `Out of scope: ${answers.scope}`,
        seed && `From starting situation: ${seed}`,
      ].filter(Boolean).join("\n"),
  },
  3: {
    title: "CTF asks about Perception",
    intro: "These questions surface what you might be missing before you confirm Gate 3.",
    steps: [
      { id: "before", ask: "How did you see this problem before?", hint: "Your earlier frame or assumption." },
      { id: "now", ask: "How might you see it differently now?", hint: "A shift, contradiction, or blind spot." },
      { id: "basis", ask: "What makes that shift plausible?", hint: "Evidence, experience, or a clear hypothesis." },
    ],
    compose: (answers) =>
      [
        answers.before && `Previously we saw: ${answers.before}`,
        answers.now && `Now we may see: ${answers.now}`,
        answers.basis && `Basis: ${answers.basis}`,
      ].filter(Boolean).join("\n"),
  },
  4: {
    title: "CTF asks about Evidence readiness",
    intro: "You can acknowledge uncertainty, or capture one piece of evidence you already trust.",
    steps: [
      { id: "know", ask: "What do you already know with some confidence?", hint: "A fact, observation, or supported claim." },
      { id: "source", ask: "Where does that come from?", hint: "Interview, document, log, or your own observation." },
      { id: "gap", ask: "What evidence is still missing?", hint: "Be honest about the gap." },
    ],
    compose: (answers) =>
      [
        answers.know && answers.know,
        answers.source && `Source: ${answers.source}`,
        answers.gap && `Still missing: ${answers.gap}`,
      ].filter(Boolean).join("\n"),
  },
  5: {
    title: "CTF asks about Opportunity",
    intro: "Name a possibility opened by what you know so far. CTF will save it as an Opportunity linked to earlier records.",
    steps: [
      { id: "possibility", ask: "What becomes newly possible if we act on this?", hint: "An opportunity, not a finished product." },
      { id: "forWhom", ask: "Who would benefit first?", hint: "Keep it concrete." },
      { id: "whyNow", ask: "Why is this worth exploring now?", hint: "Link it to the reality or evidence you already have." },
    ],
    compose: (answers) =>
      [
        answers.possibility,
        answers.forWhom && `For: ${answers.forWhom}`,
        answers.whyNow && `Why now: ${answers.whyNow}`,
      ].filter(Boolean).join("\n"),
  },
  6: {
    title: "CTF asks for a Spark",
    intro: "Turn the selected Opportunity into a provocative What if… spark.",
    steps: [
      { id: "spark", ask: "What if…?", hint: "One bold, short spark sentence." },
      { id: "tension", ask: "What tension or surprise does that spark introduce?", hint: "Keep it short." },
    ],
    compose: (answers) =>
      [answers.spark, answers.tension && `Tension: ${answers.tension}`].filter(Boolean).join("\n"),
  },
  7: {
    title: "CTF asks about the Idea",
    intro: "Shape one workable idea from the selected Spark.",
    steps: [
      { id: "name", ask: "What do you call this idea?", hint: "A short working name." },
      { id: "what", ask: "What is it, in plain language?", hint: "What would exist or change." },
      { id: "unknown", ask: "What is still unknown?", hint: "One honest unknown is enough." },
    ],
    compose: (answers) =>
      [
        answers.name && answers.what ? `${answers.name}: ${answers.what}` : answers.what || answers.name,
        answers.unknown && `Unknown: ${answers.unknown}`,
      ].filter(Boolean).join("\n"),
  },
};

function StageInterview({
  gate,
  kind,
  seed,
  realitySummary,
  busy,
  onSave,
}: {
  gate: number;
  kind: string;
  seed: string;
  realitySummary?: string;
  busy: boolean;
  onSave: (text: string) => Promise<void>;
}) {
  const script = interviewsByGate[gate];
  const [stepIndex, setStepIndex] = useState(0);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [draft, setDraft] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);

  useEffect(() => {
    setStepIndex(0);
    setAnswers({});
    setDraft("");
    setLocalError(null);
  }, [gate, kind]);

  const composed = useMemo(
    () => (script ? script.compose(answers, seed) : ""),
    [answers, script, seed],
  );

  if (!script) return null;

  const step = script.steps[Math.min(stepIndex, script.steps.length - 1)];
  const currentAnswer = answers[step.id] ?? "";
  const completed = stepIndex >= script.steps.length;

  const saveAnswer = () => {
    if (!currentAnswer.trim()) {
      setLocalError("Please answer before continuing.");
      return;
    }
    setLocalError(null);
    const nextAnswers = { ...answers, [step.id]: currentAnswer.trim() };
    setAnswers(nextAnswers);
    if (stepIndex + 1 >= script.steps.length) {
      setDraft(script.compose(nextAnswers, seed));
      setStepIndex(script.steps.length);
      return;
    }
    setStepIndex(stepIndex + 1);
  };

  return (
    <section className="interview-panel" aria-label={script.title} data-testid="stage-interview">
      <header>
        <MessageCircle size={18} />
        <div>
          <strong>{script.title}</strong>
          <p>{script.intro}</p>
        </div>
      </header>
      {realitySummary && (
        <aside className="interview-context">
          <small>From your Reality</small>
          <p>{realitySummary}</p>
        </aside>
      )}
      {!completed ? (
        <>
          <div className="interview-progress" aria-hidden>
            {script.steps.map((item, index) => (
              <span key={item.id} className={index < stepIndex ? "done" : index === stepIndex ? "active" : ""} />
            ))}
          </div>
          <p className="interview-count">Question {stepIndex + 1} of {script.steps.length}</p>
          <h3>{step.ask}</h3>
          <p className="interview-hint">{step.hint}</p>
          <textarea
            aria-label={step.ask}
            data-testid="interview-answer"
            value={currentAnswer}
            onChange={(event) => setAnswers((previous) => ({ ...previous, [step.id]: event.target.value }))}
            placeholder="Type your answer…"
          />
          {localError && <p className="status-error">{localError}</p>}
          <div className="live-controls">
            <button className="primary" type="button" data-testid="interview-next" disabled={busy} onClick={saveAnswer}>
              {stepIndex + 1 >= script.steps.length ? "Review my answers" : "Next question"}
            </button>
            {stepIndex > 0 && (
              <button className="quiet-button" type="button" disabled={busy} onClick={() => { setLocalError(null); setStepIndex(stepIndex - 1); }}>
                Back
              </button>
            )}
          </div>
        </>
      ) : (
        <>
          <h3>Here is the {kind.replaceAll("_", " ").toLowerCase()} CTF heard from you</h3>
          <p className="interview-hint">Edit if needed, then save. After it is saved you can confirm the human gate.</p>
          <textarea aria-label={`Composed ${kind}`} data-testid="interview-composed" value={draft || composed} onChange={(event) => setDraft(event.target.value)} />
          <div className="live-controls">
            <button
              className="primary"
              type="button"
              data-testid="interview-save"
              disabled={busy || !(draft || composed).trim()}
              onClick={() => void onSave((draft || composed).trim())}
            >
              Save {kind.replaceAll("_", " ").toLowerCase()}
            </button>
            <button className="quiet-button" type="button" disabled={busy} onClick={() => { setStepIndex(0); setLocalError(null); }}>
              Ask me again
            </button>
          </div>
        </>
      )}
    </section>
  );
}

function HonestState({ title, children }: { title: string; children: React.ReactNode }) {
  return <section className="live-state" role="status"><Info size={18} /><div><h2>{title}</h2><div className="live-state-body">{children}</div></div></section>;
}

function ResourceCard({ resource, onConfirm }: { resource: CTFResource; onConfirm?: () => void }) {
  const provenance = resource.data.source_location ?? resource.data.provenance ?? resource.provenance;
  const candidate = ["CANDIDATE", "CANDIDATE_UNCONFIRMED", "PROPOSED"].includes(resource.status);
  if (resource.kind === "ACTION") {
    const title = typeof resource.data.title === "string" ? resource.data.title : "Action";
    const why = typeof resource.data.why === "string" ? resource.data.why : resource.data.text;
    return (
      <article className="live-resource live-resource-action">
        <header><strong>{title}</strong><span>{resource.status}</span></header>
        {typeof why === "string" && why.trim() && <p>{why.trim()}</p>}
        <footer>v{resource.version}</footer>
      </article>
    );
  }
  if (resource.kind === "COMMITMENT_REVIEW") {
    const finding = typeof resource.data.finding === "string"
      ? resource.data.finding
      : resource.data.text;
    return (
      <article className="live-resource">
        <header><strong>Commitment review</strong><span>{resource.status}</span></header>
        {typeof finding === "string" && finding.trim() && <p>{finding.trim()}</p>}
        <footer>v{resource.version}</footer>
      </article>
    );
  }
  if (resource.kind === "EXECUTION_EVIDENCE") {
    const statement = typeof resource.data.statement === "string"
      ? resource.data.statement
      : resource.data.text;
    return (
      <article className="live-resource">
        <header><strong>Execution evidence</strong><span>{resource.status}</span></header>
        {typeof statement === "string" && statement.trim() && <p>{statement.trim()}</p>}
        <footer>v{resource.version}</footer>
      </article>
    );
  }
  if (resource.kind === "CREATION_RECORD") {
    const title = typeof resource.data.title === "string" ? resource.data.title : "Creation record";
    const summary = typeof resource.data.text === "string" ? resource.data.text : resource.data.summary;
    return (
      <article className="live-resource">
        <header><strong>{title}</strong><span>{resource.status}</span></header>
        {typeof summary === "string" && summary.trim() && <p>{summary.trim()}</p>}
        <footer>v{resource.version}</footer>
      </article>
    );
  }
  const visible = Object.entries(resource.data).filter(([key]) => !["object_key", "checksum_sha256"].includes(key)).slice(0, 7);
  return (
    <article className="live-resource" data-testid="resource-card" data-resource-id={resource.id} data-status={resource.status} data-immutable={resource.immutable ? "true" : "false"}>
      <header>
        <strong>{resource.kind.replaceAll("_", " ")}</strong>
        <span>{resource.status}</span>
        {candidate && <span data-testid="ai-proposal-badge">AI proposal</span>}
      </header>
      {visible.map(([key, value]) => <p key={key}><small>{key.replaceAll("_", " ")}</small>{labelFor(value)}</p>)}
      <footer>Provenance: {labelFor(provenance)} · v{resource.version}</footer>
      {candidate && onConfirm && <button className="secondary" onClick={onConfirm}>Confirm as human evidence</button>}
    </article>
  );
}

function DocumentPanel({ projectId, onChanged }: { projectId: string; onChanged: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [job, setJob] = useState<DocumentJob | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!job || !["QUEUED", "PROCESSING"].includes(String(job.data.status ?? job.status))) return;
    const timer = window.setInterval(() => {
      ctfClient.getDocumentJob(projectId, job.id).then((next) => {
        setJob(next);
        if (!["QUEUED", "PROCESSING"].includes(String(next.data.status ?? next.status))) onChanged();
      }).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Document status unavailable."));
    }, 1200);
    return () => window.clearInterval(timer);
  }, [job, onChanged, projectId]);

  const upload = async () => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const attachment = await ctfClient.uploadAttachment(projectId, file);
      const next = await ctfClient.analyzeDocument(projectId, attachment.id);
      setJob(next);
      onChanged();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Upload failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="live-tool">
      <h3><CloudUpload size={17} /> Document evidence</h3>
      <p>Upload a source document, start extraction, and review candidate records. Extracted claims remain unconfirmed.</p>
      <div className="live-controls">
        <input aria-label="Choose evidence document" type="file" accept=".pdf,.docx,.xlsx,.txt,.csv" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
        <button className="primary" disabled={!file || busy} onClick={upload}>{busy ? "Uploading…" : "Upload and analyze"}</button>
      </div>
      {job && <p className="job-status" aria-live="polite">Job {String(job.data.status ?? job.status)} · {Number(job.data.progress ?? 0)}% · {JSON.stringify(job.data.counts ?? {})}</p>}
      {error && <p className="status-error">{error}</p>}
    </section>
  );
}

const stageAIHelp: Record<string, { title: string; help: string; operation: string; persist: string; prompt: (seed: string) => string }> = {
  REALITY: {
    title: "Optional: draft Reality with AI",
    help: "The local model can propose a Reality record from your starting idea. It never confirms the gate. You still review the draft and click the human decision below.",
    operation: "REALITY_UPDATE",
    persist: "REALITY",
    prompt: (seed) => `Return compact JSON only. Propose a short Reality draft of what appears true right now (few short items, no long essays): ${seed}`,
  },
  QUESTION: {
    title: "Optional: draft a Question with AI",
    help: "The local model can propose the change question. You still confirm Gate 2 yourself.",
    operation: "QUESTION_REFRAME",
    persist: "QUESTION",
    prompt: (seed) => `Return compact JSON only. Propose up to three short change questions for: ${seed}`,
  },
  PERCEPTION: {
    title: "Optional: draft Perception with AI",
    help: "The local model can propose what might be missing. You still confirm Gate 3 yourself.",
    operation: "PERCEPTION_SYNTHESIS",
    persist: "PERCEPTION",
    prompt: (seed) => `Return compact JSON only. Propose a short perception shift or blind spot for: ${seed}`,
  },
};

function StageAIHelp({ project, suggestedKind, onChanged }: { project: CTFProject; suggestedKind: string | null; onChanged: () => void }) {
  const help = suggestedKind ? stageAIHelp[suggestedKind] : undefined;
  const [readiness, setReadiness] = useState<AIReadiness | null>(null);
  const [prompt, setPrompt] = useState(() => help?.prompt(project.initial_input.trim()) ?? project.initial_input);
  const [status, setStatus] = useState("Checking local AI…");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const ready = await ctfClient.getAIReadiness();
      setReadiness(ready);
      setStatus(ready.ready ? "Local AI can draft a proposed record." : "Local AI is not ready, so drafting is unavailable.");
    } catch (reason) {
      setReadiness(null);
      setStatus(reason instanceof Error ? reason.message : "AI status unavailable.");
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  if (!help) return null;

  const draft = async () => {
    if (!prompt.trim()) return;
    setBusy(true);
    setStatus("Drafting… this can take a minute on CPU.");
    try {
      await ctfClient.executeAI(project.id, {
        operation: help.operation,
        user_input: prompt.trim(),
        consequentiality: "MEDIUM",
        expected_version: project.version,
        persist_as: help.persist,
      });
      setStatus("A proposed draft was saved. Review it above, then use the human decision to continue.");
      onChanged();
    } catch (reason) {
      setStatus(reason instanceof Error ? reason.message : "AI draft failed. You can still type the record yourself.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="live-tool">
      <h3><Activity size={17} /> {help.title}</h3>
      <p>{help.help}</p>
      <p><strong>{status}</strong></p>
      <label className="ai-draft-label">
        What should the draft be based on?
        <textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} />
      </label>
      <div className="live-controls">
        <button className="secondary" type="button" data-testid="draft-with-ai" disabled={busy || !readiness?.ready || !prompt.trim()} onClick={() => void draft()}>
          <Play size={14} /> Draft with AI
        </button>
        <button className="quiet-button" type="button" disabled={busy} onClick={() => void refresh()}>Retry AI status</button>
      </div>
    </section>
  );
}

function ERILivePanel({ projectId }: { projectId: string }) {
  const [providers, setProviders] = useState<Record<string, unknown>[]>([]);
  const [events, setEvents] = useState<CTFResource[]>([]);
  const [status, setStatus] = useState("Loading…");

  useEffect(() => {
    Promise.all([ctfClient.getERIProviders(), ctfClient.getERIEvents(projectId)])
      .then(([providerData, eventData]) => {
        setProviders(providerData);
        setEvents(eventData);
        const connected = providerData.some((item) => ["CONNECTED", "ONLINE", "READY"].includes(String(item.status).toUpperCase()));
        setStatus(connected ? "CONNECTED" : "NOT CONNECTED");
      })
      .catch((reason: unknown) => setStatus(reason instanceof Error ? `OFFLINE · ${reason.message}` : "OFFLINE"));
  }, [projectId]);

  return (
    <aside className="eri-panel live-eri" aria-label="External Reality Intelligence">
      <header><div><Radar size={14} /> ERI</div><strong>{status}</strong></header>
      <div className="eri-context"><small>Provider truth</small><strong>{status}</strong><span>{providers.length} provider record(s)</span></div>
      <section><div className="eri-section-title"><span>Real events</span><small>{events.length}</small></div>
        {events.length ? events.map((event) => <ResourceCard key={event.id} resource={event} />) : <p className="empty-copy">No external reality events have been ingested. No live signals are claimed.</p>}
      </section>
    </aside>
  );
}

export function LiveWorkspace({ initialProject, onStartOver }: { initialProject: CTFProject; onStartOver: () => void }) {
  const [workspace, setWorkspace] = useState<WorkspaceResponse | null>(null);
  const [active, setActive] = useState<Stage>(() => stages.find((item) => item.gate === initialProject.active_gate.number) ?? stages[0]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [resourceText, setResourceText] = useState(initialProject.initial_input);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [decision, setDecision] = useState("");
  const [rationale, setRationale] = useState("");
  const [actionTitle, setActionTitle] = useState("");
  const [actionWhy, setActionWhy] = useState("");
  const [reviewFinding, setReviewFinding] = useState("");
  const [evidenceStatement, setEvidenceStatement] = useState("");
  const [creationRecordText, setCreationRecordText] = useState("");
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [syncedAt, setSyncedAt] = useState<string | null>(null);

  const leaveCycle = () => {
    if (window.confirm("Leave this cycle and return to the first page? You can start a different idea from there.")) {
      onStartOver();
    }
  };

  const refresh = useCallback(async () => {
    setRefreshing(true);
    try {
      const data = await ctfClient.getWorkspace(initialProject.id);
      setWorkspace(data);
      setError(null);
      setSyncedAt(new Date().toLocaleTimeString());
      const nav = resolveLiveNavigation(data.project, data.resources);
      setActive((previous) => {
        if (previous.gate > nav.navigableThrough) return stageForGate(nav.workingGate);
        if (nav.inActionPhase && previous.gate === 13) return stageForGate(14);
        if (nav.inValuePrepPhase && previous.gate <= 15) return stageForGate(15);
        if (nav.pendingGate && previous.gate !== nav.pendingGate) return stageForGate(nav.workingGate);
        return previous;
      });
      return data;
    } catch (reason) {
      setError(formatLiveError(reason instanceof Error ? reason.message : "Workspace unavailable."));
      return null;
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [initialProject.id]);

  useEffect(() => {
    void ensureLiveSession().then(() => refresh());
    const timer = window.setInterval(refresh, 5000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const project = workspace?.project ?? initialProject;
  const allResources = workspace?.resources ?? [];
  const navigation = useMemo(() => resolveLiveNavigation(project, allResources), [project, allResources]);
  const currentGate = project.active_gate.number;
  const kind = resourceKindByGate[active.gate];
  const isPendingGate = navigation.pendingGate === active.gate && project.active_gate.status === "PENDING";
  const isActionWorkspace = navigation.inActionPhase && active.gate === 14;
  const isValuePrepWorkspace = navigation.inValuePrepPhase && active.gate === 15;
  const actionPhaseKind = isActionWorkspace ? "ACTION" : kind;
  const requiredKinds = isActionWorkspace || isValuePrepWorkspace
    ? []
    : navigation.redecisionPending && active.gate === 14
      ? ["EXECUTION_EVENT"]
      : requiredKindsByGate[active.gate] ?? (kind ? [kind] : []);
  const resources = workspace?.resources.filter((item) => requiredKinds.includes(item.kind)) ?? [];
  const actionResources = allResources.filter((item) => item.kind === "ACTION");
  const executionEvidence = allResources.filter((item) => item.kind === "EXECUTION_EVIDENCE");
  const creationRecords = allResources.filter((item) => item.kind === "CREATION_RECORD");
  const commitmentReviews = allResources.filter((item) => item.kind === "COMMITMENT_REVIEW");
  const candidateEvidence = allResources.filter((item) => ["CLAIM", "EVIDENCE"].includes(item.kind) && item.provenance === "DOCUMENT");
  const isCurrent = isPendingGate || isActionWorkspace || isValuePrepWorkspace;

  const needsSelection = selectionGates.has(active.gate);
  const selectionReady = !needsSelection || selectedIds.length > 0 || resources.length > 0;
  const hasRequiredRecords = requiredKinds.length === 0
    || requiredKinds.every((requiredKind) => allResources.some((item) => item.kind === requiredKind))
    || (currentGate === 4); // Gate 4 may advance by acknowledging uncertainty without Evidence.
  const selectedIdea = useMemo(() => findSelectedIdea(allResources), [allResources]);
  const gate11Decision = (decision || gateDecisionFor(11).decision).toUpperCase();
  const gate11BriefReady = allResources.some((item) => item.kind === "DECISION_BRIEF");
  const gate11RecReady = allResources.some((item) => item.kind === "RECOMMENDATION");
  const gate11RationaleOk = gate11Decision !== "CONDITIONAL_GO" || rationale.trim().length > 0;
  const canSubmit = active.gate === 11 && isCurrent
    ? hasRequiredRecords && Boolean(selectedIdea) && gate11RationaleOk
    : isActionWorkspace || isValuePrepWorkspace
      ? false
      : navigation.reaffirmPending && active.gate === 15
        ? hasRequiredRecords
        : (hasRequiredRecords || Boolean(kind && resourceText.trim())) && selectionReady;

  const parentIdsForKind = (resourceKind: string) => {
    if (selectedIds.length && ["SPARK", "IDEA"].includes(resourceKind)) return selectedIds;
    return idsOfKinds(allResources, genealogyParentsFor(resourceKind));
  };

  const ensureGate11Context = async (idea: CTFResource, recommendation: string) => {
    if (!allResources.some((item) => item.kind === "DECISION_BRIEF")) {
      await ctfClient.createResource(
        project.id,
        "DECISION_BRIEF",
        { idea_id: idea.id, idea_version: Number(idea.version), status: "CONFIRMED" },
        "SYSTEM",
      );
    }
    if (!allResources.some((item) => item.kind === "RECOMMENDATION")) {
      await ctfClient.createResource(
        project.id,
        "RECOMMENDATION",
        { recommendation, status: "CURRENT" },
        "CTF",
      );
    }
  };

  const prepareDecisionPack = async () => {
    if (!selectedIdea) {
      setError("No selected Idea found. Go back to Gate 7 and confirm your idea selection first.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await ensureGate11Context(selectedIdea, gate11Decision);
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not prepare the decision pack.");
    } finally {
      setBusy(false);
    }
  };

  const requestCommitmentReview = async () => {
    if (!reviewFinding.trim()) {
      setError("Write a short finding before requesting the commitment review.");
      return;
    }
    if (!actionResources.length) {
      setError("Save at least one action before requesting a commitment review.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await ctfClient.createResource(
        project.id,
        "COMMITMENT_REVIEW",
        { status: "READY", finding: reviewFinding.trim(), text: reviewFinding.trim() },
      );
      setReviewFinding("");
      const next = await refresh();
      if (next) {
        setActive(stageForGate(15));
      }
    } catch (reason) {
      setError(formatLiveError(reason instanceof Error ? reason.message : "Could not request commitment review."));
    } finally {
      setBusy(false);
    }
  };

  const saveExecutionEvidence = async () => {
    const action = actionResources[0];
    if (!action) {
      setError("Save at least one action on Gate 14 before recording evidence.");
      return;
    }
    if (!evidenceStatement.trim()) {
      setError("Describe what the action proved or observed.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await ctfClient.createResource(project.id, "EXECUTION_EVIDENCE", {
        action_id: action.id,
        statement: evidenceStatement.trim(),
        text: evidenceStatement.trim(),
      });
      setEvidenceStatement("");
      await refresh();
    } catch (reason) {
      setError(formatLiveError(reason instanceof Error ? reason.message : "Could not save execution evidence."));
    } finally {
      setBusy(false);
    }
  };

  const saveCreationRecord = async () => {
    const evidence = executionEvidence[executionEvidence.length - 1];
    if (!evidence) {
      setError("Save execution evidence first.");
      return;
    }
    if (!creationRecordText.trim()) {
      setError("Summarize the creation outcome.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await ctfClient.createResource(project.id, "CREATION_RECORD", {
        title: creationRecordText.trim().slice(0, 80) || "Creation outcome",
        type: "PROTOTYPE",
        evidence_refs: [evidence.id],
        text: creationRecordText.trim(),
      });
      setCreationRecordText("");
      const next = await refresh();
      if (next) setActive(stageForGate(16));
    } catch (reason) {
      setError(formatLiveError(reason instanceof Error ? reason.message : "Could not save creation record."));
    } finally {
      setBusy(false);
    }
  };

  const saveRealizedValue = async () => {
    const stakeholder = allResources.filter((item) => item.kind === "STAKEHOLDER").slice(-1)[0];
    if (!stakeholder) {
      setError("Save a stakeholder at Gate 16 first.");
      return;
    }
    if (!resourceText.trim()) {
      setError("Describe the value that was realized.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const evidence = await ctfClient.createResource(project.id, "EVIDENCE", {
        statement: resourceText.trim(),
      });
      await ctfClient.createResource(project.id, "REALIZED_VALUE", {
        stakeholder_id: stakeholder.id,
        evidence_refs: [evidence.id],
        statement: resourceText.trim(),
        text: resourceText.trim(),
      });
      setResourceText("");
      await refresh();
    } catch (reason) {
      setError(formatLiveError(reason instanceof Error ? reason.message : "Could not save realized value."));
    } finally {
      setBusy(false);
    }
  };

  const addResource = async () => {
    if (active.gate === 17 && isPendingGate) {
      await saveRealizedValue();
      return;
    }
    const saveKind = isActionWorkspace ? "ACTION" : kind;
    if (isActionWorkspace) {
      if (!actionWhy.trim() && !resourceText.trim()) return;
    } else if (!saveKind || !resourceText.trim()) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const latest = await refresh();
      const sourceResources = latest?.resources ?? allResources;
      const payload = isActionWorkspace
        ? {
          title: actionTitle.trim() || actionWhy.trim().slice(0, 80) || resourceText.trim().slice(0, 80) || "Next action",
          why: actionWhy.trim() || resourceText.trim(),
          owner_id: "usr_owner",
          status: "PLANNED",
          text: actionWhy.trim() || resourceText.trim(),
        }
        : buildResourceData(saveKind!, resourceText, sourceResources, parentIdsForKind(saveKind!));
      const created = await ctfClient.createResource(
        project.id,
        saveKind!,
        payload,
        saveKind === "DECISION_BRIEF" ? "SYSTEM" : "USER",
      );
      if (active.gate === 11 && !sourceResources.some((item) => item.kind === "RECOMMENDATION")) {
        await ctfClient.createResource(
          project.id,
          "RECOMMENDATION",
          { recommendation: gate11Decision, status: "CURRENT", text: resourceText.trim() },
          "CTF",
        );
      }
      setResourceText("");
      setActionTitle("");
      setActionWhy("");
      if (needsSelection) {
        setSelectedIds((previous) => (active.gate === 5
          ? Array.from(new Set([...previous, created.id])).slice(0, 3)
          : [created.id]));
      }
      await refresh();
    } catch (reason) {
      setError(formatLiveError(reason instanceof Error ? reason.message : "Resource creation failed."));
    } finally {
      setBusy(false);
    }
  };

  const confirm = async () => {
    if (!canSubmit) {
      if (active.gate === 11) {
        setError(!selectedIdea
          ? "No selected Idea found. Return to Gate 7 and confirm your idea selection first."
          : "Conditional go requires a condition or rationale.");
        return;
      }
      setError(needsSelection && !selectedIds.length && !resources.length
        ? `Save and select a ${kind?.replaceAll("_", " ").toLowerCase() ?? "record"} before continuing.`
        : `Add a ${kind?.replaceAll("_", " ").toLowerCase() ?? "required"} record before confirming this gate.`);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      let ensuredIds = selectedIds;
      if (active.gate === 11 && selectedIdea) {
        await ensureGate11Context(selectedIdea, gate11Decision);
      }
      if (!hasRequiredRecords && kind && resourceText.trim() && currentGate !== 4 && active.gate !== 11) {
        const created = await ctfClient.createResource(
          project.id,
          kind,
          buildResourceData(kind, resourceText, allResources, parentIdsForKind(kind)),
        );
        ensuredIds = active.gate === 5
          ? Array.from(new Set([...selectedIds, created.id])).slice(0, 3)
          : [created.id];
        setSelectedIds(ensuredIds);
      }
      if (needsSelection && !ensuredIds.length && resources.length) {
        ensuredIds = active.gate === 5 ? resources.slice(0, 3).map((item) => item.id) : [resources[0].id];
        setSelectedIds(ensuredIds);
      }
      const defaultInput = gateDecisionFor(active.gate);
      const chosen = decision || defaultInput.decision;
      const payload: Record<string, unknown> = {};
      if ([5, 6, 7].includes(active.gate)) payload.selected_ids = ensuredIds;
      if (active.gate === 11 && selectedIdea) {
        payload.idea_id = selectedIdea.id;
        payload.idea_version = selectedIdea.version;
        if (rationale.trim()) {
          payload.rationale = rationale.trim();
          if (chosen === "CONDITIONAL_GO") payload.conditions = [rationale.trim()];
        }
      }
      if (active.gate === 18) {
        const snapshot = resources[0] ?? allResources.filter((item) => item.kind === "REALITY_SNAPSHOT").slice(-1)[0];
        payload.snapshot_id = ensuredIds[0] || selectedIds[0] || snapshot?.id;
      }
      if (active.gate === 19 && chosen === "CLOSE") {
        const cycle = resources[0] ?? allResources.filter((item) => item.kind === "CREATION_CYCLE").slice(-1)[0];
        payload.cycle_id = ensuredIds[0] || selectedIds[0] || cycle?.id;
      }
      await ctfClient.decideGate(project.id, active.gate, { decision: chosen, payload, expected_version: undefined, actor_type: "HUMAN" });
      setDecision("");
      setSelectedIds([]);
      const next = await refresh();
      if (next) {
        const nav = resolveLiveNavigation(next.project, next.resources);
        if (nav.inValuePrepPhase) setActive(stageForGate(15));
        else setActive(stageForGate(nav.workingGate));
      }
    } catch (reason) {
      setError(formatLiveError(reason instanceof Error ? reason.message : "Gate decision failed."));
    } finally {
      setBusy(false);
    }
  };

  const sliceAccent = slices.find((item) => item.id === active.slice)?.accent ?? "#3e7e68";
  const nextTitle = nextStageTitle[currentGate] ?? `Gate ${currentGate + 1}`;
  const confirmLabel = currentGate === 1
    ? "Confirm reality and go to Question"
    : currentGate === 2
      ? "Confirm question and go to Perception"
      : currentGate === 3
        ? "Confirm perception and continue"
        : currentGate === 4
          ? "Acknowledge evidence state and go to Opportunity"
          : currentGate === 5
            ? "Select opportunity and go to Spark"
            : currentGate === 6
              ? "Select spark and go to Idea"
              : currentGate === 7
                ? "Select idea and continue"
                : currentGate === 11
                  ? "Submit decision and continue"
                  : currentGate === 12
                    ? "Confirm commitment and go to Roadmap"
                    : currentGate === 13
                      ? "Confirm roadmap and go to Actions"
                      : currentGate === 14
                        ? "Confirm redecision and continue"
                        : currentGate === 15
                          ? "Reaffirm commitment and continue"
                          : currentGate === 16
                            ? "Confirm stakeholders and go to Impact"
                            : currentGate === 17
                              ? "Confirm realized value and continue"
                              : currentGate === 18
                                ? "Confirm new reality snapshot"
                                : currentGate === 19
                                  ? "Close creation cycle"
                                  : `Confirm Gate ${currentGate} and continue`;
  const formKind = actionPhaseKind ?? kind;
  const stageLockedCopy = lockedStageMessage(active.gate, navigation);
  const isCompletedStage = (active.gate < navigation.workingGate && !navigation.inValuePrepPhase)
    || (navigation.inActionPhase && active.gate === 13)
    || (active.gate === project.active_gate.number
      && project.active_gate.status === "DECIDED"
      && !navigation.inValuePrepPhase
      && !navigation.inActionPhase
      && !navigation.redecisionPending
      && !navigation.reaffirmPending
      && active.gate !== 14);
  const hasInterview = Boolean(isCurrent && kind && interviewsByGate[currentGate]);
  const realitySummary = useMemo(() => {
    const reality = workspace?.resources.find((item) => item.kind === "REALITY");
    if (!reality) return project.initial_input;
    const text = reality.data.text ?? reality.data.statement ?? reality.data.summary;
    return typeof text === "string" && text.trim() ? text : project.initial_input;
  }, [project.initial_input, workspace?.resources]);

  const saveInterviewRecord = async (text: string) => {
    if (!kind) return;
    setBusy(true);
    setError(null);
    try {
      const created = await ctfClient.createResource(
        project.id,
        kind,
        buildResourceData(kind, text, allResources, parentIdsForKind(kind)),
      );
      setResourceText(text);
      if (needsSelection) {
        setSelectedIds((previous) => (active.gate === 5
          ? Array.from(new Set([...previous, created.id])).slice(0, 3)
          : [created.id]));
      }
      await refresh();
    } catch (reason) {
      setError(formatLiveError(reason instanceof Error ? reason.message : "Could not save your answers."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="app-shell" style={{ "--current-accent": sliceAccent, "--stage-accent": sliceAccent } as React.CSSProperties}>
      <header className="app-header live-header">
        <div className="header-left">
          <button className="brand compact" type="button" onClick={leaveCycle} aria-label="Back to first page">
            <span className="brand-mark">C</span><span>CTF</span>
          </button>
          <strong>Cycle · {project.id.slice(0, 12)}</strong>
          <span>LIVE · v{project.version}{syncedAt ? ` · ${syncedAt}` : ""}</span>
        </div>
        <div className="header-actions">
          <button className="quiet-button" type="button" disabled={refreshing} onClick={() => void refresh()}>
            <RefreshCw size={14} className={refreshing ? "spin" : undefined} /> {refreshing ? "Refreshing…" : "Refresh"}
          </button>
          <button className="quiet-button" type="button" onClick={leaveCycle}><Home size={14} /> New idea</button>
        </div>
      </header>
      <div className="app-body">
        <aside className="slice-rail">
          <div className="rail-label">Server-driven cycle</div>
          {stages.map((stage) => {
            const locked = stage.gate > navigation.navigableThrough;
            return <button key={stage.id} className={`live-stage-link ${active.id === stage.id ? "active" : ""}`} disabled={locked} aria-disabled={locked} onClick={() => !locked && setActive(stage)}>
              {locked && <LockKeyhole size={12} />}<span>{stage.title}</span><small>G{stage.gate}</small>
            </button>;
          })}
        </aside>
        <main className="workspace">
          <div className="stage-header">
            <div><span className="stage-index">{slices.find((item) => item.id === active.slice)?.name} · Gate {active.gate}</span><h1>{active.title}</h1><p>{active.prompt}</p></div>
            <div className="stage-meta">{project.stage} · active gate {currentGate}</div>
          </div>
          <div className="stage-content live-content">
            {loading && <HonestState title="Loading project state">Fetching workspace resources and memory from the server.</HonestState>}
            {error && (
              <HonestState title="Live data error">
                {error}
                {isLostProject(error) && " This usually means the in-memory API was restarted and the previous cycle is gone."}
                <span className="live-error-actions">
                  <button className="secondary" type="button" onClick={() => void refresh()}>Try refresh again</button>
                  <button className="primary" type="button" onClick={onStartOver}>Back to first page</button>
                </span>
              </HonestState>
            )}
            {!loading && (
              <>
                <section className="live-summary"><strong>Project state</strong><span>{project.stage}</span><span>Gate {currentGate}: {project.active_gate.name}</span><span>Version {project.version}</span></section>
                {isCurrent && (
                  <section className="next-steps" aria-label="How to reach the next gate">
                    <strong>{isActionWorkspace ? "Action phase" : isValuePrepWorkspace ? "Value prep — unlock Gate 16" : `How to reach ${nextTitle}`}</strong>
                    <ol>
                      {isValuePrepWorkspace ? (
                        <>
                          <li className={actionResources.length ? "done" : "todo"}>
                            {actionResources.length
                              ? `Done: ${actionResources.length} action${actionResources.length === 1 ? "" : "s"} from Gate 14.`
                              : "You need at least one saved action from Gate 14."}
                          </li>
                          <li className={executionEvidence.length ? "done" : "todo"}>
                            {executionEvidence.length
                              ? "Done: execution evidence recorded."
                              : "Describe what your action proved or observed."}
                          </li>
                          <li className={creationRecords.length ? "done" : "todo"}>
                            {creationRecords.length
                              ? "Done: creation record saved — Gate 16 is open."
                              : "Save a creation record. That unlocks Gate 16 · Value."}
                          </li>
                        </>
                      ) : isActionWorkspace ? (
                        <>
                          <li className={actionResources.length ? "done" : "todo"}>
                            {actionResources.length
                              ? `Done: ${actionResources.length} action${actionResources.length === 1 ? "" : "s"} saved.`
                              : "Add at least one action below."}
                          </li>
                          <li className={commitmentReviews.length || navigation.reaffirmPending ? "done" : "todo"}>
                            {commitmentReviews.length || navigation.reaffirmPending
                              ? "Done: commitment review requested — Gate 15 is open."
                              : "Request a commitment review below to open Gate 15 · Reaffirm."}
                          </li>
                          <li className="todo">Redecision (Gate 14) is only needed when a decision-relevant execution event occurs.</li>
                        </>
                      ) : hasInterview ? (
                        <li className={hasRequiredRecords ? "done" : "todo"}>
                          {hasRequiredRecords
                            ? `Done: your ${kind?.replaceAll("_", " ").toLowerCase()} answers are saved.`
                            : "Answer CTF’s questions below. CTF will turn your answers into the required record."}
                        </li>
                      ) : requiredKinds.map((requiredKind) => {
                        const count = workspace?.resources.filter((item) => item.kind === requiredKind).length ?? 0;
                        return (
                          <li key={requiredKind} className={count ? "done" : "todo"}>
                            {count ? "Done: " : "Required: "}add at least one {requiredKind.replaceAll("_", " ").toLowerCase()} record
                            {count ? ` (${count} saved)` : " in the box below"}.
                          </li>
                        );
                      })}
                      {!hasInterview && requiredKinds.length === 0 && !isActionWorkspace && <li className="todo">No extra record is required for this gate.</li>}
                      {!isActionWorkspace && !isValuePrepWorkspace && (
                      <li className={hasRequiredRecords && (!needsSelection || selectedIds.length > 0 || resources.length > 0) ? "todo" : "waiting"}>
                        {needsSelection
                          ? `Select the ${kind?.replaceAll("_", " ").toLowerCase() ?? "record"} below, then confirm to unlock the next stage.`
                          : `Then confirm the Gate ${currentGate} human decision. That unlocks the next stage.`}
                      </li>
                      )}
                    </ol>
                  </section>
                )}
                {isCurrent && requiredKinds.length > 0 && <section className="prerequisite-checklist" aria-label="Gate prerequisites"><strong>Gate {currentGate} checklist</strong>{requiredKinds.map((requiredKind) => {
                  const count = workspace?.resources.filter((item) => item.kind === requiredKind).length ?? 0;
                  return <span key={requiredKind} className={count ? "ready" : "missing"}>{requiredKind.replaceAll("_", " ")}: {count ? `${count} available` : "waiting for your answers"}</span>;
                })}</section>}
                {isActionWorkspace && actionResources.length > 0 && (
                  <section className="action-list">
                    <h3>Saved actions</h3>
                    <div className="live-resource-grid">{actionResources.map((item) => <ResourceCard key={item.id} resource={item} />)}</div>
                  </section>
                )}
                {!isActionWorkspace && (resources.length
                  ? <div className="live-resource-grid">{resources.map((item) => <ResourceCard key={item.id} resource={item} />)}</div>
                  : (
                    hasInterview
                      ? null
                      : <HonestState title={`${kind?.replaceAll("_", " ") ?? active.title} not configured`}>No matching server resource exists for this stage yet.</HonestState>
                  ))}
                {resources.length > 0 && needsSelection && (
                  <fieldset className="selection-form">
                    <legend>
                      {active.gate === 5
                        ? "Select up to 3 opportunities to take forward"
                        : active.gate === 6
                          ? "Select the spark to take forward"
                          : active.gate === 7
                            ? "Select the idea to take forward"
                            : "Select record(s) for the gate payload"}
                    </legend>
                    {resources.map((item) => (
                      <label key={item.id}>
                        <input
                          type={active.gate === 5 ? "checkbox" : "radio"}
                          name="gate-resource"
                          checked={selectedIds.includes(item.id)}
                          onChange={(event) => setSelectedIds((previous) => event.target.checked
                            ? (active.gate === 5 ? Array.from(new Set([...previous, item.id])).slice(0, 3) : [item.id])
                            : previous.filter((id) => id !== item.id))}
                        />
                        <span>
                          <strong>{resourceLabel(item)}</strong>
                          <small>{item.id} · {item.status}</small>
                        </span>
                      </label>
                    ))}
                    {!selectedIds.length && <p className="status-error">Select at least one saved record, or confirm will use the first saved one.</p>}
                  </fieldset>
                )}
                {hasInterview && kind && (
                  <StageInterview
                    gate={currentGate}
                    kind={kind}
                    seed={project.initial_input}
                    realitySummary={currentGate === 2 || currentGate === 5 ? realitySummary : undefined}
                    busy={busy}
                    onSave={saveInterviewRecord}
                  />
                )}
                {isActionWorkspace && actionResources.length > 0 && !navigation.reaffirmPending && !commitmentReviews.length && (
                  <section className="prerequisite-form">
                    <h3>Continue to Gate 15 · Reaffirm</h3>
                    <p>Saving actions is not enough on its own. Request a commitment review to open Gate 15.</p>
                    <label>Finding<textarea data-testid="review-finding" value={reviewFinding} onChange={(event) => setReviewFinding(event.target.value)} placeholder="e.g. Commitment still holds after initial actions." /></label>
                    <button className="gate-button" type="button" data-testid="request-review" disabled={busy || !reviewFinding.trim()} onClick={() => void requestCommitmentReview()}>
                      {busy ? "Opening Gate 15…" : "Request commitment review and open Gate 15"}
                    </button>
                  </section>
                )}
                {isActionWorkspace && (
                  <section className="prerequisite-form">
                    <h3>Add action</h3>
                    <p>Describe what your team will do next. Use a short title and a clear why.</p>
                    <label>Title<input data-testid="action-title" value={actionTitle} onChange={(event) => setActionTitle(event.target.value)} placeholder="e.g. Run a safe pilot" /></label>
                    <label>Why<textarea data-testid="action-why" value={actionWhy} onChange={(event) => setActionWhy(event.target.value)} placeholder="What this action proves or unlocks" /></label>
                    <button className="secondary" type="button" data-testid="save-action" disabled={busy || (!actionWhy.trim() && !actionTitle.trim())} onClick={() => void addResource()}>Save action</button>
                  </section>
                )}
                {isCurrent && formKind && !hasInterview && !isActionWorkspace && !isValuePrepWorkspace && (
                  <section className="prerequisite-form">
                    <h3>Add {formKind.replaceAll("_", " ").toLowerCase()}</h3>
                    <p>
                      {isActionWorkspace
                        ? "Roadmap is confirmed. Describe the next action your team will take."
                        : kind === "OPPORTUNITY"
                        ? "Describe the opportunity. CTF will link it to your earlier Reality/Evidence automatically."
                        : kind === "SPARK"
                          ? "Write a What if… spark. CTF will link it to the selected Opportunity."
                          : kind === "IDEA"
                            ? "Describe the idea. CTF will link it to the selected Spark."
                            : kind === "DECISION_BRIEF"
                              ? selectedIdea
                                ? `Write your decision brief. It will be linked to idea ${resourceLabel(selectedIdea)}.`
                                : "Select an Idea at Gate 7 first, then return here to save the decision brief."
                              : kind === "ROADMAP"
                                ? "Describe what must become true. This becomes your roadmap for Gate 13."
                            : kind === "REALIZED_VALUE"
                              ? "Describe the value that was realized for your stakeholder. CTF will link supporting evidence automatically."
                              : kind === "STAKEHOLDER"
                                ? "Name who benefits from the value created. This unlocks Impact (Gate 17) after confirmation."
                                : kind === "REALITY_SNAPSHOT"
                                  ? "Describe the new reality after this creation cycle (R1, R2, …)."
                                  : kind === "CREATION_CYCLE"
                                    ? "Name this creation cycle (e.g. R0-to-R1). Confirm Gate 19 to close the cycle."
                                    : hasRequiredRecords
                                ? `A ${formKind.replaceAll("_", " ").toLowerCase()} record is already saved.`
                                : `Write the ${formKind.replaceAll("_", " ").toLowerCase()} in your own words.`}
                    </p>
                    {active.gate === 11 && (
                      <ul className="gate11-pack-status">
                        <li className={gate11BriefReady ? "ready" : "missing"}>Decision brief: {gate11BriefReady ? "saved" : "waiting"}</li>
                        <li className={gate11RecReady ? "ready" : "missing"}>CTF recommendation: {gate11RecReady ? "saved" : "created with brief"}</li>
                      </ul>
                    )}
                    <label>Record content<textarea data-testid="resource-text" value={resourceText} onChange={(event) => setResourceText(event.target.value)} placeholder={`Create ${formKind.replaceAll("_", " ").toLowerCase()} from known information`} /></label>
                    <button className="secondary" type="button" data-testid="save-resource" disabled={busy || !resourceText.trim() || (active.gate === 11 && !selectedIdea)} onClick={() => void addResource()}>Save {formKind.replaceAll("_", " ").toLowerCase()}</button>
                  </section>
                )}
                {isValuePrepWorkspace && (
                  <>
                    {actionResources.length > 0 && (
                      <section className="action-list">
                        <h3>Actions from Gate 14</h3>
                        <div className="live-resource-grid">{actionResources.map((item) => <ResourceCard key={item.id} resource={item} />)}</div>
                      </section>
                    )}
                    {executionEvidence.length > 0 && (
                      <section className="action-list">
                        <h3>Saved execution evidence</h3>
                        <div className="live-resource-grid">{executionEvidence.map((item) => <ResourceCard key={item.id} resource={item} />)}</div>
                      </section>
                    )}
                    {creationRecords.length > 0 && (
                      <section className="action-list">
                        <h3>Saved creation records</h3>
                        <div className="live-resource-grid">{creationRecords.map((item) => <ResourceCard key={item.id} resource={item} />)}</div>
                      </section>
                    )}
                    {!creationRecords.length && (
                      <>
                        {!executionEvidence.length && actionResources.length > 0 && (
                          <section className="prerequisite-form">
                            <h3>Step 1 · Execution evidence</h3>
                            <p>What did your action prove or observe? This links to your first saved action.</p>
                            <label>Evidence statement<textarea data-testid="execution-evidence" value={evidenceStatement} onChange={(event) => setEvidenceStatement(event.target.value)} placeholder="e.g. The pilot ran successfully and users completed the flow." /></label>
                            <button className="secondary" type="button" data-testid="save-execution-evidence" disabled={busy || !evidenceStatement.trim()} onClick={() => void saveExecutionEvidence()}>Save execution evidence</button>
                          </section>
                        )}
                        {executionEvidence.length > 0 && (
                          <section className="prerequisite-form">
                            <h3>Step 2 · Creation record</h3>
                            <p>Summarize what was created. Saving this opens Gate 16 · Value.</p>
                            <label>Creation outcome<textarea data-testid="creation-record" value={creationRecordText} onChange={(event) => setCreationRecordText(event.target.value)} placeholder="e.g. Portable case pilot delivered and validated." /></label>
                            <button className="gate-button" type="button" data-testid="save-creation-record" disabled={busy || !creationRecordText.trim()} onClick={() => void saveCreationRecord()}>
                              {busy ? "Opening Gate 16…" : "Save creation record and open Gate 16"}
                            </button>
                          </section>
                        )}
                      </>
                    )}
                  </>
                )}
                {navigation.reaffirmPending && active.gate === 15 && commitmentReviews.length > 0 && (
                  <section className="action-list">
                    <h3>Commitment review</h3>
                    <div className="live-resource-grid">{commitmentReviews.map((item) => <ResourceCard key={item.id} resource={item} />)}</div>
                  </section>
                )}
                {isPendingGate ? <section className="gate-card live-gate" data-testid="human-gate">
                  <div className="gate-seal"><LockKeyhole size={18} /><span>G{active.gate}</span></div>
                  <div className="gate-copy"><span>Human decision</span><h3>{confirmLabel}</h3><p>This is the required human step. AI cannot do it. Confirming Gate {currentGate} unlocks {nextTitle}.</p></div>
                  <div className="gate-form">
                    {active.gate === 11 && <select aria-label="Decision" value={decision || "CONDITIONAL_GO"} onChange={(event) => setDecision(event.target.value)}><option value="CONDITIONAL_GO">Conditional go</option><option value="GO">Go</option><option value="VALIDATE_FIRST">Validate first</option><option value="HOLD">Hold</option><option value="NO_GO">No-go</option></select>}
                    {(active.gate === 11) && <input aria-label="Decision rationale or condition" data-testid="gate-rationale" value={rationale} onChange={(event) => setRationale(event.target.value)} placeholder="Required condition or rationale for conditional go" />}
                    <button className="gate-button" type="button" data-testid="confirm-gate" disabled={busy || !canSubmit} onClick={() => void confirm()}>{busy ? "Submitting…" : confirmLabel}</button>
                  </div>
                  {!canSubmit && <p className="status-error">{active.gate === 11
                    ? (!selectedIdea
                      ? "Select an idea at Gate 7 first, then save the decision brief."
                      : !hasRequiredRecords
                        ? "Write your answer above and click Save decision brief."
                        : "Enter a condition or rationale for conditional go.")
                    : needsSelection
                      ? "Save an opportunity/spark/idea first, then select it."
                      : "Add or keep text in the record box above, then this button becomes available."}</p>}
                </section> : !isActionWorkspace && !isValuePrepWorkspace && !loading && (
                  <HonestState title={isCompletedStage ? "Completed stage" : "Locked stage"}>
                    {isCompletedStage
                      ? "This stage is complete. You can review saved records above."
                      : stageLockedCopy}
                    {!isCompletedStage && active.gate > navigation.navigableThrough && (
                      <span className="live-error-actions">
                        <button className="secondary" type="button" onClick={() => setActive(stageForGate(navigation.navigableThrough))}>
                          Go to Gate {navigation.navigableThrough}
                        </button>
                      </span>
                    )}
                  </HonestState>
                )}
                {candidateEvidence.length > 0 && <section><h2>Document candidates</h2><p className="empty-copy">These records are parsed from uploaded documents and remain candidates until a human confirms them.</p><div className="live-resource-grid">{candidateEvidence.map((item) => <ResourceCard key={item.id} resource={item} onConfirm={async () => {
                  setBusy(true);
                  setError(null);
                  try {
                    await ctfClient.confirmResource(project.id, item.kind, item.id);
                    await refresh();
                  } catch (reason) {
                    setError(reason instanceof Error ? reason.message : "Confirmation failed.");
                  } finally {
                    setBusy(false);
                  }
                }} />)}</div></section>}
                <DocumentPanel projectId={project.id} onChanged={refresh} />
                <StageAIHelp project={project} suggestedKind={kind} onChanged={refresh} />
              </>
            )}
          </div>
        </main>
        <ERILivePanel projectId={project.id} />
      </div>
    </div>
  );
}

export function LiveStartUpload({
  file,
  project,
  onComplete,
}: {
  file: File | null;
  project: CTFProject;
  onComplete: () => void;
}) {
  useEffect(() => {
    if (!file) return;
    ctfClient.uploadAttachment(project.id, file)
      .then((attachment) => ctfClient.analyzeDocument(project.id, attachment.id))
      .then(onComplete)
      .catch(() => onComplete());
  }, [file, onComplete, project.id]);
  return null;
}

export type LiveStart = (family: EntryFamily, input: string, file?: File | null) => void;
