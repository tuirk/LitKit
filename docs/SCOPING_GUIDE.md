# Scoping your review

Most people get stuck in the same places on their first SLR. This doc walks
through them. Read it before you let the agent generate queries — or, more
practically, the agent will walk you through these questions in conversation
when you say "generate the queries."

You don't need to come in with a polished protocol. You need to come in with
opinions about a few things. This doc tells you which things.

---

## The academic chain (what real reviews do)

Real systematic reviews follow a chain of decisions in a specific order.
The skill walks the user through this chain during stages 00b, 00c, and 01.
Skipping steps is allowed if you already have the output (just tell the
agent), but the chain itself is fixed:

1. **Topic** — broad subject area (you supplied this at init)
2. **Aim** — what should the review *achieve*?
3. **Research question(s)** — drafted in plain English, sharp, answerable
4. **Seeds (1–3 concrete papers)** — DOI / OpenAlex ID / PDF. Hard
   prerequisite for good vocabulary; the skill treats seeds as required before
   PICOC/query work. Without seeds, slot terms come from general association
   and queries drift (`litkit/seeds.py` also documents: no built-in discovery search).
5. **Vocabulary extraction** — KeyBERT on seed text, then LLM curation;
   produces the canonical vocabulary the rest of the review uses
6. **Framework** — structures each RQ into slots (PICOC by default),
   filled FROM the curated vocabulary
7. **Hypotheses (optional)** — directional claims you want to test;
   parallel to RQs, not derived from them
8. **Eligibility criteria** — derived from framework slots
9. **Validate** — scoping search to check the question is answerable
10. **Optionally emit a protocol draft** before search if you need a
    prospective methods commitment
11. **Run the review** (export later emits `methodology_report.md`)

**Common confusions, settled:**
- Frameworks don't *generate* the research question. You draft the RQ
  first; the framework structures it.
- Hypotheses don't *come from* research questions. They sit alongside,
  drawn from prior theory or belief.
- Most reviews have an RQ but no hypotheses. Some have both. A few have
  hypotheses without an explicit RQ (rare; usually a meta-analysis).
- **Seeds aren't supplementary.** They're the vocabulary anchor that
  PICOC slots get filled from. Without seeds, slot terms come from
  general association and queries drift into adjacent literatures.
  This was the v0.4 failure mode; v0.5+ makes seeds a hard skill prerequisite
  before vocabulary-driven queries.

---

## Frameworks: PICOC by default

The engine ships **PICOC** support out of the box (Petticrew & Roberts
2008; adopted in Kitchenham et al. 2007 software-engineering guidelines;
standard in CS / SE / AI-ML reviews). Slots:

- **P**opulation — who/what is being studied
- **I**ntervention — the method/treatment/technique applied
- **C**omparison — what it's compared against
- **O**utcome — what's measured
- **C**ontext — setting, time, scope

For other frameworks — **SPIDER** (Sample, Phenomenon of Interest, Design,
Evaluation, Research type) for qualitative/mixed-methods reviews; **SPICE**
(Setting, Perspective, Intervention, Comparison, Evaluation) for
context-bound reviews; **PEO** (Population, Exposure, Outcome) for exposure
studies; plus ~33 other frameworks documented in **Booth, Sutton &
Papaioannou's _Systematic Approaches to a Successful Literature Review_**
(SAGE, 2nd ed. 2016) — describe your framework's slots to the agent in
plain English. The engine treats them as a `custom` framework and proceeds
the same way. The framework name and slot fillings get recorded in
`project.yaml` and the final `methodology_report.md`.

If you don't have a framework preference, PICOC is the safest default
across AI/ML/finance/maths/SE reviews.

---

## Hypotheses: optional, parallel to RQs

A research question asks; a hypothesis predicts. Most exploratory reviews
don't need hypotheses. Some confirmatory reviews benefit from them.

**When to add hypotheses:**
- You have prior beliefs strong enough to commit to directional claims
- The review's job is partly to test those claims, not just describe
- Your domain has theoretical priors (econometrics, parts of finance,
  parts of ML)

**When to skip:**
- Exploratory reviews ("map", "catalog", "what's been done")
- You can't articulate a directional claim when prompted

Each hypothesis has an `id`, a `statement` (testable, falsifiable), and a
`rationale` (why expect this — prevents post-hoc rationalization later).

The engine soft-caps hypotheses at 3. More is allowed but flagged in the
protocol. Reasoning: hypothesis-tracking is done by the same LLM that
screens the paper, in the same call. With more hypotheses, false-positive
risk grows because the model is tracking more claims simultaneously and
may pattern-match weakly. **The same risk exists at any count, just lower.**
Mitigation is human spot-checking, not algorithmic — read 5+ random
records per hypothesis before relying on the synthesis.

---

## What kind of review is this, actually?

Be honest about which of these you're doing. They look the same from the
outside but the queries and screening differ.

- **Methods review.** "How is X measured / detected / modeled?" You care about
  techniques, algorithms, model families. Example: *how is regime detection
  done in prediction markets?*
- **Effects review.** "Does X affect Y?" You care about empirical findings.
  Example: *does detected regime affect Polymarket trading returns?*
- **Landscape review.** "What's the state of the field on X?" You care about
  coverage, not a specific question. Broader, looser inclusion criteria.
- **Comparative review.** "How does X differ across A, B, C?" You're carving
  the literature along an axis.

If your real question is two of these stacked together (e.g. "how is regime
detection done AND how does it affect strategies"), the agent should
generate two query sets, not one. Tell it.

---

## The seeds problem

The agent will ask for seed papers. **The single best thing you can do for
review quality is provide good seeds.** Even one well-chosen seed paper
massively improves query construction, because the agent can mine its
abstract and references for the actual vocabulary your field uses.

### "I have no seeds."

Fine. Two paths:

**Path 1 — Find one in 10 minutes.** Go to Google Scholar. Search a plain
English version of your question. Open the first 5–10 results. Read titles
and abstracts. Pick the one that's closest to what you want to find more
of. Paste its title or DOI as your seed. Done.

**Path 2 — Broad search first, then pick seeds (agent workaround).** Say:
*"I don't have seeds. Run a broad exploratory search, show me ~20 candidates,
I'll pick seeds from those."* The agent runs `02_search_open.py` with a loose
query (you approve literals first), you pick 1–3 papers, then **`00b` → `00c`**
before real query generation. This is an extra round — not a separate engine mode.
`litkit/seeds.py` explicitly says: no discovery search API; this is manual recovery.

### "I have one seed."

That's enough. Tell the agent: *"This is my one seed: [DOI or title]. Mine
it for vocabulary and surface the synonyms before drafting queries."* The
agent should come back with a list of terms it pulled from the paper's
abstract and ask you which to keep.

### "I have many seeds but they're all from the same niche."

Risk: your queries will over-fit to that niche and miss adjacent
literatures. Tell the agent your seeds are concentrated and ask it to
*deliberately propose synonyms from adjacent fields*. For example, if all
your prediction-market seeds are from finance journals, ask for the
political-science vocabulary too (election forecasting, betting markets).

---

## The "too narrow / too broad" calibration

This is the hardest part and where most reviews go wrong. Here's a heuristic:

> A good first-pass query returns somewhere between **200 and 2,000** results
> on OpenAlex.

- **Under 50:** you're too narrow. You're matching a literal phrase. Add
  synonyms; relax the AND clauses.
- **Over 5,000:** you're too broad. Your concepts are doing too much work
  separately. Either add a third concept that pins the topic down, or
  tighten one of the existing concepts.
- **200–2,000:** workable. Move on; you'll refine during screening.

Tell the agent your acceptable range up front. It can iterate the query and
report counts before committing to a search.

### Concrete examples

**Too narrow:** `"Polymarket" AND "regime"` → maybe 5 results, none of them
the methods literature you actually want.

**Too broad:** `"prediction market" AND "trading strategy"` → 4,000 results,
mostly stock-market and forex papers.

**Workable:** `("prediction market" OR "betting market" OR "Polymarket" OR
"Kalshi") AND ("regime" OR "regime switching" OR "structural break" OR
"change-point") AND ("trading" OR "strategy" OR "returns")` → ~600 results,
mostly on-topic.

The agent should construct something in this shape. If it doesn't, push back.

---

## Synonyms: what the agent should propose for you

When the agent shows you draft queries, it should also show you the
**concept table**: every concept and the synonyms it's using. Look at it.
For each concept, ask:

1. **Are common terms missing?** If your concept is "regime detection,"
   the synonyms list should include at minimum: *regime switching, regime
   change, structural break, change-point detection, state-space, hidden
   Markov, Markov switching, breakpoint, structural change*. If it's
   missing more than two of those, the agent under-researched.

2. **Are there ambiguous terms hurting you?** "Regime" by itself catches
   *political* regimes. "Network" catches *neural* networks AND *social*
   networks. Tell the agent to require regime to co-occur with a market
   word, etc.

3. **Are there controlled vocabulary terms?** PubMed has MeSH; biomedical
   reviews should use MeSH terms in addition to free-text. The agent should
   know this. Other fields don't have controlled vocab, that's fine.

If you have no idea what synonyms exist, that's a sign you should do the
discovery search first (Path 2 above) and let the seeds teach you the
vocabulary.

---

## Inclusion and exclusion criteria: what makes them good

The agent pre-fills these in `project.yaml`. Read them. The test for whether
a criterion is good: **could you apply it to a title and abstract in 10
seconds?** If you can't, it's too vague.

### Bad criteria

- *"High-quality studies"* — what's the cutoff?
- *"Relevant to traders"* — relevant how?
- *"Recent enough"* — what year?

### Good criteria

- *"Empirical study using market data (not purely theoretical)"*
- *"Reports at least one quantitative trading-performance metric (return,
  Sharpe, drawdown, win rate)"*
- *"Published 2018 or later"*

Each criterion should have an ID (`I1`, `E2`, etc.). The agent uses these
IDs in screening, so each exclusion can be audited.

### The "I'll know it when I see it" trap

Sometimes you genuinely don't know your criteria yet because you haven't
read enough of the literature. That's OK — but say so. Tell the agent:
*"My criteria are provisional. Run a small first batch of 30 papers,
let me screen them, and I'll firm up criteria from what I see."* This is
how real reviews actually go. Pretending otherwise produces a brittle
protocol that breaks on first contact.

---

## Date range

Pick this deliberately, not by default.

- **Methods reviews** usually want everything (`date_from: null`) because
  foundational methods may be old.
- **Effects reviews** usually want a recent window because old empirical
  results may not generalize.
- **Topical reviews** (something that didn't exist before year X) want
  `date_from: <X>`. Polymarket launched in 2020, so a Polymarket-specific
  review starting in 2018 only catches the prediction-markets background.
  Decide whether you want background or just the specific platform.

---

## Languages

If you only read English, set `languages: ["en"]` and don't pretend
otherwise. A review that "includes all languages" but where you can't read
half the included papers is worse than an English-only review you can
actually defend.

---

## Do you need a protocol draft?

Generate a protocol draft before search if you need a prospective methods
commitment: formal academic publication, PROSPERO or other registration,
internal sign-off requirements, or grant submissions. The agent asks once
after queries are approved and before the search runs.

Most users should skip it for internal KM, industry research, client work
without formal methodology requirements, or exploratory scans. Default is
no; you still get a full retrospective `methodology_report.md` at export.

---

## Quick checklist before approving queries

The agent has shown you draft queries. Before saying "go":

- [ ] You can name the **type** of review you're doing (methods / effects /
      landscape / comparative).
- [ ] You have **at least one concrete seed** (DOI / OpenAlex ID / PDF) before
      **`00c` vocabulary extraction**. A broad first search to *find* seeds is
      OK as a workaround, but you still run **`00b` → `00c`** before final queries.
- [ ] You've reviewed the **curated vocabulary** in
      `seeds/_vocabulary.json` and confirmed it captures real-field
      terminology.
- [ ] You looked at the **concept table** and the synonyms make sense
      (each one came from the curated vocabulary).
- [ ] You looked at the **literal query strings** AND the **API URLs**
      the agent's about to send. The agent has run a precision check
      (does the query match seeds? does it not match obvious off-topic
      titles?) and walked you through the reasoning.
- [ ] The estimated result count is **200–2,000** (or you've decided
      otherwise on purpose).
- [ ] Your **inclusion/exclusion criteria** would let you label any given
      title+abstract in under 10 seconds.
- [ ] Your **date range** is a deliberate choice, not a default.

If all eight are checked, approve the queries. If not, tell the agent
which ones you're unsure about and ask for a revision.

---

## Source defaults before scoping

At first contact, show the user the source defaults and let them change the
mix before scoping starts.

Default ON: OpenAlex, Crossref, arXiv, Semantic Scholar.

Default OFF: PubMed, Europe PMC, DBLP, Internet Archive Scholar.

Manual only: Scopus, Web of Science, Google Scholar.

`CORE_API_KEY` in `.env` plus `sources.core: true` in `project.yaml` enables the
**stage-05 CORE resolver** (not a search API).

Enable PubMed or Europe PMC for biomedical/clinical/life-sciences reviews.
Enable DBLP for CS-heavy reviews. Enable Internet Archive Scholar when grey
literature or older scanned material matters.

## A note on Crossref as a search source

LitKit enables Crossref by default, but Crossref's REST API does
*relevance ranking* on free-text queries, not strict Boolean filtering.
This matters for systematic reviews because:

- A `query=` or `query.bibliographic=` parameter ranks results by how
  well they match the keywords; it does NOT exclude non-matching
  records strictly.
- On topics where the keywords are common across multiple literatures
  (e.g. "market", "trading", "model", "review"), Crossref will
  surface tangentially-related papers and rank them high enough to fill
  the result set with noise.

LitKit's `litkit/sources/crossref.py` accepts structured params:

```json
{
  "filter": {
    "type": "journal-article",
    "has-abstract": "true",
    "from-pub-date": "2020-01-01"
  },
  "query.bibliographic": [
    "<narrow concept group with distinctive terms>",
    "<another narrow group with distinctive terms>"
  ]
}
```

Use `filter` for everything that's strictly filterable — date, type,
journal, publisher, has-abstract. These ARE strict; they exclude
non-matching records.

Use `query.bibliographic` (relevance-ranked) **only for narrow concept
groups with distinctive vocabulary** — named entities (specific products,
named methods, unique organizations), rare technical terms. Avoid
broad-keyword groups; they'll pull in noise.

If your topic has no distinctive named entities or rare terms, Crossref
may not be the right source. OpenAlex (which uses Boolean operators
properly) and the discipline-specific indexes (PubMed for biomedical,
arXiv for physics/CS preprints) are usually a better fit.

## Google Scholar manual import

Google Scholar has no public API, and LitKit does not scrape it. If Scholar
coverage matters, run the query in Scholar manually, export citations as RIS
where possible, save the file as `projects/<id>/imports/scholar_<date>.ris`,
then run:

```bash
python scripts/02b_ingest_manual.py --project <id>
```

Imported records are tagged as `google_scholar_manual`.

---

## When to come back to this doc

- Before query generation (the first time).
- When a search returns 12 or 12,000 results — calibration is off.
- When screening keeps producing `unsure` labels — your criteria are
  probably too vague.
- When you're about to start a second review and you've forgotten the
  shape of the work.

You don't need to internalize this doc. You need to know it exists.
