# Agent Guide

> **Running a review?** Use [`skills/SLR-Engine/SKILL.md`](../skills/SLR-Engine/SKILL.md), not this file.  
> **This guide** is for SLR-Engine internals — scripts, schema, stage contracts, and code changes.

You (the coding agent) are modifying or deeply debugging SLR-Engine. This is your contract.

## Operating principles

1. **SLR-Engine is deterministic. You are the judgment layer.**
   Scripts handle searching, dedup, resolving, downloading. You handle: turning
   a research question into Boolean queries, and screening abstracts.

2. **State lives in `projects/<id>/`.** Never write code that hardcodes a
   topic. Read from `project.yaml`, write to `project.db` and the project's
   `data/` folder.

3. **Every state-changing script is idempotent.** Re-running `02_search_open.py`
   will not duplicate records. Trust this; don't add guard rails on top.

4. **You don't write to the DB directly.** Use `SLR-Engine.store` helpers. The schema
   has constraints that catch bad data — let them.

5. **OA-only for downloads.** Resolve and download only **gold**, **green**, or
   **bronze** tiers (`slr_engine/oa_resolver.py`). **Hybrid** and **closed** are skipped.
   Multiple lawful OA URLs are collected and tried in order; there is no Sci-Hub
   fallback. Unretrievable includes land in `not_downloaded.csv` / `.txt`.
   Sci-Hub is out of scope.

## Per-stage instructions

### Stage: scoping conversation + query generation

**Don't generate queries silently. Walk the user through the academic chain first.**
Most users — especially those without 8+ years of methodology experience —
don't know what good research questions or queries look like and shouldn't
be expected to. Read `docs/SCOPING_GUIDE.md` for the full rationale; the
procedure below is the operational version.

**At first contact, surface the honesty disclaimer:**

> A note: this engine compresses methodology that researchers traditionally
> do by hand over weeks. The engine will offer to walk you through the
> academic steps (topic → aim → research questions → framework →
> eligibility → search → screening), but you can skip any of them by
> telling the agent what you already have. The engine's outputs are
> designed to be defensible, but they are *less methodologically honest
> than a process driven by an experienced human reviewer*. If you aim
> for academic-rigor publication, treat the engine's outputs as
> scaffolding to verify and refine, not as a finished review. If you're
> doing this for practical knowledge-gathering — a market scan, a
> competitive analysis, a knowledge-management catalog — the engine is
> a complete tool for the job.

End the disclaimer with:

> Continue with that understanding? Please answer yes or no.

After the user answers yes, show source defaults as a separate message:

> Source defaults before we scope:
>
> | Source | Default | Use when |
> |---|---:|---|
> | OpenAlex | ON | Broad academic coverage |
> | Crossref | ON | DOI/publisher metadata |
> | arXiv | ON | AI/ML, maths, quant finance, preprints |
> | Semantic Scholar | ON | CS/AI coverage, TLDRs, citation signals |
> | PubMed | OFF | Biomedical, clinical, life sciences |
> | Europe PMC | OFF | Biomedical and open full-text coverage |
> | DBLP | OFF | Computer-science-heavy reviews |
> | Internet Archive Scholar | OFF | Grey literature or older scanned material |
> | CORE | OFF | Stage **05** OA resolver — set `sources.core: true` in `project.yaml` and `CORE_API_KEY` in `.env` |
> | Scopus | Manual | Export/import only |
> | Web of Science | Manual | Export/import only |
> | Google Scholar | Manual | Export/import only |
>
> Do you want to change any sources before we continue?

Wait for source confirmation or changes before starting scoping.

#### Step 1: walk the academic chain (the heart of scoping)

The chain follows what real researchers do. Walk through it in order, but
let the user skip any step by saying *"I already have this — here it is"*.
Each step writes back to `project.yaml`.

1. **Topic.** Confirm the topic the user supplied at init. If it's clear
   already, skip. If it's vague, ask them to sharpen.

2. **Aim.** "What should this review *achieve*? Map a method space?
   Evaluate an intervention? Compare alternatives?" Save as `cfg.aim`.
   Skip if user says they don't have a separate aim.

3. **Research question(s).** This is where you draft RQs in plain English.
   Propose one or more, show them to the user, iterate. Save the approved
   list as `cfg.research_questions`. **Don't skip this step quietly** —
   if the user has no clear RQ, it usually means the topic is too vague
   and they need to sharpen it before continuing.

4. **Seeds.** Ask: "Do you have 1–3 papers you already know are
   on-topic? Even one helps a lot." Up to 3 concrete seeds — DOI,
   OpenAlex ID, or PDF path. **Hard rule: do not proceed to the
   framework step (#5) without at least one concrete seed.** The seeds
   anchor the vocabulary that downstream PICOC slots get filled from.
   Without seeds, slot terms come from your general associations and
   the queries drift into adjacent literatures.

   If the user has none on hand, suggest options (Google Scholar,
   arXiv, OpenAlex web interface) and wait. Don't proceed.

   Once seeds are in `project.yaml`, run:
   ```
   python scripts/00b_read_seeds.py --project <slug>
   ```
   This fetches metadata via OpenAlex/Crossref or extracts PDF text.

5. **Vocabulary extraction.** Run:
   ```
   python scripts/00c_extract_vocabulary.py --project <slug>
   ```
   Two stages: KeyBERT pulls candidate phrases from seed text
   (statistical anchor), then vocabulary is curated — by API if `llm.provider`
   is set, otherwise by the coding agent via handoff files in agent mode.
   Output target is `projects/<slug>/seeds/_vocabulary.json`.

   Show the curated clusters to the user. Confirm they capture what
   real papers in the field use. Edit if needed.

   This curated vocabulary is the canonical source for the next step.
   No PICOC slot terms come from anywhere else.

6. **Framework.** Offer **PICOC** by default (Petticrew & Roberts 2008;
   adopted by Kitchenham et al. 2007 SE guidelines; standard in CS / SE /
   AI-ML reviews). For other frameworks (SPIDER for qualitative, SPICE
   for context-bound, etc.), ask the user to describe their framework's
   slots in plain English — the engine treats them as `type: custom` and
   proceeds the same way. Reference the Booth/Sutton/Papaioannou book in
   `docs/SCOPING_GUIDE.md` for the full catalog.

   For PICOC, fill the slots **using terms from the curated vocabulary
   only**. Light extension is allowed — adding a known field-standard
   synonym of an already-bucketed phrase is fine. Adding generic terms
   that are merely topic-adjacent is forbidden; that's the v0.4 failure
   mode.

   - **P**opulation
   - **I**ntervention
   - **C**omparison
   - **O**utcome
   - **C**ontext

   **Fit-check (required):** before showing the slots to the user,
   walk through one seed paper and verify each slot's vocabulary would
   match it. Print the check. If a slot wouldn't match a seed, the slot
   is wrong — fix it.

   Save as `cfg.framework = {type: 'picoc', slots: {...}}`.

7. **Hypotheses (optional).** Look at the conversation so far. Recommend:
   - **add** if the user expressed directional beliefs, or the topic has
     "does X cause Y / is X better than Y" shape
   - **skip** if exploratory ("map", "catalog", "what's been done")

   Phrase as a recommendation: *"I'd recommend [adding/skipping]
   hypotheses for this review. Reason: [explain]. Override?"*.

   If adding, walk the user through formulating each hypothesis. Each
   needs:
   - `id` (H1, H2, H1a, ...)
   - `statement` — testable, falsifiable, directional
   - `rationale` — why expect this (theory/prior knowledge)

   **Soft cap at 3.** If the user wants more than 3, agree but note that
   the LLM hallucination risk grows with count. The engine logs a
   warning event automatically; the methodology artifacts add a caveat.
   Never refuse — the user is in charge.

   **No-RAG note**: when discussing hypotheses, make this explicit:
   *"This review will track each hypothesis through the LLM's reading of
   each paper. The same model that reads the paper decides whether it
   supports each hypothesis. There's no separate retrieval system. Even
   one hypothesis carries some false-positive risk; more means more."*

8. **Eligibility criteria.** Translate the framework slots and any
   hypotheses into operational include/exclude rules with stable IDs
   (`I1`, `E1`, ...). Each criterion should pass the *10-second test*:
   could you apply it to a title+abstract in 10 seconds? If not, it's
   too vague.

9. **Date range and languages.** Confirm. Flag mismatches (e.g.
   topic-specific review starting before the topic existed catches
   mostly background).

10. **Result count target.** "Roughly how many results do you want? A
    workable first pass is usually 200–2,000 records on OpenAlex."

#### Step 2: concept table (BEFORE the Boolean strings)

Run `scripts/01_generate_queries.py --project <id>` to scaffold the files,
then open `concepts.yaml` and fill it in. **The curated vocabulary clusters
map to concept groups** — each cluster becomes one concept, and the cluster's
terms become the concept's synonyms. Show the user the concept table in chat
before writing the Boolean queries:

```
C1 — prediction markets
  synonyms: prediction market, betting market, decision market,
            information market, Polymarket, Kalshi, PredictIt, Augur

C2 — regime detection
  synonyms: regime detection, regime switching, regime change,
            structural break, change-point, breakpoint, hidden Markov,
            Markov switching, state-space, structural change

C3 — trading effects
  synonyms: trading strategy, returns, Sharpe ratio, drawdown,
            backtest, alpha, profitability
```

Ask explicitly: "Are these the right concepts? Any synonyms missing or
wrong? Any ambiguous terms I should constrain (e.g. 'regime' could match
political regimes — should I require it to co-occur with a market term)?"

Wait for confirmation before proceeding.

#### Step 3: draft queries with a result-count check

Generate the query strings for enabled sources: OpenAlex, Crossref, Europe
PMC, arXiv, Semantic Scholar, PubMed if enabled, DBLP if enabled, Internet
Archive Scholar if enabled, and manual Scopus/WoS/Google Scholar if used.
Before declaring them final, **estimate the OpenAlex hit count** — e.g. a
small probe run (`02_search_open.py --max-records 25`) or OpenAlex's web UI.
Report:

> Draft queries written. Estimated OpenAlex result count: ~870.
> That's in the 200–2,000 workable range. Approve, or want to revise?

If the count is out of range, propose how to fix it (add/remove synonyms,
add/remove a concept) before showing the queries again.

#### Step 4: show all the queries

Output: write these files to `projects/<id>/queries/`:
- `concepts.yaml` — concepts with synonyms (already done in step 2)
- `openalex.txt` — OpenAlex search string
- `pubmed.txt` — PubMed E-utilities query (only if pubmed enabled)
- `europepmc.txt` — Europe PMC query
- `crossref.json` — Crossref filter dict
- `arxiv.txt` — arXiv query
- `semantic_scholar.txt` — Semantic Scholar query
- `dblp.txt` — DBLP query (only if DBLP enabled)
- `ia_scholar.txt` — Internet Archive Scholar query (only if IA Scholar enabled)
- `manual_scholar.txt` — Google Scholar manual query/import notes
- `manual_scopus.txt` — for the user to paste into Scopus
- `manual_wos.txt` — for the user to paste into Web of Science

Show the user all queries in chat. Wait for explicit approval before
running search. Never run search the same turn you generated queries.

#### Step 5: optional protocol draft before search

After the user approves the literal query strings and API URLs, ask once:
"Before we run the search, do you want a protocol draft document generated
now? It's useful for PROSPERO, journal pre-registration, internal sign-off,
or grant submission. Most users skip it for internal KM, industry research,
or quick scans; you'll still get a full methodology report at the end.
Default: skip."

If yes, run `python scripts/01a_emit_protocol_draft.py --project <id>`,
open `projects/<id>/protocol_draft.md`, show it to the user, and let them
request revisions to `project.yaml` or `queries/` before regenerating it.
Once they approve the draft, continue to search.

If no, continue directly to search. Do not treat the draft as a checkpoint;
the query-validity checks above are the load-bearing gates.

### Stage: search

Run `scripts/02_search_open.py --project <id>`. Don't modify it. If a source
fails, the script logs and continues. Inspect `projects/<id>/logs/search.log`
after.

### Stage: ingest (manual)

User exports Scopus as CSV or RIS, WoS as RIS or tab-delimited. They drop the
files in `projects/<id>/imports/`. Run `scripts/02b_ingest_manual.py --project <id>`.
The importer auto-detects format.

### Stage: screening

Run `scripts/04_screen_prep.py --project <id> --batch-size 5`. This writes
`projects/<id>/screening/batch_NNN.jsonl`. Each line is one record with
title, abstract, and a blank `decision` field.

Do not prepare or screen more than 5 records at a time. The engine's intended
operating mode is sequential, not parallel.

For each record, you decide: `include`, `exclude`, or `unsure`. You write
`decision` and `reason` (one sentence). You apply the inclusion/exclusion
criteria from `project.yaml` literally — don't relax them.

When done with a batch, run `scripts/04b_screen_commit.py --batch <path>`.
The script validates, writes labels to the DB, and **auto-includes
`from_seed` records** on the first title/abstract commit.

For borderline cases (`unsure`), leave them; a human will review. Do not
flip-flop them to `include` or `exclude` on a second pass without new info.

#### Primary path: agent labels batch JSONL

`04_screen_prep.py` writes plain `batch_NNN.jsonl`. The agent fills
`decision`, `reason`, `criteria_hit` and commits with `04b_screen_commit.py`.
No prompt packets required.

#### Alternative: LLM-driven screening (`04c_llm_screen.py`)

If the user has set an `llm:` block in `project.yaml`, you can offer to
label batches automatically with `scripts/04c_llm_screen.py --project <id>`.
It supports Anthropic (Claude), DeepSeek, and Google (Gemini). API keys
come from environment variables (ANTHROPIC_API_KEY, DEEPSEEK_API_KEY,
GOOGLE_API_KEY). Labels go in as `decided_by='llm:<provider>'` so they're
auditable separately from agent or human labels.

When to suggest LLM screening:
- Large batches (200+ records) where doing it by hand in chat is slow.
- After a calibration batch where the user confirmed your labeling is sound.
- When the user is going to walk away and let it run.

When NOT to suggest LLM screening:
- The user hasn't configured `llm:` yet — guide them through that first.
- The first batch of a new review — agent-by-hand is more transparent for
  calibration.
- The user explicitly said they want to label by hand.

After an LLM run, do a sample audit: read 5–10 of the LLM's decisions and
check that the reasons match the criteria. Report any miscalibration to the
user before continuing.

#### Alternative: agent-harness screening (`04c_llm_screen.py` in agent mode)

If `llm` is omitted or `provider: agent`, **`04c_llm_screen.py`** (not
`04_screen_prep`) stages prompt packets when you use that script. It writes:

- the editable batch / review file that the harness should update
- a `*_prompts.jsonl` file containing exact `system` and `user` prompts
- a `*_agent_request.md` file with the expected write-back target and commit command

Prompt packets use the shared schema `slr-engine-agent-prompt/v1`:

```json
{
  "schema_version": "slr-engine-agent-prompt/v1",
  "stage": "<stage>",
  "project_id": "<project>",
  "item": {"record_id": 1, "canonical_id": "rec_000001"},
  "input_refs": {...},
  "prompt": {"task": "...", "system": "...", "user": "..."},
  "output": {"write_back_to": "...", "fields": [...], "commit_command": "..."}
}
```

The boundary is deliberate: the engine stages prompts, the external harness
executes them. Python never self-calls Codex / Claude Code directly.

To validate and apply a harness response before commit, use the reference
runner:

```bash
python scripts/agent_handoff_runner.py \
  --packets projects/<id>/screening/batch_001_prompts.jsonl \
  --responses <harness-output>.jsonl
```

Use `--validate-only` if you want schema checks without mutating the staged
batch or review file.

### Stage: full-text resolution and download

`scripts/05_resolve_oa.py` collects ranked OA URL **candidates** and stores the
best as `resolved` plus alternates as `queued` (PMC → Europe PMC → OpenAlex
locations → Unpaywall published/AAM → arXiv → CORE → Crossref). Set
`contact_email` for Unpaywall; set `sources.core: true` + `CORE_API_KEY` for CORE.

`scripts/06_download.py` walks `resolved` then `queued` per record until one
fetch succeeds; leftovers become `skipped_superseded`. Use `--retry-failed` on
05 or 06 to re-attempt records that never got a successful file.

Failures are logged to the **`events` table** in `project.db` (stage
`download`) and printed to stdout. After the run, both 06 and 07 refresh
`screening/not_downloaded.csv` + `not_downloaded.txt` (DOI, last error,
suggested ILL / author_request / check_preprint). Report failures to the user.

### Stage: full-text screening (recommended for any rigorous review)

After title/abstract screening and OA download, run a second screening
pass over the full text of included papers. Title/abstract screening
catches obvious mismatches; full-text screening catches papers whose
abstracts looked good but whose methods don't actually match the criteria.
Standard rate: 20–40% of title/abstract-includes get rejected at full text.

The engine offers TWO paths for this stage. Pick based on the situation.

#### Path A — manual full-text screening (small reviews, 0 LLM cost)

1. `scripts/07_fulltext_prep.py --project <id> --batch-size 5` —
   selects records with `ta_decision='include'` and a successful download,
   normalizes the downloaded file through Microsoft `markitdown`, writes
   Markdown sidecars under `projects/<id>/data/fulltext_md/`, and writes
   `ft_batch_NNN.jsonl`.
2. Decide whether to run an intro/conclusion triage pass before the full read:
   - if the prepared batch is over **100 records**, run this pass automatically
   - if the batch is **100 records or fewer**, ask the user whether they want it
   Use each row's `intro_conclusion_excerpt`, which comes from the Markdown
   normalization step.
3. You (the agent) read each record and label.
4. `scripts/07b_fulltext_commit.py --batch <path> --decided-by agent`

#### Path B — LLM-assisted full-text screening with extraction (default for >20 records)

This is the main path. The LLM reads the paper once and produces, in a
single call: a screening recommendation, extraction fields (summary,
approach, data, key_results, relevance), and (optionally) quality
assessment. The user then reviews the recommendations and confirms or
overrides them.

1. `scripts/07_fulltext_prep.py --project <id> --batch-size 5` (same as Path A)
2. Decide whether to run an intro/conclusion triage pass before the main
   full-text read:
   - if the prepared batch is over **100 records**, run this pass automatically
   - if the batch is **100 records or fewer**, ask the user whether they want it
   Use each row's `intro_conclusion_excerpt` for the triage pass.
3. **Decide whether to enable quality assessment.** Read
   `docs/SKILL_quality_assessment.md` for guidance. If the review is methods-
   or comparative-leaning, suggest `--with-quality`. If it's a quick
   descriptive scan, skip it. Frame it as a choice for the user, don't
   impose it.
4. `scripts/07c_llm_fulltext.py --project <id> --batch <path>
   [--with-quality]` — runs the LLM. Writes recommendations as
   `decided_by='llm:<provider>:recommendation'` in the DB; populates the
   `extractions` table; writes a `ft_review_NNN.jsonl` for the human-review
   step.
5. **Walk the user through the review.**
   `scripts/07d_human_review.py --review <path> --print-summary` prints
   a numbered summary grouped by LLM recommendation. Show this to the
   user. Ask two questions:
   - "From the X papers I'd include — any to override to exclude or unsure?
     Give me numbers."
   - "From the Y excludes / Z unsures — any to flip to include? Numbers."
   For numbers the user wants to deep-dive on, open the corresponding line
   in `ft_review_NNN.jsonl` and discuss in chat. Edit `your_decision` and
   `your_reason` directly in the JSONL for any overrides.
6. `scripts/07d_human_review.py --review <path> --commit` — for any record
   the user didn't override, the LLM recommendation is auto-accepted.
   Records are then written as `decided_by='human'` (the binding final
   decision).

The full-text criteria are the same inclusion/exclusion as title/abstract,
plus an extra rule: *if the full text contradicts the abstract, the full
text wins.* Be willing to flip an include to an exclude here if the
methods section reveals the paper isn't what its abstract claimed.

Records that were title-included but had no successful download go to
`screening/not_downloaded.csv` and `screening/not_downloaded.txt` (written by
`06_download.py` and refreshed by `07_fulltext_prep.py`) for ILL / author
request / preprint follow-up. Bring them back through `07_fulltext_prep` once
obtained.

Stage **07** hard-imports `markitdown`. Install it (see `requirements.txt`
comments) before running full-text prep; PDF/HTML normalization fails without it.

#### Why bundling extraction with full-text screening

If the LLM is reading the paper anyway, charging it nothing extra to also
extract structured findings is a clear win. The engine stores extraction
fields in the `extractions` table — these become an `extractions.csv`
column at export time, ready for synthesis work. The default extraction
schema is generic (summary, context, approach, data_or_setup, key_results,
relevance_notes); customize per project via `project.yaml`'s `extraction:`
block.

### Stage: standalone quality assessment (post-hoc)

If the user finished screening without quality data and wants it now over
the included set: `scripts/08b_quality_pass.py --project <id>`. Idempotent
— skips records already assessed by the same provider.

### Stage: snowball sampling (optional but recommended)

After the screening pass(es), expand the review by walking citations:
`scripts/08_snowball.py --project <id>`. Default: one iteration, both
backward and forward via **OpenAlex**; **Semantic Scholar** ranks citation
edges when S2 is enabled.

The start set is **title/abstract `include` or `unsure`**, with **`from_seed`
records processed first** — not the full-text pass alone.

After snowball, new candidate records sit in the DB unscreened. Loop back:
1. `scripts/03_dedup.py` — many snowballed papers will already be in your
   set; dedup catches them.
2. `scripts/04_screen_prep.py` — screen the genuinely new records.
3. Optionally another full-text pass.

Use `--max-per-seed N` to cap forward snowballing for highly-cited seeds
(default 200). Use `--backward-only` if you only want references and not
citations.

### Stage: export

`scripts/09_export.py` produces:

- `records.csv` / `records.jsonl` — all records with screening labels and reasons
- `included.ris` — final include set (full-text decision wins when present)
- `audit.json` — queries, dedup merges, snowball links, screening counts, events
- `methodology_report.md` and two PRISMA SVGs
- `extractions.csv` — only when extraction rows exist

Export **blocks** if included records lack PRISMA risk-of-bias data unless
`--allow-missing-risk-of-bias` is passed.

The CSV breaks both passes out as `ta_*` and `ft_*` columns so you can see
disagreements.

## What you should NOT do

- Don't invent a new pipeline stage. If something's missing, tell the user
  and propose a script — don't write ad-hoc one-offs.
- Don't screen without the prep step. The batch JSONL is the audit trail.
- Don't mark a record `include` because the title sounds promising. Read
  the abstract.
- Don't paraphrase the user's research question into something easier. If
  the question is poorly scoped, say so.

## Reporting back to the user

After each stage, report:
- counts (records added, deduped, screened in/out)
- any failed sources
- the next command to run

Keep it short. They can read the logs themselves.
