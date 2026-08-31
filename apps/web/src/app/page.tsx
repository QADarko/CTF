"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Activity, ArrowRight, BookOpen, Check, CheckCircle2, ChevronDown, ChevronRight,
  CircleDot, CloudUpload, Database, ExternalLink, Eye, FileText, GitBranch,
  Gauge, Info, Link2, LockKeyhole, Menu, MoreHorizontal, PanelRightClose,
  PanelRightOpen, Plus, Radar, Search, Shield, Sparkles, Target, UserRound,
  X,
} from "lucide-react";
import {
  clearLiveClientState, ctfClient, ensureLiveSession, gateDecisionFor, isDemoMode, LIVE_PROJECT_KEY,
  type CapabilityResponse, type CTFProject, type EntryFamily, type ReadinessResponse,
} from "@/lib/api";
import { LiveWorkspace } from "./live-workspace";
import {
  assumptions, blueprint, claims, failureModes, gates, opportunities, project,
  realityItems, roadmap, slices, sparks, stages, stakeholders, traceNodes,
  type Confidence, type Stage,
} from "@/lib/ctf-data";

function Tag({ children, tone = "neutral" }: { children: React.ReactNode; tone?: string }) {
  return <span className={`tag tag-${tone}`}>{children}</span>;
}

function ConfidenceTag({ value }: { value: Confidence | string }) {
  return <span className="confidence"><CircleDot size={10} /> {value} confidence</span>;
}

function StartScreen({
  onStart,
  starting,
  error,
}: {
  onStart: (family: EntryFamily, input: string, file?: File | null) => void;
  starting: boolean;
  error: string | null;
}) {
  const familyToEntry = { create: "CREATION", funding: "FUNDING", document: "DOCUMENT" } as const;
  const [family, setFamily] = useState<keyof typeof familyToEntry>("create");
  const [input, setInput] = useState("Public services are moving online, but the people who need help most are being left behind.");
  const [file, setFile] = useState<File | null>(null);
  const entryFamilies = [
    { id: "create", icon: Sparkles, eyebrow: "Create something", title: "I have a challenge or possibility", copy: "Start from a situation, need, ambition, or a question you cannot yet answer." },
    { id: "funding", icon: Target, eyebrow: "Funding studio", title: "I want to apply for funding", copy: "Connect a call, early application, or funding intent to the same creation cycle." },
    { id: "document", icon: FileText, eyebrow: "Bring context", title: "I have a document or project", copy: "Add existing work as context. Files are not treated as evidence until reviewed." },
  ];

  return (
    <main className="start-shell">
      <nav className="start-nav" aria-label="Primary navigation">
        <a className="brand" href="#" aria-label="CTF home"><span className="brand-mark">C</span><span>CTF</span></a>
        <div className="start-nav-meta">{isDemoMode && <strong className="demo-badge">DEMO · FIXTURE DATA</strong>}<span>Creation, guided by reality.</span><button className="text-button">Sign in</button></div>
      </nav>
      <section className="start-hero">
        <div className="hero-copy">
          <span className="kicker"><span /> CTF creation cycle</span>
          <h1>Turn what is<br /><em>into what could be.</em></h1>
          <p>CTF helps you frame reality, create with evidence, make a human decision, and follow it through to measurable change.</p>
          <div className="hero-principles">
            <span><Check size={14} /> Human-led decisions</span>
            <span><Check size={14} /> Evidence-aware creation</span>
            <span><Check size={14} /> Full path to impact</span>
          </div>
        </div>
        <div className="entry-panel">
          <div className="try-label">TRY ME <span>· no account needed</span></div>
          <h2>Where would you like to begin?</h2>
          <div className="entry-options" role="radiogroup" aria-label="Choose entry type">
            {entryFamilies.map((item) => {
              const Icon = item.icon;
              return (
                <button key={item.id} role="radio" aria-checked={family === item.id} className={`entry-option ${family === item.id ? "selected" : ""}`} onClick={() => setFamily(item.id as keyof typeof familyToEntry)}>
                  <span className="entry-icon"><Icon size={20} /></span>
                  <span><small>{item.eyebrow}</small><strong>{item.title}</strong><em>{item.copy}</em></span>
                  <span className="radio-dot" />
                </button>
              );
            })}
          </div>
          {family === "create" ? (
            <label className="starter-input">
              <span>What is on your mind?</span>
              <textarea value={input} onChange={(event) => setInput(event.target.value)} />
            </label>
          ) : family === "funding" ? (
            <div className="intent-row"><button className="mini-choice selected">I want to apply</button><button className="mini-choice">I plan to apply</button><button className="mini-choice">I have a draft</button></div>
          ) : (
            <label className="upload-zone"><CloudUpload size={22} /><strong>Add project context</strong><span>PDF, DOCX, XLSX, TXT, or CSV · uploaded and parsed after project creation</span><input type="file" className="sr-only" accept=".pdf,.docx,.xlsx,.txt,.csv" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />{file && <em>{file.name}</em>}</label>
          )}
          <button
            className="primary start-button"
            disabled={starting || (family === "create" && !input.trim())}
            onClick={() => onStart(
              familyToEntry[family],
              family === "create" ? input.trim() : family === "funding"
                ? "Prepare a funding application and test whether the intended change is fundable."
                : "Use an existing project document as context for a new creation cycle.",
              file,
            )}
          >
            {starting ? "Starting…" : "Begin with reality"} <ArrowRight size={17} />
          </button>
          {error && <p className="method-note warning"><Info size={15} /> {error}</p>}
          <p className="privacy-note"><Shield size={13} /> Your first insight arrives before we ask you to create an account.</p>
        </div>
      </section>
      <div className="cycle-ribbon" aria-label="Five phases of the CTF cycle">
        {slices.map((slice) => <div key={slice.id}><span>{slice.number}</span><strong>{slice.name}</strong><small>{slice.description}</small></div>)}
      </div>
    </main>
  );
}

function Header({
  onGates,
  eriOpen,
  onEri,
  statusOpen,
  onStatus,
}: {
  onGates: () => void;
  eriOpen: boolean;
  onEri: () => void;
  statusOpen: boolean;
  onStatus: () => void;
}) {
  return (
    <header className="app-header">
      <div className="header-left">
        <button className="icon-button mobile-only" aria-label="Open menu"><Menu size={18} /></button>
        <a className="brand compact" href="#"><span className="brand-mark">C</span><span>CTF</span></a>
        <span className="header-rule" />
        <button className="project-switcher">
          <span><small>{project.code} · {project.cycle}</small><strong>{project.name}</strong></span><ChevronDown size={14} />
        </button>
      </div>
      <div className="header-actions">
        <strong className="demo-badge">DEMO · FIXTURE DATA</strong>
        <span className="saved"><CheckCircle2 size={14} /> Saved</span>
        <button className={`quiet-button ${statusOpen ? "active" : ""}`} onClick={onStatus}><Gauge size={15} /> Architecture status</button>
        <button className="quiet-button" onClick={onGates}><LockKeyhole size={15} /> 19 gates</button>
        <button className={`quiet-button ${eriOpen ? "active" : ""}`} onClick={onEri}><Radar size={15} /> ERI</button>
        <button className="avatar" aria-label="User profile">DK</button>
      </div>
    </header>
  );
}

function SliceRail({ active, onSelect }: { active: Stage; onSelect: (stage: Stage) => void }) {
  return (
    <aside className="slice-rail">
      <div className="rail-label">Creation cycle</div>
      {slices.map((slice) => {
        const sliceStages = stages.filter((item) => item.slice === slice.id);
        const selected = slice.id === active.slice;
        return (
          <section className={`slice-group ${selected ? "selected" : ""}`} key={slice.id} style={{ "--slice-accent": slice.accent } as React.CSSProperties}>
            <button className="slice-heading" onClick={() => onSelect(sliceStages[0])}>
              <span className="slice-num">{slice.number}</span>
              <span><strong>{slice.name}</strong><small>{slice.description}</small></span>
              {selected && <span className="active-line" />}
            </button>
            {selected && (
              <div className="stage-list">
                {sliceStages.map((stage) => {
                  const Icon = stage.icon;
                  return <button key={stage.id} className={active.id === stage.id ? "active" : ""} onClick={() => onSelect(stage)}><Icon size={14} /><span>{stage.title}</span><small>G{stage.gate}</small></button>;
                })}
              </div>
            )}
          </section>
        );
      })}
      <div className="rail-footer"><GitBranch size={15} /><span><strong>Cycle genealogy</strong><small>42 linked decisions</small></span></div>
    </aside>
  );
}

function StageHeader({ stage }: { stage: Stage }) {
  const slice = slices.find((item) => item.id === stage.slice)!;
  return (
    <div className="stage-header" style={{ "--stage-accent": slice.accent } as React.CSSProperties}>
      <div><span className="stage-index">{slice.number} / {String(stages.filter((s) => s.slice === stage.slice).findIndex((s) => s.id === stage.id) + 1).padStart(2, "0")}</span><h1>{stage.title}</h1><p>{stage.prompt}</p></div>
      <div className="stage-meta"><Tag tone="version">Method v1.0</Tag><span>{project.updated}</span><button className="icon-button" aria-label="More options"><MoreHorizontal size={18} /></button></div>
    </div>
  );
}

function GateCard({
  stage,
  onConfirm,
  confirmed,
  disabled,
  error,
}: {
  stage: Stage;
  onConfirm: () => void;
  confirmed: boolean;
  disabled: boolean;
  error: string | null;
}) {
  return (
    <section className={`gate-card ${confirmed ? "is-confirmed" : ""}`}>
      <div className="gate-seal"><LockKeyhole size={18} /><span>G{String(stage.gate).padStart(2, "0")}</span></div>
      <div className="gate-copy">
        <span>Human decision point</span>
        <h3>{confirmed ? `${stage.title} confirmed` : `Confirm this ${stage.title.toLowerCase()} before continuing`}</h3>
        <p>{confirmed ? "Your decision is recorded with this version. You can still review its genealogy." : "CTF can recommend and explain. Only you can move the creation cycle forward."}</p>
      </div>
      <div className="gate-actions">
        {confirmed ? <button className="gate-confirmed"><CheckCircle2 size={16} /> Recorded</button> : <>
          <button className="secondary">Revise</button>
          <button className="gate-button" disabled={disabled} onClick={onConfirm}>I confirm <ArrowRight size={16} /></button>
        </>}
      </div>
      {error && <p className="method-note warning"><Info size={15} /> {error}</p>}
    </section>
  );
}

function FrameContent({ stage }: { stage: Stage["id"] }) {
  if (stage === "question") return (
    <div className="content-stack">
      <section className="context-strip"><span>From confirmed reality</span><p>Access breaks when applicants move between channels, while repeated verification adds delay.</p><ConfidenceTag value="High" /></section>
      <div className="section-heading"><div><span className="eyebrow">Three reframings</span><h2>Choose the question worth creating around</h2></div><Tag tone="human">Human selects</Tag></div>
      <div className="question-grid">
        {[
          ["01 · Systemic", "How might public services preserve continuity when a person needs to change channels?", "Recommended"],
          ["02 · Value", "How might we make speed and equitable access reinforce—not trade against—each other?", "Alternative"],
          ["03 · Causal", "What causes applicants to lose progress between assisted and digital service?", "Diagnostic"],
        ].map((q, i) => <article className={`question-card ${i === 0 ? "selected" : ""}`} key={q[0]}><span>{q[0]}</span><h3>{q[1]}</h3><footer><Tag tone={i === 0 ? "green" : "neutral"}>{q[2]}</Tag><button>{i === 0 ? <Check size={15} /> : "Select"}</button></footer></article>)}
      </div>
      <button className="inline-add"><Plus size={15} /> Write my own question</button>
    </div>
  );

  if (stage === "perception") return (
    <div className="content-stack">
      <div className="section-heading"><div><span className="eyebrow">Perception shift</span><h2>A different way to see the system</h2></div><ConfidenceTag value="Medium" /></div>
      <section className="shift-card">
        <div><span>Previously we saw</span><p>A choice between a fast digital service and a slower assisted service.</p></div>
        <ArrowRight size={23} />
        <div><span>Now we may see</span><p>Continuity—not channel—is the design problem. Assistance can be a moment in one journey.</p></div>
      </section>
      <div className="insight-grid">
        <article><Eye size={19} /><span>Blind spot</span><h3>Channel switching is treated as failure, not a normal need.</h3><p>Raised from interviews with assisted-service users.</p></article>
        <article><GitBranch size={19} /><span>Contradiction</span><h3>The push for digital speed creates duplicate work for complex cases.</h3><p>Supported by operational data and process maps.</p></article>
        <article><Sparkles size={19} /><span>New lens</span><h3>Design the case to travel, rather than asking the person to restart.</h3><p>CTF hypothesis · requires exploration.</p></article>
      </div>
    </div>
  );

  return (
    <div className="content-stack">
      <section className="reality-summary">
        <div><span className="eyebrow">R₀ snapshot · candidate</span><h2>A service transition that risks excluding the people who need continuity most.</h2><p>CTF has separated what is observed from what is inferred. Review each item before confirming the starting reality.</p></div>
        <div className="completeness"><strong>Ready</strong><span>Core reality sufficiently understood</span><div><i /></div></div>
      </section>
      <div className="reality-grid">
        {realityItems.map((item) => <article className="reality-item" key={item.text}><header><Tag tone={item.type === "Assumption" ? "amber" : "neutral"}>{item.type}</Tag><ConfidenceTag value={item.confidence} /></header><h3>{item.text}</h3><footer><Database size={13} /> {item.source}<button aria-label="View provenance"><Link2 size={14} /></button></footer></article>)}
        <button className="add-card"><Plus size={20} /><span>Add what is missing</span></button>
      </div>
      <section className="gap-row"><Info size={17} /><div><strong>One material unknown remains</strong><span>We do not yet know where applicants most often abandon the process.</span></div><Tag tone="amber">Researchable</Tag><button>Carry forward</button></section>
    </div>
  );
}

function CreateContent({ stage }: { stage: Stage["id"] }) {
  if (stage === "opportunity") return (
    <div className="content-stack">
      <div className="section-heading"><div><span className="eyebrow">Opportunity space</span><h2>Three spaces grounded in current evidence</h2></div><span className="selection-count">2 of 3 selected</span></div>
      <div className="opportunity-grid">{opportunities.map((item, i) => <article key={item.id} className={`opportunity-card ${item.selected ? "selected" : ""}`}><header><span>{item.id}</span><button aria-label={item.selected ? "Deselect" : "Select"}>{item.selected ? <CheckCircle2 /> : <CircleDot />}</button></header><h3>{item.title}</h3><p>{item.text}</p><div className="metric-pair"><span>Evidence <strong>{item.evidence}</strong></span><span>Value potential <strong>{item.value}</strong></span></div><button className="trace-link"><GitBranch size={14} /> Why CTF sees this <ChevronRight size={14} /></button>{i === 0 && <span className="recommended-tab">Strongest fit</span>}</article>)}</div>
      <p className="method-note"><Info size={15} /> Opportunities are spaces for creation—not proposed solutions.</p>
    </div>
  );
  if (stage === "spark") return (
    <div className="spark-workspace">
      <div className="spark-intro"><span className="eyebrow">Spark studio</span><h2>Leave the obvious path.</h2><p>These are provocations, not solutions. Choose what opens the most generative direction—or write your own.</p></div>
      <div className="spark-list">{sparks.map((spark, i) => <button className={`spark-card ${i === 1 ? "selected" : ""}`} key={spark.text}><Tag tone={spark.origin === "Yours" ? "human" : "purple"}>{spark.origin}</Tag><blockquote>“{spark.text}”</blockquote><span>{i === 1 ? <><Check size={14} /> Selected spark</> : <>Explore <ArrowRight size={14} /></>}</span></button>)}</div>
      <label className="own-spark"><Sparkles size={18} /><span><strong>Your spark</strong><small>Finish the provocation in your own words.</small></span><input placeholder="What if…" /><button>Develop</button></label>
    </div>
  );
  if (stage === "idea") return (
    <div className="content-stack">
      <section className="idea-title"><div><span className="eyebrow">Idea blueprint · v2</span><h2>One journey, many ways to continue</h2><p>A continuous public-service case that carries verified progress across digital and assisted channels.</p></div><div className="logic-score"><span>Logic check</span><strong>Strong</strong><small>Evidence basis: medium</small></div></section>
      <div className="blueprint-grid">{blueprint.map(([label, text], i) => <article key={label} className={i < 5 ? "major" : ""}><header><span>{String(i + 1).padStart(2, "0")}</span><strong>{label}</strong>{[6, 8].includes(i) && <Tag tone="amber">{i === 6 ? "3 open" : "2 open"}</Tag>}</header><p>{text}</p>{i === 4 && <Tag tone="purple">CTF proposal</Tag>}</article>)}</div>
      <button className="genealogy-button"><GitBranch size={16} /> Show the path to this idea <span>R₀ → Q → P → E → O → S → Idea</span><ChevronRight size={16} /></button>
    </div>
  );
  return (
    <div className="content-stack">
      <div className="dashboard-summary">
        <div><span className="eyebrow">Evidence dashboard</span><h2>We know enough to explore—<br />not enough to assume.</h2></div>
        <div className="evidence-ring"><strong>3</strong><span>material claims</span></div>
        <div className="evidence-legend"><span><i className="green" /> 1 supported</span><span><i className="amber" /> 1 partial</span><span><i className="red" /> 1 contradicted</span></div>
      </div>
      <div className="claim-list">{claims.map((claim) => <article key={claim.id} className="claim-card"><span className={`status-bar ${claim.tone}`} /><div className="claim-id">{claim.id}</div><div className="claim-copy"><h3>{claim.text}</h3><p><FileText size={13} /> {claim.source}</p></div><Tag tone={claim.tone}>{claim.status}</Tag><ConfidenceTag value={claim.confidence} /><button aria-label="Open evidence detail"><ChevronRight size={18} /></button></article>)}</div>
      <div className="evidence-actions"><button><CloudUpload size={17} /><span><strong>Add evidence</strong><small>PDF, DOCX, XLSX</small></span></button><button><Search size={17} /><span><strong>Investigate a gap</strong><small>1 decision-relevant gap</small></span></button><button><BookOpen size={17} /><span><strong>Document library</strong><small>4 sources</small></span></button></div>
    </div>
  );
}

function DecideContent({ stage }: { stage: Stage["id"] }) {
  if (stage === "adversarial") return (
    <div className="content-stack red-team">
      <div className="role-shift"><Shield size={20} /><div><span>Independent reasoning mode</span><strong>CTF is now trying to break the idea—not defend it.</strong></div><Tag tone="red">Red team</Tag></div>
      <div className="section-heading"><div><span className="eyebrow">Failure modes</span><h2>The strongest reasons this could fail</h2></div><button className="secondary">View pre-mortem</button></div>
      <div className="failure-grid">{failureModes.map((mode) => <article key={mode.title}><header><Tag tone="red">{mode.category}</Tag><Tag tone={mode.basis === "Hypothetical" ? "amber" : "neutral"}>{mode.basis}</Tag></header><h3>{mode.title}</h3><div><span>Impact <strong>{mode.impact}</strong></span><span>Likelihood <strong>{mode.likelihood}</strong></span></div><button>Inspect mechanism <ChevronRight size={14} /></button></article>)}</div>
      <section className="counterargument"><span>Strongest counterargument</span><blockquote>“A shared case layer may centralize complexity without changing the fragmented ownership that created it.”</blockquote><p>This is deliberately left unanswered for your review.</p></section>
    </div>
  );
  if (stage === "boundaries") return (
    <div className="content-stack">
      <div className="section-heading"><div><span className="eyebrow">Human-owned values</span><h2>What are we unwilling to sacrifice?</h2></div><Tag tone="human"><UserRound size={12} /> You decide</Tag></div>
      <div className="boundary-list">
        {[
          ["No digital-only exclusion", "People must retain a supported path regardless of ability or access.", "Non-negotiable", "Aligned"],
          ["Human control over data reuse", "Consent must be visible, understandable, and reversible.", "Non-negotiable", "Tension"],
          ["No hidden burden transfer", "Efficiency cannot depend on uncompensated frontline work.", "Very important", "Unknown"],
        ].map((b) => <article key={b[0]}><span className="boundary-priority">{b[2]}</span><div><h3>{b[0]}</h3><p>{b[1]}</p></div><Tag tone={b[3] === "Aligned" ? "green" : b[3] === "Tension" ? "amber" : "neutral"}>{b[3]}</Tag><button><ChevronRight size={17} /></button></article>)}
      </div>
      <section className="consequence-map"><div><span>Who benefits</span><strong>Applicants</strong><small>Time, continuity, dignity</small></div><ArrowRight /><div><span>Who bears change</span><strong>Service agents</strong><small>New exception workload</small></div><ArrowRight /><div><span>Unknown effect</span><strong>Partner agencies</strong><small>Ownership needs evidence</small></div></section>
    </div>
  );
  if (stage === "decision") return (
    <div className="content-stack decision-space">
      <div className="decision-brief"><div><span className="eyebrow">Decision brief · Idea v2</span><h2>A strong value case with one assumption that can still stop the idea.</h2><p>Evidence is sufficient to proceed only if legal reuse is validated before pilot investment.</p></div><div className="recommendation"><span>CTF recommends</span><strong>VALIDATE FIRST</strong><small>Explainable rule path · not a score</small></div></div>
      <div className="brief-factors">{[["Evidence", "Medium", "3 claims"], ["Value potential", "High", "2 stakeholder gains"], ["Critical risk", "High", "1 kill assumption"], ["Value conflict", "None", "1 tension"]].map((f) => <div key={f[0]}><span>{f[0]}</span><strong>{f[1]}</strong><small>{f[2]}</small></div>)}</div>
      <section className="human-decision"><span className="eyebrow">Your decision</span><h3>Recommendation is not decision.</h3><div>{["Go", "Conditional go", "Validate first", "Redesign", "Hold", "No-go"].map((d, i) => <button className={i === 2 ? "selected" : ""} key={d}>{i === 2 && <CheckCircle2 size={16} />}{d}</button>)}</div><label><span>Decision rationale</span><textarea defaultValue="Validate the legal basis for consented data reuse before committing pilot resources." /></label></section>
    </div>
  );
  return (
    <div className="content-stack">
      <div className="section-heading"><div><span className="eyebrow">Assumption map</span><h2>The idea depends on these being true</h2></div><Tag tone="amber">1 kill assumption</Tag></div>
      <div className="assumption-list">{assumptions.map((item) => <article key={item.title}><span className={`criticality ${item.level.toLowerCase()}`}>{item.level}</span><div><h3>{item.title}</h3><p><Activity size={13} /> {item.test}</p></div><Tag tone={item.state === "Unvalidated" ? "red" : "amber"}>{item.state}</Tag><button>Review <ChevronRight size={14} /></button></article>)}</div>
      <section className="validation-plan"><div><Target size={20} /><span><small>Next best validation</small><strong>Commission independent legal assessment</strong></span></div><p>Resolves the only confirmed kill assumption and decision condition DC-04.</p><button>Open validation plan</button></section>
    </div>
  );
}

function ActivateContent({ stage }: { stage: Stage["id"] }) {
  if (stage === "commitment") return (
    <div className="content-stack">
      <div className="transition-banner"><span>Decision</span><strong>Validate first</strong><ArrowRight /><span>Commitment</span><strong>Prove legal and operational feasibility</strong></div>
      <section className="commitment-contract"><header><div><span className="eyebrow">Commitment contract · draft</span><h2>Validate and operate one safe continuity pilot by 12 December.</h2></div><Tag tone="human">Human-owned</Tag></header><div className="contract-grid">{[["Owner", "Service Transformation Lead"], ["Scope", "200-case assisted/digital pilot"], ["Time horizon", "02 Sep — 12 Dec 2026"], ["Review condition", "Legal opinion or material access harm"]].map((item) => <div key={item[0]}><span>{item[0]}</span><strong>{item[1]}</strong></div>)}</div></section>
      <div className="resource-row">{[["Time", "Confirmed"], ["People", "Partial"], ["Budget", "Planned"], ["Partner capacity", "Unknown"]].map((r) => <div key={r[0]}><span>{r[0]}</span><strong>{r[1]}</strong><i className={r[1].toLowerCase().replace(" ", "-")} /></div>)}</div>
      <p className="method-note warning"><Info size={15} /> Decision ≠ commitment. Two resource gaps remain before activation.</p>
    </div>
  );
  if (stage === "roadmap") return (
    <div className="content-stack">
      <div className="section-heading"><div><span className="eyebrow">Outcome architecture · roadmap v1</span><h2>Plan states to achieve—not tasks to accumulate</h2></div><Tag tone="version">Progressive plan</Tag></div>
      <div className="roadmap">{roadmap.map((row, i) => <article key={row.month}><div className="timeline-node"><span>{i + 1}</span><i /></div><div className="roadmap-time">{row.month}</div><div className="roadmap-body"><span>Outcome</span><h3>{row.outcome}</h3><p><ArrowRight size={13} /> {row.action}</p></div><div className="roadmap-evidence"><span>Required evidence</span><strong>{row.evidence}</strong></div><Tag tone={row.status === "Ready" ? "green" : "neutral"}>{row.status}</Tag></article>)}</div>
    </div>
  );
  if (stage === "reaffirm") return (
    <div className="content-stack">
      <section className="drift-hero"><div><span className="eyebrow">Commitment drift</span><h2>The commitment still holds,<br />but one resource signal needs attention.</h2></div><div className="drift-level"><span>Current drift</span><strong>Medium</strong><small>2 signals · no character inference</small></div></section>
      <div className="reality-events"><article><Tag tone="red">Decision relevant</Tag><h3>Legal opinion narrowed permitted reuse</h3><p>Decision condition DC-04 may require a redesigned consent mechanism.</p><button>Open re-decision review</button></article><article><Tag tone="amber">Material</Tag><h3>Partner capacity moved from planned to unavailable</h3><p>Roadmap can preserve validated work with one minimal change.</p><button>View replan diff</button></article></div>
      <div className="roadmap-diff"><span>Roadmap v1 → v2 proposal</span><div><Tag tone="green">Preserve 7</Tag><Tag tone="amber">Modify 2</Tag><Tag tone="neutral">Add 1</Tag><Tag tone="red">Cancel 0</Tag></div><button>Review minimal change <ChevronRight size={14} /></button></div>
    </div>
  );
  return (
    <div className="content-stack">
      <section className="nba-hero"><div className="nba-rank">NEXT<br />BEST<br />ACTION</div><div><span className="eyebrow">Recommended now · ACT-014</span><h2>Prepare the independent legal review package.</h2><p>This action validates the only kill assumption and unblocks the pilot decision.</p><div><Tag tone="red">Decision relevance · critical</Tag><Tag tone="green">Evidence gain · high</Tag><Tag tone="amber">Blocking effect · high</Tag></div></div><button>Open action <ArrowRight size={16} /></button></section>
      <div className="current-outcome"><div><span>Current outcome</span><h3>Legal feasibility confirmed</h3><small>1 of 2 milestones evidenced</small></div><div className="milestone-progress"><span><i style={{ width: "50%" }} /></span><strong>Evidence, not activity</strong></div></div>
      <div className="action-list">{[
        ["ACT-014", "Prepare independent legal review package", "Ready", "Legal feasibility", "Evidence required"],
        ["ACT-019", "Prototype explicit consent and withdrawal", "Planned", "Safe data reuse", "Hard dependency"],
        ["ACT-021", "Map assisted-to-digital handoff", "In progress", "Journey continuity", "Observation due"],
      ].map((a) => <article key={a[0]}><span className="action-id">{a[0]}</span><div><h3>{a[1]}</h3><p><Link2 size={12} /> Why: advances “{a[3]}”</p></div><Tag tone={a[2] === "Ready" ? "green" : a[2] === "In progress" ? "blue" : "neutral"}>{a[2]}</Tag><span className="action-requirement">{a[4]}</span><button><ChevronRight size={17} /></button></article>)}</div>
    </div>
  );
}

function TransformContent({ stage }: { stage: Stage["id"] }) {
  if (stage === "impact") return (
    <div className="content-stack">
      <div className="section-heading"><div><span className="eyebrow">Impact pathway</span><h2>Inspect every link—not just the result</h2></div><ConfidenceTag value="Medium" /></div>
      <div className="impact-chain">{[
        ["Creation", "Continuous case layer", "Verified"], ["Adoption", "72% active use", "Supported"], ["Outcome", "Processing time ↓", "Supported"], ["Value", "11.2 days saved", "Partial"], ["Impact", "Lower admin burden", "Emerging"],
      ].map((n, i) => <div key={n[0]} className="impact-node"><article><span>{n[0]}</span><strong>{n[1]}</strong><Tag tone={i < 3 ? "green" : "amber"}>{n[2]}</Tag></article>{i < 4 && <span className="chain-link"><ArrowRight /><small>{i === 2 ? "partial" : "supported"}</small></span>}</div>)}</div>
      <section className="attribution"><div><span>Attribution confidence</span><strong>Medium</strong><p>The creation likely contributed materially, but staffing increased during the same period.</p></div><div><span>Counterfactual</span><strong>12–15 days without change</strong><p>Historical trend estimate · low confidence</p></div><button>Inspect alternatives</button></section>
    </div>
  );
  if (stage === "transformation") return (
    <div className="content-stack">
      <section className="transformation-hero"><div><span className="eyebrow">Transformation assessment</span><h2>Material change—<em>not yet transformation.</em></h2><p>Service behavior changed, but governance and cross-agency ownership are not yet embedded.</p></div><div className="classification-scale">{["Optimization", "Improvement", "Material change", "Transformation"].map((x, i) => <span className={i === 2 ? "active" : ""} key={x}><i />{x}</span>)}</div></section>
      <div className="dimension-grid">{[["Process", "Transformed", "Cross-channel continuity is operational"], ["Behavior", "Material change", "Agents intervene before abandonment"], ["Governance", "Improvement", "Ownership remains project-dependent"], ["System logic", "Emerging", "Case-first model is not yet standard"]].map((d) => <article key={d[0]}><span>{d[0]}</span><strong>{d[1]}</strong><p>{d[2]}</p></article>)}</div>
      <div className="sustainability-row"><div><span>Sustainability</span><strong>Dependent</strong><small>Relies on pilot governance</small></div><div><span>Reversibility</span><strong>Partially reversible</strong><small>Core infrastructure is reusable</small></div><div><span>Evidence strength</span><strong>Moderate</strong><small>Two quality gaps remain</small></div></div>
    </div>
  );
  if (stage === "r1") return (
    <div className="content-stack">
      <section className="r1-header"><div><span>R₀ · Sep 2026</span><h2>Fragmented journeys and 15-day processing</h2></div><ArrowRight /><div><span>R₁ · Jun 2027</span><h2>Continuous journeys with uneven operational load</h2></div></section>
      <div className="delta-list">{[
        ["Processing time", "15 days", "4.8 days", "Improved"],
        ["Assisted completion", "61%", "79%", "Improved"],
        ["Agent exception load", "Baseline unknown", "+9%", "Worsened"],
        ["Cross-agency ownership", "Fragmented", "Pilot agreement", "Material change"],
        ["Cyber risk", "Not mapped", "High", "New dimension"],
      ].map((d) => <article key={d[0]}><strong>{d[0]}</strong><span>{d[1]}</span><ArrowRight size={14} /><span>{d[2]}</span><Tag tone={d[3] === "Improved" ? "green" : d[3] === "Worsened" ? "red" : "amber"}>{d[3]}</Tag></article>)}</div>
      <section className="cycle-choice"><div><span className="eyebrow">Cycle review</span><h3>R₁ is evidence-grounded and ready for a human decision.</h3><p>Keep this cycle open, adapt the creation, close it, or use R₁ as the next cycle&apos;s starting reality.</p></div><div><button>Keep open</button><button>Adapt</button><button className="selected">Start next cycle <ArrowRight size={15} /></button></div></section>
    </div>
  );
  return (
    <div className="content-stack">
      <div className="section-heading"><div><span className="eyebrow">Value review</span><h2>Expected value and realized value</h2></div><Tag tone="amber">Mixed outcome</Tag></div>
      <div className="value-overview"><div><span>Baseline</span><strong>15.0</strong><small>days average processing</small></div><div className="value-change"><ArrowRight /><strong>−68%</strong><span>verified change</span></div><div><span>Current</span><strong>4.8</strong><small>days average processing</small></div><div><span>Target</span><strong>3.0</strong><small>days · not yet reached</small></div></div>
      <div className="stakeholder-list">{stakeholders.map((s) => <article key={s.name}><div className="stakeholder-avatar">{s.name.slice(0, 2).toUpperCase()}</div><div><h3>{s.name}</h3><p>{s.role}</p></div><strong>{s.value}</strong><Tag tone={s.status === "Negative effect" ? "red" : s.status === "Realized" ? "green" : "amber"}>{s.status}</Tag><button><ChevronRight size={17} /></button></article>)}</div>
      <p className="method-note warning"><Info size={15} /> Aggregate improvement does not erase the confirmed increase in agent workload.</p>
    </div>
  );
}

function ERIPanel({ onClose }: { onClose: () => void }) {
  return (
    <aside className="eri-panel" aria-label="External Reality Intelligence">
      <header><div><span className="live-dot" /> External Reality Intelligence</div><button onClick={onClose} aria-label="Close ERI panel"><PanelRightClose size={17} /></button></header>
      <div className="eri-context"><small>Watching current decision context</small><strong>Legal feasibility + equitable access</strong><span>Last scan · 28 Aug, 22:46</span></div>
      <section><div className="eri-section-title"><span>Material signals</span><Tag tone="red">2 new</Tag></div>
        <article className="signal high"><header><Tag tone="red">Decision relevant</Tag><span>27 Aug</span></header><h3>New consent guidance narrows acceptable data reuse</h3><p>The regulator now expects purpose-specific renewal after assisted access.</p><footer><span>Official guidance · primary source</span><ExternalLink size={13} /></footer></article>
        <article className="signal medium"><header><Tag tone="amber">Material</Tag><span>25 Aug</span></header><h3>Peer service reports higher assisted completion</h3><p>A comparable pilot improved completion without digital-only routing.</p><footer><span>Published pilot review</span><ExternalLink size={13} /></footer></article>
      </section>
      <section><div className="eri-section-title"><span>Reality pulse</span><small>5 monitored</small></div>
        {["Regulation", "Public trust", "Accessibility", "Technology", "Partner capacity"].map((x, i) => <div className="pulse" key={x}><span>{x}</span><i><b style={{ width: `${[78, 42, 64, 26, 55][i]}%` }} /></i><small>{i === 0 ? "Rising" : i === 3 ? "Stable" : "Watch"}</small></div>)}
      </section>
      <footer><Shield size={14} /> ERI proposes reality signals. It cannot change confirmed creation memory.</footer>
    </aside>
  );
}

function GateDrawer({ current, confirmed, onClose }: { current: number; confirmed: Set<number>; onClose: () => void }) {
  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <aside className="gate-drawer" onMouseDown={(e) => e.stopPropagation()} aria-modal="true" role="dialog" aria-label="Human gates">
        <header><div><span className="eyebrow">Human authority</span><h2>19 decision gates</h2><p>AI may prepare and recommend. It cannot pass these gates.</p></div><button onClick={onClose} aria-label="Close"><X size={19} /></button></header>
        <div className="gate-list">{gates.map((gate) => {
          const done = confirmed.has(gate.number) || gate.number < current;
          const active = gate.number === current;
          return <div key={gate.number} className={active ? "active" : ""}><span className="gate-state">{done ? <Check size={13} /> : active ? <CircleDot size={13} /> : gate.number}</span><span><small>{slices.find((s) => s.id === gate.slice)?.name}</small><strong>Gate {String(gate.number).padStart(2, "0")} · {gate.label}</strong></span><Tag tone={done ? "green" : active ? "amber" : "neutral"}>{done ? "Confirmed" : active ? "Current" : "Locked"}</Tag></div>;
        })}</div>
      </aside>
    </div>
  );
}

const statusLabels = {
  IMPLEMENTED: "Implemented",
  PARTIAL: "Partial",
  NOT_IMPLEMENTED: "Not implemented",
  BLOCKED_EXTERNAL: "External blocker",
  DEFERRED_V1: "Deferred V1",
} as const;

function ArchitectureStatusDrawer({ onClose }: { onClose: () => void }) {
  const [capabilities, setCapabilities] = useState<CapabilityResponse | null>(null);
  const [readiness, setReadiness] = useState<ReadinessResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    Promise.all([ctfClient.getCapabilities(), ctfClient.getReadiness()])
      .then(([capabilityData, readinessData]) => {
        if (active) {
          setCapabilities(capabilityData);
          setReadiness(readinessData);
        }
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : "Architecture status is unavailable.");
      });
    return () => { active = false; };
  }, []);

  const mode = readiness?.runtime.persistence === "mock" ? "Demo snapshot" : "Live API";
  const priorityGaps = capabilities?.capabilities
    .filter((item) => item.priority === "P0" && item.status !== "IMPLEMENTED");

  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <aside className="status-drawer" onMouseDown={(event) => event.stopPropagation()} aria-modal="true" role="dialog" aria-label="Architecture status">
        <header>
          <div><span className="eyebrow">Verified capability inventory</span><h2>Architecture status</h2><p>Repository evidence, external dependencies, and known gaps—not product claims.</p></div>
          <button onClick={onClose} aria-label="Close"><X size={19} /></button>
        </header>
        {error && <p className="status-error"><Info size={15} /> {error}</p>}
        {!capabilities || !readiness ? !error && <p className="status-loading">Loading verified status…</p> : (
          <>
            <div className="status-mode">
              <Tag tone={mode === "Live API" ? "green" : "amber"}>{mode}</Tag>
              <span>Verified {capabilities.last_verified}</span>
              <strong>{readiness.release.ready ? "No P0 gaps" : `${readiness.release.blocker_count} P0 gaps`}</strong>
            </div>
            <div className="status-counts">
              {(Object.keys(statusLabels) as Array<keyof typeof statusLabels>).map((status) => (
                <div key={status} className={`status-count status-${status.toLowerCase()}`}>
                  <strong>{capabilities.summary.by_status[status]}</strong>
                  <span>{statusLabels[status]}</span>
                </div>
              ))}
            </div>
            <section className="runtime-status">
              <h3>Runtime truth</h3>
              <div>
                <span><small>AI</small><strong>{readiness.ai.ready ? "Ready" : readiness.ai.non_production ? "Demo only" : "Not ready"}</strong><em>{readiness.ai.provider}</em></span>
                <span><small>Persistence</small><strong>{readiness.runtime.durable ? "Durable mode" : "Non-durable"}</strong><em>{readiness.runtime.persistence}</em></span>
                <span><small>Objects</small><strong>{readiness.runtime.object_store_durable ? "Durable mode" : "Local/mock"}</strong><em>{readiness.runtime.object_store}</em></span>
                <span><small>Document worker</small><strong>{readiness.document_worker.status}</strong><em>{readiness.document_worker.mode}</em></span>
                <span><small>KHAL</small><strong>{readiness.khal.status}</strong><em>No live feed claimed</em></span>
                <span><small>Pilot</small><strong>{readiness.pilot.completed ? "Completed" : "Not completed"}</strong><em>{readiness.pilot.status}</em></span>
              </div>
            </section>
            <section className="priority-gaps">
              <div className="status-section-title"><h3>Priority gaps</h3><span>{priorityGaps?.length ?? 0} shown</span></div>
              {priorityGaps?.map((item) => (
                <article key={item.id}>
                  <div><code>{item.id}</code><Tag tone={item.status === "NOT_IMPLEMENTED" ? "red" : item.status === "BLOCKED_EXTERNAL" ? "purple" : "amber"}>{statusLabels[item.status]}</Tag></div>
                  <h4>{item.name}</h4>
                  <p>{item.gaps[0] ?? "No gap description supplied."}</p>
                  {item.blocked_by.length > 0 && <small>Blocked by: {item.blocked_by.join(" ")}</small>}
                </article>
              ))}
            </section>
          </>
        )}
      </aside>
    </div>
  );
}

function GenealogyBar({ stage }: { stage: Stage }) {
  const activeIndex = Math.min(stages.findIndex((s) => s.id === stage.id), traceNodes.length - 1);
  return <div className="genealogy-bar"><span><GitBranch size={14} /> Live genealogy</span><div>{traceNodes.map((node, i) => <span key={node} className={i <= activeIndex ? "reached" : ""}>{node}{i < traceNodes.length - 1 && <ChevronRight size={11} />}</span>)}</div><button>Inspect trace</button></div>;
}

function Workspace({ initialProject }: { initialProject: CTFProject }) {
  const [active, setActive] = useState(stages[0]);
  const [liveProject, setLiveProject] = useState(initialProject);
  const [eriOpen, setEriOpen] = useState(true);
  const [gatesOpen, setGatesOpen] = useState(false);
  const [statusOpen, setStatusOpen] = useState(false);
  const [confirmed, setConfirmed] = useState<Set<number>>(() => new Set());
  const [gateError, setGateError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const slice = useMemo(() => slices.find((s) => s.id === active.slice)!, [active]);

  const selectStage = (stage: Stage) => {
    setActive(stage);
    setGateError(null);
  };
  const confirm = async () => {
    setConfirming(true);
    setGateError(null);
    try {
      const payload = active.gate === 11
        ? { rationale: "Proceed with explicit safeguards.", conditions: ["Validate consent before launch"] }
        : {};
      const result = await ctfClient.decideGate(
        liveProject.id,
        active.gate,
        { ...gateDecisionFor(active.gate, payload), expected_version: liveProject.version },
      );
      setConfirmed((previous) => new Set(previous).add(result.gate.number));
      setLiveProject((previous) => ({
        ...previous,
        stage: result.project_stage,
        version: result.project_version,
        active_gate: result.next_gate,
      }));
      const nextStage = stages.find((stage) => stage.gate === result.next_gate.number);
      if (result.next_gate.status === "PENDING" && nextStage) setActive(nextStage);
    } catch (error) {
      setGateError(error instanceof Error ? error.message : "The gate decision failed.");
    } finally {
      setConfirming(false);
    }
  };

  return (
    <div className="app-shell" style={{ "--current-accent": slice.accent } as React.CSSProperties}>
      <Header
        onGates={() => setGatesOpen(true)}
        eriOpen={eriOpen}
        onEri={() => setEriOpen((value) => !value)}
        statusOpen={statusOpen}
        onStatus={() => setStatusOpen(true)}
      />
      <div className="app-body">
        <SliceRail active={active} onSelect={selectStage} />
        <main className="workspace">
          <StageHeader stage={active} />
          <div className="stage-content">
            {active.slice === "frame" && <FrameContent stage={active.id} />}
            {active.slice === "create" && <CreateContent stage={active.id} />}
            {active.slice === "decide" && <DecideContent stage={active.id} />}
            {active.slice === "activate" && <ActivateContent stage={active.id} />}
            {active.slice === "transform" && <TransformContent stage={active.id} />}
            <GateCard
              stage={active}
              confirmed={
                confirmed.has(active.gate)
                && !(liveProject.active_gate.number === active.gate && liveProject.active_gate.status === "PENDING")
              }
              onConfirm={confirm}
              disabled={confirming}
              error={gateError}
            />
          </div>
          <GenealogyBar stage={active} />
        </main>
        {eriOpen && <ERIPanel onClose={() => setEriOpen(false)} />}
      </div>
      {!eriOpen && <button className="eri-fab" onClick={() => setEriOpen(true)}><PanelRightOpen size={16} /> ERI</button>}
      {gatesOpen && <GateDrawer current={active.gate} confirmed={confirmed} onClose={() => setGatesOpen(false)} />}
      {statusOpen && <ArchitectureStatusDrawer onClose={() => setStatusOpen(false)} />}
    </div>
  );
}

export default function Home() {
  const [liveProject, setLiveProject] = useState<CTFProject | null>(null);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);

  useEffect(() => {
    if (isDemoMode) return;
    const projectId = localStorage.getItem(LIVE_PROJECT_KEY);
    if (!projectId) return;
    setStarting(true);
    ensureLiveSession()
      .then(() => ctfClient.getProject(projectId))
      .then(setLiveProject)
      .catch(() => clearLiveClientState())
      .finally(() => setStarting(false));
  }, []);

  const startOver = () => {
    clearLiveClientState();
    setLiveProject(null);
    setStartError(null);
  };

  const start = async (entryFamily: EntryFamily, initialInput: string, file?: File | null) => {
    setStarting(true);
    setStartError(null);
    try {
      const created = await ctfClient.createProject({
        entryFamily,
        entryType: entryFamily === "CREATION" ? "PROBLEM" : "INTENT",
        initialInput,
      });
      if (!isDemoMode) localStorage.setItem(LIVE_PROJECT_KEY, created.id);
      if (file && !isDemoMode) {
        const attachment = await ctfClient.uploadAttachment(created.id, file);
        await ctfClient.analyzeDocument(created.id, attachment.id);
      }
      setLiveProject(created);
    } catch (error) {
      setStartError(error instanceof Error ? error.message : "Could not start the creation cycle.");
    } finally {
      setStarting(false);
    }
  };

  return liveProject
    ? isDemoMode ? <Workspace initialProject={liveProject} /> : <LiveWorkspace initialProject={liveProject} onStartOver={startOver} />
    : <StartScreen onStart={start} starting={starting} error={startError} />;
}
