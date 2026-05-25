# AGENT.md

For the **AGENT** operating this repo — read when the workspace opens.
**Figure out what the user wants, then follow the right path below.**

---

## 1. User wants to RUN a literature review

**Read and follow [`skills/litkit/SKILL.md`](skills/litkit/SKILL.md).**
That skill overrides everything else in this file for scoping, conversation
style, and stage order.

You are the **operator**, not a tour guide. Run scripts; don't explain the
architecture unless asked.

**Conversational rules (skill enforces these):**

- One or two questions at a time — never a scoping form.
- Surface the honesty disclaimer once at start; wait for yes/no.
- Seeds before PICOC / queries — vocabulary comes from real papers (`00b`, `00c`).
- Show literal query strings + API URLs before `02_search_open.py`; get explicit OK.
- Screening batches: max **5** records (`04_screen_prep.py --batch-size 5`).

**Read when needed:**

| Moment | Doc |
|--------|-----|
| Labeling title/abstract batches | [`docs/SKILL_screening.md`](docs/SKILL_screening.md) |
| Suggesting `--with-quality` / RoB | [`docs/SKILL_quality_assessment.md`](docs/SKILL_quality_assessment.md) |
| User asks "what is PICOC?" | [`docs/SCOPING_GUIDE.md`](docs/SCOPING_GUIDE.md) |
| Full pipeline table | [`README.md`](README.md) |

**Operator checklist** (details in skill + README):

```
00 init → 00b seeds → 00c vocabulary → scoping in project.yaml
→ 01 queries (user approves literals) → 02 search → 02b manual imports
→ 03 dedup → 04 screen (loop) → 05 resolve OA → 06 download
→ 07 full-text (loop, batches of 5) → 08 snowball → loop 03/04 if new hits
→ 09 export
```

**Resume:** inspect `projects/<id>/` (`project.yaml`, `project.db`, `screening/`,
`exports/`), say what's done, propose the next script.

---

## 2. User wants to CHANGE the engine (code, scripts, schema)

Read [`docs/AGENT_GUIDE.md`](docs/AGENT_GUIDE.md). Do not use it to run reviews.

- Topic config lives in `project.yaml` — never hardcode topics in Python.
- New pipeline stages → numbered script in `scripts/` + document it.
- State changes go through `litkit.store` helpers, not ad-hoc SQL.

---

## 3. User is human and wants to understand the product

Point them to [`README.md`](README.md). They do not need this file or the skill.

---

## Repo layout

| Path | Purpose |
|------|---------|
| `litkit/` | Engine library — edit only when fixing/extending the engine |
| `scripts/` | Numbered CLI stages (`00`–`09`) you invoke |
| `projects/<id>/` | One review: `project.yaml`, `project.db`, `queries/`, `screening/`, `exports/`, `seeds/` |
| `skills/litkit/SKILL.md` | How to run a review (operator manual) |
| `projects/_example/project.yaml` | Example config shape (IT topic demo) |

---

## Hard rules (always)

- **OA-only downloads** — no Sci-Hub; paywalled → `not_downloaded.txt`.
- **Don't bypass `04_screen_prep.py`** — batch JSONL is the audit trail.
- **`decided_by` provenance:** `agent` (hand labels), `llm:<provider>` (`04c`),
  `human` (overrides), `seed` (auto-include on first commit).
- **Agent mode** (`llm: null` or `provider: agent`): stage handoff files; no API key required.
- **Don't relax inclusion/exclusion criteria** without asking the user.
- **Silent-zero ≠ real null** — if a source returned 0 with HTTP errors, fix or acknowledge before dedup.

---

## Anti-patterns

- Dumping a form with all scoping fields at once.
- Explaining the engine instead of running the next stage.
- PICOC slots before seeds and `_vocabulary.json` exist.
- Inventing search vocabulary not in the curated seed vocabulary.
- Running search without showing literal queries and URLs.
- Marking include from title only — read the abstract.
- Writing one-off scripts instead of using/extending numbered stages.
- Skipping human review on LLM full-text (`07d`) — LLM output is recommendations only.
