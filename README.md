# LitKit

LitKit helps you go from a research question to a curated set of open-access
academic papers you can trace. It is a step-by-step literature review workflow
grounded in academic methodology, but lightweight for personal research with
open databases and open-access sources. A skill wraps the workflow so your
coding agent runs it with you: clarify what you need, define inclusion and
exclusion, write search queries, find and dedupe papers, screen in batches,
download full text where openly available, and export the shortlist with an
audit trail.

## LitKit vs agent deep / web search

**Agent deep search and web skills** answer a question in chat: search the web,
read pages, summarize, cite a few links. Fast and conversational — good for a
quick take.

**LitKit** runs a review project on disk: scoped question, criteria, queries,
dedupe, screening, export. The deliverable is a **curated shortlist with an
audit trail**, not a paragraph in the thread.

| | Agent deep / web search | LitKit |
|---|-------------------------|--------|
| **Output** | Summary + ad-hoc links | Shortlist + CSV/RIS + audit log |
| **Sources** | Web, blogs, news, mixed quality | Academic APIs (OpenAlex, Crossref, arXiv, …) |
| **Curation** | Model picks what looks relevant | You set include/exclude; screen in batches |
| **Dedup** | Same paper may appear from different URLs | Cross-source dedup by DOI / title / author |
| **Reproducibility** | Hard to replay what was searched | Saved queries, counts, and decisions in `projects/` |
| **Resume** | New chat often means starting over | `Continue project [id]` |
| **Citation follow-up** | Rarely systematic | Snowball references and citations (stage **08**) |
| **Full text** | Snippets from pages fetched | OA resolve and download pipeline |
| **Citation accuracy** | Risk of invented or wrong links | Records from APIs and metadata, not free-form generation |
| **Speed** | Faster for orientation | Slower — by design |

Use deep search when you need a quick read. Use LitKit when the deliverable is a
traceable paper set you can export, revisit, and defend.

**Good fit:** knowledge workers, students, founders, analysts — anyone who wants
more rigor than ChatGPT or a Scholar scroll, including with **partial access**
(a few PDFs, a Scholar export, one Scopus file from a colleague) mixed with free
APIs. Strong on technical topics (AI/ML, software, finance) where OpenAlex, arXiv,
and Semantic Scholar cover the field.

**Not for:**

- Cochrane / Covidence dual-reviewer workflows or meta-analysis
- Autonomous research agent — numbered scripts and state on disk, you in the loop
- Sci-Hub or paywall bulk download (OA full text only; paywalled → `screening/not_downloaded.txt`)
- One-shot Q&A — one project folder per review, built to resume
- Journal submission on autopilot — traceable scaffolding you verify, not blind κ or forest plots

---

## Quick start

Verify install: python scripts/smoke_verify.py (uses projects/_demo/).


1. Install the skill — [`skills/litkit/`](skills/litkit/) → your agent's
   skills folder ([`skills/README.md`](skills/README.md)).
2. Open this repo in the agent and say: *"Help me start a literature review on
   [topic]."*
3. The agent scopes, searches, screens, and exports to `projects/<id>/exports/`.
   Resume: *"Continue project [id]."*

Install the skill if you can — without it, agents often explain the workflow
instead of running it.

---

## How LitKit Finds Relevant Papers

Two paths — often used together. Both end in the same screening, full-text,
and export stages.

### Citation-first (pearl growing)

Best when you have a few good papers but don't know Boolean query syntax.

1. You provide **1–3 seed papers** (DOI, OpenAlex ID, or PDF).
2. **00b** ingests them as starting records.
3. **00c** reads vocabulary from their abstracts/text.
4. You screen as usual (**04**).
5. **08** snowballs backward references and forward citations (OpenAlex).
6. Loop **08 → 03 → 04** until no new candidates appear.

### Keyword search

Best when you know what terms to search, or want broad coverage up front.

1. **00b** ingests seeds; **00c** reads vocabulary from their text (requires at least one good seed).
2. **01** turns vocabulary into query templates; you approve the literal strings.
3. **02** runs them against open APIs (see Sources below).
4. **03** dedupes, then **04** screens.

Optional: drop Scopus, Web of Science, or Google Scholar exports in
`projects/<id>/imports/` — whatever partial access you have — and ingest at
**02b**.

---

## Sources

Three intake paths — all merge into the same dedup and screening pipeline.

| Stage | Sources |
|-------|---------|
| **02 — open APIs** | OpenAlex · Crossref · arXiv · Semantic Scholar |
| **02 — optional** | PubMed · Europe PMC (clinical) · DBLP (CS) · IA Scholar (grey lit) — toggle in `project.yaml` |
| **02b — manual** | Scopus · Web of Science · Google Scholar → RIS/CSV in `imports/` as `scopus_*`, `wos_*`, `scholar_*` |
| **05–06 — full text** | PMC → Europe PMC → OpenAlex → Unpaywall → CORE (if `sources.core: true` + `CORE_API_KEY`) → Crossref |

**Optional keys and sources.** Nothing above requires paid accounts. Extra sources and
`.env` keys (`OPENALEX_API_KEY`, `S2_API_KEY`, `NCBI_API_KEY`, `CORE_API_KEY`) are
optional — add them for rate limits or extra resolvers. `CORE_API_KEY` is used only
when `sources.core: true` in `project.yaml`. `OPENALEX_API_KEY` can also live in
`project.yaml` as `openalex_api_key`.
Set `contact_email` in `project.yaml`. Paywalled or hybrid tiers are not
auto-downloaded; see `screening/not_downloaded.txt`.

**Default: agent drives judgment.** With no `llm:` block (or `provider: agent`), your
coding agent handles vocabulary curation, screening, and full-text review via the
skill. The scripts handle search, dedup, resolve, download, and export.

**Optional: scripts call APIs directly.** Set `llm.provider` in `project.yaml` plus
provider keys in `.env` to run unattended LLM stages (04c, 07c, 08b). That path and
`agent_handoff_runner.py` are **stub/reference implementations** — workable, but the
intended workflow is agent + skill, not headless automation.

---

## Pipeline stages

| # | Stage | What it does | Who decides |
|---|-------|--------------|-------------|
| 00 | init | Scaffold project folder + DB | — |
| 00b | read seeds | **Pearl growing — start:** fetch 1–3 seed papers (DOI/OpenAlex/PDF); ingest as `from_seed` records | LitKit |
| 00c | extract vocab | **Pearl growing — vocabulary:** read seed text; KeyBERT + agent curation → canonical terms for queries and PICOC | LitKit + agent |
| 01 | query gen | Generate query templates from `project.yaml` | agent fills templates using curated vocabulary |
| 01a | protocol draft (optional) | Emit `protocol_draft.md` before search | agent + user |
| 02 | search (open) | Keyword path: OpenAlex, Crossref, arXiv, Semantic Scholar by default; PubMed/Europe PMC/DBLP/IA Scholar optional. Pre-flight validator + post-flight sanity. | LitKit |
| 02b | ingest manual | Scopus/WoS/Google Scholar RIS or CSV exports | LitKit |
| 03 | dedup | DOI/PMID/OpenAlex exact match + fuzzy title+author+year. Refuses if search left blocking issues; refuses after screening unless `--force`. | LitKit |
| 04 | screen prep | Export batch JSONL (max 5 records per batch) | LitKit |
| 04b | T/A screen commit | Label JSONL, commit; auto-includes `from_seed` records on first commit | agent |
| 04c | T/A screen LLM (optional) | Unattended via Anthropic/DeepSeek/Google, or handoff packets in agent mode | LitKit / agent |
| 05 | resolve OA | PMC → EPMC → OpenAlex → Unpaywall → CORE → Crossref (gold/green/bronze only) | LitKit |
| 06 | download | Fetch OA full text for allowed tiers only | LitKit |
| 07 | full-text prep | PDF/HTML/XML → markdown; intro/conclusion excerpt for triage | LitKit |
| 07b | manual full-text commit | Commit hand labels | agent |
| 07c | LLM full-text + extraction | Combined screen+extract+optional risk-of-bias assessment | LitKit + agent |
| 07d | human review | Agent shows summary, user overrides, commit | user (final), agent (assistant) |
| 08 | snowball | **Pearl growing — expand:** backward refs + forward citations (OpenAlex; S2 ranks edges if enabled) | LitKit |
| 08b | risk-of-bias pass (post-hoc) | Add PRISMA RoB data to already-included papers | LitKit + agent |
| 08c | quality commit | Commit RoB batch labels | agent |
| 09 | export | CSV / RIS / JSONL + `extractions.csv` (if any) + audit.json + methodology_report.md + 2 PRISMA SVGs. Blocks if included records lack RoB unless `--allow-missing-risk-of-bias`. | LitKit |

Stages **00b** and **00c** run before query generation and produce the canonical
vocabulary that PICOC slots are filled from. Without them, queries get built
from the agent's general associations rather than real-field terminology.

After snowball (**08**), new candidate records exist in the DB unscreened. Loop
back to dedup (**03**) and screen (**04** or **04c**), then resolve/download/screen new
includes before export.

Example project config: [`projects/_example/project.yaml`](projects/_example/project.yaml).

---

## Optional dependencies

Core: stdlib + PyYAML (`pip install -r requirements.txt`). Everything below is optional.

| Add | Enables | Without it |
|-----|---------|------------|
| `keybert`, `sentence-transformers` | Better vocabulary at **00c** | Frequency fallback (weaker); agent still curates in agent mode |
| `markitdown`, PDF libs | PDF/HTML → markdown at **07** | Stage **07** fails on PDF conversion until installed (`requirements.txt` comments) |
| `llm:` + provider keys in `.env` | Unattended LLM at **04c** / **07c** / **08b** | Agent labels batches via skill (default) |

Direct LLM calls and `agent_handoff_runner.py` are stub/reference paths — see Sources above.

---

## External agent handoff

**Primary path (skill + Cursor):** the agent edits staged files directly — e.g.
`04_screen_prep.py` writes `batch_*.jsonl`; you label rows and run
`04b_screen_commit.py`. No prompt packets required.

**Handoff path (stub/reference):** when `llm:` is omitted or `provider: agent`,
some scripts also write structured prompt packets for an external harness. LitKit
never calls Codex / Claude Code from Python — it stages files on disk.

| Script | Stage | Prompt file | Companion |
|--------|-------|-------------|-----------|
| `00c_extract_vocabulary.py` | `vocabulary_curation` | `seeds/_vocabulary_prompt.json` | `seeds/_vocabulary_agent_request.md` |
| `04c_llm_screen.py` | `title_abstract_screening` | `screening/batch_*_prompts.jsonl` | `screening/batch_*_agent_request.md` |
| `07c_llm_fulltext.py` | `full_text_screen_extract` | `screening/ft_review_*_prompts.jsonl` | `screening/ft_review_*_agent_request.md` |
| `08b_quality_pass.py` | `quality_assessment` | `screening/quality_batch_*_prompts.jsonl` | `screening/quality_batch_*_agent_request.md` |

Shared packet schema (`litkit-agent-prompt/v1`):

```json
{
  "schema_version": "litkit-agent-prompt/v1",
  "stage": "title_abstract_screening",
  "project_id": "my-project",
  "item": {"record_id": 123, "canonical_id": "rec_000123"},
  "input_refs": {"batch_file": "...", "criteria_file": "..."},
  "prompt": {
    "task": "screen",
    "system": "...",
    "user": "...",
    "response_shape": {"decision": "include|exclude|unsure"}
  },
  "output": {
    "write_back_to": "...",
    "fields": ["decision", "reason", "criteria_hit"],
    "commit_command": "python scripts/04b_screen_commit.py --batch ..."
  }
}
```

Vocabulary packets use `output.write_to` instead of `write_back_to`.

Reference runner (validate or apply harness responses before commit):

```bash
python scripts/agent_handoff_runner.py \
  --packets projects/<id>/screening/batch_001_prompts.jsonl \
  --responses <harness-output>.jsonl

python scripts/agent_handoff_runner.py ... --validate-only   # check only
```

---

## Reproducibility

Every project produces:

- **`exports/records.csv` / `records.jsonl`** — all records with screening labels and reasons
- **`exports/audit.json`** — queries run, dedup merges, snowball links, screening counts, event log
- **`exports/methodology_report.md`** and **two PRISMA SVGs** (`prisma_flow.svg`, `expanded_prisma.svg`)
- **`exports/extractions.csv`** — when extraction / RoB passes have run

Useful as a methods appendix for internal sign-off, client work, or later academic write-up.

---

## Project layout

```
LitKit/                         repo root
├── litkit/                        Python library (sources, store, dedup, resolver, …)
├── scripts/                    Numbered stages the agent runs
├── projects/
│   ├── _example/               Template project.yaml
│   └── <id>/                   One folder per review
│       ├── project.yaml        Scope, criteria, source toggles
│       ├── project.db          SQLite record + screening state
│       ├── seeds/              Seed papers, vocabulary, KeyBERT bucket
│       ├── queries/            Search strings (fill before stage 02)
│       ├── imports/            Manual Scopus / WoS / Scholar exports (02b)
│       ├── screening/          Batches, criteria, handoff files
│       ├── data/fulltext/      Downloaded OA PDFs / HTML
│       ├── data/fulltext_md/   Normalized markdown (stage 07)
│       ├── logs/               search.log, events in project.db, …
│       └── exports/            CSV, RIS, audit.json, PRISMA SVGs
├── skills/litkit/              Operating skill for coding agents
├── docs/                       Scoping, screening, RoB, dev guide
├── AGENT.md                    Agent entry when the workspace opens
├── requirements.txt
└── .env.example                Optional API keys (copy to `.env`)
```

**Docs:** humans read this README. Agents running reviews follow
[`skills/litkit/SKILL.md`](skills/litkit/SKILL.md). Kit changes:
[`docs/AGENT_GUIDE.md`](docs/AGENT_GUIDE.md). [`AGENT.md`](AGENT.md) routes
agents at workspace open.

## License

MIT — see [LICENSE](LICENSE).
