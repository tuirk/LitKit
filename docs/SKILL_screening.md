---
name: SLR-Engine-screening
description: Use this skill when screening titles and abstracts for a systematic literature review. Triggers when the user has run scripts/04_screen_prep.py and you see batch_NNN.jsonl files in projects/<id>/screening/.
---

# Screening Skill

You are doing first-pass title/abstract screening for a systematic literature
review. This is not autonomous research. You are a triage assistant whose
labels will be reviewed.

## Inputs

Semantic Scholar records may include `tldr`. Treat TLDR as a triage hint,
not as evidence that overrides the abstract.

- `projects/<id>/project.yaml` — has `inclusion` and `exclusion` blocks. These
  are the criteria. Read them before every batch.
- `projects/<id>/screening/batch_NNN.jsonl` — one record per line.

## What you write

For each record, fill in three fields:

```json
{
  "decision": "include" | "exclude" | "unsure",
  "reason": "one sentence, references the specific criterion",
  "criteria_hit": ["E1", "I2"]
}
```

`criteria_hit` references the IDs you give each criterion in `project.yaml`
(e.g. `E1` = "exclude non-English", `I2` = "include RCTs only").

## Decision rules

If `tldr` is present, read it first to orient yourself, then verify against
the title and abstract. If TLDR and abstract disagree, trust the abstract. If
TLDR is missing, screen normally.

**Include** when:
- title or abstract clearly matches the population, intervention, comparator,
  outcome (or whatever the analog is for non-medical reviews), AND
- no exclusion criterion is clearly triggered.

**Exclude** when:
- an exclusion criterion is clearly triggered (wrong population, wrong design,
  wrong language, out of date range), OR
- it's clearly off-topic.

**Unsure** when:
- the abstract is missing, AND title alone is ambiguous, OR
- the abstract is present but doesn't disambiguate against the criteria.

## Hard rules

1. **One sentence per `reason`.** If you need a paragraph, you're overthinking
   it — pick `unsure`.

2. **Don't relax criteria.** If the inclusion says "RCTs only" and the abstract
   describes a cohort study, that's `exclude`, not `unsure`.

3. **Don't infer beyond the abstract.** If the abstract doesn't say what the
   intervention was, you don't know what the intervention was. That's `unsure`.

4. **Don't read titles only.** The whole point of abstract screening is the
   abstract. If `abstract` is empty, default to `unsure` unless the title
   triggers a hard exclusion (clearly wrong language, clearly an editorial,
   etc.).

5. **Be consistent across the batch.** If you excluded record 14 for being a
   case report, and record 31 is also a case report, exclude it too.

## Calibration check

Scoping seeds are auto-included by the engine at title/abstract screening with
`decided_by=seed` and are omitted from ordinary batches. After committing a
batch, spot-check that the seeds really fit the criteria as written. If a seed
would fail the criteria, revise the criteria before moving on.

Before labeling a batch, look at `project.yaml`'s `seed_examples`. The user
provides 2–3 papers they would clearly include and 2–3 they'd clearly exclude.
If your reasoning doesn't reproduce those labels, stop and ask the user to
clarify the criteria. Don't proceed with miscalibrated criteria.

## Output

Write the modified JSONL back to the same path. Then run:

```
python scripts/04b_screen_commit.py --batch projects/<id>/screening/batch_NNN.jsonl
```

The commit script validates schema, checks every record has a decision, and
writes labels to the DB. If validation fails, it tells you which line.

## What this skill is not

- Not full-text screening. That's a separate stage.
- Not data extraction. You're labeling include/exclude only.
- Not a quality assessment. Don't downgrade a paper because the methods sound
  weak — that's the human reviewer's job at the next stage.
