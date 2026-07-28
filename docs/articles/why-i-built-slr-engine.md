# Why I built SLR-Engine

I built an open-source engine for running systematic literature reviews driven by a coding agent: Claude Code, Codex, Cursor Hermes, or any agent that can read markdown skill files and execute scripts. It's for researchers and knowledge-management practitioners, students, self-learners, and small project teams who need serious literature work without relying on chat agents' web search or deep-research modes.

A systematic literature review is a structured process for surveying everything published on a research question: defining the question, searching multiple databases with controlled vocabulary, screening every hit against pre-declared inclusion criteria, retrieving full texts, extracting structured data, and producing reproducible outputs (PRISMA flow diagrams, audit trails, methodology documents).

Done by hand it takes weeks. Done badly it takes weeks and produces bias. SLR-Engine compresses the deterministic parts (querying APIs, normalizing schemas, deduplicating, resolving open-access full text, snowballing citations, exporting) and leaves the judgment parts (turning a question into queries, screening abstracts, deciding inclusion) to a human-in-the-loop conversation with an agent.

The user does not need to know the methodology. The agent walks the user through a structured conversation, runs the right scripts at the right moments, and produces defensible outputs. The user is in charge at every judgment point; the engine refuses to proceed when something looks structurally wrong.

---

## How I got here

I have a background spanning eight years where research has been part of the work the whole time, but I didn't actually learn how to do it *properly* until I started a master's degree halfway through.

The work I do regularly involves answering *"what's been done on X?"* for a client, for a paper, for an internal strategy document. Lately I've wanted to do real, structured research on new topics for myself too, without relying on chat agents or their deep-search functions. These hit unavailable sources more often than anything useful, especially behind paywalls or outside what the search index has crawled recently.

Me and most people around me default to a chat agent's web-search tool for this kind of question. We get arXiv at best, with limited coverage and no methodology underneath. I wanted something better for projects that deserve more thinking than a prompt. I assume most users of this engine will be people like me: working researchers, project partners, students, hobbyists, self-learners.

Existing tools fall into three buckets, each solving a part of the problem instead of an end-to-end solution:

**Commercial research assistants** (Elicit, ResearchRabbit, Consensus) are smooth to use but opaque about methodology. They surface what looks relevant by some ranking heuristic the user can't inspect. They don't produce PRISMA-aligned documentation or separate deterministic steps from judgment steps. Good for an afternoon scan, not defensible research.

**Classical SLR tools** (Covidence, EPPI-Reviewer, Rayyan) are built for medical evidence synthesis. They enforce rigor but assume RCTs and clinical trials, which is the wrong shape for technical domains. They also assume you already know how to write a Boolean query, define PICO slots, and structure a protocol. Scaffolding, not guidance.

**Ad-hoc agent prompting.** Ask Claude, GPT, or Gemini to "review the literature on X." It will produce something plausible. It will not be a systematic review. No audit trail, no reproducibility, no defensible search strategy, no methodology document. Plausible output, no rigor.

What I wanted, and couldn't find: a methodology-rigorous SLR pipeline that a coding agent can drive conversationally; outputs defensible enough for academic or KM publication; transparent about trade-offs; auditable line by line because the code is open and the audit trail is structured data on disk.

So I built it.

---

## Why it matters for me

There are many tools that help you "find papers" and many that help you "chat about papers." Fewer help you run an actual review process while preserving method, auditability, and human control. This engine is my attempt to close that gap.

It is not a black box research assistant. It is a staged, inspectable system that lets an agent be genuinely useful without letting the methodology disappear inside the model. The agent handles conversational judgment; the engine handles determinism, validation, and audit. The user stays in charge wherever the review's validity depends on their decisions.

---

## Design principles

Five principles constrain every decision downstream.

**Agent-as-operator, human-as-principal.** The agent runs scripts, reads outputs, and proposes next steps. The human approves, edits, or overrides at every judgment point. Validity-affecting decisions are surfaced with the agent's recommendation and the engine's evidence; the human commits. The engine is not trying to make the agent autonomous. It is trying to make the agent legible. When something goes wrong, you can ask whether it was a judgment error or a process error. That only works if the roles stay separate.

**Deterministic engine, delegated judgment.** Ingestion, validation, dedup, storage, and export are deterministic: same inputs, same outputs, queryable through the audit log. Judgment work (vocabulary curation, screening, extraction, risk-of-bias appraisal) is delegated to an LLM or external coding agent inside named stages, then parsed and committed with explicit `decided_by` provenance.

**Audit trail first.** Every state change writes to SQLite. Every decision records who made it (`human`, `agent`, `seed`), when, and why. The methodology document is generated from the audit log, not reconstructed from memory.

**Refuse to proceed silently.** Malformed queries, suspicious search counts, skipped prerequisites, missing risk-of-bias data: the engine surfaces the problem and stops. Fix it, or override explicitly. Quiet success on bad inputs is the failure mode I most wanted to prevent.

**Honest about trade-offs.** The engine compresses weeks of hand-run methodology into days. Outputs are designed to be defensible, but less methodologically honest than a process run by an experienced reviewer alone. The disclaimer surfaces at first contact with the agent.

---

## Architecture

Three layers: human above agent above engine.

```
┌──────────────────────────────────────────────────────────────┐
│  HUMAN (the principal)                                        │
│    Approves topic, RQs, vocabulary, queries, criteria,        │
│    screening decisions. Final authority on inclusion.         │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│  AGENT (Claude Code / Codex / Cursor Hermes / any skill agent)│
│    Reads SKILL.md. Drives the conversation. Runs scripts.     │
│    Proposes next steps. Never commits judgment without        │
│    explicit human approval.                                   │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│  ENGINE (Python, deterministic)                               │
│    scripts/: pipeline stages (00→09)                          │
│    slr_engine/: core library (sources, store, dedup, prisma…) │
│    projects/<id>/: per-review state                           │
│      ├── project.yaml: scoping & config                       │
│      ├── project.db: records, screening, audit trail          │
│      ├── seeds/: per-seed JSON + curated vocabulary           │
│      ├── queries/: per-source query files                     │
│      ├── imports/: manual exports from Scopus/WoS/Scholar     │
│      ├── screening/: batches, criteria, agent handoff files   │
│      ├── data/fulltext/: downloaded OA PDFs                   │
│      ├── data/fulltext_md/: normalized markdown (stage 07)    │
│      └── exports/: final artifacts                            │
└──────────────────────────────────────────────────────────────┘
```

Each layer is decoupled. The **operator skill** (`skills/slr-engine/SKILL.md`) is the contract between agent and engine: stage order, conversation rhythm, what to surface, what never to do. Drop it into any agent's skill directory and that agent can drive the engine.

---

## Further reading

| Document | For |
|----------|-----|
| [Introduction to SLR-Engine](introduction-to-slr-engine.md) | Plain-language overview and conversation flow |
| [Review process walkthrough](review-process-walkthrough.md) | Stage-by-stage detail (files, keys, time estimates) |
| [Methodological foundations](methodological-foundations.md) | Five methodology pillars and references |
| [AGENT.md](../../AGENT.md) | Agent entry when the workspace opens |
| [Operator skill](../../skills/slr-engine/SKILL.md) | What the coding agent loads to run a review |
