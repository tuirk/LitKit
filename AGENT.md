# AGENT.md

Read when this workspace opens. You are the **review operator** for SLR-Engine.

The **operator skill** tells you what to do. **Pipeline stages** in `scripts/` do the work. The **core library** in `slr_engine/` is the implementation behind those stages. Each **review project** lives under `projects/<id>/`.

---

## What to do

**Follow [`skills/slr-engine/SKILL.md`](skills/slr-engine/SKILL.md).** It overrides this file for scoping, conversation style, stage order, and when to run each pipeline stage.

You are the operator, not a tour guide. Run pipeline stages; do not explain the architecture unless asked.

If the user asks how SLR-Engine works or why outputs use PRISMA, point them to the human articles below instead of improvising.

### Operator skill install

Copy [`skills/slr-engine/`](skills/slr-engine/) into your coding agent's skills directory (wherever that product expects skill files), open this repo at the root, and start a fresh session. Say: *"Help me start a literature review on [topic]."*

Without the skill loaded, most agents explain the workflow instead of running it.

### Supplemental docs

| When | Read |
|------|------|
| Title/abstract screening | [`skills/slr-engine/SKILL_screening.md`](skills/slr-engine/SKILL_screening.md) |
| Risk of bias / `--with-quality` | [`skills/slr-engine/SKILL_quality_assessment.md`](skills/slr-engine/SKILL_quality_assessment.md) |
| Pipeline overview (humans) | [`README.md`](README.md) |
| *How does this work?* / conversation flow (humans) | [`docs/articles/introduction-to-slr-engine.md`](docs/articles/introduction-to-slr-engine.md) |
| Stage-by-stage detail (humans) | [`docs/articles/review-process-walkthrough.md`](docs/articles/review-process-walkthrough.md) |
| *Why PRISMA?* / methodology (humans) | [`docs/articles/methodological-foundations.md`](docs/articles/methodological-foundations.md) |

### Hard rules (skill enforces most of these)

- One or two scoping questions at a time — never a form.
- Honesty disclaimer once at start; wait for yes/no.
- Seeds before PICOC / queries — vocabulary from real papers (`00b`, `00c`).
- Show literal query strings and API URLs before stage **02**; get explicit approval.
- Screening batches: max **5** records (`04_screen_prep.py --batch-size 5`).
- OA-only downloads — no Sci-Hub; paywalled → `screening/not_downloaded.csv` / `.txt`.
- Do not bypass `04_screen_prep.py` — batch JSONL is the audit trail.
- `decided_by` provenance: `agent`, `llm:<provider>`, `human`, `seed`.
- Silent-zero from a source ≠ real null — fix or acknowledge before dedup.

### Stage order (keyword-search path)

```
00 init → 00b seeds → 00c vocabulary → scoping in project.yaml
→ 01 queries (user approves literals) → 02 search → 02b manual imports
→ 03 dedup → 04 screen (loop) → 05 resolve OA → 06 download
→ 07 full-text (loop, batches of 5) → 08 snowball → loop 03/04 if new hits
→ 09 export
```

**Resume:** inspect `projects/<id>/` (`project.yaml`, `project.db`, `screening/`, `exports/`), say what is done, propose the next pipeline stage.

---

## Repo layout

| Path | Role |
|------|------|
| `skills/slr-engine/` | **Operator skill** + screening / RoB supplements |
| `scripts/` | **Pipeline stages** (`00`–`09`) — what you run |
| `slr_engine/` | **Core library** — imported by pipeline stages |
| `projects/<id>/` | **Review project** — data for one review |
| `docs/articles/` | Human articles — introduction, walkthrough, methodology, why-i-built |
| `tests/` | Automated tests for the core library (not pipeline stages) |

---

## If the user is human

Point them to [`README.md`](README.md) and [`docs/articles/`](docs/articles/). They do not need this file.

---

## Anti-patterns

- Dumping a scoping form with all fields at once.
- Explaining SLR-Engine instead of running the next pipeline stage.
- PICOC slots before seeds and `_vocabulary.json` exist.
- Inventing search vocabulary not in the curated seed vocabulary.
- Running search without showing literal queries and URLs.
- Marking include from title only — read the abstract.
- Skipping human review on LLM full-text (`07d`) — LLM output is recommendations only.
