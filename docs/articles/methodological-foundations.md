# Methodological foundations

SLR-Engine is grounded in systematic-review methodology. This document records the five methodological pillars the engine rests on and the canonical references for each.

---

## Pillar 1 — Scoping framework (PICOC and its alternatives)

### What the literature gives us

A framework is a structured template for sharpening a research question into searchable components. The dominant framework in evidence-based medicine is **PICO** (Population, Intervention, Comparison, Outcome), formalized by Richardson, Wilson, Nishikawa, and Hayward (1995). The framework is built around interventional clinical questions: "in patients with condition P, does intervention I compared to alternative C produce outcome O." Sackett's evidence-based medicine handbook (Sackett et al., 2000) embedded PICO as the standard.

For non-clinical and non-interventional questions, PICO falls short. The "C" (comparison) doesn't fit reviews where there's no comparator group; the "I" (intervention) doesn't fit methods reviews or descriptive reviews. Several extensions exist:

- **PICOC** — adds a Context slot (Petticrew & Roberts, 2008). The most common extension for social-science and applied-domain reviews. The "C" addition turns the framework into one that can scope questions like "in domain D, what methods M have been used to address problem P, with what outcomes O, in context K."
- **PICOS** — adds a Study Designs slot (the "S"). Used when the review is constrained to specific study types (RCTs only, observational studies only, etc.).
- **SPIDER** — Sample, Phenomenon of Interest, Design, Evaluation, Research type (Cooke, Smith, & Booth, 2012). For qualitative evidence synthesis where "intervention" framing doesn't apply.
- **SPICE** — Setting, Perspective, Intervention, Comparison, Evaluation (Booth, 2006). For information-need reviews where context matters more than population.
- **ECLIPSE** — for health policy and management questions.
- **BeHEMoTh** — for theory-driven reviews.

Kitchenham and Charters (2007) adapted PICO into PICOC for software-engineering reviews; Kitchenham et al. (2009) followed up with an empirical study of how the framework actually got used. These two papers are the canonical references for SLR methodology in technical domains, and they're what made the framework legible to AI/ML, finance, and other non-biomedical fields.

The reason this matters: choosing the wrong framework produces a research question that resists answering because its components don't map cleanly onto the literature's structure. A "what methods M have been used" question framed as PICO becomes awkward (what's the intervention? what's the comparator?); the same question framed as PICOC scopes naturally.

### What the engine does with this

SLR-Engine defaults to **PICOC** for CS, AI/ML, finance, and applied-maths reviews. The agent walks the user through slot filling during scoping. Other frameworks use `framework.type: custom` in `project.yaml` with user-described slots; downstream stages only need searchable concept groups, not framework validation.

**Engine-specific decisions:**

- **Vocabulary-constrained slots** — slot terms must come from `seeds/_vocabulary.json`, not agent-generated synonyms.
- **Mandatory fit-check** — before proposing slots, the agent verifies each slot would match at least one seed paper.
- **Custom frameworks only** — SPIDER, SPICE, etc. are not built-in templates; the agent works from a plain-English slot description when needed.

---

## Pillar 2 — Reporting standard (PRISMA)

### What the literature gives us

PRISMA (Preferred Reporting Items for Systematic Reviews and Meta-Analyses) is the reporting standard for systematic reviews. Its history:

- **Original PRISMA** — Liberati et al. (2009) and Moher et al. (2009): 27-item checklist plus four-phase flow diagram (identification, screening, eligibility, included). Targeted at evidence-based medicine reviews initially but adopted broadly.
- **PRISMA 2020** — Page, McKenzie, Bossuyt, et al. (2021): major update. Separate boxes for database results vs. other sources; 27 items with sub-items (47 reporting requirements total). Current standard.
- **PRISMA-P** — Moher, Shamseer, Clarke, et al. (2015), with the elaboration paper by Shamseer et al. (2015). Protocol-stage companion: 17-item checklist for what to report in the *protocol* before the review runs. Used for PROSPERO registration.
- **PRISMA extensions** — PRISMA-S for search reporting (Rethlefsen et al., 2021), PRISMA-ScR for scoping reviews (Tricco et al., 2018), PRISMA-NMA for network meta-analyses (Hutton et al., 2015), and others.

PRISMA's job is reporting transparency. It doesn't tell you how to do the review; it tells you what to report when you've done it. The flow diagram makes the selection process visible: records identified per source, duplicates removed, exclusions at title-abstract and full-text (with reasons), studies included.

The reason this matters: a review without PRISMA-aligned reporting is not auditable. A reader can't see which records were considered, which were rejected, or why. PRISMA's adoption across journals (mandatory in many) is what made systematic reviews verifiable as a research output.

### What the engine does with this

At export (stage **09**), the engine produces:

- **`prisma_flow.svg`** — canonical PRISMA 2020 flow diagram. Counts come from the audit log; publication-ready.
- **`expanded_prisma.svg`** — engine-aware variant adding scoping, intro/conclusion triage, synthesis, RoB, and snowball iterations. For full audit; canonical diagram goes in the paper.
- **`methodology_report.md`** — structurally aligned with PRISMA-P checklist items, written retrospectively. Does *not* claim PRISMA-P compliance (that requires prospective registration).

---

## Pillar 3 — Search methodology (Boolean queries plus controlled vocabulary)

### What the literature gives us

Systematic-review search is grounded in information-retrieval methodology adapted to academic literature databases. The relevant references span several traditions:

- **Boolean search** — Salton's classical IR work (Salton & McGill, 1983) established AND / OR / NOT plus phrase quoting as the search primitive.
- **Controlled vocabulary** — MeSH (PubMed), ACM CCS (CS), IEEE Thesaurus (engineering). Stevens (1965) and LCSH are foundational.
- **Sensitivity vs. specificity** — McKibbon, Wilczynski, and Haynes (2004) studied the trade-off empirically for clinical questions; the principle applies wherever comprehensive coverage matters.
- **Source-specific syntax** — PubMed Entrez (`[tiab]`, `[MeSH]`); Web of Science (`TS=`, `TI=`); Crossref structured params; OpenAlex Boolean in `search=` (Priem, Piwowar, & Orr, 2022). Cochrane Handbook (Higgins et al., 2019) and CADIMA document these.
- **Query validation** — most SLR methodology assumes the reviewer knows Boolean syntax; the engine automates validation because malformed queries produce silent failures.

The reason this matters: search quality is load-bearing. A bad search produces a corpus that no amount of careful screening can fix.

### What the engine does with this

Search runs through three layers. The operator skill requires literal query strings and API URLs in chat before stage **02** runs.

1. **Per-source adapters** — eight adapters, each speaking native query syntax: OpenAlex Boolean with parentheses, Crossref structured `filter` keys (relevance-ranked free text is avoided), PubMed Entrez field tags, arXiv prefix tags, and so on. Adapters normalize results to `NormalizedRecord`; queries stay source-specific.

2. **Pre-flight validator** — every query is checked before any HTTP request. Errors block structurally broken queries — the common failure is a flat keyword list with no Boolean operators, which OpenAlex treats as implicit AND and returns zero results. Warnings surface suspicious-but-possibly-valid patterns (single-synonym concept groups, long flat Crossref strings).

3. **Post-flight sanity check** — after search completes, flags pagination caps, asymmetric coverage across sources, implausible totals, and zero-result runs where HTTP errors were logged during the run. Blocking issues halt the pipeline before dedup; warnings can be acknowledged and proceed.

---

## Pillar 4 — Snowball protocol (citation-network expansion)

### What the literature gives us

Snowball sampling grows the included set by following citations forward (papers that cite a known relevant paper) and backward (papers cited by a known relevant paper). Two origins in the methodology literature:

- **Webster & Watson (2002)** — proposed snowball as the primary search method for information-systems reviews. Database search as supplement when vocabulary is unstable and indexes inconsistent.
- **Wohlin (2014)** — formalized snowball for software-engineering SLRs: start set → backward snowball (screen references) → forward snowball (screen citing papers) → iterate to closure.

Wohlin's protocol is the canonical reference for technical-domain reviews. Citation-context analysis (Semantic Scholar S2ORC — Lo et al., 2020; SPECTER — Cohan et al., 2020) can prioritize high-yield citation links at scale.

The reason this matters: keyword search alone misses recent unindexed work (forward snowball) and foundational work whose vocabulary has drifted (backward snowball).

### What the engine does with this

Wohlin's three-phase protocol, plus:

- **Seeds first** — `from_seed=1` records auto-include at T/A; snowball expands seeds before other T/A-pass records.
- **OpenAlex edges** — backward via `referenced_works`, forward via `cited_by_api_url`; new records re-enter dedup and screening each iteration.
- **Closure reporting** — iterations log new candidates and new inclusions; zero new inclusions signals completion.
- **Optional S2 ranking** — `isInfluential` and `intents` sort candidates when Semantic Scholar is enabled.

---

## Pillar 5 — Risk-of-bias appraisal (study-quality assessment)

### What the literature gives us

Risk of bias assesses how trustworthy individual included studies are. Established instruments by study type:

- **CASP (2018)** — qualitative studies (ten-item checklist).
- **ROBINS-I (Sterne et al., 2016)** — non-randomized intervention studies (seven domains).
- **RoB 2 (Sterne et al., 2019)** — randomized trials (five domains).
- **JBI critical appraisal tools** — prevalence, descriptive, cohort, qualitative, and other study types.
- **AMSTAR 2 (Shea et al., 2017)** — systematic reviews of reviews.

**GRADE** (Guyatt et al., 2008) sits above per-study RoB: certainty of evidence across studies (high / moderate / low / very low), based on design, RoB, inconsistency, indirectness, imprecision, and publication bias.

The reason this matters: without RoB, synthesis can't distinguish strong from weak evidence. PRISMA 2020 includes RoB reporting as a checklist item; Cochrane reviews require it.

### What the engine does with this

RoB is **opt-in**:

- **`--with-quality` on full-text screening (07c)** — agent applies CASP, ROBINS-I, JBI, or custom rubric; outputs per-domain judgements and overall rating.
- **Instrument choice** — guided by `skills/slr-engine/SKILL_quality_assessment.md`; recorded in the methodology report.
- **Export gate** — stage **09** blocks if included records lack `risk_of_bias_overall` unless `--allow-missing-risk-of-bias`.
- **Retroactive pass** — stage **08b** adds RoB to already-included papers without re-screening.

**Engine-specific decisions:**

- **Opt-in** — landscape and descriptive reviews often don't need per-study RoB.
- **Multiple instruments** — no single default; custom rubrics supported.
- **GRADE not automated** — per-study RoB only; cross-study certainty assessment stays with the researcher.

---

## How the five pillars combine

The pillars constrain each other:

| From | To | Relationship |
|------|-----|--------------|
| Framework (1) | Search (3) | PICOC slots become query concept groups |
| Search (3) | Snowball (4) | T/A-pass records plus seeds feed citation expansion |
| Snowball (4) | RoB (5) | RoB applies to the final included set |
| All pillars | Reporting (2) | Audit log → PRISMA counts; methodology report sections mirror PRISMA-P |

The engine encodes these dependencies in stage ordering: export blocks on incomplete RoB; dedup blocks on search sanity failures; screening requires dedup; and so on.

---

## References

Booth, A. (2006). Clear and present questions: formulating questions for evidence based practice. *Library Hi Tech*, 24(3), 355–368. https://doi.org/10.1108/07378830610692179

Cohan, A., Feldman, S., Beltagy, I., Downey, D., & Weld, D. S. (2020). SPECTER: Document-level representation learning using citation-informed transformers. *Proceedings of ACL 2020*, 2270–2282. https://doi.org/10.18653/v1/2020.acl-main.207

Cooke, A., Smith, D., & Booth, A. (2012). Beyond PICO: the SPIDER tool for qualitative evidence synthesis. *Qualitative Health Research*, 22(10), 1435–1443. https://doi.org/10.1177/1049732312452938

Critical Appraisal Skills Programme (2018). *CASP Qualitative Studies Checklist*. CASP UK. https://casp-uk.net/casp-tools-checklists/

Guyatt, G. H., Oxman, A. D., Vist, G. E., Kunz, R., Falck-Ytter, Y., Alonso-Coello, P., & Schünemann, H. J. (2008). GRADE: an emerging consensus on rating quality of evidence and strength of recommendations. *BMJ*, 336(7650), 924–926. https://doi.org/10.1136/bmj.39489.470347.AD

Higgins, J. P. T., Thomas, J., Chandler, J., Cumpston, M., Li, T., Page, M. J., & Welch, V. A. (Eds.) (2019). *Cochrane Handbook for Systematic Reviews of Interventions*, 2nd Edition. Wiley. https://training.cochrane.org/handbook

Hutton, B., Salanti, G., Caldwell, D. M., et al. (2015). The PRISMA extension statement for reporting of systematic reviews incorporating network meta-analyses of health care interventions. *Annals of Internal Medicine*, 162(11), 777–784. https://doi.org/10.7326/M14-2385

Kitchenham, B. A., & Charters, S. (2007). *Guidelines for performing systematic literature reviews in software engineering* (EBSE Technical Report EBSE-2007-01). Keele University and University of Durham. https://www.elsevier.com/__data/promis_misc/525444systematicreviewsguide.pdf

Kitchenham, B. A., Pearl Brereton, O., Budgen, D., Turner, M., Bailey, J., & Linkman, S. (2009). Systematic literature reviews in software engineering — a systematic literature review. *Information and Software Technology*, 51(1), 7–15. https://doi.org/10.1016/j.infsof.2008.09.009

Liberati, A., Altman, D. G., Tetzlaff, J., et al. (2009). The PRISMA statement for reporting systematic reviews and meta-analyses of studies that evaluate health care interventions: explanation and elaboration. *PLoS Medicine*, 6(7), e1000100. https://doi.org/10.1371/journal.pmed.1000100

Lo, K., Wang, L. L., Neumann, M., Kinney, R., & Weld, D. S. (2020). S2ORC: The Semantic Scholar Open Research Corpus. *Proceedings of ACL 2020*, 4969–4983. https://doi.org/10.18653/v1/2020.acl-main.447

McKibbon, K. A., Wilczynski, N. L., & Haynes, R. B. (2004). Developing optimal search strategies for retrieving clinically sound treatment studies in MEDLINE. *Journal of the Medical Library Association*, 92(3), 372–377. https://doi.org/10.3163/1536-5050.92.3.372

Moher, D., Liberati, A., Tetzlaff, J., Altman, D. G., & PRISMA Group (2009). Preferred reporting items for systematic reviews and meta-analyses: the PRISMA statement. *PLoS Medicine*, 6(7), e1000097. https://doi.org/10.1371/journal.pmed.1000097

Moher, D., Shamseer, L., Clarke, M., et al. (2015). Preferred Reporting Items for Systematic Review and Meta-Analysis Protocols (PRISMA-P) 2015 statement. *Systematic Reviews*, 4(1), 1. https://doi.org/10.1186/2046-4053-4-1

Page, M. J., McKenzie, J. E., Bossuyt, P. M., et al. (2021). The PRISMA 2020 statement: an updated guideline for reporting systematic reviews. *BMJ*, 372, n71. https://doi.org/10.1136/bmj.n71

Petticrew, M., & Roberts, H. (2008). *Systematic Reviews in the Social Sciences: A Practical Guide*. Blackwell.

Priem, J., Piwowar, H., & Orr, R. (2022). OpenAlex: A fully-open index of scholarly works, authors, venues, institutions, and concepts. *arXiv preprint*, arXiv:2205.01833. https://doi.org/10.48550/arXiv.2205.01833

Rethlefsen, M. L., Kirtley, S., Waffenschmidt, S., et al. (2021). PRISMA-S: an extension to the PRISMA Statement for Reporting Literature Searches in Systematic Reviews. *Systematic Reviews*, 10(1), 39. https://doi.org/10.1186/s13643-021-01623-x

Richardson, W. S., Wilson, M. C., Nishikawa, J., & Hayward, R. S. A. (1995). The well-built clinical question: a key to evidence-based decisions. *ACP Journal Club*, 123(3), A12–A13.

Sackett, D. L., Straus, S. E., Richardson, W. S., Rosenberg, W., & Haynes, R. B. (2000). *Evidence-Based Medicine: How to Practice and Teach EBM*, 2nd Edition. Churchill Livingstone.

Salton, G., & McGill, M. J. (1983). *Introduction to Modern Information Retrieval*. McGraw-Hill.

Shamseer, L., Moher, D., Clarke, M., et al. (2015). Preferred Reporting Items for Systematic Review and Meta-Analysis Protocols (PRISMA-P) 2015: elaboration and explanation. *BMJ*, 350, g7647. https://doi.org/10.1136/bmj.g7647

Shea, B. J., Reeves, B. C., Wells, G., et al. (2017). AMSTAR 2: a critical appraisal tool for systematic reviews that include randomised or non-randomised studies of healthcare interventions, or both. *BMJ*, 358, j4008. https://doi.org/10.1136/bmj.j4008

Sterne, J. A., Hernán, M. A., Reeves, B. C., et al. (2016). ROBINS-I: a tool for assessing risk of bias in non-randomised studies of interventions. *BMJ*, 355, i4919. https://doi.org/10.1136/bmj.i4919

Sterne, J. A. C., Savović, J., Page, M. J., et al. (2019). RoB 2: a revised tool for assessing risk of bias in randomised trials. *BMJ*, 366, l4898. https://doi.org/10.1136/bmj.l4898

Stevens, M. E. (1965). *Automatic Indexing: A State-of-the-Art Report*. National Bureau of Standards.

Tricco, A. C., Lillie, E., Zarin, W., et al. (2018). PRISMA Extension for Scoping Reviews (PRISMA-ScR): Checklist and Explanation. *Annals of Internal Medicine*, 169(7), 467–473. https://doi.org/10.7326/M18-0850

Webster, J., & Watson, R. T. (2002). Analyzing the past to prepare for the future: writing a literature review. *MIS Quarterly*, 26(2), xiii–xxiii.

Wohlin, C. (2014). Guidelines for snowballing in systematic literature studies and a replication in software engineering. *Proceedings of EASE '14*, Article 38, 1–10. https://doi.org/10.1145/2601248.2601268
