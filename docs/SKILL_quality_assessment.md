---
name: litkit-risk-of-bias-assessment
description: Use this skill when the user is doing full-text screening, export, or PRISMA reporting and needs study risk-of-bias assessment. The skill explains PRISMA-oriented risk-of-bias fields and how they differ from generic quality assessment.
---

# Risk-of-Bias Assessment Skill

PRISMA 2020 expects systematic reviews to report study risk-of-bias methods
and per-study risk-of-bias results. The engine used to call this "quality
assessment"; for PRISMA-facing reviews, treat it as **risk-of-bias /
critical-appraisal assessment**, not a skippable nice-to-have.

Risk-of-bias data never overrides the human's inclusion decision. It is
separate evidence-appraisal data used for interpretation, sensitivity analysis,
and reporting.

## When To Require It

For academic systematic reviews, tell the user risk-of-bias assessment should
be completed before export. The export script blocks missing RoB data unless
the user explicitly passes `--allow-missing-risk-of-bias`.

You may allow skipping only when:

- The user explicitly says this is a practical or non-publication scan.
- The review is descriptive or scoping-style, and the user accepts that PRISMA-style systematic-review reporting will be incomplete.
- The user chooses to run RoB later via `08b_quality_pass.py`.

## How To Phrase It

Use this wording before full-text screening:

> PRISMA expects risk-of-bias assessment for included studies. I can do it while reading full text with `--with-quality` (legacy flag name). It adds overall RoB, domain-level judgements, and justification notes. This costs more tokens, but if we skip it the final export will block unless you explicitly override. Run with risk-of-bias assessment now? Yes/no?

If the user says no, record that this is a deliberate skip and remind them they
can add it later via:

```bash
python scripts/08b_quality_pass.py --project <id>
```

## Required RoB Fields

`risk_of_bias_tool`: named tool or rubric used. If the project specifies a
formal tool, use it. Otherwise use `LitKit domain-based risk-of-bias rubric`.

`risk_of_bias_overall`: one of `low`, `some_concerns`, `high`, `unclear`.

`risk_of_bias_domains`: list of domain-level judgements. Each item should
include `domain`, `judgement`, `rationale`, and `evidence_quote` when available.

`risk_of_bias_notes`: 1-2 sentences justifying the overall judgement with
concrete evidence.

For AI/ML/finance/maths reviews, typical domains include selection bias,
confounding, missing data, outcome measurement, selective reporting, data
leakage, comparator/baseline adequacy, and reproducibility.

## Supporting Quality Fields

The engine still captures legacy/supporting fields:

- `methodological_rigor`: high | medium | low | unclear.
- `evidence_strength`: strong | moderate | weak | unclear.
- `limitations_acknowledged`: yes | partial | no.
- `quality_notes`: concise concern/strength notes.

These are useful, but PRISMA reporting should rely on the `risk_of_bias_*`
fields.

## What The User Does With This Data

Risk-of-bias fields are for:

- PRISMA reporting: per-study risk-of-bias methods and results.
- Sensitivity analysis: whether conclusions hold among lower-risk studies.
- CSV filtering and interpretation.
- Avoiding overstatement when included evidence is high risk.

When presenting recommendations, surface RoB inline:

> rec_000023 - Bayesian online change-point detection for Polymarket (2024)
> RoB: low - Pre-registered OOS window; leakage checks reported.

## Running RoB After The Fact

If RoB was not enabled during full-text screening, run it over included papers:

```bash
python scripts/08b_quality_pass.py --project <id>
```

Then commit any agent-authored batch:

```bash
python scripts/08c_quality_commit.py --batch projects/<id>/screening/quality_batch_001.jsonl
```
