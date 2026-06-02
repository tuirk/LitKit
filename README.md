# SLR-Engine

SLR-Engine is an automated systematic literature review (SLR) pipeline with
human-in-the-loop where needed.

A systematic literature review (SLR) is a structured method to find, screen, and
summarize published research on a specific question using explicit search
strategies and documented inclusion criteria—not ad-hoc searching. See
[SLR-Engine vs agent deep / web search](#slr-engine-vs-agent-deep--web-search) below.

The engine is a mix of deterministic scripts and prompts wrapped with an agent
skill so your coding agent runs and walks you through the workflow. Your agent
takes a research question, clarifies goals, extracts keywords, writes queries,
searches academic databases, deduplicates sources, does an initial evaluation and
records inclusion/exclusion decisions, builds an evidence set, downloads relevant
papers (when available) for further multi-pass screening, and exports a review
corpus. At the end you're left with a curated set of papers ready for synthesis.

## Working with a coding agent

SLR-Engine expects a **coding agent** (via the skill in `skills/slr-engine/`) to
run the workflow with you.

- **Scripts** do the mechanical work: search databases, dedupe, resolve downloads,
  export files.
- **You + the agent** do the judgment work: scope the question, set inclusion rules,
  label screening batches (usually a few papers at a time in simple files on disk),
  and override anything that looks wrong.

The Python code never calls an LLM by itself in the default setup; it prepares
files, your agent reads them and runs the next script. Optional API-based LLM
screening exists for power users—see **Sources** below and
[`docs/AGENT_GUIDE.md`](docs/AGENT_GUIDE.md) if you need that path.

**Docs:** humans read this README. Agents running reviews follow
[`skills/slr-engine/SKILL.md`](skills/slr-engine/SKILL.md). Engine changes:
[`docs/AGENT_GUIDE.md`](docs/AGENT_GUIDE.md). [`AGENT.md`](AGENT.md) routes
agents at workspace open.

## Output

You get a **project folder** on disk: screened papers plus **research reporting**
you can show in a thesis, report, or methods appendix—not just a chat summary.

**Evidence set**

- **Downloaded open-access PDFs** (when found) — full papers in the project folder,
  not just abstracts.
- **Your shortlist** — which papers made the cut, with include/exclude reasons.
- **Spreadsheet of every paper touched** — title, source, decisions, who decided.
- **Import file for reference tools** — Zotero, Mendeley, etc.
- **Optional study notes** — fields pulled from full-text reading, plus optional
  quality / risk-of-bias ratings when you run that pass.

**Reporting and traceability**

- **PRISMA flow diagrams** — standard and detailed charts of how many records were
  identified, screened, included, and excluded.
- **Methods report** — a readable write-up of your search, screening, and decisions.
- **Full audit log** — exact queries run, duplicates merged, and screening counts.
- **Optional protocol draft** — a prospective plan before search, if you generate one
  at the start.

You can stop mid-review and resume; the folder keeps queries, screening work, and
downloads until export.

Ready for synthesis, writing, or analysis.

## SLR-Engine vs agent deep / web search

**Agent deep search and web skills** answer a question in chat: search the web,
read pages, summarize, cite a few links. Fast and conversational—good for a quick
take.

**SLR-Engine** runs a structured review on disk. The output is a reproducible
dataset of screened academic papers with decision history, not a conversational
answer.

Use deep search when you need a quick read. Use SLR-Engine when the deliverable is a
traceable paper set you can export, revisit, and defend.

**Good fit:** students, researchers, hobbyists, analysts, knowledge workers—anyone
who needs real sources to ground their work on.

| | Agent deep / web search | SLR-Engine |
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

## Step-by-step workflow

Scripts live in `scripts/` (`00`–`09`). The last column marks who runs each step:
**script** (Python only), **agent** (coding agent via `skills/slr-engine/`), **user**
(you), or a combination. Optional LLM stages (`04c`, `07c`, `08b`) add script-driven
API calls where noted.

| # | Stage | What it does | Who |
|---|-------|--------------|-----|
| 00 | init | Create `projects/<id>/`: `project.yaml`, SQLite `project.db`, folders for seeds, queries, imports, screening, full text, logs, exports | — |
| 00b | read seeds | Ingest 1–3 anchor papers (DOI, OpenAlex ID, or PDF) as `from_seed` records; auto-included on first title/abstract commit. Start of **pearl growing** when you have good papers but weak Boolean queries | script |
| 00c | extract vocab | KeyBERT (optional) + agent curation → `seeds/_vocabulary.json`; canonical terms for queries and PICOC—avoid inventing search vocabulary from general knowledge | script + agent |
| 01 | query gen | Scaffold `queries/` templates; agent fills literals from `project.yaml` + vocabulary; you approve strings before **02**. **Keyword search** path after **00c** | agent |
| 01a | protocol draft (optional) | Emit prospective `protocol_draft.md` before search | agent + user |
| 02 | search (open) | Run approved queries on enabled APIs (OpenAlex, Crossref, arXiv, Semantic Scholar default; PubMed, Europe PMC, DBLP, IA Scholar optional). Pre-flight query validation; post-search sanity (silent zeros, cap hits). Records + `source_hits` + frozen `queries` in DB; `logs/search.log` | script |
| 02b | ingest manual (optional) | Scopus / WoS / Google Scholar RIS or CSV from `imports/`—use partial paid access alongside free APIs | script |
| 03 | dedup | DOI / PMID / OpenAlex exact match, then fuzzy title+author+year; `dedup_log`. Blocks on unacknowledged search issues; blocks re-dedup after screening unless `--force` | script |
| 04 | screen prep | Export unscreened records to `screening/batch_*.jsonl` (≤5 per batch) + `criteria.md` | script |
| 04b | T/A screen commit | Label batches (`decision`, `reason`, `criteria_hit`); commit with provenance (`agent`, `human`, `seed`, …) | agent |
| 04c | T/A screen LLM (optional) | Unattended LLM or agent handoff packets (`*_prompts.jsonl`) | script / agent |
| 05 | resolve OA | PMC → Europe PMC → OpenAlex → Unpaywall → CORE (optional) → Crossref; gold/green/bronze only | script |
| 06 | download | Fetch OA full text to `data/fulltext/` | script |
| 07 | full-text prep | PDF/HTML/XML → `data/fulltext_md/`; intro/conclusion excerpts for triage; `not_downloaded.txt` for paywalled includes | script |
| 07b | full-text commit | Commit hand labels on full-text batches | agent |
| 07c | LLM full-text + extract (optional) | Screen + structured extraction on paper text; `--with-quality` adds PRISMA-oriented risk-of-bias fields | script + agent |
| 07d | human review | Review LLM recommendations; user overrides; final commit | user (final), agent (assistant) |
| 08 | snowball (optional) | Backward references + forward citations (OpenAlex; S2 ranks edges if enabled). **Pearl growing expand:** loop **08 → 03 → 04** (then **05–07** for new includes) until no new candidates | script |
| 08b | risk-of-bias (optional) | Post-hoc RoB on included papers | script + agent |
| 08c | quality commit | Commit RoB batch labels | agent |
| 09 | export | `records.csv` / `records.jsonl`, `included.ris`, `extractions.csv` (if any), `audit.json`, `methodology_report.md`, `prisma_flow.svg`, `expanded_prisma.svg`. Blocks if included lack RoB unless `--allow-missing-risk-of-bias` | script |

**Discovery paths (often combined):** *Pearl growing* — **00b** → **00c** → **04** → **08**, then loop **08 → 03 → 04**. *Keyword search* — **00b** → **00c** → **01** → **02** → **03** → **04**. Then shared path: **05** → **06** → **07** (optional **08b**) → **09**.

Example config: [`projects/_example/project.yaml`](projects/_example/project.yaml).

---

## Quick start

Verify install: python scripts/smoke_verify.py (uses projects/_demo/).


1. Install the skill — [`skills/slr-engine/`](skills/slr-engine/) → your agent's
   skills folder ([`skills/README.md`](skills/README.md)).
2. Open this repo in the agent and say: *"Help me start a literature review on
   [topic]."*
3. The agent scopes, searches, screens, and exports to `projects/<id>/exports/`.
   Resume: *"Continue project [id]."*

Install the skill if you can — without it, agents often explain the workflow
instead of running it.

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

## Optional dependencies

Core: stdlib + PyYAML (`pip install -r requirements.txt`). Everything below is optional.

| Add | Enables | Without it |
|-----|---------|------------|
| `keybert`, `sentence-transformers` | Better vocabulary at **00c** | Frequency fallback (weaker); agent still curates in agent mode |
| `markitdown`, PDF libs | PDF/HTML → markdown at **07** | Stage **07** fails on PDF conversion until installed (`requirements.txt` comments) |
| `llm:` + provider keys in `.env` | Unattended LLM at **04c** / **07c** / **08b** | Agent labels batches via skill (default) |

Direct LLM calls and `agent_handoff_runner.py` are stub/reference paths — see Sources above.

---

## Project layout

```
SLR-Engine/                    repo root
├── slr_engine/                    Python library (sources, store, dedup, resolver, …)
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
├── skills/slr-engine/          Operating skill for coding agents
├── docs/                       Scoping, screening, RoB, dev guide
├── AGENT.md                    Agent entry when the workspace opens
├── requirements.txt
└── .env.example                Optional API keys (copy to `.env`)
```

## License

MIT — see [LICENSE](LICENSE).
